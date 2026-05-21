from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from config import DATA_DIR
from deliverability import deliverability_flags
from mismatch_detection import apply_mismatch_to_row
from sales_principles import evaluate_sales_principles
from schemas import canonicalize_dataframe, canonicalize_row
from taxonomy import (
    APP_SURFACE_TERMS,
    B2B_TERMS,
    BOOKING_TERMS,
    COMMERCE_TERMS,
    CONVERSATIONAL_STARTS,
    EDIT_QUALITY_FLAGS,
    OUTCOME_TERMS,
    SEVERE_QUALITY_FLAGS,
    VISUAL_CLAIM_TERMS,
    WEBSITE_SURFACE_TERMS,
)


SENDABILITY_COLUMNS = [
    "row_id",
    "run_id",
    "example_id",
    "model_opening_line",
    "current_opening_line",
    "final_delivery_line",
    "sendability_decision",
    "sendability_score",
    "sendability_reasons",
    "hard_fail_reasons",
    "soft_edit_reasons",
    "evidence_score",
    "copy_quality_score",
    "outcome_alignment_score",
    "template_fit_score",
    "surface_correctness",
    "surface_correctness_score",
    "surface_correctness_reasons",
    "visual_reliability_score",
    "viewport_scope",
    "viewport_scope_score",
    "viewport_scope_reasons",
    "evidence_scope",
    "privacy_flags",
    "client_safe_asset_status",
    "sendability_dimensions",
    "specificity_score",
    "one_insight_score",
    "friction_relevance_score",
    "outcome_bridge_score",
    "commercial_relevance_score",
    "signal_to_implication_bridge_score",
    "salesy_language_flag",
    "fake_familiarity_flag",
    "evidence_supported_claim_score",
    "sales_principles_score",
    "sales_principles_summary",
    "sales_principles_reasons",
    "recommended_opener",
    "recommended_opener_option",
    "recommended_opener_reason",
    "selected_opener",
    "selected_opener_source",
    "edited_final_opener",
    "human_decision",
    "edited_line",
    "edit_reason_category",
    "edit_notes",
    "company_website_mismatch",
    "person_company_mismatch",
    "input_mapping_warning",
    "mismatch_reason",
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
    "signal_to_implication_bridge",
    "bad_pitch_flow",
    "visual_evidence_uncertain",
    "surface_uncertain",
    "other",
]

GOLDSET_SPLITS = ["reviewed_examples", "frozen_eval_set", "candidate_training_set"]

GOLDSET_COLUMNS = [
    "created_at",
    "imported_at",
    "goldset_split",
    "example_id",
    "row_id",
    "run_id",
    "source_kind",
    "origin_run_id",
    "origin_row_id",
    "label_source",
    "is_frozen_eval_example",
    "is_training_candidate",
    "company",
    "person",
    "role",
    "website",
    "model_opening_line",
    "current_opening_line",
    "final_delivery_line",
    "template_preview",
    "original_line",
    "edited_line",
    "preferred_line",
    "non_preferred_line",
    "human_decision",
    "edit_reason_category",
    "edit_notes",
    "recommended_opener",
    "recommended_opener_option",
    "recommended_opener_reason",
    "selected_opener",
    "selected_opener_source",
    "edited_final_opener",
    "non_selected_opener_options",
    "opener_option_1",
    "opener_option_1_angle",
    "opener_option_1_evidence",
    "opener_option_1_source_url",
    "opener_option_1_sendability",
    "opener_option_1_sendability_score",
    "opener_option_1_quality_flags",
    "opener_option_1_sales_principles_summary",
    "opener_option_1_rejection_or_edit_reason",
    "opener_option_2",
    "opener_option_2_angle",
    "opener_option_2_evidence",
    "opener_option_2_source_url",
    "opener_option_2_sendability",
    "opener_option_2_sendability_score",
    "opener_option_2_quality_flags",
    "opener_option_2_sales_principles_summary",
    "opener_option_2_rejection_or_edit_reason",
    "opener_option_3",
    "opener_option_3_angle",
    "opener_option_3_evidence",
    "opener_option_3_source_url",
    "opener_option_3_sendability",
    "opener_option_3_sendability_score",
    "opener_option_3_quality_flags",
    "opener_option_3_sales_principles_summary",
    "opener_option_3_rejection_or_edit_reason",
    "sales_principles_score",
    "sales_principles_summary",
    "sales_principles_reasons",
    "signal_to_implication_bridge_score",
    "sendability_decision",
    "sendability_score",
    "sendability_reasons",
    "hard_fail_reasons",
    "soft_edit_reasons",
    "evidence_score",
    "copy_quality_score",
    "outcome_alignment_score",
    "template_fit_score",
    "surface_correctness",
    "surface_correctness_score",
    "surface_correctness_reasons",
    "visual_reliability_score",
    "viewport_scope",
    "viewport_scope_score",
    "viewport_scope_reasons",
    "evidence_scope",
    "privacy_flags",
    "client_safe_asset_status",
    "evidence_found",
    "evidence_refs",
    "quality_flags",
    "company_website_mismatch",
    "person_company_mismatch",
    "input_mapping_warning",
    "mismatch_reason",
    "visual_confidence",
    "friction_type",
    "surface_used",
    "conversion_outcome",
    "product_type",
    "tone_profile",
    "writer_model",
    "judge_model",
]


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


def _has_assertive_claim_language(line: str) -> bool:
    lowered = line.lower()
    patterns = [
        "i bet",
        "that's costing",
        "that is costing",
        "almost certainly",
        "likely causes",
        "likely causing",
    ]
    return any(pattern in lowered for pattern in patterns)


def _hash_parts(*values: Any) -> str:
    payload = "\n".join(_text(value).lower() for value in values if _text(value))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16] if payload else ""


def _series_or_blank(df: pd.DataFrame, column: str) -> pd.Series:
    if column in df:
        return df[column].fillna("").astype(str)
    return pd.Series([""] * len(df), index=df.index, dtype=str)


def _line_from_mapping(row: Mapping[str, Any]) -> str:
    for column in [
        "edited_final_opener",
        "selected_opener",
        "recommended_opener",
        "personalized_line",
        "opening_line",
        "current_opening_line",
        "model_opening_line",
    ]:
        value = _text(row.get(column))
        if value:
            return value
    return ""


def ensure_line_provenance(df: pd.DataFrame) -> pd.DataFrame:
    """Add non-destructive line provenance columns used by review, evals and training."""
    out = df.copy()
    current = _series_or_blank(out, "selected_opener")
    for candidate_column in ["recommended_opener", "personalized_line", "opening_line", "current_opening_line"]:
        candidate = _series_or_blank(out, candidate_column)
        current = current.mask(current.str.strip().eq(""), candidate)

    original_candidates = [
        "model_opening_line",
        "original_line",
        "non_preferred_line",
        "personalized_line",
        "opening_line",
    ]
    model_line = pd.Series([""] * len(out), index=out.index, dtype=str)
    for column in original_candidates:
        candidate = _series_or_blank(out, column)
        model_line = model_line.mask(model_line.str.strip().eq(""), candidate)

    if "model_opening_line" in out:
        existing_model = _series_or_blank(out, "model_opening_line")
        out["model_opening_line"] = existing_model.mask(existing_model.str.strip().eq(""), model_line)
    else:
        out["model_opening_line"] = model_line

    out["current_opening_line"] = current.mask(current.str.strip().eq(""), _series_or_blank(out, "current_opening_line"))

    human = _series_or_blank(out, "human_decision").str.lower()
    edited = _series_or_blank(out, "edited_final_opener")
    edited = edited.mask(edited.str.strip().eq(""), _series_or_blank(out, "edited_line"))
    final_line = out["current_opening_line"].copy()
    use_edit = human.isin({"send", "edit"}) & edited.str.strip().ne("")
    final_line = final_line.mask(use_edit, edited)
    out["final_delivery_line"] = final_line
    if "edited_final_opener" not in out:
        out["edited_final_opener"] = edited

    if "row_id" not in out or _series_or_blank(out, "row_id").str.strip().eq("").any():
        existing_row_id = _series_or_blank(out, "row_id")
        generated = pd.Series([str(i + 1) for i in range(len(out))], index=out.index, dtype=str)
        out["row_id"] = existing_row_id.mask(existing_row_id.str.strip().eq(""), generated)
    if "run_id" not in out:
        out["run_id"] = ""
    if "example_id" not in out:
        out["example_id"] = ""
    existing_example = _series_or_blank(out, "example_id")
    generated_ids = out.apply(
        lambda row: _hash_parts(
            row.get("run_id"),
            row.get("row_id"),
            row.get("company"),
            row.get("person"),
            row.get("website"),
            row.get("model_opening_line"),
        ),
        axis=1,
    )
    out["example_id"] = existing_example.mask(existing_example.str.strip().eq(""), generated_ids)
    return out


def _score_from_penalties(base: int, penalties: list[int]) -> int:
    return max(0, min(100, base - sum(penalties)))


def evaluate_evidence(row: Mapping[str, Any]) -> tuple[int, list[str], list[str]]:
    evidence = _text(row.get("evidence_found") or row.get("evidence_used_for_copy") or row.get("evidence_points"))
    source_urls = _text(row.get("source_urls"))
    screenshots = _text(row.get("shareable_screenshots") or row.get("screenshots") or row.get("screenshot_paths"))
    visual_confidence = _lower(row.get("visual_confidence"))
    quality_flags = _split_flags(row.get("quality_flags"))

    hard: list[str] = []
    soft: list[str] = []
    score = 25

    if not evidence:
        hard.append("missing_evidence")
        return 0, hard, soft
    score += 25
    if source_urls:
        score += 20
    else:
        soft.append("source_url_missing")
    if screenshots:
        score += 10
    if visual_confidence == "high":
        score += 15
    elif visual_confidence == "medium":
        score += 8
    elif visual_confidence == "low":
        soft.append("low_visual_confidence")
        score -= 8
    if "weak_evidence" in quality_flags or "thin_content" in quality_flags:
        soft.append("weak_evidence")
        score -= 15
    if "unsupported_claims" in quality_flags or "unsupported_claim" in quality_flags:
        hard.append("unsupported_claim")
        score -= 35
    score = max(0, min(100, score))
    if score < 60:
        hard.append("evidence_below_send_threshold")
    return score, hard, soft


def evaluate_copy_quality(row: Mapping[str, Any]) -> tuple[int, list[str], list[str]]:
    line = _line_from_mapping(row)
    quality_flags = _split_flags(row.get("quality_flags"))
    hard: list[str] = []
    soft: list[str] = []
    penalties: list[int] = []

    if not line or line.startswith("["):
        hard.append("no_sendable_personalized_line")
        penalties.append(60)
    if "—" in line or "–" in line:
        hard.append("dash_character_in_line")
        penalties.append(35)
    words = _word_count(line)
    if words > 42:
        soft.append("far_too_long")
        penalties.append(20)
    elif words > 35:
        soft.append("slightly_too_long")
        penalties.append(10)
    if line and not _lower(line).startswith(CONVERSATIONAL_STARTS):
        soft.append("missing_conversational_opening")
        penalties.append(10)
    if any(flag in quality_flags for flag in {"genericness", "generic", "too_generic"}):
        soft.append("too_generic")
        penalties.append(15)
    if "technical_audit_language" in quality_flags:
        soft.append("technical_audit_language")
        penalties.append(15)
    if "hallucination" in quality_flags:
        hard.append("hallucination")
        penalties.append(45)
    delivery_flags = deliverability_flags(line)
    if "html_in_personalization_line" in delivery_flags:
        hard.append("html_in_personalization_line")
        penalties.append(45)
    if "spam_trigger_language" in delivery_flags:
        soft.append("spam_trigger_language")
        penalties.append(15)
    return _score_from_penalties(100, penalties), hard, soft


def evaluate_outcome_alignment(row: Mapping[str, Any]) -> tuple[int, list[str]]:
    line = _line_from_mapping(row)
    outcome = _text(row.get("conversion_outcome"))
    combined = f"{line} {outcome}"
    if not line:
        return 0, ["missing_line"]
    if _has_any(combined, OUTCOME_TERMS):
        return 100, []
    return 55, ["missing_activation_conversion_or_dropoff_outcome"]


def evaluate_template_fit(row: Mapping[str, Any]) -> tuple[int, list[str]]:
    line = _line_from_mapping(row)
    if not line or line.startswith("["):
        return 0, ["missing_line"]
    penalties: list[int] = []
    reasons: list[str] = []
    if not _lower(line).startswith(CONVERSATIONAL_STARTS):
        reasons.append("missing_conversational_opening")
        penalties.append(15)
    if _word_count(line) > 35:
        reasons.append("template_line_too_long")
        penalties.append(12)
    if not _has_any(line, OUTCOME_TERMS):
        reasons.append("pitch_bridge_unclear")
        penalties.append(18)
    if line.endswith("?"):
        reasons.append("question_opening_may_break_template_flow")
        penalties.append(8)
    return _score_from_penalties(100, penalties), reasons


def evaluate_visual_reliability(row: Mapping[str, Any]) -> tuple[int, list[str]]:
    line = _line_from_mapping(row)
    visual_confidence = _lower(row.get("visual_confidence"))
    visual_flags = _split_flags(row.get("visual_flags") or row.get("visual_quality_flags"))
    screenshots = _text(row.get("shareable_screenshots") or row.get("screenshots") or row.get("screenshot_paths"))
    reasons: list[str] = []
    if not visual_flags and not _has_any(line, VISUAL_CLAIM_TERMS):
        return 80, []
    score_by_confidence = {"high": 95, "medium": 78, "low": 45, "none": 35, "": 35}
    score = score_by_confidence.get(visual_confidence, 50)
    if not screenshots:
        reasons.append("visual_claim_without_shareable_screenshot")
        score -= 15
    if visual_confidence in {"", "none", "low"}:
        reasons.append("visual_claim_needs_manual_check")
    return max(0, min(100, score)), reasons


def evaluate_viewport_scope(row: Mapping[str, Any]) -> tuple[str, int, list[str]]:
    line = _line_from_mapping(row)
    blob = " ".join(
        [
            _text(row.get("shareable_screenshots")),
            _text(row.get("screenshots")),
            _text(row.get("screenshot_paths")),
            _text(row.get("visual_confidence_reasons")),
            _text(row.get("visual_flags") or row.get("visual_quality_flags")),
            _text(row.get("ux_validator_findings")),
            _text(row.get("advanced_detector_flags")),
        ]
    ).lower()
    visual_claim = _has_any(line, VISUAL_CLAIM_TERMS) or _has_any(blob, VISUAL_CLAIM_TERMS)
    has_mobile = "mobile" in blob
    has_desktop = "desktop" in blob
    if not visual_claim:
        return "not_required", 80, []
    if has_mobile and has_desktop:
        return "mobile_and_desktop", 95, []
    if has_mobile:
        return "mobile_only", 72, ["visual_claim_only_confirmed_on_mobile"]
    if has_desktop:
        return "desktop_only", 65, ["visual_claim_only_confirmed_on_desktop"]
    return "unknown", 35, ["visual_claim_without_viewport_scope"]


def evaluate_evidence_scope(row: Mapping[str, Any]) -> str:
    has_source = bool(_text(row.get("source_urls")))
    has_screenshot = bool(_text(row.get("shareable_screenshots") or row.get("screenshots") or row.get("screenshot_paths")))
    has_trace = bool(_text(row.get("trace_files")))
    if has_source and has_screenshot:
        return "source_and_screenshot"
    if has_source:
        return "source_only"
    if has_screenshot:
        return "screenshot_only"
    if has_trace:
        return "trace_only_internal"
    return "thin_or_missing"


def evaluate_privacy(row: Mapping[str, Any]) -> tuple[str, str]:
    flags: list[str] = []
    trace_files = _text(row.get("trace_files"))
    screenshots = _text(row.get("shareable_screenshots") or row.get("screenshots") or row.get("screenshot_paths"))
    debug_blob = " ".join(
        [
            trace_files,
            screenshots,
            _text(row.get("dead_link_checks")),
            _text(row.get("ux_validator_findings")),
            _text(row.get("advanced_detector_flags")),
        ]
    ).lower()
    if trace_files:
        flags.append("trace_files_internal_only")
    if "c:\\users\\" in debug_blob or "/users/" in debug_blob:
        flags.append("local_paths_need_sanitizing")
    if "headers" in debug_blob or "cookie" in debug_blob or "authorization" in debug_blob:
        flags.append("possible_sensitive_debug_metadata")
    if flags:
        return " | ".join(_dedupe(flags)), "client_safe_export_required"
    return "", "client_safe"


def evaluate_surface_correctness(row: Mapping[str, Any]) -> tuple[str, int, list[str], bool]:
    line = _line_from_mapping(row)
    evidence = _text(row.get("evidence_found") or row.get("evidence_used_for_copy") or row.get("evidence_points"))
    surface_checked = _text(row.get("surface_checked"))
    research_priority = _text(row.get("research_priority"))
    product_surface = _lower(row.get("product_surface_type"))
    combined = f"{line} {evidence} {surface_checked} {research_priority}".lower()
    line_lower = line.lower()
    source_urls = _lower(row.get("source_urls"))
    app_evidence_blob = " ".join(
        [
            evidence,
            source_urls,
            _text(row.get("app_store_summary")),
            _text(row.get("app_review_themes")),
            _text(row.get("app_review_complaints")),
        ]
    ).lower()

    reasons: list[str] = []
    hard_wrong = False
    if not product_surface:
        return "Unknown", 65, ["product_surface_type_missing"], False

    if product_surface == "app_first_product":
        has_app_surface = _has_any(combined, APP_SURFACE_TERMS) or "apps.apple.com" in source_urls or "play.google.com" in source_urls
        app_evidence_available = _has_any(app_evidence_blob, APP_SURFACE_TERMS) or "apps.apple.com" in source_urls or "play.google.com" in source_urls
        website_line = _has_any(line_lower, {"website", "landing page", "homepage", "blog"})
        if website_line:
            reasons.append("website_surface_used_for_app_first_product")
            if app_evidence_available:
                reasons.append("app_review_evidence_preferred")
                return "Review", 45, reasons, hard_wrong
            return "Review", 58, reasons, hard_wrong
        if has_app_surface:
            return "Correct", 95, [], False
        return "Review", 55, ["app_first_requires_app_or_review_surface"], False

    if product_surface == "marketplace_booking_flow":
        if _has_any(combined, BOOKING_TERMS):
            return "Correct", 95, [], False
        return "Review", 62, ["booking_flow_without_booking_surface"], False

    if product_surface == "commerce_product_page":
        if _has_any(combined, COMMERCE_TERMS):
            return "Correct", 92, [], False
        return "Review", 62, ["commerce_product_without_checkout_or_product_page_surface"], False

    if product_surface == "b2b_service":
        if _has_any(combined, B2B_TERMS | WEBSITE_SURFACE_TERMS):
            return "Correct", 88, [], False
        return "Review", 65, ["b2b_service_surface_unclear"], False

    if product_surface == "website_first_leadgen":
        if _has_any(combined, WEBSITE_SURFACE_TERMS | B2B_TERMS):
            return "Correct", 90, [], False
        if _has_any(line_lower, APP_SURFACE_TERMS):
            reasons.append("website_first_leadgen_but_line_uses_app_surface")
            return "Review", 55, reasons, False
        return "Review", 65, ["website_first_surface_unclear"], False

    return "Review", 60, [f"unknown_product_surface_type:{product_surface}"], False


def evaluate_sendability(row: Mapping[str, Any]) -> dict[str, Any]:
    row = apply_mismatch_to_row(canonicalize_row(dict(row)))
    line = _line_from_mapping(row)
    status = _lower(row.get("status"))
    quality_flags = _split_flags(row.get("quality_flags"))

    evidence_score, evidence_hard, evidence_soft = evaluate_evidence(row)
    copy_score, copy_hard, copy_soft = evaluate_copy_quality(row)
    outcome_score, outcome_reasons = evaluate_outcome_alignment(row)
    template_score, template_reasons = evaluate_template_fit(row)
    visual_score, visual_reasons = evaluate_visual_reliability(row)
    viewport_scope, viewport_score, viewport_reasons = evaluate_viewport_scope(row)
    evidence_scope = evaluate_evidence_scope(row)
    privacy_flags, client_safe_asset_status = evaluate_privacy(row)
    surface_label, surface_score, surface_reasons, surface_hard = evaluate_surface_correctness(row)
    sales_result = evaluate_sales_principles(
        line,
        evidence=_text(row.get("evidence_found") or row.get("evidence_used_for_copy") or row.get("evidence_points")),
        source_url=_text(row.get("source_urls")),
        angle=_text(row.get("chosen_angle") or row.get("friction_type")),
        campaign_context=_text(row.get("campaign_context")),
        manual_app_verified=bool(_text(row.get("app_flow_observation"))),
    )

    hard_reasons: list[str] = []
    soft_reasons: list[str] = []

    if status == "research only" or "research_only" in quality_flags:
        hard_reasons.append("research_only")
    if _is_yes(row.get("needs_manual_review")):
        soft_reasons.append("marked_for_manual_review")
    severe_matches = sorted(flag for flag in quality_flags if flag in SEVERE_QUALITY_FLAGS)
    edit_matches = sorted(flag for flag in quality_flags if flag in EDIT_QUALITY_FLAGS)
    hard_reasons.extend(severe_matches)
    soft_reasons.extend(edit_matches)
    hard_reasons.extend(evidence_hard)
    hard_reasons.extend(copy_hard)
    soft_reasons.extend(evidence_soft)
    soft_reasons.extend(copy_soft)
    soft_reasons.extend(outcome_reasons)
    soft_reasons.extend(template_reasons)
    soft_reasons.extend(visual_reasons)
    soft_reasons.extend(viewport_reasons)
    soft_reasons.extend(surface_reasons)
    if surface_hard:
        hard_reasons.extend(surface_reasons)
    if sales_result.fake_familiarity_flag:
        hard_reasons.append("fake_familiarity_claim")
    if sales_result.evidence_supported_claim_score < 35:
        hard_reasons.append("unsupported_meaningful_claim")
    if sales_result.salesy_language_flag:
        soft_reasons.append("salesy_language")
    if sales_result.specificity_score < 55:
        soft_reasons.append("low_specificity")
    if sales_result.one_insight_score < 60:
        soft_reasons.append("multiple_insights")
    if sales_result.outcome_bridge_score < 60:
        soft_reasons.append("missing_outcome_bridge")
    if sales_result.commercial_relevance_score < 60:
        soft_reasons.append("commercial_relevance_unclear")
    if sales_result.signal_to_implication_bridge_score < 55:
        soft_reasons.append("signal_to_implication_bridge_weak")
    if any(reason.startswith("unsupported_implication") for reason in sales_result.sales_principles_reasons):
        hard_reasons.append("unsupported_implication")
    if _has_assertive_claim_language(line) and (evidence_score < 75 or visual_score < 60 or viewport_score < 60):
        soft_reasons.append("assertive_claim_language_with_weak_evidence")
    if str(row.get("input_mapping_warning", "")).lower() == "yes":
        soft_reasons.append("input_mapping_warning")

    hard_reasons = _dedupe(hard_reasons)
    soft_reasons = _dedupe([reason for reason in soft_reasons if reason not in hard_reasons])

    weighted_score = round(
        evidence_score * 0.20
        + copy_score * 0.18
        + outcome_score * 0.13
        + template_score * 0.12
        + surface_score * 0.13
        + sales_result.sales_principles_score * 0.18
        + visual_score * 0.035
        + viewport_score * 0.025
    )
    if not line:
        weighted_score = min(weighted_score, 20)
    if hard_reasons:
        weighted_score = min(weighted_score, 59)
    elif soft_reasons:
        weighted_score = min(weighted_score, 84)
    score = max(0, min(100, weighted_score))

    if hard_reasons:
        decision = "Reject"
    elif soft_reasons or score < 85:
        decision = "Edit"
    else:
        decision = "Send"

    reasons = _dedupe(hard_reasons + soft_reasons)
    dimensions = (
        f"evidence={evidence_score}; copy={copy_score}; outcome={outcome_score}; "
        f"template={template_score}; surface={surface_score}; sales_principles={sales_result.sales_principles_score}; "
        f"signal_bridge={sales_result.signal_to_implication_bridge_score}; visual={visual_score}; viewport={viewport_score}"
    )
    return {
        "sendability_decision": decision,
        "sendability_score": score,
        "sendability_reasons": " | ".join(reasons),
        "hard_fail_reasons": " | ".join(hard_reasons),
        "soft_edit_reasons": " | ".join(soft_reasons),
        "evidence_score": evidence_score,
        "copy_quality_score": copy_score,
        "outcome_alignment_score": outcome_score,
        "template_fit_score": template_score,
        "surface_correctness": surface_label,
        "surface_correctness_score": surface_score,
        "surface_correctness_reasons": " | ".join(surface_reasons),
        "visual_reliability_score": visual_score,
        "viewport_scope": viewport_scope,
        "viewport_scope_score": viewport_score,
        "viewport_scope_reasons": " | ".join(viewport_reasons),
        "evidence_scope": evidence_scope,
        "privacy_flags": privacy_flags,
        "client_safe_asset_status": client_safe_asset_status,
        "sendability_dimensions": dimensions,
        "specificity_score": sales_result.specificity_score,
        "one_insight_score": sales_result.one_insight_score,
        "friction_relevance_score": sales_result.friction_relevance_score,
        "outcome_bridge_score": sales_result.outcome_bridge_score,
        "commercial_relevance_score": sales_result.commercial_relevance_score,
        "signal_to_implication_bridge_score": sales_result.signal_to_implication_bridge_score,
        "salesy_language_flag": "yes" if sales_result.salesy_language_flag else "no",
        "fake_familiarity_flag": "yes" if sales_result.fake_familiarity_flag else "no",
        "evidence_supported_claim_score": sales_result.evidence_supported_claim_score,
        "sales_principles_score": sales_result.sales_principles_score,
        "sales_principles_summary": sales_result.sales_principles_summary,
        "sales_principles_reasons": " | ".join(sales_result.sales_principles_reasons),
        "company_website_mismatch": row.get("company_website_mismatch", ""),
        "person_company_mismatch": row.get("person_company_mismatch", ""),
        "input_mapping_warning": row.get("input_mapping_warning", ""),
        "mismatch_reason": row.get("mismatch_reason", ""),
    }


def apply_sendability_to_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = canonicalize_dataframe(df)
    for column in SENDABILITY_COLUMNS:
        if column not in out.columns:
            if column == "human_decision":
                out[column] = "unreviewed"
            elif column == "edit_reason_category":
                out[column] = "not_reviewed"
            else:
                out[column] = ""
    out = ensure_line_provenance(out)
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


def goldset_path(split: str = "reviewed_examples") -> Path:
    if split not in GOLDSET_SPLITS:
        raise ValueError(f"Unknown goldset split: {split}")
    return DATA_DIR / "goldset" / f"{split}.csv"


def goldset_paths() -> dict[str, Path]:
    return {split: goldset_path(split) for split in GOLDSET_SPLITS}


def _preferred_line(row: Mapping[str, Any]) -> str:
    human_decision = _lower(row.get("human_decision"))
    edited = _text(row.get("edited_final_opener") or row.get("edited_line"))
    current = _text(row.get("selected_opener") or row.get("current_opening_line") or row.get("personalized_line") or row.get("opening_line"))
    final = _text(row.get("final_delivery_line"))
    if human_decision in {"send", "edit"}:
        return edited or final or current
    return ""


def _non_preferred_line(row: Mapping[str, Any]) -> str:
    human_decision = _lower(row.get("human_decision"))
    edited = _text(row.get("edited_final_opener") or row.get("edited_line"))
    original = _text(row.get("model_opening_line") or row.get("original_line") or row.get("selected_opener") or row.get("personalized_line") or row.get("opening_line"))
    if human_decision == "reject":
        return original
    if edited and edited != original:
        return original
    return ""


def rows_for_goldset(df: pd.DataFrame, split: str = "reviewed_examples") -> pd.DataFrame:
    if split not in GOLDSET_SPLITS:
        raise ValueError(f"Unknown goldset split: {split}")
    if df.empty or "human_decision" not in df:
        return pd.DataFrame(columns=GOLDSET_COLUMNS)
    enriched = apply_sendability_to_dataframe(df)
    mask = enriched["human_decision"].fillna("unreviewed").astype(str).str.lower().ne("unreviewed")
    selected = enriched.loc[mask].copy()
    if selected.empty:
        return pd.DataFrame(columns=GOLDSET_COLUMNS)

    selected["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    selected["goldset_split"] = split
    selected["source_kind"] = selected.get("source_kind", "operator_review")
    selected["origin_run_id"] = selected.get("origin_run_id", selected.get("run_id", ""))
    selected["origin_row_id"] = selected.get("origin_row_id", selected.get("row_id", ""))
    selected["label_source"] = selected.get("label_source", "internal_reviewer")
    selected["is_frozen_eval_example"] = "yes" if split == "frozen_eval_set" else "no"
    selected["is_training_candidate"] = "yes" if split == "candidate_training_set" else "no"
    selected["original_line"] = selected.get("model_opening_line", selected.get("personalized_line", ""))
    selected["current_opening_line"] = selected.get("current_opening_line", selected.get("personalized_line", ""))
    selected["selected_opener"] = selected.get("selected_opener", selected.get("recommended_opener", selected.get("personalized_line", "")))
    selected["edited_final_opener"] = selected.get("edited_final_opener", selected.get("edited_line", ""))
    selected["final_delivery_line"] = selected.get("final_delivery_line", selected.get("edited_final_opener", selected.get("edited_line", "")))
    selected["preferred_line"] = selected.apply(lambda row: _preferred_line(row.to_dict()), axis=1)
    selected["non_preferred_line"] = selected.apply(lambda row: _non_preferred_line(row.to_dict()), axis=1)
    selected["non_selected_opener_options"] = selected.apply(
        lambda row: " | ".join(
            option
            for option in [
                _text(row.get("opener_option_1") or row.get("option_1_line")),
                _text(row.get("opener_option_2") or row.get("option_2_line")),
                _text(row.get("opener_option_3") or row.get("option_3_line")),
            ]
            if option and option != _text(row.get("selected_opener"))
        ),
        axis=1,
    )
    selected["surface_used"] = selected.get("surface_checked", "")
    selected["product_type"] = selected.get("product_surface_type", "")
    source_urls = selected["source_urls"].astype(str) if "source_urls" in selected else pd.Series([""] * len(selected), index=selected.index)
    screenshots = (
        selected["shareable_screenshots"].astype(str)
        if "shareable_screenshots" in selected
        else pd.Series([""] * len(selected), index=selected.index)
    )
    selected["evidence_refs"] = source_urls + " | " + screenshots
    selected["writer_model"] = selected.get("model_name", "")
    selected["judge_model"] = "deterministic_sendability_gate_v3_sales_principles"
    for column in GOLDSET_COLUMNS:
        if column not in selected:
            selected[column] = ""
    return selected[GOLDSET_COLUMNS]


def append_goldset_feedback(df: pd.DataFrame, split: str = "reviewed_examples", path: Path | None = None) -> tuple[Path, int]:
    path = path or goldset_path(split)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = rows_for_goldset(df, split=split)
    if rows.empty:
        return path, 0
    if path.exists():
        existing = pd.read_csv(path, dtype=str).fillna("")
        for column in GOLDSET_COLUMNS:
            if column not in existing:
                existing[column] = ""
        rows = pd.concat([existing[GOLDSET_COLUMNS], rows], ignore_index=True)
        if "example_id" in rows:
            rows = rows.drop_duplicates(subset=["goldset_split", "example_id"], keep="last")
    rows.to_csv(path, index=False, encoding="utf-8-sig")
    return path, len(rows_for_goldset(df, split=split))


def load_goldset_summary() -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for split, path in goldset_paths().items():
        if not path.exists():
            records.append({"split": split, "rows": 0, "send": 0, "edit": 0, "reject": 0, "top_reason": ""})
            continue
        df = pd.read_csv(path, dtype=str).fillna("")
        decisions = df.get("human_decision", pd.Series(dtype=str)).str.lower()
        reason_counter: Counter[str] = Counter()
        for value in df.get("edit_reason_category", pd.Series(dtype=str)).tolist():
            if value and value != "not_reviewed":
                reason_counter[str(value)] += 1
        records.append(
            {
                "split": split,
                "rows": len(df),
                "send": int((decisions == "send").sum()),
                "edit": int((decisions == "edit").sum()),
                "reject": int((decisions == "reject").sum()),
                "top_reason": reason_counter.most_common(1)[0][0] if reason_counter else "",
            }
        )
    return pd.DataFrame(records)
