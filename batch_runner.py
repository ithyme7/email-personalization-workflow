from __future__ import annotations

import argparse
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from angle_selector import evidence_for_selected_angle, select_angle
from config import ensure_directories, load_settings
from deep_research import collect_deep_research
from evidence_extractor import evidence_to_payload, extract_evidence
from export import export_client_batch_rows, export_rows, export_sending_tool_rows
from checkpoint import load_checkpoint, save_checkpoint, cleanup_checkpoint
from defaults import _default_next_sentence
from input_loader import load_leads
from llm_client import LLMClient
from models import EvidenceFact, EvidenceResult, LeadInput, PersonalizationDraft, QCResult, ResearchResult, join_list
from personalization_writer import write_personalization
from preflight import has_blocking_failures, preflight_summary, run_preflight
from prompt_versions import prompt_hashes, tone_profile_hash
from quality_checker import check_quality
from rate_limiter import RateLimiter
from run_history import append_generated_email_rows
from feedback import SendFeedback, init_feedback_db
from impact_analyzer import build_feedback_context
from schemas import stable_hash
from surface_classifier import classify_surface, is_app_first, research_priority_for
from tone_profiles import load_tone_profile
from web_research import research_company

PITCH_SENTENCE = "We help mobile app teams with this type of work, figure out where users drop off and why."
ProgressCallback = Callable[[dict[str, Any]], None]
SERIOUS_QUALITY_FLAGS = {
    "em_dash",
    "genericness",
    "unsupported_claims",
    "generic_praise",
    "too_long",
    "opening_line_too_long",
    "ai_mush",
    "missing_outcome_tie",
    "poor_pitch_flow",
    "missing_conversational_template_open",
    "missing_specific_dropoff_hypothesis",
    "too_abstract",
    "not_conversion_focused",
    "missing_visible_friction",
    "blog_angle_low_value",
    "weak_or_vague_proof_angle",
    "broad_positioning_not_explained",
    "better_priority_angle_available",
    "wrong_surface",
    "multiple_insights",
    "manual_review_needed",
    "role_forced",
    "angle_gate_no_sendable_friction",
    "selected_angle_not_strong",
    "app_store_angle_review",
    "low_confidence_visual_finding",
    "technical_audit_language",
    "download_claim",
    "company_name_not_lowercase",
}


def _emit_progress(progress_callback: ProgressCallback | None, **payload: Any) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(payload)
    except Exception:
        logging.debug("Progress callback failed", exc_info=True)


def _base_row(lead: LeadInput) -> dict[str, Any]:
    row = {
        "company_name": lead.company_name,
        "website_url": lead.website_url,
        "linkedin_url": lead.linkedin_url,
        "recipient_name": lead.recipient_name,
        "recipient_role": lead.recipient_role,
        "campaign_context": lead.campaign_context,
        "linkedin_observation": lead.linkedin_observation,
        "linkedin_source_note": lead.linkedin_source_note,
        "app_store_url": lead.app_store_url,
        "app_store_summary": "",
        "app_review_themes": "",
        "app_flow_observation": lead.app_flow_observation,
        "app_flow_source_note": lead.app_flow_source_note,
        "screenshot_url": lead.screenshot_url,
        "recent_news_url": lead.recent_news_url,
        "recent_news_note": lead.recent_news_note,
        "competitor_context": lead.competitor_context,
        "research_depth": lead.research_depth,
        "friction_checklist": "",
        "app_check_status": "",
        "recommended_manual_check": "",
        "product_surface_type": "",
        "research_priority": "",
        "app_review_complaints": "",
        "template_preview": "",
        "visual_observations": "",
        "visual_quality_flags": "",
        "visual_confidence": "",
        "visual_confidence_score": "",
        "visual_confidence_reasons": "",
        "screenshot_paths": "",
        "shareable_screenshot_files": "",
        "trace_files": "",
        "advanced_detector_flags": "",
        "ux_validator_findings": "",
        "dead_link_checks": "",
        "friction_type": "",
        "surface_checked": "",
        "conversion_outcome": "",
        "angle_gate_decision": "",
        "angle_gate_notes": "",
        "blocked_angles": "",
        "angle_priority": "",
        "blog_used": "",
        "why_this_angle": "",
        "raw_research_summary": "",
        "evidence_points": "",
        "evidence_used_for_copy": "",
        "chosen_angle": "",
        "opening_line": "",
        "tailored_insight": "",
        "opening_line_option_1": "",
        "tailored_insight_option_1": "",
        "chosen_angle_option_1": "",
        "evidence_used_for_copy_option_1": "",
        "confidence_score_option_1": "",
        "quality_flags_option_1": "",
        "needs_manual_review_option_1": "",
        "reviewer_notes_option_1": "",
        "template_preview_option_1": "",
        "opening_line_option_2": "",
        "tailored_insight_option_2": "",
        "chosen_angle_option_2": "",
        "evidence_used_for_copy_option_2": "",
        "confidence_score_option_2": "",
        "quality_flags_option_2": "",
        "needs_manual_review_option_2": "",
        "reviewer_notes_option_2": "",
        "template_preview_option_2": "",
        "opening_line_option_3": "",
        "tailored_insight_option_3": "",
        "chosen_angle_option_3": "",
        "evidence_used_for_copy_option_3": "",
        "confidence_score_option_3": "",
        "quality_flags_option_3": "",
        "needs_manual_review_option_3": "",
        "reviewer_notes_option_3": "",
        "template_preview_option_3": "",
        "prompt_set_hash": "",
        "evidence_prompt_hash": "",
        "write_prompt_hash": "",
        "qc_prompt_hash": "",
        "tone_profile_hash": "",
        "confidence_score": "",
        "evidence_strength_score": "",
        "personalization_quality_score": "",
        "send_confidence": "review",
        "quality_flags": "",
        "source_urls": "",
        "needs_manual_review": True,
        "reviewer_notes": "",
    }
    for column, value in lead.original_columns.items():
        if str(column).strip():
            row[f"input__{str(column).strip()}"] = value
    return row


def _first_name(name: str) -> str:
    cleaned = str(name or "").strip()
    return cleaned.split()[0] if cleaned else "[Name]"


def _template_preview(lead: LeadInput, opening_line: str) -> str:
    line = str(opening_line or "").strip()
    if not line or line.startswith("["):
        return ""
    next_sentence = lead.campaign_context.strip() or _default_next_sentence(lead)
    return f"Hey {_first_name(lead.recipient_name)}\n\n{line}\n\n{next_sentence}"


def _attach_run_metadata(
    row: dict[str, Any],
    client: LLMClient,
    tone_profile_name: str,
    prompt_meta: dict[str, str] | None = None,
    tone_hash: str = "",
) -> dict[str, Any]:
    row["tone_profile"] = tone_profile_name
    row["model_provider"] = client.settings.llm_provider
    row["model_name"] = client.settings.model_name
    row.update(prompt_meta or {})
    row["tone_profile_hash"] = tone_hash
    usage = client.usage_summary()
    row["llm_calls"] = usage["llm_calls"]
    row["estimated_input_tokens"] = usage["estimated_input_tokens"]
    row["estimated_output_tokens"] = usage["estimated_output_tokens"]
    return row


def _looks_app_first(lead: LeadInput, row: dict[str, Any] | None = None, research: ResearchResult | None = None) -> bool:
    row = row or {}
    if row.get("product_surface_type") == "app_first_product":
        return True
    text_parts = [
        lead.website_url,
        lead.optional_notes,
        lead.app_store_url,
        lead.app_flow_observation,
        row.get("app_store_url", ""),
        row.get("app_store_summary", ""),
        row.get("surface_checked", ""),
        row.get("raw_research_summary", ""),
    ]
    if research:
        text_parts.append(research.summary)
    text = " ".join(str(part or "") for part in text_parts).lower()
    domain = urlparse(lead.website_url).netloc.lower()
    app_markers = {
        "app store",
        "google play",
        "download on the app store",
        "get it on google play",
        "mobile app",
        "ios app",
        "android app",
        "the app",
        "download the app",
        "app onboarding",
    }
    return domain.endswith(".app") or bool(lead.app_store_url.strip()) or any(marker in text for marker in app_markers)


def _set_surface_metadata(
    row: dict[str, Any],
    lead: LeadInput,
    research: ResearchResult | None = None,
    deep_research=None,
) -> None:
    surface_type = classify_surface(lead, research, deep_research)
    row["product_surface_type"] = surface_type
    row["research_priority"] = research_priority_for(surface_type)


def _manual_check_recommendation(
    lead: LeadInput,
    row: dict[str, Any],
    research: ResearchResult | None = None,
) -> tuple[str, str]:
    flags = str(row.get("quality_flags", "")).lower()
    visual_confidence = str(row.get("visual_confidence", "")).lower()
    friction_type = str(row.get("friction_type", "")).lower()
    surface = str(row.get("surface_checked", "")).lower()
    notes: list[str] = []

    app_first = _looks_app_first(lead, row, research)
    has_manual_app_observation = bool(str(row.get("app_flow_observation", "") or lead.app_flow_observation).strip())
    if app_first and not has_manual_app_observation:
        notes.append(
            "Open the app or app-store flow if accessible. Check first screen, signup/onboarding steps, time to core value, paywall, booking or subscription flow."
        )
    if "low_confidence_visual_finding" in flags or visual_confidence == "low":
        notes.append("Verify the visual finding manually in the screenshot/browser before using it in a sendable line.")
    if "evidence_failed" in flags or "research_failed" in flags or not str(row.get("evidence_points", "")).strip():
        notes.append("Find one concrete current issue manually: broken formatting, CTA visibility, onboarding/signup friction, weak proof, or broad positioning.")
    if friction_type in {"weak_testimonial_or_case_study", "weak_or_missing_proof"}:
        notes.append("Check whether case studies/testimonials are missing direct quotes, screenshots, concrete outcomes, or on-page proof near the CTA.")
    if friction_type in {"broad_positioning", "unclear_value_prop"}:
        notes.append("Check whether the landing page speaks to too many audiences/use cases and pick the clearest conversion-impact angle.")
    if "app listing" in surface or "app_store_angle_review" in flags:
        notes.append("If possible, confirm the app-store/app-listing hypothesis with a quick app walkthrough before sending.")

    status = "app walkthrough recommended" if app_first and not has_manual_app_observation else "not required"
    if notes:
        return status, " ".join(dict.fromkeys(notes))
    return status, ""


def _placeholder_row(lead: LeadInput, note: str) -> dict[str, Any]:
    row = _base_row(lead)
    row["quality_flags"] = "manual_review"
    row["reviewer_notes"] = join_list(lead.validation_errors + [note])
    return row


def _offline_research_row(lead: LeadInput, settings: Settings, deep_research_enabled: bool) -> dict[str, Any]:
    row = _base_row(lead)
    research = research_company(lead, settings)
    deep_research = None
    notes = research.reviewer_notes.copy()

    if deep_research_enabled:
        deep_research = collect_deep_research(lead, settings)
        research.source_urls = list(dict.fromkeys(research.source_urls + deep_research.source_urls))
        notes.extend(deep_research.reviewer_notes)
        row.update(
            {
                "linkedin_observation": deep_research.linkedin_observation,
                "linkedin_source_note": deep_research.linkedin_source_note,
                "app_store_url": deep_research.app_store_url,
                "app_store_summary": deep_research.app_store_summary,
                "app_review_themes": join_list(deep_research.app_review_themes),
                "app_flow_observation": deep_research.app_flow_observation,
                "app_flow_source_note": deep_research.app_flow_source_note,
                "screenshot_url": deep_research.screenshot_url,
                "recent_news_url": deep_research.recent_news_url,
                "recent_news_note": deep_research.recent_news_note,
                "competitor_context": deep_research.competitor_context,
                "friction_checklist": join_list(deep_research.friction_checklist),
                "app_review_complaints": join_list(deep_research.review_complaints),
            }
        )
    _set_surface_metadata(row, lead, research, deep_research)
    if row["product_surface_type"] == "app_first_product":
        research.summary = join_list(
            [
                f"Product surface type: {row['product_surface_type']}. Research priority: {row['research_priority']}",
                research.summary,
            ]
        )
    row.update(
        {
            "visual_observations": join_list(research.visual_observations),
            "visual_quality_flags": join_list(research.visual_quality_flags),
            "visual_confidence": research.visual_confidence,
            "visual_confidence_score": research.visual_confidence_score,
            "visual_confidence_reasons": join_list(research.visual_confidence_reasons),
            "screenshot_paths": join_list(research.screenshot_paths),
            "trace_files": join_list(research.trace_files),
            "advanced_detector_flags": join_list(research.advanced_detector_flags),
            "ux_validator_findings": join_list(research.ux_validator_findings),
            "dead_link_checks": join_list(research.dead_link_checks),
        }
    )

    evidence_parts: list[str] = []
    for page in research.pages[:2]:
        excerpt = page.text[:700]
        evidence_parts.append(f"Source: {page.url}\nTitle: {page.title}\nText: {excerpt}")
    if deep_research and deep_research.app_store_summary:
        evidence_parts.append(deep_research.app_store_summary[:1000])
    if research.visual_observations:
        evidence_parts.append(
            "Visual review evidence: "
            + join_list(research.visual_observations)
            + f" Visual confidence: {research.visual_confidence or 'none'} ({research.visual_confidence_score}/100). "
            + join_list(research.visual_confidence_reasons)
            + " Screenshot paths: "
            + join_list(research.screenshot_paths)
        )
    if row.get("product_surface_type") == "app_first_product":
        evidence_parts.insert(0, f"Research priority: {row.get('research_priority')}")
    if row.get("app_review_themes"):
        evidence_parts.insert(0, "Public review theme clusters: " + row["app_review_themes"])
    if row.get("app_review_complaints"):
        evidence_parts.insert(0, "Public review complaint signals: " + row["app_review_complaints"])
    if research.ux_validator_findings or research.dead_link_checks:
        evidence_parts.append(
            "Internal UX validator evidence, do not copy technical wording directly: "
            + join_list(research.ux_validator_findings[:8])
            + (" Dead link checks: " + join_list(research.dead_link_checks[:8]) if research.dead_link_checks else "")
        )

    row.update(
        {
            "raw_research_summary": research.summary,
            "evidence_points": join_list(evidence_parts),
            "source_urls": join_list(research.source_urls),
            "send_confidence": "review",
            "quality_flags": join_list(
                ["offline_research_only", "ai_generation_unavailable", join_list(research.visual_quality_flags)]
            ),
            "needs_manual_review": True,
            "reviewer_notes": join_list(
                notes
                + [
                    "Research-only output because AI writing is unavailable without active API quota."
                ]
            ),
        }
    )
    app_check_status, manual_check = _manual_check_recommendation(lead, row, research)
    row["app_check_status"] = app_check_status
    row["recommended_manual_check"] = manual_check
    return row


def _copy_personalization_for_contact(row: dict[str, Any], lead: LeadInput) -> dict[str, Any]:
    copied = dict(row)
    copied.update(
        {
            "company_name": lead.company_name,
            "website_url": lead.website_url,
            "linkedin_url": lead.linkedin_url,
            "recipient_name": lead.recipient_name,
            "recipient_role": lead.recipient_role,
            "campaign_context": lead.campaign_context,
            "linkedin_observation": lead.linkedin_observation,
            "linkedin_source_note": lead.linkedin_source_note,
            "app_store_url": lead.app_store_url,
            "app_flow_observation": lead.app_flow_observation,
            "app_flow_source_note": lead.app_flow_source_note,
            "screenshot_url": lead.screenshot_url,
            "recent_news_url": lead.recent_news_url,
            "recent_news_note": lead.recent_news_note,
            "competitor_context": lead.competitor_context,
        }
    )
    for key in list(copied.keys()):
        if key.startswith("input__"):
            copied.pop(key, None)
    for column, value in lead.original_columns.items():
        if str(column).strip():
            copied[f"input__{str(column).strip()}"] = value
    note = copied.get("reviewer_notes", "")
    copied["reviewer_notes"] = join_list([note, "Reused personalization from duplicate company row"])
    copied["template_preview"] = _template_preview(lead, copied.get("opening_line", ""))
    for index in range(1, 4):
        copied[f"template_preview_option_{index}"] = _template_preview(
            lead,
            copied.get(f"opening_line_option_{index}", ""),
        )
    app_check_status, manual_check = _manual_check_recommendation(lead, copied)
    copied["app_check_status"] = app_check_status
    copied["recommended_manual_check"] = manual_check
    return copied


def _format_evidence(evidence: EvidenceResult) -> str:
    parts = []
    for fact in evidence.facts:
        generic = "generic" if fact.too_generic_to_use else "specific"
        detail = ", ".join(
            value
            for value in [
                fact.strength,
                generic,
                fact.friction_type,
                fact.surface_checked,
                fact.conversion_outcome,
            ]
            if value
        )
        parts.append(f"{fact.fact} ({detail}, source: {fact.source_url})")
    return join_list(parts)


def _top_evidence_fact(evidence: EvidenceResult):
    usable = [fact for fact in evidence.facts if not fact.too_generic_to_use]
    candidates = usable or evidence.facts
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda fact: (
            fact.angle_priority or 99,
            {"strong": 0, "medium": 1, "weak": 2}.get(fact.strength, 3),
            bool(fact.blog_used),
        ),
    )[0]


def _evidence_strength_score(evidence: EvidenceResult) -> int:
    score = 0
    for fact in evidence.facts:
        if fact.too_generic_to_use:
            continue
        if fact.strength == "strong":
            score += 2
        elif fact.strength == "medium":
            score += 1
    return max(1, min(5, score)) if evidence.facts else 0


def _variant_evidence(
    evidence: EvidenceResult,
    fact: EvidenceFact,
    allowed_facts: list[EvidenceFact],
    excluded_friction_types: set[str] | None = None,
) -> EvidenceResult:
    excluded = excluded_friction_types or set()
    supporting_facts = [
        candidate
        for candidate in allowed_facts
        if candidate is not fact
        and candidate.friction_type not in excluded
        and (
            candidate.conversion_outcome == fact.conversion_outcome
            or candidate.surface_checked == fact.surface_checked
        )
    ]
    selected_facts = [fact] + supporting_facts[:1]
    selected_angles = [
        f"{candidate.friction_type}: {candidate.fact} Outcome: {candidate.conversion_outcome}".strip()
        for candidate in selected_facts
    ]
    return EvidenceResult(
        facts=selected_facts,
        possible_angles=selected_angles,
        needs_manual_review=evidence.needs_manual_review,
        reviewer_notes=evidence.reviewer_notes,
        raw=evidence.raw,
    )


def _write_and_qc_variant(
    client: LLMClient,
    lead: LeadInput,
    evidence: EvidenceResult,
    tone_profile,
    variant_index: int,
    avoid_opening_lines: list[str],
    variant_instruction: str,
    max_iterations: int = 3,
    feedback_context: str = "",
    research_depth: float = 1.0,
) -> tuple[PersonalizationDraft, QCResult]:
    """Generate + QC a personalization variant with iterative refinement.

    Each iteration:
      1. Generate draft at decreasing temperature (0.6 → 0.4)
      2. Run quality check
      3. If QC fails, feed suggested_rewrite back as starting point
      4. Track best result across all iterations
      5. Early exit on score >= 8 with no blocking flags
    """
    best_draft: PersonalizationDraft | None = None
    best_qc: QCResult | None = None
    last_qc_suggested_rewrite: dict[str, str] = {}
    used_opening_lines: list[str] = list(avoid_opening_lines)
    previous_failure_reasons: list[str] = []

    for iteration in range(max_iterations):
        # Temperature decay: 0.6, 0.55, 0.5, ... floor at 0.4
        temperature = max(0.4, 0.6 - 0.05 * iteration)
        qc_temperature = max(0.3, 0.4 - 0.05 * iteration)

        draft = write_personalization(
            client,
            lead,
            evidence,
            tone_profile,
            previous_failure_reasons=previous_failure_reasons if iteration > 0 else None,
            variant_index=variant_index,
            avoid_opening_lines=used_opening_lines,
            variant_instruction=variant_instruction,
            qc_suggested_rewrite=last_qc_suggested_rewrite if iteration > 0 else None,
            temperature=temperature,
            feedback_context=feedback_context,
            research_depth=research_depth,
        )
        qc = check_quality(
            client, lead, evidence, draft, tone_profile,
            temperature=qc_temperature,
            feedback_context=feedback_context,
            research_depth=research_depth,
        )

        logging.info(
            "Variant %d iteration %d/%d: score=%d passed=%s flags=%s temp=%.2f",
            variant_index,
            iteration + 1,
            max_iterations,
            qc.score,
            qc.passed,
            qc.quality_flags,
            temperature,
        )

        # Track best result seen so far (prefer passing > higher score > newer)
        if best_qc is None or qc.passed and not best_qc.passed or (
            qc.score > best_qc.score and qc.passed == best_qc.passed
        ):
            best_draft = draft
            best_qc = qc

        # Early exit: strong pass, no need to refine further
        if qc.passed and qc.score >= 8:
            break

        # Prepare feedback for next iteration
        previous_failure_reasons = qc.reasons + qc.quality_flags
        if qc.suggested_rewrite:
            last_qc_suggested_rewrite = qc.suggested_rewrite
        used_opening_lines.append(draft.opening_line)

    assert best_draft is not None and best_qc is not None
    if not best_qc.passed:
        logging.info(
            "Variant %d: best score after %d iteration(s) was %d (did not pass)",
            variant_index,
            max_iterations,
            best_qc.score,
        )
    return best_draft, best_qc


def _store_variant(
    row: dict[str, Any],
    lead: LeadInput,
    index: int,
    draft: PersonalizationDraft,
    qc: QCResult,
    needs_review: bool,
) -> None:
    row[f"opening_line_option_{index}"] = draft.opening_line
    row[f"tailored_insight_option_{index}"] = draft.tailored_insight
    row[f"chosen_angle_option_{index}"] = draft.chosen_angle
    row[f"evidence_used_for_copy_option_{index}"] = join_list(draft.evidence_used_for_copy)
    row[f"confidence_score_option_{index}"] = qc.score
    row[f"quality_flags_option_{index}"] = join_list(qc.quality_flags)
    row[f"needs_manual_review_option_{index}"] = needs_review
    row[f"reviewer_notes_option_{index}"] = join_list(qc.reasons)
    row[f"template_preview_option_{index}"] = _template_preview(lead, draft.opening_line)


def _best_variant_index(variants: list[tuple[int, PersonalizationDraft, QCResult, bool]]) -> int:
    if not variants:
        return 0
    ordered = sorted(
        variants,
        key=lambda item: (
            item[3],
            -item[2].score,
            bool(SERIOUS_QUALITY_FLAGS.intersection(set(item[2].quality_flags))),
            item[0],
        ),
    )
    return ordered[0][0]


def _process_valid_lead(
    client: LLMClient,
    lead: LeadInput,
    manual_review_mode: bool,
    deep_research_enabled: bool,
    tone_profile_name: str,
    feedback_context: str = "",
) -> dict[str, Any]:
    row = _base_row(lead)

    # Lead-weighted research: schaal research-inspanning op basis van research_depth
    max_pages = max(1, round(lead.research_depth * client.settings.max_pages_per_company))
    research = research_company(lead, client.settings, max_pages=max_pages)

    # Deep research alleen voor leads met voldoende depth
    deep_research = None
    effective_deep_research = deep_research_enabled and lead.research_depth >= 0.6
    if effective_deep_research:
        deep_research = collect_deep_research(lead, client.settings)
        deep_prompt_text = deep_research.to_prompt_text()
        if deep_prompt_text:
            research.summary = join_list([research.summary, f"Deep personalization context:\n{deep_prompt_text}"])
        research.source_urls = list(dict.fromkeys(research.source_urls + deep_research.source_urls))
        research.reviewer_notes.extend(deep_research.reviewer_notes)
        row.update(
            {
                "linkedin_observation": deep_research.linkedin_observation,
                "linkedin_source_note": deep_research.linkedin_source_note,
                "app_store_url": deep_research.app_store_url,
                "app_store_summary": deep_research.app_store_summary,
                "app_review_themes": join_list(deep_research.app_review_themes),
                "app_flow_observation": deep_research.app_flow_observation,
                "app_flow_source_note": deep_research.app_flow_source_note,
                "screenshot_url": deep_research.screenshot_url,
                "recent_news_url": deep_research.recent_news_url,
                "recent_news_note": deep_research.recent_news_note,
                "competitor_context": deep_research.competitor_context,
                "friction_checklist": join_list(deep_research.friction_checklist),
                "app_review_complaints": join_list(deep_research.review_complaints),
            }
        )
    _set_surface_metadata(row, lead, research, deep_research)
    research.summary = join_list(
        [
            f"Product surface type: {row['product_surface_type']}. Research priority: {row['research_priority']}",
            research.summary,
        ]
    )
    row.update(
        {
            "visual_observations": join_list(research.visual_observations),
            "visual_quality_flags": join_list(research.visual_quality_flags),
            "visual_confidence": research.visual_confidence,
            "visual_confidence_score": research.visual_confidence_score,
            "visual_confidence_reasons": join_list(research.visual_confidence_reasons),
            "screenshot_paths": join_list(research.screenshot_paths),
            "trace_files": join_list(research.trace_files),
            "advanced_detector_flags": join_list(research.advanced_detector_flags),
            "ux_validator_findings": join_list(research.ux_validator_findings),
            "dead_link_checks": join_list(research.dead_link_checks),
        }
    )
    row["raw_research_summary"] = research.summary
    row["source_urls"] = join_list(research.source_urls)
    if research.visual_quality_flags or research.advanced_detector_flags:
        row["quality_flags"] = join_list(
            [
                row.get("quality_flags", ""),
                join_list(research.visual_quality_flags),
                join_list(research.advanced_detector_flags),
            ]
        )

    if not research.summary.strip():
        row["quality_flags"] = "research_failed"
        row["reviewer_notes"] = join_list(research.reviewer_notes)
        if manual_review_mode:
            app_check_status, manual_check = _manual_check_recommendation(lead, row, research)
            row["app_check_status"] = app_check_status
            row["recommended_manual_check"] = manual_check
            return row
        raise RuntimeError(f"Research failed for {lead.company_name}: {row['reviewer_notes']}")

    tone_profile = load_tone_profile(tone_profile_name)
    evidence = extract_evidence(client, lead, research, tone_profile)
    row["evidence_points"] = _format_evidence(evidence)
    selection = select_angle(evidence)
    gated_evidence = evidence_for_selected_angle(evidence, selection)
    evidence_strength_score = _evidence_strength_score(gated_evidence)
    row.update(
        {
            "angle_gate_decision": selection.decision,
            "angle_gate_notes": join_list(selection.reviewer_notes),
            "blocked_angles": join_list(selection.blocked_facts[:6]),
        }
    )

    if selection.selected_fact:
        selected_fact = selection.selected_fact
        row.update(
            {
                "friction_type": selected_fact.friction_type,
                "surface_checked": selected_fact.surface_checked,
                "conversion_outcome": selected_fact.conversion_outcome,
                "angle_priority": selected_fact.angle_priority,
                "blog_used": selected_fact.blog_used,
                "why_this_angle": selected_fact.why_this_angle,
            }
        )
        if selected_fact.blog_used:
            row["quality_flags"] = join_list([row.get("quality_flags", ""), "blog_angle_low_value"])

    if not evidence.facts:
        row["quality_flags"] = "evidence_failed"
        row["reviewer_notes"] = join_list(research.reviewer_notes + evidence.reviewer_notes)
        if manual_review_mode:
            app_check_status, manual_check = _manual_check_recommendation(lead, row, research)
            row["app_check_status"] = app_check_status
            row["recommended_manual_check"] = manual_check
            return row
        raise RuntimeError(f"Evidence extraction failed for {lead.company_name}: {row['reviewer_notes']}")

    if selection.selected_fact is None:
        row["quality_flags"] = join_list([row.get("quality_flags", ""), join_list(selection.quality_flags)])
        row["reviewer_notes"] = join_list(
            research.reviewer_notes + evidence.reviewer_notes + selection.reviewer_notes
        )
        row["needs_manual_review"] = True
        row["send_confidence"] = "review"
        app_check_status, manual_check = _manual_check_recommendation(lead, row, research)
        row["app_check_status"] = app_check_status
        row["recommended_manual_check"] = manual_check
        return row

    variant_facts = selection.allowed_facts[: client.settings.personalization_options]
    while variant_facts and len(variant_facts) < client.settings.personalization_options:
        variant_facts.append(variant_facts[-1])
    variants: list[tuple[int, PersonalizationDraft, QCResult, bool]] = []
    avoid_opening_lines: list[str] = []
    variant_instructions = [
        "Option 1: choose the strongest sendable friction angle.",
        "Option 2: choose a meaningfully different angle if evidence allows, ideally user feedback, app-store review, onboarding, or conversion friction.",
        "Option 3: choose another distinct angle if evidence allows, ideally proof, positioning, CTA, website, or visual friction.",
    ]
    for variant_index, fact in enumerate(variant_facts[: client.settings.personalization_options], 1):
        # Forceer evidence diversiteit: sluit friction types uit die al gebruikt zijn
        excluded = frozenset(
            variants[i][2].chosen_angle.split(":")[0].strip()
            for i in range(len(variants))
            if variants[i][2].chosen_angle and ":" in variants[i][2].chosen_angle
        )
        variant_evidence = _variant_evidence(evidence, fact, selection.allowed_facts, excluded_friction_types=excluded)
        draft, qc = _write_and_qc_variant(
            client,
            lead,
            variant_evidence,
            tone_profile,
            variant_index,
            avoid_opening_lines,
            variant_instructions[min(variant_index - 1, len(variant_instructions) - 1)],
            max_iterations=client.settings.max_refinement_iterations,
            feedback_context=feedback_context,
        )
        variant_flags = set(selection.quality_flags).union(qc.quality_flags)
        variant_needs_review = (
            research.needs_manual_review
            or variant_evidence.needs_manual_review
            or selection.needs_manual_review
            or not qc.passed
            or qc.score < 8
            or bool(SERIOUS_QUALITY_FLAGS.intersection(variant_flags))
        )
        _store_variant(row, lead, variant_index, draft, qc, variant_needs_review)
        variants.append((variant_index, draft, qc, variant_needs_review))
        if draft.opening_line:
            avoid_opening_lines.append(draft.opening_line)

        # Vroege afsluiting: als variant 1 al >= 8 scoort en geen serieuze flags heeft,
        # hoeven we geen extra varianten te genereren.
        if variant_index >= 1 and qc.passed and qc.score >= 10 and not bool(
            SERIOUS_QUALITY_FLAGS.intersection(variant_flags)
        ):
            break

    best_index = _best_variant_index(variants)
    if best_index == 0:
        draft = PersonalizationDraft()
        qc = QCResult(score=0, passed=False, reasons=["No personalization options were generated"], quality_flags=["manual_review_needed"])
        needs_review = True
    else:
        _, draft, qc, needs_review = next(item for item in variants if item[0] == best_index)

    existing_flags = {
        flag.strip()
        for flag in str(row.get("quality_flags", "")).replace(";", "|").split("|")
        if flag.strip()
    }
    combined_flags = existing_flags.union(set(selection.quality_flags)).union(set(qc.quality_flags))
    needs_review = needs_review or bool(SERIOUS_QUALITY_FLAGS.intersection(combined_flags))

    notes = research.reviewer_notes + evidence.reviewer_notes + selection.reviewer_notes + qc.reasons
    row.update(
        {
            "evidence_used_for_copy": join_list(draft.evidence_used_for_copy),
            "chosen_angle": draft.chosen_angle,
            "opening_line": draft.opening_line,
            "tailored_insight": draft.tailored_insight,
            "template_preview": _template_preview(lead, draft.opening_line),
            "confidence_score": qc.score,
            "evidence_strength_score": evidence_strength_score,
            "personalization_quality_score": qc.score,
            "send_confidence": "send" if not needs_review and evidence_strength_score >= 3 else "review",
            "quality_flags": join_list(
                [row.get("quality_flags", ""), join_list(selection.quality_flags), join_list(qc.quality_flags)]
            ),
            "needs_manual_review": needs_review,
            "reviewer_notes": join_list(notes),
        }
    )
    app_check_status, manual_check = _manual_check_recommendation(lead, row, research)
    row["app_check_status"] = app_check_status
    row["recommended_manual_check"] = manual_check
    return row


def _process_single_lead(
    settings: Settings,
    args: argparse.Namespace,
    lead: LeadInput,
    tone_profile_name: str,
    prompt_meta: dict[str, str],
    tone_hash: str,
    rate_limiter: RateLimiter | None = None,
    feedback_context: str = "",
) -> dict[str, Any]:
    """Worker-functie: verwerk één lead met een eigen LLMClient (thread-safe)."""
    client = LLMClient(settings, rate_limiter=rate_limiter)

    lead_label = lead.company_name or lead.website_url or "unnamed row"

    if not lead.is_valid:
        row = _attach_run_metadata(
            _placeholder_row(lead, "Row was not processed because input validation failed"),
            client,
            tone_profile_name,
            prompt_meta,
            tone_hash,
        )
        return _row_to_dict(row, lead_label, "validation_failed")

    if not client.available:
        row = _offline_research_row(lead, settings, args.deep_research)
        missing_key_note = f"{settings.llm_provider.upper()}_API_KEY is missing."
        row["reviewer_notes"] = join_list([row.get("reviewer_notes", ""), missing_key_note])
        row = _attach_run_metadata(row, client, tone_profile_name, prompt_meta, tone_hash)
        return _row_to_dict(row, lead_label, "offline")

    try:
        row = _process_valid_lead(
            client, lead, args.manual_review_mode, args.deep_research,
            tone_profile_name, feedback_context=fb_context,
        )
        row = _attach_run_metadata(row, client, tone_profile_name, prompt_meta, tone_hash)
        return _row_to_dict(row, lead_label, "complete")
    except Exception as exc:
        logging.exception("Failed to process %s", lead.company_name)
        if args.manual_review_mode:
            row = _placeholder_row(lead, f"Processing failed: {exc}")
            row = _attach_run_metadata(row, client, tone_profile_name, prompt_meta, tone_hash)
            return _row_to_dict(row, lead_label, "failed_review")
        raise


def _row_to_dict(row: dict[str, Any], company: str, status: str) -> dict[str, Any]:
    """Helper om resultaat terug te sturen met statusinformatie."""
    row["_status"] = status
    row["_company"] = company
    return row


def run_batch(args: argparse.Namespace, progress_callback: ProgressCallback | None = None) -> list[dict[str, Any]]:
    ensure_directories()
    settings = load_settings()
    tone_profile_name = str(getattr(args, "tone_profile", "") or settings.tone_profile)
    prompt_meta = prompt_hashes()
    tone_profile_for_hash = load_tone_profile(tone_profile_name)
    tone_hash = tone_profile_hash(tone_profile_for_hash.to_prompt_payload())
    run_id = uuid.uuid4().hex[:16]

    if not getattr(args, "skip_preflight", False):
        checks = run_preflight(settings, output_dir=Path(args.output).parent, check_api=False)
        if has_blocking_failures(checks):
            raise RuntimeError("Pre-flight system check failed:\n" + preflight_summary(checks))

    leads = load_leads(args.input, args.campaign_context, deduplicate=not args.reuse_duplicate_personalization)
    total = len(leads)

    _emit_progress(
        progress_callback,
        event="start",
        current=0,
        total=total,
        progress=0.0,
        stage="Starting parallel batch",
        company="",
    )

    # ---- Determine key/API mode ----
    if settings.llm_provider == "gemini":
        key_name = "GEMINI_API_KEY"
    elif settings.llm_provider == "openrouter":
        key_name = "OPENROUTER_API_KEY"
    elif settings.llm_provider == "deepseek":
        key_name = "DEEPSEEK_API_KEY"
    else:
        key_name = "OPENAI_API_KEY"

    ai_available = True
    ai_unavailable_note = ""
    # Gedeelde rate limiter voor alle workers (token-bucket, thread-safe)
    rate_limiter = RateLimiter(
        max_requests=settings.max_requests_per_minute,
        window_seconds=60.0,
    )
    master_client = LLMClient(settings, rate_limiter=rate_limiter)
    if master_client.available:
        ok, preflight_note = master_client.validate_access()
        if ok:
            logging.info("AI preflight check passed for %s", settings.llm_provider)
        else:
            ai_available = False
            ai_unavailable_note = (
                f"AI generation disabled for this run because the {settings.llm_provider} preflight check failed: "
                f"{preflight_note}. Research, visual review and workbook export still ran."
            )
            logging.error(ai_unavailable_note)
    else:
        ai_available = False
        missing_key_note = f"{key_name} is missing. Input was validated, but AI generation and QC require an API key."
        ai_unavailable_note = missing_key_note

    # When no AI is available, only research/scraping runs -> safe to use more workers
    max_workers = settings.max_workers
    if not ai_available:
        max_workers = max(max_workers, 8)

    logging.info("Parallel batch: %d leads, %d workers", total, max_workers)

    # ---- Feedback-context: historische sends ophalen ----
    init_feedback_db()
    fb_context = build_feedback_context()
    if fb_context:
        logging.info("Feedback context loaded from previous sends.")

    # ---- Checkpoint: laad reeds verwerkte resultaten ----
    existing_checkpoint = load_checkpoint(args.output)
    if existing_checkpoint:
        logging.info(
            "Checkpoint gevonden: %d van %d leads reeds verwerkt. Doorgaan...",
            len(existing_checkpoint),
            total,
        )
    rows_by_index: dict[int, dict[str, Any]] = {}
    futures = {}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for index, lead in enumerate(leads, 1):
            # Sla leads over die al in het checkpoint zitten
            if index in existing_checkpoint:
                rows_by_index[index] = existing_checkpoint[index]
                continue
            future = pool.submit(
                _process_single_lead,
                settings,
                args,
                lead,
                tone_profile_name,
                prompt_meta,
                tone_hash,
                rate_limiter,
                fb_context,
            )
            futures[future] = index

        completed = len(rows_by_index)
        for future in as_completed(futures):
            index = futures[future]
            lead = leads[index - 1]
            lead_label = lead.company_name or lead.website_url or f"Row {index}"
            try:
                result_row = future.result()
                status = result_row.pop("_status", "unknown")
                result_row.pop("_company", None)
                rows_by_index[index] = result_row
            except Exception as exc:
                logging.exception("Fatal error processing %s", lead_label)
                if args.manual_review_mode:
                    placeholder = _placeholder_row(lead, f"Fatal error: {exc}")
                    placeholder = _attach_run_metadata(
                        placeholder, master_client, tone_profile_name, prompt_meta, tone_hash
                    )
                    rows_by_index[index] = placeholder
                else:
                    raise
            completed += 1
            # ---- Checkpoint na elke lead ----
            save_checkpoint(rows_by_index, args.output)
            _emit_progress(
                progress_callback,
                event="batch_progress",
                current=completed,
                total=total,
                progress=completed / total if total else 1.0,
                stage="Processing (parallel)",
                company=lead_label,
            )

    # ---- Assemble rows in original order ----
    rows = [rows_by_index[i] for i in range(1, total + 1)]

    # ---- Post-processing (sequential, fast) ----
    usage = master_client.usage_summary()
    for row_index, row in enumerate(rows, 1):
        row["run_id"] = row.get("run_id") or run_id
        row["row_id"] = row.get("row_id") or str(row_index)
        row["example_id"] = row.get("example_id") or stable_hash(
            row["run_id"],
            row["row_id"],
            row.get("company_name", ""),
            row.get("recipient_name", ""),
            row.get("opening_line", ""),
        )
        row.update(usage)
        row.update(prompt_meta)
        row["tone_profile_hash"] = tone_hash

    # ---- Opruimen: checkpoint is niet meer nodig ----
    cleanup_checkpoint(args.output)

    append_generated_email_rows(rows)
    _emit_progress(
        progress_callback,
        event="export",
        current=total,
        total=total,
        progress=1.0,
        stage="Exporting workbook",
        company="",
    )

    if args.client_batch_output:
        export_client_batch_rows(rows, args.output)
    else:
        export_rows(rows, args.output)
    sending_preset = str(getattr(args, "sending_tool_preset", "") or "").strip()
    if sending_preset:
        sending_output = str(getattr(args, "sending_tool_output", "") or "").strip()
        if not sending_output:
            base = Path(args.output)
            sending_output = str(base.with_name(f"{base.stem}_{sending_preset}.csv"))
        export_sending_tool_rows(rows, sending_output, preset=sending_preset)
        logging.info("Exported %s sending-tool rows to %s", sending_preset, sending_output)

    logging.info("Exported %s rows to %s", len(rows), args.output)

    # ---- Feedback: gegenereerde emails opslaan voor toekomstige leerling ----
    feedback_stored = store_generated_emails(rows)
    if feedback_stored:
        logging.info("Stored %d generated emails in feedback database for future learning.", feedback_stored)

    _emit_progress(
        progress_callback,
        event="complete",
        current=total,
        total=total,
        progress=1.0,
        stage="Complete",
        company="",
    )
    return rows


class BatchRunner:
    def __init__(self, args: argparse.Namespace, progress_callback: ProgressCallback | None = None) -> None:
        self.args = args
        self.progress_callback = progress_callback

    def run(self) -> list[dict[str, Any]]:
        return run_batch(self.args, self.progress_callback)


def run(args: argparse.Namespace, progress_callback: ProgressCallback | None = None) -> list[dict[str, Any]]:
    return BatchRunner(args, progress_callback).run()