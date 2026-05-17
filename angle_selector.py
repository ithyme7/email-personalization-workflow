from __future__ import annotations

import re

from models import AngleSelection, EvidenceFact, EvidenceResult
from taxonomy import (
    APP_FIRST_MARKERS,
    BROAD_POSITIONING_MARKERS,
    DISALLOWED_FRICTION_TYPES,
    FRICTION_MARKERS,
    HIGH_VALUE_BUG_MARKERS,
    HIGH_VALUE_CTA_MARKERS,
    HIGH_VALUE_FLOW_MARKERS,
    HIGH_VALUE_PROOF_MARKERS,
    LOW_PRIORITY_MICRO_UX_MARKERS,
    OUTCOME_TERMS,
    POSITIVE_ONLY_MARKERS,
    PRIORITY_FRICTION_TYPES,
)

OUTCOME_WORDS = OUTCOME_TERMS | {"trust"}


def _combined_text(fact: EvidenceFact) -> str:
    return " ".join(
        [
            fact.fact,
            fact.why_it_matters,
            fact.friction_type,
            fact.surface_checked,
            fact.conversion_outcome,
            fact.why_this_angle,
        ]
    ).lower()


def _evidence_text(fact: EvidenceFact) -> str:
    return " ".join(
        [
            fact.fact,
            fact.why_it_matters,
            fact.surface_checked,
            fact.conversion_outcome,
            fact.why_this_angle,
        ]
    ).lower()


def _contains_any(text: str, markers: set[str]) -> bool:
    return any(marker in text for marker in markers)


def _has_outcome(fact: EvidenceFact) -> bool:
    text = _combined_text(fact)
    return bool(fact.conversion_outcome.strip()) or _contains_any(text, OUTCOME_WORDS)


def _has_visible_friction(fact: EvidenceFact) -> bool:
    text = _evidence_text(fact)
    if fact.friction_type in PRIORITY_FRICTION_TYPES and fact.friction_type != "other_specific_friction":
        return True
    return _contains_any(text, FRICTION_MARKERS)


def _looks_positive_only(fact: EvidenceFact) -> bool:
    text = _combined_text(fact)
    return _contains_any(text, POSITIVE_ONLY_MARKERS) and not _has_visible_friction(fact)


def _visual_confidence_rank(fact: EvidenceFact) -> int:
    text = _combined_text(fact)
    if "visual confidence: high" in text or "high-confidence" in text:
        return 0
    if "visual confidence: medium" in text or "medium-confidence" in text:
        return 1
    if "visual confidence: low" in text or "low-confidence" in text:
        return 3
    return 2


def _is_visual_claim(fact: EvidenceFact) -> bool:
    text = _combined_text(fact)
    visual_markers = {
        "visual confidence:",
        "screenshot",
        "mobile screenshot",
        "desktop screenshot",
        "rendered",
        "above the fold",
        "below the fold",
        "low contrast",
        "horizontal overflow",
        "offscreen",
        "cropped",
        "overlap",
    }
    visual_friction_types = {
        "broken_formatting",
        "low_visibility_cta",
        "hidden_signup_or_login",
    }
    return _contains_any(text, visual_markers) or fact.friction_type in visual_friction_types


def _fact_block_reasons(fact: EvidenceFact) -> list[str]:
    reasons: list[str] = []
    if fact.too_generic_to_use:
        reasons.append("generic_evidence")
    if fact.blog_used or fact.friction_type in DISALLOWED_FRICTION_TYPES or "blog" in fact.surface_checked.lower():
        reasons.append("blog_angle_low_value")
    if fact.friction_type not in PRIORITY_FRICTION_TYPES:
        reasons.append("unsupported_friction_type")
    if not _has_visible_friction(fact):
        reasons.append("missing_visible_friction")
    if not _has_outcome(fact):
        reasons.append("missing_outcome_tie")
    if _looks_positive_only(fact):
        reasons.append("positive_observation_only")
    if _visual_confidence_rank(fact) == 3 and _is_visual_claim(fact):
        reasons.append("low_confidence_visual_finding")
    return reasons


def _angle_bucket(fact: EvidenceFact) -> int:
    text = _combined_text(fact)
    friction_priority = PRIORITY_FRICTION_TYPES.get(fact.friction_type, 99)

    if fact.friction_type == "broken_formatting" or _contains_any(text, HIGH_VALUE_BUG_MARKERS):
        return 0
    if fact.friction_type in {
        "onboarding_friction",
        "signup_friction",
        "checkout_friction",
        "unnecessary_clicks",
        "hidden_signup_or_login",
    } or _contains_any(text, HIGH_VALUE_FLOW_MARKERS):
        return 1
    if fact.friction_type == "low_visibility_cta" or _contains_any(text, HIGH_VALUE_CTA_MARKERS):
        return 2
    if fact.friction_type in {"weak_testimonial_or_case_study", "weak_or_missing_proof"} or _contains_any(
        text, HIGH_VALUE_PROOF_MARKERS
    ):
        return 3
    if fact.friction_type in {"broad_positioning", "unclear_value_prop"} or _contains_any(
        text, BROAD_POSITIONING_MARKERS
    ):
        return 4
    if fact.friction_type == "app_store_signal":
        return 1 if _contains_any(text, APP_FIRST_MARKERS) else 5
    return friction_priority


def _micro_ux_penalty(fact: EvidenceFact) -> int:
    text = _combined_text(fact)
    if _contains_any(text, LOW_PRIORITY_MICRO_UX_MARKERS) and not (
        _contains_any(text, HIGH_VALUE_BUG_MARKERS)
        or _contains_any(text, HIGH_VALUE_CTA_MARKERS)
        or _contains_any(text, HIGH_VALUE_FLOW_MARKERS)
    ):
        return 2
    return 0


def _surface_rank(fact: EvidenceFact) -> int:
    surface_text = fact.surface_checked.lower()
    evidence_text = _evidence_text(fact)
    if (
        "app onboarding" in surface_text
        or "signup" in surface_text
        or "checkout" in surface_text
        or "booking" in surface_text
        or _contains_any(evidence_text, {"first screen", "booking flow", "signup flow", "onboarding"})
    ):
        return 0
    if "app listing" in surface_text or "app-store" in surface_text or "google play" in surface_text:
        return 1
    if "mobile" in surface_text or "screenshot" in evidence_text:
        return 2
    if "landing" in surface_text or "homepage" in surface_text or "website" in surface_text:
        return 3
    if "case study" in surface_text or "testimonial" in surface_text:
        return 4
    if "blog" in surface_text:
        return 7
    return 5


def _rank_fact(fact: EvidenceFact) -> tuple[int, int, int, int, int, int, int]:
    explicit_priority = fact.angle_priority if fact.angle_priority > 0 else 9
    angle_bucket = _angle_bucket(fact)
    strength_rank = {"strong": 0, "medium": 1, "weak": 2}.get(fact.strength, 3)
    return (
        angle_bucket,
        _micro_ux_penalty(fact),
        strength_rank,
        _visual_confidence_rank(fact),
        _surface_rank(fact),
        explicit_priority,
        len(fact.fact),
    )


def select_angle(evidence: EvidenceResult) -> AngleSelection:
    allowed: list[EvidenceFact] = []
    blocked: list[str] = []
    flags: list[str] = []

    for fact in evidence.facts:
        reasons = _fact_block_reasons(fact)
        if reasons:
            blocked.append(f"{fact.fact} [{', '.join(reasons)}]")
            flags.extend(reasons)
            continue
        allowed.append(fact)

    allowed = sorted(allowed, key=_rank_fact)
    selected = allowed[0] if allowed else None
    blocked_flags = list(dict.fromkeys(flags))

    if selected is None:
        return AngleSelection(
            selected_fact=None,
            allowed_facts=[],
            blocked_facts=blocked,
            decision="manual_review_no_sendable_angle",
            quality_flags=list(dict.fromkeys(blocked_flags + ["angle_gate_no_sendable_friction"])),
            reviewer_notes=[
                "No evidence survived the Step B angle gate. Needs a manual friction, proof, positioning, or conversion observation before writing."
            ],
            needs_manual_review=True,
        )

    selected_flags: list[str] = []
    selected_notes: list[str] = []
    selected_notes.append(
        "Angle gate selected the highest-ranked current friction point using the priority order."
    )
    if selected.strength != "strong":
        selected_flags.append("selected_angle_not_strong")
        selected_notes.append("Selected angle is usable but not strong, so review before sending.")

    if selected.friction_type == "app_store_signal":
        selected_flags.append("app_store_angle_review")
        selected_notes.append("Selected angle is based on public app-store/app-listing evidence, so check it manually if possible.")

    return AngleSelection(
        selected_fact=selected,
        allowed_facts=allowed[:3],
        blocked_facts=blocked,
        decision="selected_sendable_angle" if not selected_flags else "selected_review_angle",
        quality_flags=list(dict.fromkeys(selected_flags)),
        reviewer_notes=selected_notes,
        needs_manual_review=bool(selected_flags),
    )


def evidence_for_selected_angle(evidence: EvidenceResult, selection: AngleSelection) -> EvidenceResult:
    selected = selection.selected_fact
    if selected is None:
        selected_facts: list[EvidenceFact] = []
    else:
        supporting_facts = [
            fact
            for fact in selection.allowed_facts
            if fact is not selected
            and (
                fact.friction_type == selected.friction_type
                or fact.conversion_outcome == selected.conversion_outcome
                or fact.surface_checked == selected.surface_checked
            )
        ]
        selected_facts = [selected] + supporting_facts[:1]
    selected_angles = [
        f"{fact.friction_type}: {fact.fact} Outcome: {fact.conversion_outcome}".strip()
        for fact in selected_facts
    ]
    return EvidenceResult(
        facts=selected_facts,
        possible_angles=selected_angles,
        needs_manual_review=evidence.needs_manual_review or selection.needs_manual_review,
        reviewer_notes=evidence.reviewer_notes + selection.reviewer_notes,
        raw=evidence.raw,
    )
