from __future__ import annotations

import re
from urllib.parse import urlparse

from models import EvidenceResult, LeadInput, PersonalizationDraft
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


DOWNLOAD_PATTERNS = (
    r"\bi\s+downloaded\b",
    r"\bi\s+installed\b",
    r"\bafter\s+downloading\b",
    r"\bafter\s+installing\b",
)


def _brand_candidates(lead: LeadInput | None) -> list[str]:
    if lead is None:
        return []
    candidates: list[str] = []
    if lead.company_name:
        candidates.append(lead.company_name)
    parsed = urlparse(lead.website_url or "")
    host = parsed.netloc.replace("www.", "")
    if host:
        candidates.append(host.split(".")[0])
    cleaned: list[str] = []
    for candidate in candidates:
        value = re.sub(r"\s+", " ", str(candidate or "").strip())
        if len(value) >= 3 and value.lower() not in {"app", "www", "com", "the"}:
            cleaned.append(value)
    return sorted(dict.fromkeys(cleaned), key=len, reverse=True)


def _replace_brand_casing(text: str, lead: LeadInput | None) -> str:
    result = str(text or "")
    for candidate in _brand_candidates(lead):
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(candidate)}(?![A-Za-z0-9])", re.IGNORECASE)
        result = pattern.sub(candidate.lower(), result)
    return result


def _remove_download_claims(text: str) -> str:
    result = str(text or "")
    replacements = {
        r"\bi\s+downloaded\s+the\b": "I opened the",
        r"\bi\s+downloaded\b": "I opened",
        r"\bi\s+installed\s+the\b": "I opened the",
        r"\bi\s+installed\b": "I opened",
        r"\bafter\s+downloading\b": "after opening",
        r"\bafter\s+installing\b": "after opening",
    }
    for pattern, replacement in replacements.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


def sanitize_personalization_draft(draft: PersonalizationDraft, lead: LeadInput | None = None) -> PersonalizationDraft:
    """Apply deterministic copy safety fixes before QC sees the draft."""
    opening_line = _replace_brand_casing(_remove_download_claims(draft.opening_line), lead).strip()
    tailored_insight = _replace_brand_casing(_remove_download_claims(draft.tailored_insight), lead).strip()
    chosen_angle = _replace_brand_casing(draft.chosen_angle, lead).strip()
    evidence_used = [_replace_brand_casing(value, lead).strip() for value in draft.evidence_used_for_copy if str(value).strip()]
    return PersonalizationDraft(
        opening_line=opening_line,
        tailored_insight=tailored_insight,
        chosen_angle=chosen_angle,
        evidence_used_for_copy=evidence_used,
    )


def _has_download_claim(text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in DOWNLOAD_PATTERNS)


def _has_non_lowercase_brand(text: str, lead: LeadInput | None) -> bool:
    for candidate in _brand_candidates(lead):
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(candidate)}(?![A-Za-z0-9])", re.IGNORECASE)
        for match in pattern.finditer(text or ""):
            if match.group(0) != match.group(0).lower():
                return True
    return False


def local_personalization_flags(
    draft: PersonalizationDraft,
    evidence: EvidenceResult | None = None,
    lead: LeadInput | None = None,
) -> list[str]:
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
    if _has_download_claim(text):
        flags.append("download_claim")
    if _has_non_lowercase_brand(draft.opening_line, lead):
        flags.append("company_name_not_lowercase")
    if draft.opening_line and not (
        line_lower.startswith("i was ")
        or line_lower.startswith("i just ")
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
