from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from config import DATA_DIR


SENDABILITY_COLUMNS = [
    "sendability_decision",
    "sendability_score",
    "sendability_reasons",
    "human_decision",
    "edited_line",
    "edit_reason_category",
    "edit_notes",
]

HUMAN_DECISIONS = ["unreviewed", "send", "edit", "reject"]

EDIT_REASON_CATEGORIES = [
    "not_reviewed",
    "good_as_is",
    "tone",
    "wrong_surface",
    "too_technical",
    "weak_evidence",
    "too_generic",
    "too_long",
    "missing_outcome",
    "unsupported_claim",
    "bad_pitch_flow",
    "visual_evidence_uncertain",
    "other",
]

GOLDSET_COLUMNS = [
    "created_at",
    "company",
    "person",
    "role",
    "website",
    "original_line",
    "edited_line",
    "human_decision",
    "edit_reason_category",
    "edit_notes",
    "sendability_decision",
    "sendability_score",
    "sendability_reasons",
    "evidence_found",
    "quality_flags",
    "visual_confidence",
    "friction_type",
    "surface_checked",
    "conversion_outcome",
    "product_surface_type",
    "tone_profile",
    "model_name",
]

SEVERE_FLAGS = {
    "ai_generation_unavailable",
    "research_failed",
    "evidence_failed",
    "unsupported_claims",
    "unsupported_claim",
    "hallucination",
    "em_dash",
    "invalid_json",
}

EDIT_FLAGS = {
    "genericness",
    "generic",
    "too_generic",
    "manual_review",
    "weak_evidence",
    "blog_angle_low_value",
    "technical_audit_language",
    "wrong_surface",
    "low_confidence_visual_finding",
    "thin_content",
}

OUTCOME_TERMS = {
    "activation",
    "activate",
    "activated",
    "booking",
    "bookings",
    "signup",
    "sign-up",
    "sign up",
    "conversion",
    "convert",
    "converts",
    "converted",
    "drop off",
    "drop-off",
    "dropoff",
    "retention",
    "retain",
    "churn",
    "paywall",
    "subscription",
    "checkout",
    "first session",
    "onboarding",
    "revenue",
    "users",
    "user",
    "trial",
    "install",
    "download",
}

CONVERSATIONAL_STARTS = (
    "i was checking",
    "i was just checking",
    "i just checked",
    "i checked",
    "i opened",
    "i downloaded",
    "i tried",
    "i clicked",
    "i went through",
    "i was on",
    "i had a look",
)

VISUAL_CLAIM_TERMS = {
    "button",
    "cta",
    "first load",
    "screen",
    "page",
    "mobile",
    "formatting",
    "layout",
    "click",
    "clicked",
    "tap",
    "above the fold",
    "hard to see",
    "easy to miss",
    "broken",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _text(value).lower()


def _split_flags(value: Any) -> set[str]:
    text = _lower(value).replace("\n", "|").replace(";", "|").replace(",", "|")
    return {part.strip() for part in text.split("|") if part.strip()}


def _is_yes(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _lower(value) in {"true", "waar", "yes", "1", "review"}


def _word_count(text: str) -> int:
    return len([word for word in text.replace("/", " ").split() if word.strip()])


def _has_any(text: str, terms: set[str] | tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = item.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def evaluate_sendability(row: Mapping[str, Any]) -> dict[str, Any]:
    line = _text(row.get("personalized_line") or row.get("opening_line"))
    evidence = _text(row.get("evidence_found") or row.get("evidence_used_for_copy") or row.get("evidence_points"))
    source_urls = _text(row.get("source_urls"))
    status = _lower(row.get("status"))
    quality_flags = _split_flags(row.get("quality_flags"))
    visual_flags = _split_flags(row.get("visual_flags") or row.get("visual_quality_flags"))
    visual_confidence = _lower(row.get("visual_confidence"))
    product_surface = _lower(row.get("product_surface_type"))

    reject_reasons: list[str] = []
    edit_reasons: list[str] = []
    score = 100

    if not line or line.startswith("["):
        reject_reasons.append("no_sendable_personalized_line")
        score -= 45
    if status == "research only" or "research_only" in quality_flags:
        reject_reasons.append("research_only")
        score -= 30
    if not evidence:
        reject_reasons.append("missing_evidence")
        score -= 25
    if not source_urls and not _text(row.get("shareable_screenshots")):
        edit_reasons.append("source_or_screenshot_missing")
        score -= 10

    severe_matches = sorted(flag for flag in quality_flags if flag in SEVERE_FLAGS)
    if severe_matches:
        reject_reasons.extend(severe_matches)
        score -= 20 * len(severe_matches)

    edit_matches = sorted(flag for flag in quality_flags if flag in EDIT_FLAGS)
    if edit_matches:
        edit_reasons.extend(edit_matches)
        score -= 10 * len(edit_matches)

    if _is_yes(row.get("needs_manual_review")):
        edit_reasons.append("marked_for_manual_review")
        score -= 12
    if "—" in line or "–" in line:
        reject_reasons.append("dash_character_in_line")
        score -= 25
    if _word_count(line) > 38:
        edit_reasons.append("too_long")
        score -= 10
    if line and not _has_any(line, OUTCOME_TERMS):
        edit_reasons.append("missing_activation_conversion_or_dropoff_outcome")
        score -= 12
    if line and not _lower(line).startswith(CONVERSATIONAL_STARTS):
        edit_reasons.append("missing_conversational_opening")
        score -= 8
    if "app_first" in product_surface and _has_any(line, {"website", "landing page", "blog"}) and "app" not in _lower(line):
        edit_reasons.append("app_first_but_line_uses_website_surface")
        score -= 12
    if _has_any(line, VISUAL_CLAIM_TERMS) and visual_confidence in {"", "none", "low"}:
        edit_reasons.append("visual_claim_needs_manual_check")
        score -= 12
    if visual_flags and visual_confidence == "low":
        edit_reasons.append("low_confidence_visual_finding")
        score -= 8

    score = max(0, min(100, score))
    reasons = _dedupe(reject_reasons + edit_reasons)

    if reject_reasons:
        decision = "Reject"
    elif edit_reasons or score < 85:
        decision = "Edit"
    else:
        decision = "Send"

    return {
        "sendability_decision": decision,
        "sendability_score": score,
        "sendability_reasons": " | ".join(reasons),
    }


def apply_sendability_to_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for column in SENDABILITY_COLUMNS:
        if column not in out.columns:
            if column == "human_decision":
                out[column] = "unreviewed"
            elif column == "edit_reason_category":
                out[column] = "not_reviewed"
            else:
                out[column] = ""
    for idx, row in out.iterrows():
        result = evaluate_sendability(row.to_dict())
        for key, value in result.items():
            out.at[idx, key] = value
    return out


def apply_sendability_to_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item.update(evaluate_sendability(item))
        item.setdefault("human_decision", "unreviewed")
        item.setdefault("edited_line", "")
        item.setdefault("edit_reason_category", "not_reviewed")
        item.setdefault("edit_notes", "")
        enriched.append(item)
    return enriched


def rows_for_goldset(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "human_decision" not in df:
        return pd.DataFrame(columns=GOLDSET_COLUMNS)
    mask = df["human_decision"].fillna("unreviewed").astype(str).str.lower().ne("unreviewed")
    selected = df.loc[mask].copy()
    if selected.empty:
        return pd.DataFrame(columns=GOLDSET_COLUMNS)

    selected["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    selected["original_line"] = selected.get("personalized_line", "")
    selected["tone_profile"] = selected.get("tone_profile", "")
    selected["model_name"] = selected.get("model_name", "")
    for column in GOLDSET_COLUMNS:
        if column not in selected:
            selected[column] = ""
    return selected[GOLDSET_COLUMNS]


def append_goldset_feedback(df: pd.DataFrame, path: Path | None = None) -> tuple[Path, int]:
    path = path or DATA_DIR / "goldset" / "human_edits.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = rows_for_goldset(df)
    if rows.empty:
        return path, 0
    if path.exists():
        existing = pd.read_csv(path, dtype=str).fillna("")
        rows = pd.concat([existing, rows], ignore_index=True)
    rows.to_csv(path, index=False, encoding="utf-8-sig")
    return path, len(rows_for_goldset(df))
