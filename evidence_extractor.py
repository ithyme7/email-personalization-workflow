from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from config import CACHE_DIR
from llm_client import LLMClient, LLMError, load_prompt
from models import EvidenceFact, EvidenceResult, LeadInput, ResearchResult, ToneProfile


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _evidence_cache_path(
    lead: LeadInput, research_summary: str, tone_profile_name: str
) -> Path:
    """Bepaal cache-pad op basis van lead-identiteit + research samenvatting + tone."""
    key = f"{lead.company_name}:{lead.website_url}:{research_summary}:{tone_profile_name}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"evidence_{digest}.json"


def _serialize_evidence_result(er: EvidenceResult) -> dict[str, Any]:
    return {
        "facts": [
            {
                "fact": f.fact,
                "why_it_matters": f.why_it_matters,
                "source_url": f.source_url,
                "strength": f.strength,
                "too_generic_to_use": f.too_generic_to_use,
                "friction_type": f.friction_type,
                "surface_checked": f.surface_checked,
                "conversion_outcome": f.conversion_outcome,
                "angle_priority": f.angle_priority,
                "blog_used": f.blog_used,
                "why_this_angle": f.why_this_angle,
            }
            for f in er.facts
        ],
        "possible_angles": er.possible_angles,
        "needs_manual_review": er.needs_manual_review,
        "reviewer_notes": er.reviewer_notes,
        "raw": er.raw,
    }


def _deserialize_evidence_result(data: dict[str, Any]) -> EvidenceResult:
    return EvidenceResult(
        facts=[
            EvidenceFact(
                fact=item.get("fact", ""),
                why_it_matters=item.get("why_it_matters", ""),
                source_url=item.get("source_url", ""),
                strength=item.get("strength", "weak"),
                too_generic_to_use=item.get("too_generic_to_use", True),
                friction_type=item.get("friction_type", ""),
                surface_checked=item.get("surface_checked", ""),
                conversion_outcome=item.get("conversion_outcome", ""),
                angle_priority=item.get("angle_priority", 0),
                blog_used=item.get("blog_used", False),
                why_this_angle=item.get("why_this_angle", ""),
            )
            for item in data.get("facts", [])
        ],
        possible_angles=data.get("possible_angles", []),
        needs_manual_review=data.get("needs_manual_review", False),
        reviewer_notes=data.get("reviewer_notes", []),
        raw=data.get("raw", {}),
    )


def extract_evidence(
    client: LLMClient,
    lead: LeadInput,
    research: ResearchResult,
    tone_profile: ToneProfile | None = None,
) -> EvidenceResult:
    """Haal evidence op via LLM — met lokale cache om dubbele calls te voorkomen."""
    tone_name = tone_profile.name if tone_profile else ""
    cache_file = _evidence_cache_path(lead, research.summary, tone_name)

    # Probeer cache te lezen
    try:
        if cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            logging.debug("Evidence cache hit voor %s", lead.company_name)
            return _deserialize_evidence_result(cached)
    except (json.JSONDecodeError, OSError) as exc:
        logging.debug("Evidence cache leesfout voor %s: %s", lead.company_name, exc)

    # Geen cache → LLM-aanroep
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

    result = EvidenceResult(
        facts=facts,
        possible_angles=[str(angle) for angle in raw.get("possible_angles", []) if str(angle).strip()],
        needs_manual_review=needs_review,
        reviewer_notes=notes,
        raw=raw,
    )

    # Schrijf resultaat naar cache (fire-and-forget)
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps(_serialize_evidence_result(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logging.debug("Evidence gecached voor %s (%d facts)", lead.company_name, len(facts))
    except OSError:
        logging.debug("Kon evidence niet cachen voor %s", lead.company_name)

    return result


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