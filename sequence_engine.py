from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llm_client import LLMClient
from models import LeadInput, PersonalizationDraft, ToneProfile
from copy_guardrails import sanitize_personalization_draft

from string import Template

logger = logging.getLogger(__name__)


# --- Follow-up strategy per step ---
STEP_STRATEGIES = {
    1: "Add new value — share a relevant insight, case study, or data point the recipient hasn't seen",
    2: "Social proof — reference results others in their space have achieved",
    3: "Low-friction ask — make a clear single ask (15-min call, quick question, one-click demo)",
    4: "Breakup email — short, respectful close that signals you'll stop following up unless they say otherwise",
}

MAX_SEQUENCE_STEPS = 4


@dataclass
class SequenceStep:
    step_number: int
    follow_up_type: str  # "value" | "social_proof" | "direct_ask" | "breakup"
    opening_line: str = ""
    body_text: str = ""
    cta_text: str = ""
    chosen_angle: str = ""
    evidence_used_for_copy: list[str] = field(default_factory=list)
    quality_score: float = 0.0
    quality_flags: list[str] = field(default_factory=list)
    needs_review: bool = True


@dataclass
class SequenceResult:
    lead_id: str
    company_name: str
    original_email: PersonalizationDraft | None = None
    steps: list[SequenceStep] = field(default_factory=list)
    sequence_status: str = "draft"  # "draft" | "qc_passed" | "needs_review"
    overall_quality_score: float = 0.0
    reviewer_notes: list[str] = field(default_factory=list)


def _load_followup_system_prompt() -> str:
    path = Path(__file__).resolve().parent / "prompts" / "followup_sequence_system.txt"
    return path.read_text(encoding="utf-8")


def _load_followup_user_template() -> Template:
    path = Path(__file__).resolve().parent / "prompts" / "followup_sequence_user.txt"
    return Template(path.read_text(encoding="utf-8"))


def _pick_remaining_evidence(
    all_evidence: list[str],
    used_in_original: list[str],
    count: int = 3,
) -> list[str]:
    """Pick evidence items not already used in the original email."""
    unused = [e for e in all_evidence if e not in used_in_original]
    return unused[:count]


def _build_user_payload(
    lead: LeadInput,
    original_draft: PersonalizationDraft,
    step_number: int,
    tone_profile: ToneProfile | None,
    all_evidence_texts: list[str],
    feedback_context: str = "",
) -> str:
    """Build the user-facing prompt for a follow-up step."""
    total_steps = min(MAX_SEQUENCE_STEPS, 4)
    used_evidence = original_draft.evidence_used_for_copy or []
    remaining = _pick_remaining_evidence(all_evidence_texts, used_evidence)

    return _load_followup_user_template().safe_substitute(
        original_angle=original_draft.chosen_angle or "",
        original_opening_line=original_draft.opening_line or "",
        step_number=step_number,
        total_steps=total_steps,
        step_strategy=STEP_STRATEGIES.get(step_number, STEP_STRATEGIES[MAX_SEQUENCE_STEPS]),
        reply_status="has not replied" if step_number < 4 else "no reply after previous follow-ups",
        reply_context="No reply received to the previous email",
        failed_angles=" | ".join(original_draft.evidence_used_for_copy[:3]),
        used_evidence=" | ".join(used_evidence[:5]),
        remaining_evidence_text=" | ".join(remaining) if remaining else "No additional evidence available",
        tone_profile_json=json.dumps(
            tone_profile.to_prompt_payload() if tone_profile else {}
        ),
        feedback_context=feedback_context,
    )


def generate_sequence(
    client: LLMClient,
    lead: LeadInput,
    original_draft: PersonalizationDraft,
    tone_profile: ToneProfile | None,
    all_evidence_texts: list[str],
    feedback_context: str = "",
    max_steps: int = MAX_SEQUENCE_STEPS,
) -> SequenceResult:
    """Generate a full follow-up sequence for a lead.

    Steps:
      1. Value-add email (new insight/angle)
      2. Social proof email
      3. Direct ask email
      4. Breakup email

    Each step uses a different angle and fresh evidence where available.
    """
    result = SequenceResult(
        lead_id=f"{lead.company_name}:{lead.website_url}",
        company_name=lead.company_name,
        original_email=original_draft,
        sequence_status="draft",
        reviewer_notes=[],
    )

    steps_to_generate = min(max_steps, MAX_SEQUENCE_STEPS)
    blocklist_angles: set[str] = set()

    for step_num in range(1, steps_to_generate + 1):
        step = _generate_single_step(
            client=client,
            lead=lead,
            original_draft=original_draft,
            step_number=step_num,
            tone_profile=tone_profile,
            all_evidence_texts=all_evidence_texts,
            blocklist_angles=blocklist_angles,
            feedback_context=feedback_context,
        )
        result.steps.append(step)

        # If step generated an angle, add it to blocklist for next steps
        if step.chosen_angle:
            blocklist_angles.add(step.chosen_angle.split(":")[0].strip().lower())

        # Stop generating if breakup step is reached
        if step.follow_up_type == "breakup":
            break

    # Score the overall sequence
    all_scores = [s.quality_score for s in result.steps if s.quality_score > 0]
    result.overall_quality_score = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0.0

    # Needs review if any step has quality flags
    result.needs_review = any(s.needs_review for s in result.steps)
    result.sequence_status = "needs_review" if result.needs_review else "qc_passed"

    return result


def _generate_single_step(
    client: LLMClient,
    lead: LeadInput,
    original_draft: PersonalizationDraft,
    step_number: int,
    tone_profile: ToneProfile | None,
    all_evidence_texts: list[str],
    blocklist_angles: set[str],
    feedback_context: str = "",
) -> SequenceStep:
    """Generate a single follow-up email step."""
    system_prompt = _load_followup_system_prompt()
    user_payload = _build_user_payload(
        lead=lead,
        original_draft=original_draft,
        step_number=step_number,
        tone_profile=tone_profile,
        all_evidence_texts=all_evidence_texts,
        feedback_context=feedback_context,
    )

    try:
        raw = client.complete_json(system_prompt, user_payload, temperature=0.5)
    except Exception as exc:
        logger.error("Follow-up generation failed for step %d: %s", step_number, exc)
        return SequenceStep(
            step_number=step_number,
            follow_up_type="value",
            quality_score=0.0,
            quality_flags=[f"llm_error: {exc}"],
            needs_review=True,
        )

    step = _parse_step_response(raw, step_number, blocklist_angles)
    return step


def _parse_step_response(raw: dict[str, Any], step_number: int, blocklist: set[str]) -> SequenceStep:
    """Parse LLM response into a SequenceStep with validation."""
    follow_up_type = str(raw.get("follow_up_type", "value")).lower()
    if follow_up_type not in {"value", "social_proof", "direct_ask", "breakup"}:
        follow_up_type = "value"

    angle = str(raw.get("chosen_angle", "")).strip()
    opening = str(raw.get("opening_line", "")).strip()
    body = str(raw.get("body_text", "")).strip()
    cta = str(raw.get("cta_text", "")).strip()
    evidence = [str(e).strip() for e in raw.get("evidence_used_for_copy", []) if str(e).strip()]

    # Quality flags
    flags: list[str] = []
    needs_review = False

    if not angle:
        flags.append("missing_angle")
        needs_review = True
    if not opening:
        flags.append("missing_opening_line")
        needs_review = True
    if not body:
        flags.append("missing_body_text")
        needs_review = True
    if not cta and follow_up_type != "breakup":
        flags.append("missing_cta")
        needs_review = True

    # Check for angle reuse
    if angle:
        angle_key = angle.split(":")[0].strip().lower()
        if any(blocked in angle_key or angle_key in blocked for blocked in blocklist):
            flags.append("repeated_angle")
            needs_review = True

    # Generic quality heuristics
    if opening and len(opening) < 20:
        flags.append("opening_too_short")
    if body and len(body) < 30:
        flags.append("body_too_short")
    if follow_up_type != "breakup" and any(
        kw in (opening + " " + body).lower()
        for kw in ["just checking in", "bumping this", "following up again", "sorry to bother"]
    ):
        flags.append("generic_followup_language")
        needs_review = True

    # Score: start high, deduct for flags
    score = 8.0
    if "missing_angle" in flags:
        score -= 4
    if "missing_opening_line" in flags:
        score -= 3
    if "missing_body_text" in flags:
        score -= 2
    if "missing_cta" in flags:
        score -= 1.5
    if "repeated_angle" in flags:
        score -= 3
    if "generic_followup_language" in flags:
        score -= 2
    if "opening_too_short" in flags:
        score -= 1
    if "body_too_short" in flags:
        score -= 1

    return SequenceStep(
        step_number=step_number,
        follow_up_type=follow_up_type,
        opening_line=opening,
        body_text=body,
        cta_text=cta,
        chosen_angle=angle,
        evidence_used_for_copy=evidence,
        quality_score=max(0.0, min(10.0, score)),
        quality_flags=flags,
        needs_review=needs_review or score < 7,
    )


def sequence_result_to_rows(result: SequenceResult, base_row: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a SequenceResult into export-ready rows (one per step)."""
    rows = []
    for step in result.steps:
        row = base_row.copy()
        row.update(
            {
                "sequence_step": step.step_number,
                "follow_up_type": step.follow_up_type,
                "sequence_opening_line": step.opening_line,
                "sequence_body_text": step.body_text,
                "sequence_cta_text": step.cta_text,
                "sequence_chosen_angle": step.chosen_angle,
                "sequence_evidence_used": " | ".join(step.evidence_used_for_copy),
                "sequence_quality_score": step.quality_score,
                "sequence_quality_flags": " | ".join(step.quality_flags) if step.quality_flags else "",
                "sequence_needs_review": step.needs_review,
            }
        )
        rows.append(row)
    return rows