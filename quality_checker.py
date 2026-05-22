from __future__ import annotations

from llm_client import LLMClient, LLMError, load_prompt, load_prompt_pair
from models import EvidenceResult, LeadInput, PersonalizationDraft, QCResult, ToneProfile
from evidence_extractor import evidence_to_payload
from copy_guardrails import local_personalization_flags
from defaults import _default_next_sentence

from string import Template
import json


SYSTEM_TEMPLATE, _USER_TEMPLATE_STR = load_prompt_pair("qc_personalization")
_USER_TEMPLATE = Template(_USER_TEMPLATE_STR)

BLOCKING_QC_FLAGS = {
    "em_dash",
    "unsupported_claims",
    "unsupported_claim",
    "hallucination",
    "download_claim",
    "company_name_not_lowercase",
    "missing_evidence_used_for_copy",
    "line_not_grounded_in_evidence",
    "evidence_used_not_in_extracted_facts",
    "missing_grounding_evidence",
}


def _local_flags(
    draft: PersonalizationDraft,
    evidence: EvidenceResult | None = None,
    lead: LeadInput | None = None,
) -> list[str]:
    return local_personalization_flags(draft, evidence, lead)


def check_quality(
    client: LLMClient,
    lead: LeadInput,
    evidence: EvidenceResult,
    draft: PersonalizationDraft,
    tone_profile: ToneProfile | None = None,
    temperature: float = 0.4,
    feedback_context: str = "",
) -> QCResult:
    next_sentence = lead.campaign_context.strip() or _default_next_sentence(lead)

    user_text = _USER_TEMPLATE.safe_substitute(
        company_name=lead.company_name or "",
        website_url=lead.website_url or "",
        recipient_name=lead.recipient_name or "",
        recipient_role=lead.recipient_role or "",
        campaign_context=lead.campaign_context or "",
        linkedin_observation=lead.linkedin_observation or "",
        app_flow_observation=lead.app_flow_observation or "",
        recent_news_note=lead.recent_news_note or "",
        competitor_context=lead.competitor_context or "",
        required_next_sentence=next_sentence,
        evidence_text=json.dumps(evidence_to_payload(evidence), ensure_ascii=False),
        draft_opening_line=draft.opening_line or "",
        draft_tailored_insight=draft.tailored_insight or "",
        draft_chosen_angle=draft.chosen_angle or "",
        draft_evidence_used=json.dumps(draft.evidence_used_for_copy, ensure_ascii=False),
        tone_profile_text=json.dumps(
            tone_profile.to_prompt_payload() if tone_profile else {},
            ensure_ascii=False,
        ),
        feedback_context=feedback_context,
    )

    local_flags = _local_flags(draft, evidence, lead)
    try:
        raw = client.complete_json(SYSTEM_TEMPLATE, user_text, temperature=temperature)
    except LLMError as exc:
        return QCResult(
            score=0,
            passed=False,
            reasons=[str(exc)],
            quality_flags=local_flags + ["qc_failed"],
        )

    flags = [str(flag).strip() for flag in raw.get("quality_flags", []) if str(flag).strip()]
    for required_flag in local_flags:
        if required_flag not in flags:
            flags.append(required_flag)

    if BLOCKING_QC_FLAGS.intersection(flags):
        passed = False
        score = min(int(raw.get("score", 0) or 0), 7)
    else:
        score = int(raw.get("score", 0) or 0)
        passed = bool(raw.get("pass", False)) and score >= 8

    return QCResult(
        score=max(0, min(10, score)),
        passed=passed,
        reasons=[str(reason) for reason in raw.get("reasons", []) if str(reason).strip()],
        suggested_rewrite=raw.get("suggested_rewrite", {})
        if isinstance(raw.get("suggested_rewrite", {}), dict)
        else {},
        quality_flags=flags,
    )