from __future__ import annotations

from llm_client import LLMClient, LLMError, load_prompt
from models import EvidenceResult, LeadInput, PersonalizationDraft, QCResult, ToneProfile
from evidence_extractor import evidence_to_payload
from copy_guardrails import local_personalization_flags


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
) -> QCResult:
    prompt = load_prompt("qc_personalization.txt")
    next_sentence = lead.campaign_context.strip() or "We help mobile app teams with this type of work, figure out where users drop off and why."
    payload = {
        "company_name": lead.company_name,
        "website_url": lead.website_url,
        "recipient_name": lead.recipient_name,
        "recipient_role": lead.recipient_role,
        "campaign_context": lead.campaign_context,
        "linkedin_observation": lead.linkedin_observation,
        "app_flow_observation": lead.app_flow_observation,
        "recent_news_note": lead.recent_news_note,
        "competitor_context": lead.competitor_context,
        "email_template_context": (
            "Hey [Name]\n"
            "{personalized_line}\n"
            f"{next_sentence}\n"
            "In a recent app project, session replays showed users bouncing off a paywall because the copy was unclear. "
            "After the paywall was rewritten, conversion improved materially."
        ),
        "evidence": evidence_to_payload(evidence),
        "draft": {
            "opening_line": draft.opening_line,
            "tailored_insight": draft.tailored_insight,
            "chosen_angle": draft.chosen_angle,
            "evidence_used_for_copy": draft.evidence_used_for_copy,
        },
        "tone_profile": tone_profile.to_prompt_payload() if tone_profile else {},
    }
    local_flags = _local_flags(draft, evidence, lead)
    try:
        raw = client.complete_json(prompt, payload)
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
        suggested_rewrite=raw.get("suggested_rewrite", {}) if isinstance(raw.get("suggested_rewrite", {}), dict) else {},
        quality_flags=flags,
    )
