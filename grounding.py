from __future__ import annotations

import re
from typing import Iterable

from models import EvidenceResult, PersonalizationDraft


STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "before",
    "because",
    "could",
    "from",
    "have",
    "into",
    "that",
    "their",
    "there",
    "this",
    "through",
    "users",
    "when",
    "where",
    "which",
    "with",
    "would",
    "your",
}


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9'-]{3,}", text.lower())
    return {word.strip("'") for word in words if word not in STOPWORDS}


def _evidence_text(evidence: EvidenceResult) -> str:
    chunks: list[str] = []
    for fact in evidence.facts:
        chunks.extend([fact.fact, fact.why_it_matters, fact.surface_checked, fact.conversion_outcome])
    return " ".join(chunks)


def _overlap_ratio(claim_terms: Iterable[str], evidence_terms: set[str]) -> float:
    terms = set(claim_terms)
    if not terms:
        return 0.0
    return len(terms & evidence_terms) / len(terms)


def grounding_flags(draft: PersonalizationDraft, evidence: EvidenceResult) -> list[str]:
    evidence_terms = _keywords(_evidence_text(evidence))
    line_terms = _keywords(draft.opening_line)
    used_terms = _keywords(" ".join(draft.evidence_used_for_copy))
    flags: list[str] = []

    if not evidence_terms:
        return ["missing_grounding_evidence"]
    if used_terms and _overlap_ratio(used_terms, evidence_terms) < 0.2:
        flags.append("evidence_used_not_in_extracted_facts")
    if line_terms and _overlap_ratio(line_terms, evidence_terms) < 0.18:
        flags.append("line_not_grounded_in_evidence")
    return flags
