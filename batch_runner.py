from __future__ import annotations

import argparse
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from angle_selector import evidence_for_selected_angle, select_angle
from checkpoint import cleanup_checkpoint, load_checkpoint, save_checkpoint
from config import Settings, ensure_directories, load_settings
from deep_research import collect_deep_research
from email_verification import verify_lead_email
from evidence_extractor import evidence_to_payload, extract_evidence
from export import export_client_batch_rows, export_delivery_rows, export_rows, export_sending_tool_rows
from input_loader import dedupe_key, load_leads
from lead_quality import LeadQualityContext, build_lead_quality_context, evaluate_lead_quality
from llm_client import LLMClient
from mismatch_detection import apply_mismatch_to_row
from models import EvidenceFact, EvidenceResult, LeadInput, PersonalizationDraft, QCResult, ResearchResult, join_list
from copy_guardrails import soften_draft_for_weak_evidence
from personalization_writer import write_personalization
from preflight import has_blocking_failures, preflight_summary, run_preflight
from prompt_versions import prompt_hashes, tone_profile_hash
from quality_checker import check_quality
from rate_limiter import RateLimiter
from research_tasks import recommended_research_context, run_research_tasks
from run_history import append_generated_email_rows
from sales_principles import SalesPrinciplesResult, evaluate_sales_principles
from schemas import stable_hash
from sendability import evaluate_sendability
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
    "fake_familiarity_claim",
    "unsupported_meaningful_claim",
    "unsupported_implication",
    "input_mapping_warning",
    "salesy_language",
    "low_specificity",
    "company_name_not_lowercase",
}


def _emit_progress(progress_callback: ProgressCallback | None, **payload: Any) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(payload)
    except Exception:
        logging.debug("Progress callback failed", exc_info=True)


def _base_row(lead: LeadInput, lead_quality_context: LeadQualityContext | None = None) -> dict[str, Any]:
    email_verification = verify_lead_email(lead.original_columns)
    lead_quality = evaluate_lead_quality(lead, lead_quality_context, email_verification)
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
        "friction_checklist": "",
        "app_check_status": "",
        "recommended_manual_check": "",
        "lead_quality_score": lead_quality.lead_quality_score,
        "lead_quality_flags": join_list(lead_quality.lead_quality_flags),
        "missing_required_fields": join_list(lead_quality.missing_required_fields),
        "duplicate_company": lead_quality.duplicate_company,
        "duplicate_contact": lead_quality.duplicate_contact,
        "app_link_status": lead_quality.app_link_status,
        "ready_for_personalization": lead_quality.ready_for_personalization,
        "lead_quality_notes": lead_quality.lead_quality_notes,
        "email_verification_status": email_verification.status,
        "email_verification_confidence": email_verification.confidence,
        "email_verification_reason": email_verification.reason,
        "company_website_mismatch": "",
        "person_company_mismatch": "",
        "input_mapping_warning": "",
        "mismatch_reason": "",
        "product_surface_type": "",
        "research_priority": "",
        "research_revenue_model": "",
        "research_revenue_model_confidence": "",
        "research_revenue_model_evidence": "",
        "research_revenue_model_source_url": "",
        "research_target_customer": "",
        "research_target_customer_confidence": "",
        "research_target_customer_evidence": "",
        "research_target_customer_source_url": "",
        "research_website_tech_stack": "",
        "research_website_tech_stack_confidence": "",
        "research_website_tech_stack_evidence": "",
        "research_latest_funding_details": "",
        "research_latest_funding_confidence": "",
        "research_latest_funding_source_url": "",
        "research_traffic_summary": "",
        "research_traffic_confidence": "",
        "research_traffic_source": "",
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
        "opener_option_1": "",
        "opener_option_1_angle": "",
        "opener_option_1_evidence": "",
        "opener_option_1_source_url": "",
        "opener_option_1_sendability": "",
        "opener_option_1_sendability_score": "",
        "opener_option_1_quality_flags": "",
        "opener_option_1_sales_principles_summary": "",
        "opener_option_1_rejection_or_edit_reason": "",
        "opening_line_option_1": "",
        "tailored_insight_option_1": "",
        "chosen_angle_option_1": "",
        "evidence_used_for_copy_option_1": "",
        "confidence_score_option_1": "",
        "quality_flags_option_1": "",
        "needs_manual_review_option_1": "",
        "reviewer_notes_option_1": "",
        "template_preview_option_1": "",
        "opener_option_2": "",
        "opener_option_2_angle": "",
        "opener_option_2_evidence": "",
        "opener_option_2_source_url": "",
        "opener_option_2_sendability": "",
        "opener_option_2_sendability_score": "",
        "opener_option_2_quality_flags": "",
        "opener_option_2_sales_principles_summary": "",
        "opener_option_2_rejection_or_edit_reason": "",
        "opening_line_option_2": "",
        "tailored_insight_option_2": "",
        "chosen_angle_option_2": "",
        "evidence_used_for_copy_option_2": "",
        "confidence_score_option_2": "",
        "quality_flags_option_2": "",
        "needs_manual_review_option_2": "",
        "reviewer_notes_option_2": "",
        "template_preview_option_2": "",
        "opener_option_3": "",
        "opener_option_3_angle": "",
        "opener_option_3_evidence": "",
        "opener_option_3_source_url": "",
        "opener_option_3_sendability": "",
        "opener_option_3_sendability_score": "",
        "opener_option_3_quality_flags": "",
        "opener_option_3_sales_principles_summary": "",
        "opener_option_3_rejection_or_edit_reason": "",
        "opening_line_option_3": "",
        "tailored_insight_option_3": "",
        "chosen_angle_option_3": "",
        "evidence_used_for_copy_option_3": "",
        "confidence_score_option_3": "",
        "quality_flags_option_3": "",
        "needs_manual_review_option_3": "",
        "reviewer_notes_option_3": "",
        "template_preview_option_3": "",
        "recommended_opener": "",
        "recommended_opener_option": "",
        "recommended_opener_reason": "",
        "selected_opener": "",
        "selected_opener_source": "",
        "edited_final_opener": "",
        "human_decision": "unreviewed",
        "edit_reason_category": "not_reviewed",
        "edit_notes": "",
        "specificity_score": "",
        "one_insight_score": "",
        "friction_relevance_score": "",
        "outcome_bridge_score": "",
        "commercial_relevance_score": "",
        "signal_to_implication_bridge_score": "",
        "salesy_language_flag": "",
        "fake_familiarity_flag": "",
        "evidence_supported_claim_score": "",
        "sales_principles_score": "",
        "sales_principles_summary": "",
        "sales_principles_reasons": "",
        "prompt_set_hash": "",
        "evidence_prompt_hash": "",
        "write_prompt_hash": "",
        "qc_prompt_hash": "",
        "tone_profile_hash": "",
        "confidence_score": "",
        "evidence_strength_score": "",
        "personalization_quality_score": "",
        "send_confidence": "review",
        "quality_flags": join_list(lead_quality.lead_quality_flags),
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
    next_sentence = lead.campaign_context.strip() or PITCH_SENTENCE
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


def _apply_mismatch_flags(row: dict[str, Any]) -> dict[str, Any]:
    row.update(apply_mismatch_to_row(row))
    if str(row.get("input_mapping_warning", "")).lower() == "yes":
        row["quality_flags"] = join_list([row.get("quality_flags", ""), "input_mapping_warning"])
        row["needs_manual_review"] = True
    return row


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


def _placeholder_row(
    lead: LeadInput,
    note: str,
    lead_quality_context: LeadQualityContext | None = None,
) -> dict[str, Any]:
    row = _base_row(lead, lead_quality_context)
    row["quality_flags"] = "manual_review"
    row["reviewer_notes"] = join_list(lead.validation_errors + [note])
    return row


def _offline_research_row(
    lead: LeadInput,
    settings: Settings,
    deep_research_enabled: bool,
    lead_quality_context: LeadQualityContext | None = None,
) -> dict[str, Any]:
    row = _base_row(lead, lead_quality_context)
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
    research_fields = run_research_tasks(lead, research, settings)
    row.update({key: value for key, value in research_fields.items() if not key.startswith("_")})
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
    research_context = recommended_research_context(research_fields)
    if research_context:
        evidence_parts.append("Structured enrichment usable for opener: " + research_context)
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


def _copy_personalization_for_contact(
    row: dict[str, Any],
    lead: LeadInput,
    lead_quality_context: LeadQualityContext | None = None,
) -> dict[str, Any]:
    copied = dict(row)
    email_verification = verify_lead_email(lead.original_columns)
    lead_quality = evaluate_lead_quality(lead, lead_quality_context, email_verification)
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
            "lead_quality_score": lead_quality.lead_quality_score,
            "lead_quality_flags": join_list(lead_quality.lead_quality_flags),
            "missing_required_fields": join_list(lead_quality.missing_required_fields),
            "duplicate_company": lead_quality.duplicate_company,
            "duplicate_contact": lead_quality.duplicate_contact,
            "app_link_status": lead_quality.app_link_status,
            "ready_for_personalization": lead_quality.ready_for_personalization,
            "lead_quality_notes": lead_quality.lead_quality_notes,
            "email_verification_status": email_verification.status,
            "email_verification_confidence": email_verification.confidence,
            "email_verification_reason": email_verification.reason,
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
    copied["selected_opener"] = copied.get("recommended_opener", copied.get("opening_line", ""))
    copied["selected_opener_source"] = copied.get("recommended_opener_option", "")
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


def _variant_evidence(evidence: EvidenceResult, fact: EvidenceFact, allowed_facts: list[EvidenceFact]) -> EvidenceResult:
    supporting_facts = [
        candidate
        for candidate in allowed_facts
        if candidate is not fact
        and (
            candidate.friction_type == fact.friction_type
            or candidate.conversion_outcome == fact.conversion_outcome
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
) -> tuple[PersonalizationDraft, QCResult]:
    draft = write_personalization(
        client,
        lead,
        evidence,
        tone_profile,
        variant_index=variant_index,
        avoid_opening_lines=avoid_opening_lines,
        variant_instruction=variant_instruction,
    )
    draft = soften_draft_for_weak_evidence(draft, evidence)
    qc = check_quality(client, lead, evidence, draft, tone_profile)
    if not qc.passed:
        rewrite_reasons = qc.reasons + qc.quality_flags
        rewritten = write_personalization(
            client,
            lead,
            evidence,
            tone_profile,
            previous_failure_reasons=rewrite_reasons,
            variant_index=variant_index,
            avoid_opening_lines=avoid_opening_lines + [draft.opening_line],
            variant_instruction=variant_instruction,
        )
        rewritten = soften_draft_for_weak_evidence(rewritten, evidence)
        rewritten_qc = check_quality(client, lead, evidence, rewritten, tone_profile)
        if rewritten_qc.score >= qc.score:
            return rewritten, rewritten_qc
    return draft, qc


def _sales_for_variant(
    lead: LeadInput,
    evidence: EvidenceResult,
    draft: PersonalizationDraft,
) -> SalesPrinciplesResult:
    evidence_text = _format_evidence(evidence) or join_list(draft.evidence_used_for_copy)
    source_urls = join_list([fact.source_url for fact in evidence.facts if fact.source_url])
    return evaluate_sales_principles(
        draft.opening_line,
        evidence=evidence_text,
        source_url=source_urls,
        angle=draft.chosen_angle,
        campaign_context=lead.campaign_context,
        manual_app_verified=bool(lead.app_flow_observation.strip()),
    )


def _variant_sendability_row(
    base_row: dict[str, Any],
    draft: PersonalizationDraft,
    qc: QCResult,
    evidence: EvidenceResult,
    sales: SalesPrinciplesResult,
    needs_review: bool,
) -> dict[str, Any]:
    evidence_text = join_list(draft.evidence_used_for_copy) or _format_evidence(evidence)
    source_urls = join_list([fact.source_url for fact in evidence.facts if fact.source_url])
    quality_flags = join_list(
        [
            base_row.get("quality_flags", ""),
            join_list(qc.quality_flags),
            "fake_familiarity_claim" if sales.fake_familiarity_flag else "",
            "salesy_language" if sales.salesy_language_flag else "",
            "unsupported_meaningful_claim" if sales.evidence_supported_claim_score < 35 else "",
            "multiple_insights" if sales.one_insight_score < 60 else "",
            "missing_outcome_bridge" if sales.outcome_bridge_score < 60 else "",
        ]
    )
    row = dict(base_row)
    row.update(
        {
            "personalized_line": draft.opening_line,
            "opening_line": draft.opening_line,
            "current_opening_line": draft.opening_line,
            "selected_opener": draft.opening_line,
            "chosen_angle": draft.chosen_angle,
            "evidence_used_for_copy": evidence_text,
            "evidence_found": evidence_text,
            "source_urls": source_urls or base_row.get("source_urls", ""),
            "quality_flags": quality_flags,
            "needs_manual_review": needs_review,
            "specificity_score": sales.specificity_score,
            "one_insight_score": sales.one_insight_score,
            "friction_relevance_score": sales.friction_relevance_score,
            "outcome_bridge_score": sales.outcome_bridge_score,
            "commercial_relevance_score": sales.commercial_relevance_score,
            "signal_to_implication_bridge_score": sales.signal_to_implication_bridge_score,
            "salesy_language_flag": "yes" if sales.salesy_language_flag else "no",
            "fake_familiarity_flag": "yes" if sales.fake_familiarity_flag else "no",
            "evidence_supported_claim_score": sales.evidence_supported_claim_score,
            "sales_principles_score": sales.sales_principles_score,
            "sales_principles_summary": sales.sales_principles_summary,
            "sales_principles_reasons": join_list(sales.sales_principles_reasons),
        }
    )
    return row


def _store_variant(
    row: dict[str, Any],
    lead: LeadInput,
    index: int,
    draft: PersonalizationDraft,
    qc: QCResult,
    evidence: EvidenceResult,
    sales: SalesPrinciplesResult,
    sendability: dict[str, Any],
    needs_review: bool,
) -> None:
    evidence_text = join_list(draft.evidence_used_for_copy) or _format_evidence(evidence)
    source_urls = join_list([fact.source_url for fact in evidence.facts if fact.source_url])
    rejection_or_edit_reason = join_list(
        [
            sendability.get("hard_fail_reasons", ""),
            sendability.get("soft_edit_reasons", ""),
            join_list(sales.sales_principles_reasons),
        ]
    )
    quality_flags = join_list(
        [
            join_list(qc.quality_flags),
            sendability.get("hard_fail_reasons", ""),
            sendability.get("soft_edit_reasons", ""),
        ]
    )
    row[f"opener_option_{index}"] = draft.opening_line
    row[f"opener_option_{index}_angle"] = draft.chosen_angle
    row[f"opener_option_{index}_evidence"] = evidence_text
    row[f"opener_option_{index}_source_url"] = source_urls
    row[f"opener_option_{index}_sendability"] = sendability.get("sendability_decision", "")
    row[f"opener_option_{index}_sendability_score"] = sendability.get("sendability_score", "")
    row[f"opener_option_{index}_quality_flags"] = quality_flags
    row[f"opener_option_{index}_sales_principles_summary"] = sales.sales_principles_summary
    row[f"opener_option_{index}_rejection_or_edit_reason"] = rejection_or_edit_reason
    row[f"opening_line_option_{index}"] = draft.opening_line
    row[f"tailored_insight_option_{index}"] = draft.tailored_insight
    row[f"chosen_angle_option_{index}"] = draft.chosen_angle
    row[f"evidence_used_for_copy_option_{index}"] = evidence_text
    row[f"confidence_score_option_{index}"] = qc.score
    row[f"quality_flags_option_{index}"] = quality_flags
    row[f"needs_manual_review_option_{index}"] = needs_review
    row[f"reviewer_notes_option_{index}"] = join_list([join_list(qc.reasons), rejection_or_edit_reason])
    row[f"template_preview_option_{index}"] = _template_preview(lead, draft.opening_line)


def _best_variant_index(variants: list[dict[str, Any]]) -> int:
    if not variants:
        return 0
    ordered = sorted(
        variants,
        key=lambda item: (
            str(item["sendability"].get("sendability_decision", "")) != "Send",
            item["needs_review"],
            -int(item["sendability"].get("sendability_score", 0) or 0),
            -int(item["sales"].sales_principles_score),
            -int(item["qc"].score),
            bool(SERIOUS_QUALITY_FLAGS.intersection(set(item["qc"].quality_flags))),
            item["index"],
        ),
    )
    return int(ordered[0]["index"])


def _select_recommended_opener(row: dict[str, Any], variants: list[dict[str, Any]]) -> None:
    if not variants:
        row["recommended_opener"] = ""
        row["recommended_opener_option"] = "no_sendable_option"
        row["recommended_opener_reason"] = "No opener options were generated."
        row["selected_opener"] = ""
        row["selected_opener_source"] = ""
        return
    best_index = _best_variant_index(variants)
    best = next(item for item in variants if item["index"] == best_index)
    sendability = best["sendability"]
    sales = best["sales"]
    decision = str(sendability.get("sendability_decision", ""))
    score = int(sendability.get("sendability_score", 0) or 0)
    hard_reasons = str(sendability.get("hard_fail_reasons", "") or "").strip()
    if decision != "Send" or score < 85 or hard_reasons:
        row["recommended_opener"] = ""
        row["recommended_opener_option"] = "no_sendable_option"
        row["recommended_opener_reason"] = join_list(
            [
                "No option cleared the sendability threshold.",
                f"Best option was option_{best_index} with {decision} ({score}/100).",
                hard_reasons,
                sendability.get("soft_edit_reasons", ""),
            ]
        )
        row["selected_opener"] = ""
        row["selected_opener_source"] = ""
        return
    row["recommended_opener"] = best["draft"].opening_line
    row["recommended_opener_option"] = f"option_{best_index}"
    row["recommended_opener_reason"] = join_list(
        [
            f"Option {best_index} had the strongest evidence, sendability {score}/100, and sales-principles {sales.sales_principles_score}/100.",
            sendability.get("sales_principles_summary", ""),
        ]
    )
    row["selected_opener"] = row["recommended_opener"]
    row["selected_opener_source"] = row["recommended_opener_option"]


def _process_valid_lead(
    client: LLMClient,
    lead: LeadInput,
    manual_review_mode: bool,
    deep_research_enabled: bool,
    tone_profile_name: str,
    lead_quality_context: LeadQualityContext | None = None,
) -> dict[str, Any]:
    row = _base_row(lead, lead_quality_context)
    row = _apply_mismatch_flags(row)
    if str(row.get("input_mapping_warning", "")).lower() == "yes":
        row["quality_flags"] = join_list([row.get("quality_flags", ""), "pre_run_input_mapping_warning"])
        row["reviewer_notes"] = join_list(
            [
                row.get("reviewer_notes", ""),
                "Skipped expensive research/generation because company/contact/website mapping looks inconsistent.",
                row.get("mismatch_reason", ""),
            ]
        )
        row["needs_manual_review"] = True
        row["send_confidence"] = "review"
        app_check_status, manual_check = _manual_check_recommendation(lead, row, None)
        row["app_check_status"] = app_check_status
        row["recommended_manual_check"] = manual_check
        return row

    research = research_company(lead, client.settings)
    deep_research = None
    if deep_research_enabled:
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
    research_fields = run_research_tasks(lead, research, client.settings)
    row.update({key: value for key, value in research_fields.items() if not key.startswith("_")})
    enrichment_context = recommended_research_context(research_fields)
    research.summary = join_list(
        [
            f"Product surface type: {row['product_surface_type']}. Research priority: {row['research_priority']}",
            f"Structured enrichment usable for opener: {enrichment_context}" if enrichment_context else "",
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
            return _apply_mismatch_flags(row)
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
            return _apply_mismatch_flags(row)
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
        return _apply_mismatch_flags(row)

    variant_facts = selection.allowed_facts[: client.settings.personalization_options]
    while variant_facts and len(variant_facts) < client.settings.personalization_options:
        variant_facts.append(variant_facts[-1])
    variants: list[dict[str, Any]] = []
    avoid_opening_lines: list[str] = []
    variant_instructions = [
        "Option 1: choose the strongest sendable friction angle.",
        "Option 2: choose a meaningfully different angle if evidence allows, ideally user feedback, app-store review, onboarding, or conversion friction.",
        "Option 3: choose another distinct angle if evidence allows, ideally proof, positioning, CTA, website, or visual friction.",
    ]
    for variant_index, fact in enumerate(variant_facts[: client.settings.personalization_options], 1):
        variant_evidence = _variant_evidence(evidence, fact, selection.allowed_facts)
        draft, qc = _write_and_qc_variant(
            client,
            lead,
            variant_evidence,
            tone_profile,
            variant_index,
            avoid_opening_lines,
            variant_instructions[min(variant_index - 1, len(variant_instructions) - 1)],
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
        sales = _sales_for_variant(lead, variant_evidence, draft)
        variant_sendability_row = _variant_sendability_row(row, draft, qc, variant_evidence, sales, variant_needs_review)
        sendability = evaluate_sendability(variant_sendability_row)
        if sendability.get("sendability_decision") != "Send":
            variant_needs_review = True
        _store_variant(row, lead, variant_index, draft, qc, variant_evidence, sales, sendability, variant_needs_review)
        variants.append(
            {
                "index": variant_index,
                "draft": draft,
                "qc": qc,
                "sales": sales,
                "sendability": sendability,
                "needs_review": variant_needs_review,
                "evidence": variant_evidence,
            }
        )
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
        sales = evaluate_sales_principles("")
        sendability = evaluate_sendability({"personalized_line": "", "quality_flags": "manual_review_needed"})
    else:
        best_variant = next(item for item in variants if item["index"] == best_index)
        draft = best_variant["draft"]
        qc = best_variant["qc"]
        sales = best_variant["sales"]
        sendability = best_variant["sendability"]
        needs_review = best_variant["needs_review"]
    _select_recommended_opener(row, variants)

    existing_flags = {
        flag.strip()
        for flag in str(row.get("quality_flags", "")).replace(";", "|").split("|")
        if flag.strip()
    }
    combined_flags = existing_flags.union(set(selection.quality_flags)).union(set(qc.quality_flags))
    if sales.fake_familiarity_flag:
        combined_flags.add("fake_familiarity_claim")
    if sales.salesy_language_flag:
        combined_flags.add("salesy_language")
    if sales.evidence_supported_claim_score < 35:
        combined_flags.add("unsupported_meaningful_claim")
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
            "send_confidence": "send" if row.get("recommended_opener") and not needs_review and evidence_strength_score >= 3 else "review",
            "quality_flags": join_list(
                [row.get("quality_flags", ""), join_list(selection.quality_flags), join_list(combined_flags)]
            ),
            "needs_manual_review": needs_review,
            "reviewer_notes": join_list(notes),
            "specificity_score": sales.specificity_score,
            "one_insight_score": sales.one_insight_score,
            "friction_relevance_score": sales.friction_relevance_score,
            "outcome_bridge_score": sales.outcome_bridge_score,
            "commercial_relevance_score": sales.commercial_relevance_score,
            "signal_to_implication_bridge_score": sales.signal_to_implication_bridge_score,
            "salesy_language_flag": "yes" if sales.salesy_language_flag else "no",
            "fake_familiarity_flag": "yes" if sales.fake_familiarity_flag else "no",
            "evidence_supported_claim_score": sales.evidence_supported_claim_score,
            "sales_principles_score": sales.sales_principles_score,
            "sales_principles_summary": sales.sales_principles_summary,
            "sales_principles_reasons": join_list(sales.sales_principles_reasons),
        }
    )
    if not row.get("recommended_opener"):
        row["needs_manual_review"] = True
        row["quality_flags"] = join_list([row.get("quality_flags", ""), "no_sendable_option"])
    app_check_status, manual_check = _manual_check_recommendation(lead, row, research)
    row["app_check_status"] = app_check_status
    row["recommended_manual_check"] = manual_check
    return _apply_mismatch_flags(row)


def _process_single_lead(
    settings: Settings,
    args: argparse.Namespace,
    lead: LeadInput,
    tone_profile_name: str,
    prompt_meta: dict[str, str],
    tone_hash: str,
    lead_quality_context: LeadQualityContext | None = None,
    ai_available: bool = True,
    ai_unavailable_note: str = "",
    rate_limiter: RateLimiter | None = None,
) -> dict[str, Any]:
    """Worker-functie: verwerk één lead met een eigen LLMClient (thread-safe)."""
    client = LLMClient(settings, rate_limiter=rate_limiter)

    lead_label = lead.company_name or lead.website_url or "unnamed row"

    if not lead.is_valid:
        row = _attach_run_metadata(
            _placeholder_row(lead, "Row was not processed because input validation failed", lead_quality_context),
            client,
            tone_profile_name,
            prompt_meta,
            tone_hash,
        )
        return _row_to_dict(row, lead_label, "validation_failed")

    if not ai_available or not client.available:
        row = _offline_research_row(lead, settings, args.deep_research, lead_quality_context)
        missing_key_note = ai_unavailable_note or f"{settings.llm_provider.upper()}_API_KEY is missing."
        row["reviewer_notes"] = join_list([row.get("reviewer_notes", ""), missing_key_note])
        row = _attach_run_metadata(row, client, tone_profile_name, prompt_meta, tone_hash)
        return _row_to_dict(row, lead_label, "offline")

    try:
        row = _process_valid_lead(
            client,
            lead,
            args.manual_review_mode,
            args.deep_research,
            tone_profile_name,
            lead_quality_context,
        )
        row = _attach_run_metadata(row, client, tone_profile_name, prompt_meta, tone_hash)
        return _row_to_dict(row, lead_label, "complete")
    except Exception as exc:
        logging.exception("Failed to process %s", lead.company_name)
        if args.manual_review_mode:
            row = _placeholder_row(lead, f"Processing failed: {exc}", lead_quality_context)
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
    lead_quality_context = build_lead_quality_context(leads)
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
                lead_quality_context,
                ai_available,
                ai_unavailable_note,
                rate_limiter,
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
                    placeholder = _placeholder_row(lead, f"Fatal error: {exc}", lead_quality_context)
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
        output_path = Path(args.output)
        delivery_output = output_path.with_name(f"{output_path.stem}_delivery_export{output_path.suffix}")
        review_needed_output = output_path.with_name(f"{output_path.stem}_review_needed{output_path.suffix}")
        export_delivery_rows(rows, delivery_output, review_needed_output)
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
