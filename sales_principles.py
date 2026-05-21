from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from taxonomy import OUTCOME_TERMS


FRICTION_TERMS = {
    "activation",
    "booking",
    "checkout",
    "churn",
    "complaint",
    "confusing",
    "conversion",
    "drop-off",
    "drop off",
    "friction",
    "hidden",
    "login",
    "missing",
    "onboarding",
    "paywall",
    "proof",
    "retention",
    "signup",
    "trust",
    "unclear",
    "weak",
}

GENERIC_CLEVER_TERMS = {
    "caught my eye",
    "game-changer",
    "great work",
    "impressive",
    "love what you're doing",
    "loved your",
    "really cool",
    "smart approach",
    "unique approach",
}

SALESY_TERMS = {
    "10x",
    "amazing",
    "crush",
    "game-changer",
    "guaranteed",
    "limited time",
    "revolutionary",
    "skyrocket",
    "supercharge",
    "unlock massive",
}

FAKE_APP_FAMILIARITY_PATTERNS = (
    r"\bi\s+downloaded\s+(?:the\s+)?(?:[a-z0-9'\-]+\s+)?app\b",
    r"\bi\s+installed\s+(?:the\s+)?(?:[a-z0-9'\-]+\s+)?app\b",
    r"\bi\s+tried\s+(?:the\s+)?(?:[a-z0-9'\-]+\s+)?app\b",
    r"\bi\s+loved\s+using\s+(?:the\s+)?(?:[a-z0-9'\-]+\s+)?app\b",
    r"\bi\s+opened\s+(?:the\s+)?(?:[a-z0-9'\-]+\s+)?app\b",
)

MEANINGFUL_CLAIM_TERMS = {
    "raised",
    "funding",
    "traffic",
    "visitors",
    "downloads",
    "revenue",
    "doubled",
    "profitable",
    "used by",
    "customers include",
}

IMPLICATION_CUES = {
    "could mean",
    "could be",
    "might be",
    "may be",
    "usually that means",
    "usually means",
    "suggests",
    "which could",
    "that could",
    "that might",
    "that may",
    "risk",
    "without letting",
}

TENSION_TERMS = {
    "activation",
    "bookings",
    "booking",
    "conversion",
    "drop-off",
    "drop off",
    "friction",
    "quality",
    "retention",
    "scale",
    "scaling",
    "trust",
    "volume",
}

BUSINESS_SIGNAL_TERMS = {
    "hiring",
    "sdr",
    "sales development",
    "opening",
    "role",
    "job",
    "jobs",
    "careers",
    "review",
    "rating",
    "paywall",
    "signup",
    "onboarding",
    "booking",
    "demo",
    "pricing",
    "trial",
    "access code",
    "waitlist",
}

UNSUPPORTED_IMPLICATION_TERMS = {
    "revenue doubled",
    "doubled revenue",
    "profitable",
    "churn is up",
    "traffic dropped",
    "must be struggling",
    "almost certainly",
}

CLAIM_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "app",
    "are",
    "because",
    "before",
    "checking",
    "could",
    "from",
    "have",
    "into",
    "just",
    "line",
    "that",
    "the",
    "their",
    "there",
    "this",
    "users",
    "which",
    "with",
    "would",
    "your",
}


@dataclass
class SalesPrinciplesResult:
    specificity_score: int = 0
    one_insight_score: int = 0
    friction_relevance_score: int = 0
    outcome_bridge_score: int = 0
    commercial_relevance_score: int = 0
    signal_to_implication_bridge_score: int = 0
    salesy_language_flag: bool = False
    fake_familiarity_flag: bool = False
    evidence_supported_claim_score: int = 0
    sales_principles_score: int = 0
    sales_principles_summary: str = ""
    sales_principles_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _contains_any(text: str, terms: set[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9'\-]{2,}", text.lower())
        if token not in CLAIM_STOPWORDS
    }


def _word_count(text: str) -> int:
    return len([part for part in text.replace("/", " ").split() if part.strip()])


def _score_specificity(line: str, evidence: str, source_url: str) -> tuple[int, list[str]]:
    reasons: list[str] = []
    score = 45
    line_tokens = _tokens(line)
    evidence_tokens = _tokens(evidence)
    overlap = line_tokens.intersection(evidence_tokens)
    if evidence.strip():
        score += 20
    if source_url.strip():
        score += 10
    if len(overlap) >= 4:
        score += 25
    elif len(overlap) >= 2:
        score += 12
    else:
        reasons.append("weak_evidence_overlap")
        score -= 15
    if _contains_any(line, GENERIC_CLEVER_TERMS):
        reasons.append("generic_or_clever_without_specificity")
        score -= 25
    if _word_count(line) < 7:
        reasons.append("too_short_to_carry_specific_observation")
        score -= 10
    return max(0, min(100, score)), reasons


def _score_one_insight(line: str) -> tuple[int, list[str]]:
    lower = line.lower()
    reasons: list[str] = []
    idea_markers = len(re.findall(r"\b(and|plus|while|also|but|as well as)\b", lower))
    comma_count = line.count(",")
    score = 95
    if idea_markers >= 3 or comma_count >= 3:
        score = 45
        reasons.append("multiple_ideas_in_one_opener")
    elif idea_markers >= 2 or comma_count == 2:
        score = 70
        reasons.append("possibly_multiple_ideas")
    return score, reasons


def _score_friction(line: str, angle: str, evidence: str) -> tuple[int, list[str]]:
    opener_claim = f"{line} {angle}"
    if _contains_any(opener_claim, FRICTION_TERMS):
        return 92, []
    if _contains_any(line, GENERIC_CLEVER_TERMS):
        return 35, ["generic_praise_without_friction"]
    if _contains_any(evidence, FRICTION_TERMS):
        return 58, ["evidence_has_friction_but_opener_does_not_use_it"]
    return 55, ["missing_clear_friction_or_proof_gap"]


def _score_outcome_bridge(line: str, angle: str, campaign_context: str) -> tuple[int, list[str]]:
    outcome_terms = set(OUTCOME_TERMS) | {
        "activation",
        "booking",
        "bookings",
        "conversion",
        "drop-off",
        "drop off",
        "retention",
        "trust",
        "user behaviour",
        "user behavior",
    }
    combined = f"{line} {angle} {campaign_context}"
    if _contains_any(combined, outcome_terms):
        return 94, []
    return 48, ["missing_natural_bridge_to_pitch_outcome"]


def _score_commercial_relevance(line: str, angle: str, evidence: str) -> tuple[int, list[str]]:
    commercial_terms = {
        "activation",
        "booking",
        "bookings",
        "checkout",
        "conversion",
        "drop-off",
        "drop off",
        "paywall",
        "retention",
        "revenue",
        "signup",
        "subscribe",
        "subscription",
        "trust",
    }
    if _contains_any(f"{line} {angle} {evidence}", commercial_terms):
        return 90, []
    return 55, ["commercial_relevance_unclear"]


def _score_signal_to_implication_bridge(line: str, evidence: str) -> tuple[int, list[str]]:
    reasons: list[str] = []
    lower_line = line.lower()
    lower_evidence = evidence.lower()
    has_signal = bool(_tokens(line).intersection(_tokens(evidence))) or _contains_any(lower_line, BUSINESS_SIGNAL_TERMS)
    has_implication = _contains_any(lower_line, IMPLICATION_CUES)
    has_tension = _contains_any(lower_line, TENSION_TERMS)

    unsupported = [
        term for term in UNSUPPORTED_IMPLICATION_TERMS if term in lower_line and term not in lower_evidence
    ]
    if unsupported:
        return 25, ["unsupported_implication:" + ",".join(unsupported[:3])]

    hard_claims = {
        "revenue",
        "profitable",
        "traffic",
        "doubled",
        "funding",
        "raised",
    }
    invented_hard_claims = [
        term for term in hard_claims if term in lower_line and term not in lower_evidence
    ]
    if invented_hard_claims:
        return 35, ["unsupported_implication:" + ",".join(invented_hard_claims[:3])]

    if has_signal and has_implication and has_tension:
        return 92, []
    if has_signal and has_implication:
        return 68, ["weak_or_general_business_implication"]
    if has_signal:
        return 42, ["signal_only_no_implication_bridge"]
    return 50, ["missing_concrete_signal_for_implication_bridge"]


def _evidence_support_score(line: str, evidence: str, source_url: str) -> tuple[int, list[str]]:
    reasons: list[str] = []
    if not evidence.strip():
        return 0, ["missing_evidence_for_claim"]
    line_tokens = _tokens(line)
    evidence_tokens = _tokens(evidence)
    overlap = line_tokens.intersection(evidence_tokens)
    score = 55 + min(35, len(overlap) * 7)
    if source_url.strip():
        score += 10
    lower_line = line.lower()
    lower_evidence = evidence.lower()
    unsupported_claims = [
        term for term in MEANINGFUL_CLAIM_TERMS if term in lower_line and term not in lower_evidence
    ]
    if unsupported_claims:
        reasons.append("unsupported_meaningful_claim:" + ",".join(unsupported_claims[:3]))
        score = min(score, 25)
    if len(overlap) < 2:
        reasons.append("line_not_clearly_supported_by_evidence")
        score = min(score, 45)
    return max(0, min(100, score)), reasons


def _fake_familiarity(line: str, manual_app_verified: bool) -> bool:
    if manual_app_verified:
        return False
    return any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in FAKE_APP_FAMILIARITY_PATTERNS)


def evaluate_sales_principles(
    opener: str,
    evidence: str = "",
    source_url: str = "",
    angle: str = "",
    campaign_context: str = "",
    manual_app_verified: bool = False,
) -> SalesPrinciplesResult:
    line = str(opener or "").strip()
    if not line:
        return SalesPrinciplesResult(
            sales_principles_summary="Reject: no opener to evaluate.",
            sales_principles_reasons=["missing_opener"],
        )

    reasons: list[str] = []
    specificity, specificity_reasons = _score_specificity(line, evidence, source_url)
    one_insight, one_insight_reasons = _score_one_insight(line)
    friction, friction_reasons = _score_friction(line, angle, evidence)
    outcome, outcome_reasons = _score_outcome_bridge(line, angle, campaign_context)
    commercial, commercial_reasons = _score_commercial_relevance(line, angle, evidence)
    bridge, bridge_reasons = _score_signal_to_implication_bridge(line, evidence)
    evidence_score, evidence_reasons = _evidence_support_score(line, evidence, source_url)
    salesy = _contains_any(line, SALESY_TERMS)
    fake = _fake_familiarity(line, manual_app_verified)

    reasons.extend(specificity_reasons)
    reasons.extend(one_insight_reasons)
    reasons.extend(friction_reasons)
    reasons.extend(outcome_reasons)
    reasons.extend(commercial_reasons)
    reasons.extend(bridge_reasons)
    reasons.extend(evidence_reasons)
    if salesy:
        reasons.append("salesy_or_hype_language")
    if fake:
        reasons.append("fake_app_familiarity_claim")

    weighted = round(
        specificity * 0.20
        + one_insight * 0.12
        + friction * 0.18
        + outcome * 0.16
        + commercial * 0.12
        + bridge * 0.10
        + evidence_score * 0.10
    )
    if salesy:
        weighted = min(weighted, 72)
    if fake:
        weighted = min(weighted, 35)
    if bridge < 35:
        weighted = min(weighted, 58)
    score = max(0, min(100, weighted))

    if fake or evidence_score < 35:
        label = "Reject"
    elif score < 75 or reasons:
        label = "Edit"
    else:
        label = "Send"
    summary_bits = [f"{label}: sales-principles score {score}/100"]
    if reasons:
        summary_bits.append("; ".join(dict.fromkeys(reasons[:4])))
    else:
        summary_bits.append("specific, evidence-backed, commercially relevant, and low-salesy")

    return SalesPrinciplesResult(
        specificity_score=specificity,
        one_insight_score=one_insight,
        friction_relevance_score=friction,
        outcome_bridge_score=outcome,
        commercial_relevance_score=commercial,
        signal_to_implication_bridge_score=bridge,
        salesy_language_flag=salesy,
        fake_familiarity_flag=fake,
        evidence_supported_claim_score=evidence_score,
        sales_principles_score=score,
        sales_principles_summary=". ".join(summary_bits),
        sales_principles_reasons=list(dict.fromkeys(reasons)),
    )
