from __future__ import annotations

from llm_client import LLMClient, LLMError, load_prompt
from models import EvidenceResult, LeadInput, PersonalizationDraft
from evidence_extractor import evidence_to_payload


def write_personalization(
    client: LLMClient,
    lead: LeadInput,
    evidence: EvidenceResult,
    previous_failure_reasons: list[str] | None = None,
) -> PersonalizationDraft:
    prompt = load_prompt("write_personalization.txt")
    full_template = (
        "Hey [Name]\n"
        "{personalized_line}\n"
        "We help mobile app teams with this type of work, figure out where users drop off and why.\n"
        "In a recent app project, session replays showed users bouncing off a paywall because the copy was unclear. "
        "After the paywall was rewritten, conversion improved materially."
    )
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
        "email_template_context": full_template,
        "required_next_sentence": "We help mobile app teams with this type of work, figure out where users drop off and why.",
        "evidence": evidence_to_payload(evidence),
        "possible_angles": evidence.possible_angles,
        "previous_failure_reasons": previous_failure_reasons or [],
    }
    try:
        raw = client.complete_json(prompt, payload)
    except LLMError as exc:
        return PersonalizationDraft(
            opening_line="",
            tailored_insight="",
            chosen_angle="",
            evidence_used_for_copy=[f"LLM generation failed: {exc}"],
        )

    return PersonalizationDraft(
        opening_line=str(raw.get("opening_line", "")).strip(),
        tailored_insight=str(raw.get("tailored_insight", "")).strip(),
        chosen_angle=str(raw.get("chosen_angle", "")).strip(),
        evidence_used_for_copy=[str(value).strip() for value in raw.get("evidence_used_for_copy", []) if str(value).strip()],
    )
