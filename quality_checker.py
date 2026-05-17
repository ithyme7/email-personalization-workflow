from __future__ import annotations

from llm_client import LLMClient, LLMError, load_prompt
from models import EvidenceResult, LeadInput, PersonalizationDraft, QCResult, ToneProfile
from evidence_extractor import evidence_to_payload
from deliverability import deliverability_flags
from grounding import grounding_flags
from taxonomy import ABSTRACT_PHRASES, BANNED_FILLER_WORDS, OUTCOME_TERMS, TECHNICAL_AUDIT_TERMS


def _local_flags(draft: PersonalizationDraft, evidence: EvidenceResult | None = None) -> list[str]:
    text = f"{draft.opening_line} {draft.tailored_insight}"
    line_lower = draft.opening_line.lower()
    text_lower = text.lower()
    flags: list[str] = []
    if "—" in text:
        flags.append("em_dash")
    if any(word in text_lower for word in BANNED_FILLER_WORDS):
        flags.append("generic_praise")
    if "blog" in line_lower or "article" in line_lower:
        flags.append("blog_angle_low_value")
    if len(draft.opening_line.split()) > 40:
        flags.append("opening_line_too_long")
    if not draft.evidence_used_for_copy:
        flags.append("missing_evidence_used_for_copy")
    if draft.opening_line and not (
        line_lower.startswith("i was ")
        or line_lower.startswith("i just ")
        or line_lower.startswith("i downloaded ")
        or line_lower.startswith("i opened ")
        or line_lower.startswith("i checked ")
        or line_lower.startswith("i had a look ")
    ):
        flags.append("missing_conversational_template_open")
    outcome_words = OUTCOME_TERMS | {"complete"}
    if draft.opening_line and not any(word in line_lower for word in outcome_words):
        flags.append("missing_specific_dropoff_hypothesis")
    if any(phrase in line_lower for phrase in ABSTRACT_PHRASES) and not any(
        word in line_lower for word in ["costing", "hurting", "drop", "churn", "conversion", "signup", "booking"]
    ):
        flags.append("too_abstract")
    positive_observation_markers = [
        "helps",
        "makes it easier",
        "is key to",
        "is crucial for",
        "could be key",
        "unique approach",
        "powerful motivator",
        "validation",
    ]
    friction_markers = [
        "costing",
        "hurting",
        "killing",
        "drop",
        "churn",
        "friction",
        "unclear",
        "hidden",
        "hard to",
        "too many",
        "broken",
        "cropped",
        "blends",
        "weak",
        "missing",
        "not clear",
    ]
    if any(marker in line_lower for marker in positive_observation_markers) and not any(
        marker in line_lower for marker in friction_markers
    ):
        flags.append("missing_visible_friction")
    if any(term in line_lower for term in TECHNICAL_AUDIT_TERMS):
        flags.append("technical_audit_language")
    flags.extend(deliverability_flags(draft.opening_line))
    if evidence:
        flags.extend(grounding_flags(draft, evidence))
        evidence_text = " ".join(
            f"{fact.fact} {fact.surface_checked} {fact.why_it_matters}" for fact in evidence.facts
        ).lower()
        app_evidence = any(
            marker in evidence_text
            for marker in [
                "app listing",
                "app onboarding",
                "app store",
                "google play",
                "review complaint",
                "paywall",
                "access code",
                "subscription",
                "first screen",
            ]
        )
        if app_evidence and ("website" in line_lower or "blog" in line_lower) and "app" not in line_lower:
            flags.append("wrong_surface")
    return flags


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
    local_flags = _local_flags(draft, evidence)
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

    if "em_dash" in flags:
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
