from __future__ import annotations

from llm_client import LLMClient, LLMError, load_prompt, load_prompt_pair
from models import EvidenceResult, LeadInput, PersonalizationDraft, ToneProfile
from evidence_extractor import evidence_to_payload
from copy_guardrails import sanitize_personalization_draft
from defaults import _default_next_sentence

from string import Template
import json


SYSTEM_TEMPLATE, _USER_TEMPLATE_STR = load_prompt_pair("write_personalization")


def _render_user_payload(
    lead: LeadInput,
    evidence: EvidenceResult,
    tone_profile: ToneProfile | None,
    required_next_sentence: str,
    variant_index: int = 1,
    avoid_opening_lines: list[str] | None = None,
    variant_instruction: str = "",
    previous_failure_reasons: list[str] | None = None,
    qc_suggested_rewrite: dict[str, str] | None = None,
    feedback_context: str = "",
    research_depth: float = 1.0,
) -> str:
    """Fill the user template with the lead-specific data."""
    evidence_payload = json.dumps(evidence_to_payload(evidence))

    if qc_suggested_rewrite:
        prev = {
            "opening_line": qc_suggested_rewrite.get("opening_line", ""),
            "tailored_insight": qc_suggested_rewrite.get("tailored_insight", ""),
            "chosen_angle": lead.campaign_context or "",
            "evidence_used_for_copy": [],
        }
    else:
        prev = {}

    tpl = Template(_USER_TEMPLATE_STR)
    return tpl.safe_substitute(
        company_name=lead.company_name or "",
        website_url=lead.website_url or "",
        recipient_name=lead.recipient_name or "",
        recipient_role=lead.recipient_role or "",
        campaign_context=lead.campaign_context or "",
        optional_notes=lead.optional_notes or "",
        linkedin_observation=lead.linkedin_observation or "",
        linkedin_source_note=lead.linkedin_source_note or "",
        app_store_url=lead.app_store_url or "",
        app_flow_observation=lead.app_flow_observation or "",
        app_flow_source_note=lead.app_flow_source_note or "",
        screenshot_url=lead.screenshot_url or "",
        recent_news_url=lead.recent_news_url or "",
        recent_news_note=lead.recent_news_note or "",
        competitor_context=lead.competitor_context or "",
        required_next_sentence=required_next_sentence,
        evidence_json=evidence_payload,
        previous_draft_json=json.dumps(prev),
        variant_index=variant_index,
        avoid_opening_lines=avoid_opening_lines or [],
        variant_instruction=variant_instruction or "",
        tone_profile_json=json.dumps(
            tone_profile.to_prompt_payload() if tone_profile else {}
        ),
        feedback_context=feedback_context,
        research_depth=research_depth,
    )


def write_personalization(
    client: LLMClient,
    lead: LeadInput,
    evidence: EvidenceResult,
    tone_profile: ToneProfile | None = None,
    previous_failure_reasons: list[str] | None = None,
    variant_index: int = 1,
    avoid_opening_lines: list[str] | None = None,
    variant_instruction: str = "",
    qc_suggested_rewrite: dict[str, str] | None = None,
    temperature: float = 0.6,
    feedback_context: str = "",
    research_depth: float = 1.0,
) -> PersonalizationDraft:
    required_next_sentence = lead.campaign_context.strip() or _default_next_sentence(lead)
    user_text = _render_user_payload(
        lead=lead,
        evidence=evidence,
        tone_profile=tone_profile,
        required_next_sentence=required_next_sentence,
        variant_index=variant_index,
        avoid_opening_lines=avoid_opening_lines,
        variant_instruction=variant_instruction,
        previous_failure_reasons=previous_failure_reasons,
        qc_suggested_rewrite=qc_suggested_rewrite,
        feedback_context=feedback_context,
        research_depth=research_depth,
    )
    try:
        raw = client.complete_json(SYSTEM_TEMPLATE, user_text, temperature=temperature)
    except LLMError as exc:
        return PersonalizationDraft(
            opening_line="",
            tailored_insight="",
            chosen_angle="",
            evidence_used_for_copy=[f"LLM generation failed: {exc}"],
        )

    draft = PersonalizationDraft(
        opening_line=str(raw.get("opening_line", "")).strip(),
        tailored_insight=str(raw.get("tailored_insight", "")).strip(),
        chosen_angle=str(raw.get("chosen_angle", "")).strip(),
        evidence_used_for_copy=[
            str(value).strip() for value in raw.get("evidence_used_for_copy", []) if str(value).strip()
        ],
    )
    return sanitize_personalization_draft(draft, lead)