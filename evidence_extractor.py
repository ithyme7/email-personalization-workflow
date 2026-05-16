from __future__ import annotations

from typing import Any

from llm_client import LLMClient, LLMError, load_prompt
from models import EvidenceFact, EvidenceResult, LeadInput, ResearchResult, ToneProfile


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def extract_evidence(
    client: LLMClient,
    lead: LeadInput,
    research: ResearchResult,
    tone_profile: ToneProfile | None = None,
) -> EvidenceResult:
    prompt = load_prompt("evidence_extraction.txt")
    payload = {
        "company_name": lead.company_name,
        "website_url": lead.website_url,
        "recipient_name": lead.recipient_name,
        "recipient_role": lead.recipient_role,
        "campaign_context": lead.campaign_context,
        "optional_notes": lead.optional_notes,
        "linkedin_observation": lead.linkedin_observation,
        "linkedin_source_note": lead.linkedin_source_note,
        "app_store_url": lead.app_store_url,
        "app_flow_observation": lead.app_flow_observation,
        "app_flow_source_note": lead.app_flow_source_note,
        "screenshot_url": lead.screenshot_url,
        "recent_news_url": lead.recent_news_url,
        "recent_news_note": lead.recent_news_note,
        "competitor_context": lead.competitor_context,
        "website_research_text": research.summary,
        "source_urls": research.source_urls,
        "tone_profile": tone_profile.to_prompt_payload() if tone_profile else {},
    }
    try:
        raw = client.complete_json(prompt, payload)
    except LLMError as exc:
        return EvidenceResult(needs_manual_review=True, reviewer_notes=[str(exc)])

    facts: list[EvidenceFact] = []
    for item in raw.get("facts", []):
        if not isinstance(item, dict):
            continue
        facts.append(
            EvidenceFact(
                fact=str(item.get("fact", "")).strip(),
                why_it_matters=str(item.get("why_it_matters", "")).strip(),
                source_url=str(item.get("source_url", "")).strip(),
                strength=str(item.get("strength", "weak")).strip().lower(),
                too_generic_to_use=bool(item.get("too_generic_to_use", True)),
                friction_type=str(item.get("friction_type", "")).strip(),
                surface_checked=str(item.get("surface_checked", "")).strip(),
                conversion_outcome=str(item.get("conversion_outcome", "")).strip(),
                angle_priority=_safe_int(item.get("angle_priority", 0), 0),
                blog_used=bool(item.get("blog_used", False)),
                why_this_angle=str(item.get("why_this_angle", "")).strip(),
            )
        )

    strong_facts = [fact for fact in facts if fact.strength == "strong" and not fact.too_generic_to_use]
    needs_review = bool(raw.get("needs_manual_review", False)) or not strong_facts
    notes = [str(note) for note in raw.get("reviewer_notes", []) if str(note).strip()]
    if not strong_facts:
        notes.append("No strong, specific evidence found")

    return EvidenceResult(
        facts=facts,
        possible_angles=[str(angle) for angle in raw.get("possible_angles", []) if str(angle).strip()],
        needs_manual_review=needs_review,
        reviewer_notes=notes,
        raw=raw,
    )


def evidence_to_payload(evidence: EvidenceResult) -> list[dict[str, Any]]:
    return [
        {
            "fact": fact.fact,
            "why_it_matters": fact.why_it_matters,
            "source_url": fact.source_url,
            "strength": fact.strength,
            "too_generic_to_use": fact.too_generic_to_use,
            "friction_type": fact.friction_type,
            "surface_checked": fact.surface_checked,
            "conversion_outcome": fact.conversion_outcome,
            "angle_priority": fact.angle_priority,
            "blog_used": fact.blog_used,
            "why_this_angle": fact.why_this_angle,
        }
        for fact in evidence.facts
    ]
