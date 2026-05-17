from __future__ import annotations

from models import EvidenceResult, PersonalizationDraft
from deliverability import deliverability_flags
from grounding import grounding_flags
from taxonomy import ABSTRACT_PHRASES, BANNED_FILLER_WORDS, OUTCOME_TERMS, TECHNICAL_AUDIT_TERMS


POSITIVE_OBSERVATION_MARKERS = {
    "helps",
    "makes it easier",
    "is key to",
    "is crucial for",
    "could be key",
    "unique approach",
    "powerful motivator",
    "validation",
}

FRICTION_MARKERS = {
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
}

APP_EVIDENCE_MARKERS = {
    "app listing",
    "app onboarding",
    "app store",
    "google play",
    "review complaint",
    "paywall",
    "access code",
    "subscription",
    "first screen",
}


def local_personalization_flags(draft: PersonalizationDraft, evidence: EvidenceResult | None = None) -> list[str]:
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
    if any(phrase in line_lower for phrase in ABSTRACT_PHRASES) and not any(word in line_lower for word in FRICTION_MARKERS):
        flags.append("too_abstract")
    if any(marker in line_lower for marker in POSITIVE_OBSERVATION_MARKERS) and not any(
        marker in line_lower for marker in FRICTION_MARKERS
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
        app_evidence = any(marker in evidence_text for marker in APP_EVIDENCE_MARKERS)
        if app_evidence and ("website" in line_lower or "blog" in line_lower) and "app" not in line_lower:
            flags.append("wrong_surface")

    return list(dict.fromkeys(flags))
