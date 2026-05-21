from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import pandas as pd

from mismatch_detection import apply_mismatch_to_row
from sendability import apply_sendability_to_dataframe


DELIVERY_COLUMNS = [
    "company",
    "person",
    "role",
    "website",
    "personalized_line",
    "selected_opener_source",
]

CLIENT_SAFE_DELIVERY_COLUMNS = [
    "company",
    "person",
    "role",
    "website",
    "personalized_line",
    "source_urls",
    "safe_screenshots",
    "privacy_scan_flags",
    "screenshot_privacy_notes",
    "client_safe_notes",
]

BLOCKING_DELIVERY_REASONS = {
    "fake_familiarity_claim",
    "hallucination",
    "input_mapping_warning",
    "line_not_grounded_in_evidence",
    "no_sendable_personalized_line",
    "research_only",
    "duplicate_company_opener",
    "unsupported_claim",
    "unsupported_meaningful_claim",
}


@dataclass(frozen=True)
class DeliveryAudit:
    input_rows: int
    delivery_rows: int
    excluded_rows: int
    excluded_edit_rows: int
    excluded_reject_rows: int
    excluded_unapproved_rows: int
    excluded_policy_rows: int

    def to_dict(self) -> dict[str, int]:
        return {
            "input_rows": self.input_rows,
            "delivery_rows": self.delivery_rows,
            "excluded_rows": self.excluded_rows,
            "excluded_edit_rows": self.excluded_edit_rows,
            "excluded_reject_rows": self.excluded_reject_rows,
            "excluded_unapproved_rows": self.excluded_unapproved_rows,
            "excluded_policy_rows": self.excluded_policy_rows,
        }


def _series(df: pd.DataFrame, column: str) -> pd.Series:
    if column in df:
        return df[column].fillna("").astype(str)
    return pd.Series([""] * len(df), index=df.index, dtype=str)


def _split_reasons(value: Any) -> set[str]:
    return {
        item.strip().lower()
        for item in str(value or "").replace("\n", "|").replace(";", "|").replace(",", "|").split("|")
        if item.strip()
    }


def _append_reason(value: Any, reason: str) -> str:
    items = [item.strip() for item in str(value or "").replace("\n", "|").replace(";", "|").split("|") if item.strip()]
    if reason.lower() not in {item.lower() for item in items}:
        items.append(reason)
    return " | ".join(items)


def _normalise_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _add_duplicate_company_opener_flags(prepared: pd.DataFrame) -> pd.DataFrame:
    if prepared.empty:
        return prepared
    out = prepared.copy()
    company_key = _series(out, "company").map(_normalise_key)
    line_key = _series(out, "personalized_line").map(lambda value: re.sub(r"\s+", " ", value.lower()).strip())
    if not company_key.ne("").any() or not line_key.ne("").any():
        return out

    keys = pd.DataFrame({"company_key": company_key, "line_key": line_key}, index=out.index)
    group_sizes = keys.groupby(["company_key", "line_key"], dropna=False)["line_key"].transform("size")
    duplicate_mask = company_key.ne("") & line_key.ne("") & group_sizes.gt(1)
    for idx in out.index[duplicate_mask]:
        out.at[idx, "duplicate_company_opener"] = "yes"
        out.at[idx, "quality_flags"] = _append_reason(out.at[idx, "quality_flags"] if "quality_flags" in out else "", "duplicate_company_opener")
        out.at[idx, "sendability_reasons"] = _append_reason(
            out.at[idx, "sendability_reasons"] if "sendability_reasons" in out else "",
            "duplicate_company_opener",
        )
        out.at[idx, "soft_edit_reasons"] = _append_reason(
            out.at[idx, "soft_edit_reasons"] if "soft_edit_reasons" in out else "",
            "duplicate_company_opener",
        )
    if "duplicate_company_opener" not in out:
        out["duplicate_company_opener"] = ""
    return out


def _row_reasons(row: pd.Series) -> set[str]:
    reasons = set()
    reasons.update(_split_reasons(row.get("hard_fail_reasons")))
    reasons.update(_split_reasons(row.get("quality_flags")))
    reasons.update(_split_reasons(row.get("sendability_reasons")))
    reasons.update(_split_reasons(row.get("soft_edit_reasons")))
    reasons.update(_split_reasons(row.get("surface_correctness_reasons")))
    reasons.update(_split_reasons(row.get("delivery_exclusion_reason")))
    if str(row.get("input_mapping_warning", "")).lower() == "yes":
        reasons.add("input_mapping_warning")
    return reasons


def _numeric(row: pd.Series, column: str, default: int = 0) -> int:
    try:
        value = row.get(column, default)
        if value in {"", None}:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _review_priority(row: pd.Series) -> tuple[int, str, str]:
    if str(row.get("delivery_exclusion_reason", "") or "") == "":
        return 0, "", "included_in_delivery"

    reasons = _row_reasons(row)
    score = _numeric(row, "sendability_score", 0)
    bridge = _numeric(row, "signal_to_implication_bridge_score", 100)
    visual = _numeric(row, "visual_reliability_score", 100)
    human = str(row.get("human_decision", "") or "").lower()
    decision = str(row.get("sendability_decision", "") or "")

    if "input_mapping_warning" in reasons:
        return 20, "company/contact/website mapping looks inconsistent", "fix_input_mapping_before_copy_review"
    if decision == "Reject" or human == "reject" or reasons.intersection(BLOCKING_DELIVERY_REASONS - {"duplicate_company_opener"}):
        return 10, "hard policy block or rejected row", "reject_or_find_new_evidence"
    if "duplicate_company_opener" in reasons:
        return 45, "same company has the same final opener more than once", "make_contact_or_company_specific"
    if "website_surface_used_for_app_first_product" in reasons or "app_review_evidence_preferred" in reasons:
        return 70, "app-first product used weaker website-surface copy", "replace_with_app_or_review_surface"
    if visual < 70 or "visual_claim_needs_manual_check" in reasons:
        return 65, "visual/screenshot evidence needs manual confirmation", "manual_visual_check_then_edit"
    if bridge < 55 or "signal_to_implication_bridge_weak" in reasons:
        return 60, "opener needs a stronger signal-to-implication bridge", "rewrite_signal_to_implication_bridge"
    if decision == "Edit" and score >= 80:
        return 90, "high-scoring edit likely needs a small human rewrite", "quick_human_edit_candidate"
    if decision == "Edit":
        return 55, "edit decision needs human-approved final opener", "rewrite_or_approve_final_opener"
    return 40, "not sendable or not approved yet", "manual_review"


def prepare_delivery_candidates(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    source = df.copy().where(pd.notna(df), "")
    rows = [apply_mismatch_to_row(row.to_dict()) for _, row in source.iterrows()]
    prepared = apply_sendability_to_dataframe(pd.DataFrame(rows))

    selected = _series(prepared, "selected_opener").str.strip()
    if "personalized_line" in prepared:
        prepared.loc[selected.ne(""), "personalized_line"] = selected[selected.ne("")]
    else:
        prepared["personalized_line"] = selected

    human = _series(prepared, "human_decision").str.lower()
    edited_final = _series(prepared, "edited_final_opener").str.strip()
    edited_line = _series(prepared, "edited_line").str.strip()
    approved = human.isin({"send", "edit"})
    final_edit = edited_final.mask(edited_final.eq(""), edited_line)
    prepared.loc[approved & final_edit.ne(""), "personalized_line"] = final_edit[approved & final_edit.ne("")]
    prepared = _add_duplicate_company_opener_flags(prepared)
    return prepared.where(pd.notna(prepared), "")


def delivery_filter_mask(prepared: pd.DataFrame) -> pd.Series:
    if prepared.empty:
        return pd.Series([], index=prepared.index, dtype=bool)
    human = _series(prepared, "human_decision").str.lower()
    decision = _series(prepared, "sendability_decision")
    line = _series(prepared, "personalized_line").str.strip()
    edited_final = _series(prepared, "edited_final_opener").str.strip()
    edited_line = _series(prepared, "edited_line").str.strip()
    has_final_edit = edited_final.ne("") | edited_line.ne("")
    human_send = human.eq("send") & line.ne("")
    human_edit = human.eq("edit") & has_final_edit & line.ne("")
    auto_send = human.isin({"", "unreviewed"}) & decision.eq("Send") & line.ne("")
    base_ok = human_send | human_edit | auto_send

    blocked = []
    for _, row in prepared.iterrows():
        reasons = _row_reasons(row)
        blocked.append(bool(reasons.intersection(BLOCKING_DELIVERY_REASONS)))
    return base_ok & ~pd.Series(blocked, index=prepared.index)


def add_delivery_exclusion_reasons(prepared: pd.DataFrame) -> pd.DataFrame:
    out = prepared.copy()
    mask = delivery_filter_mask(out)
    reasons: list[str] = []
    for idx, row in out.iterrows():
        if bool(mask.loc[idx]):
            reasons.append("")
            continue
        human = str(row.get("human_decision", "") or "").lower()
        decision = str(row.get("sendability_decision", "") or "")
        row_reasons = _row_reasons(row)
        if human == "reject" or decision == "Reject":
            reasons.append("excluded_reject")
        elif human == "edit" and not str(row.get("edited_final_opener") or row.get("edited_line") or "").strip():
            reasons.append("edit_without_human_approved_final_opener")
        elif decision == "Edit" and human not in {"send", "edit"}:
            reasons.append("edit_needs_human_approval")
        elif row_reasons.intersection(BLOCKING_DELIVERY_REASONS) or str(row.get("input_mapping_warning", "")).lower() == "yes":
            reasons.append("blocked_by_delivery_policy:" + "|".join(sorted(row_reasons.intersection(BLOCKING_DELIVERY_REASONS)) or ["input_mapping_warning"]))
        else:
            reasons.append("not_sendable_or_not_approved")
    out["delivery_exclusion_reason"] = reasons
    priorities = [_review_priority(row) for _, row in out.iterrows()]
    out["review_priority_score"] = [priority[0] for priority in priorities]
    out["review_priority_reason"] = [priority[1] for priority in priorities]
    out["review_action_recommendation"] = [priority[2] for priority in priorities]
    return out


def split_delivery_review_needed(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, DeliveryAudit]:
    prepared = add_delivery_exclusion_reasons(prepare_delivery_candidates(df))
    mask = delivery_filter_mask(prepared)
    delivery = prepared.loc[mask].copy()
    review_needed = prepared.loc[~mask].copy()
    if not review_needed.empty and "review_priority_score" in review_needed:
        review_needed["_review_priority_sendability_sort"] = pd.to_numeric(
            review_needed.get("sendability_score", 0),
            errors="coerce",
        ).fillna(0)
        review_needed = review_needed.sort_values(
            by=["review_priority_score", "_review_priority_sendability_sort"],
            ascending=[False, False],
            kind="mergesort",
        ).drop(columns=["_review_priority_sendability_sort"])
    human = _series(prepared, "human_decision").str.lower()
    decision = _series(prepared, "sendability_decision")
    policy_blocked = pd.Series(
        [
            bool(_row_reasons(row).intersection(BLOCKING_DELIVERY_REASONS))
            for _, row in prepared.iterrows()
        ],
        index=prepared.index,
    )
    audit = DeliveryAudit(
        input_rows=len(prepared),
        delivery_rows=len(delivery),
        excluded_rows=len(review_needed),
        excluded_edit_rows=int((~mask & decision.eq("Edit")).sum()),
        excluded_reject_rows=int((~mask & (decision.eq("Reject") | human.eq("reject"))).sum()),
        excluded_unapproved_rows=int((~mask & human.isin({"", "unreviewed"})).sum()),
        excluded_policy_rows=int((~mask & policy_blocked).sum()),
    )
    return delivery, review_needed, audit


def strict_delivery_dataframe(df: pd.DataFrame, columns: list[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame, DeliveryAudit]:
    delivery, review_needed, audit = split_delivery_review_needed(df)
    output_columns = columns or DELIVERY_COLUMNS
    for column in output_columns:
        if column not in delivery:
            delivery[column] = ""
    return delivery[output_columns].copy(), review_needed, audit
