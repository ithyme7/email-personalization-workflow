from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from angle_selector import evidence_for_selected_angle, select_angle
from config import ensure_directories, load_settings
from deep_research import collect_deep_research
from evidence_extractor import evidence_to_payload, extract_evidence
from export import export_client_batch_rows, export_rows
from input_loader import dedupe_key, load_leads
from llm_client import LLMClient
from models import EvidenceResult, LeadInput, PersonalizationDraft, QCResult, ResearchResult, join_list
from personalization_writer import write_personalization
from quality_checker import check_quality
from tone_profiles import load_tone_profile
from web_research import research_company

PITCH_SENTENCE = "We help mobile app teams with this type of work, figure out where users drop off and why."


def _base_row(lead: LeadInput) -> dict[str, Any]:
    return {
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
        "app_flow_observation": lead.app_flow_observation,
        "app_flow_source_note": lead.app_flow_source_note,
        "screenshot_url": lead.screenshot_url,
        "recent_news_url": lead.recent_news_url,
        "recent_news_note": lead.recent_news_note,
        "competitor_context": lead.competitor_context,
        "friction_checklist": "",
        "app_check_status": "",
        "recommended_manual_check": "",
        "template_preview": "",
        "visual_observations": "",
        "visual_quality_flags": "",
        "visual_confidence": "",
        "visual_confidence_score": "",
        "visual_confidence_reasons": "",
        "screenshot_paths": "",
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
        "confidence_score": "",
        "evidence_strength_score": "",
        "personalization_quality_score": "",
        "send_confidence": "review",
        "quality_flags": "",
        "source_urls": "",
        "needs_manual_review": True,
        "reviewer_notes": "",
    }


def _first_name(name: str) -> str:
    cleaned = str(name or "").strip()
    return cleaned.split()[0] if cleaned else "[Name]"


def _template_preview(lead: LeadInput, opening_line: str) -> str:
    line = str(opening_line or "").strip()
    if not line or line.startswith("["):
        return ""
    next_sentence = lead.campaign_context.strip() or PITCH_SENTENCE
    return f"Hey {_first_name(lead.recipient_name)}\n\n{line}\n\n{next_sentence}"


def _attach_run_metadata(row: dict[str, Any], client: LLMClient, tone_profile_name: str) -> dict[str, Any]:
    row["tone_profile"] = tone_profile_name
    row["model_provider"] = client.settings.llm_provider
    row["model_name"] = client.settings.model_name
    return row


def _looks_app_first(lead: LeadInput, row: dict[str, Any] | None = None, research: ResearchResult | None = None) -> bool:
    row = row or {}
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


def _offline_research_row(lead: LeadInput, deep_research_enabled: bool) -> dict[str, Any]:
    row = _base_row(lead)
    settings = load_settings()
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
                "app_flow_observation": deep_research.app_flow_observation,
                "app_flow_source_note": deep_research.app_flow_source_note,
                "screenshot_url": deep_research.screenshot_url,
                "recent_news_url": deep_research.recent_news_url,
                "recent_news_note": deep_research.recent_news_note,
                "competitor_context": deep_research.competitor_context,
                "friction_checklist": join_list(deep_research.friction_checklist),
            }
        )
    row.update(
        {
            "visual_observations": join_list(research.visual_observations),
            "visual_quality_flags": join_list(research.visual_quality_flags),
            "visual_confidence": research.visual_confidence,
            "visual_confidence_score": research.visual_confidence_score,
            "visual_confidence_reasons": join_list(research.visual_confidence_reasons),
            "screenshot_paths": join_list(research.screenshot_paths),
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
    note = copied.get("reviewer_notes", "")
    copied["reviewer_notes"] = join_list([note, "Reused personalization from duplicate company row"])
    copied["template_preview"] = _template_preview(lead, copied.get("opening_line", ""))
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


def _process_valid_lead(
    client: LLMClient,
    lead: LeadInput,
    manual_review_mode: bool,
    deep_research_enabled: bool,
    tone_profile_name: str,
) -> dict[str, Any]:
    row = _base_row(lead)

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
                "app_flow_observation": deep_research.app_flow_observation,
                "app_flow_source_note": deep_research.app_flow_source_note,
                "screenshot_url": deep_research.screenshot_url,
                "recent_news_url": deep_research.recent_news_url,
                "recent_news_note": deep_research.recent_news_note,
                "competitor_context": deep_research.competitor_context,
                "friction_checklist": join_list(deep_research.friction_checklist),
            }
        )
    row.update(
        {
            "visual_observations": join_list(research.visual_observations),
            "visual_quality_flags": join_list(research.visual_quality_flags),
            "visual_confidence": research.visual_confidence,
            "visual_confidence_score": research.visual_confidence_score,
            "visual_confidence_reasons": join_list(research.visual_confidence_reasons),
            "screenshot_paths": join_list(research.screenshot_paths),
        }
    )
    row["raw_research_summary"] = research.summary
    row["source_urls"] = join_list(research.source_urls)
    if research.visual_quality_flags:
        row["quality_flags"] = join_list([row.get("quality_flags", ""), join_list(research.visual_quality_flags)])

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

    draft = write_personalization(client, lead, gated_evidence, tone_profile)
    qc = check_quality(client, lead, gated_evidence, draft, tone_profile)

    if not qc.passed:
        rewrite_reasons = qc.reasons + qc.quality_flags
        rewritten = write_personalization(
            client,
            lead,
            gated_evidence,
            tone_profile,
            previous_failure_reasons=rewrite_reasons,
        )
        rewritten_qc = check_quality(client, lead, gated_evidence, rewritten, tone_profile)
        if rewritten_qc.score >= qc.score:
            draft = rewritten
            qc = rewritten_qc

    serious_quality_flags = {
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
    }
    existing_flags = {
        flag.strip()
        for flag in str(row.get("quality_flags", "")).replace(";", "|").split("|")
        if flag.strip()
    }
    combined_flags = existing_flags.union(set(selection.quality_flags)).union(set(qc.quality_flags))
    needs_review = (
        research.needs_manual_review
        or gated_evidence.needs_manual_review
        or selection.needs_manual_review
        or not qc.passed
        or qc.score < 8
        or bool(serious_quality_flags.intersection(combined_flags))
    )

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


def run(args: argparse.Namespace) -> list[dict[str, Any]]:
    ensure_directories()
    settings = load_settings()
    client = LLMClient(settings)
    tone_profile_name = str(getattr(args, "tone_profile", "") or settings.tone_profile)
    leads = load_leads(args.input, args.campaign_context, deduplicate=not args.reuse_duplicate_personalization)

    rows: list[dict[str, Any]] = []
    processed_by_key: dict[str, dict[str, Any]] = {}
    if settings.llm_provider == "gemini":
        key_name = "GEMINI_API_KEY"
    elif settings.llm_provider == "openrouter":
        key_name = "OPENROUTER_API_KEY"
    elif settings.llm_provider == "deepseek":
        key_name = "DEEPSEEK_API_KEY"
    else:
        key_name = "OPENAI_API_KEY"
    missing_key_note = f"{key_name} is missing. Input was validated, but AI generation and QC require an API key."
    ai_available = client.available
    ai_unavailable_note = missing_key_note
    if client.available:
        ok, preflight_note = client.validate_access()
        if ok:
            logging.info("AI preflight check passed for %s", settings.llm_provider)
        else:
            ai_available = False
            ai_unavailable_note = (
                f"AI generation disabled for this run because the {settings.llm_provider} preflight check failed: "
                f"{preflight_note}. Research, visual review and workbook export still ran."
            )
            logging.error(ai_unavailable_note)

    for lead in leads:
        logging.info("Processing %s", lead.company_name or lead.website_url or "unnamed row")
        if not lead.is_valid:
            rows.append(
                _attach_run_metadata(
                    _placeholder_row(lead, "Row was not processed because input validation failed"),
                    client,
                    tone_profile_name,
                )
            )
            continue
        key = dedupe_key(lead)
        if args.reuse_duplicate_personalization and key in processed_by_key:
            rows.append(
                _attach_run_metadata(
                    _copy_personalization_for_contact(processed_by_key[key], lead),
                    client,
                    tone_profile_name,
                )
            )
            continue
        if not ai_available:
            row = _offline_research_row(lead, args.deep_research)
            row["reviewer_notes"] = join_list([row.get("reviewer_notes", ""), ai_unavailable_note])
            row = _attach_run_metadata(row, client, tone_profile_name)
            rows.append(row)
            processed_by_key[key] = row
            continue
        try:
            row = _process_valid_lead(client, lead, args.manual_review_mode, args.deep_research, tone_profile_name)
            row = _attach_run_metadata(row, client, tone_profile_name)
            rows.append(row)
            processed_by_key[key] = row
        except Exception as exc:
            logging.exception("Failed to process %s", lead.company_name)
            if args.manual_review_mode:
                row = _placeholder_row(lead, f"Processing failed: {exc}")
                row = _attach_run_metadata(row, client, tone_profile_name)
                rows.append(row)
                processed_by_key[key] = row
            else:
                raise

    if args.client_batch_output:
        export_client_batch_rows(rows, args.output)
    else:
        export_rows(rows, args.output)
    logging.info("Exported %s rows to %s", len(rows), args.output)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate researched, reviewable email personalization notes from a CSV.")
    parser.add_argument("--input", required=True, help="Path to input CSV")
    parser.add_argument("--output", required=True, help="Path to output CSV or XLSX")
    parser.add_argument("--campaign-context", default="", help="Default campaign context when a row does not provide one")
    parser.add_argument(
        "--manual-review-mode",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Export weak or failed rows for review instead of failing the whole batch",
    )
    parser.add_argument(
        "--reuse-duplicate-personalization",
        action="store_true",
        help="Process each company once, then reuse the same personalization for duplicate contact rows",
    )
    parser.add_argument(
        "--client-batch-output",
        action="store_true",
        help="Export compact client columns: company, person, role, website, evidence found, personalized line, flags, review",
    )
    parser.add_argument(
        "--deep-research",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Add public app-store discovery plus supplied LinkedIn/app-flow/news/screenshot context to the research prompt",
    )
    parser.add_argument(
        "--tone-profile",
        default="",
        help="Tone profile name or JSON path. Built-ins: friction_first, proof_led_b2b, founder_casual",
    )
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


if __name__ == "__main__":
    parsed_args = parse_args()
    logging.basicConfig(level=parsed_args.log_level, format="%(levelname)s: %(message)s")
    run(parsed_args)
