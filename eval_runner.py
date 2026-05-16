from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config import DATA_DIR, OUTPUT_DIR
from sendability import apply_sendability_to_dataframe, goldset_path


EVAL_DETAIL_COLUMNS = [
    "company",
    "person",
    "human_decision",
    "gate_decision",
    "agreement",
    "false_send",
    "sendability_score",
    "hard_fail_reasons",
    "soft_edit_reasons",
    "surface_correctness",
    "surface_correctness_score",
    "evidence_score",
    "copy_quality_score",
    "outcome_alignment_score",
    "template_fit_score",
    "visual_reliability_score",
    "viewport_scope",
    "edit_reason_category",
    "original_line",
    "preferred_line",
]


def _normalize_goldset(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy().fillna("")
    if "personalized_line" not in out and "original_line" in out:
        out["personalized_line"] = out["original_line"]
    if "surface_checked" not in out and "surface_used" in out:
        out["surface_checked"] = out["surface_used"]
    if "product_surface_type" not in out and "product_type" in out:
        out["product_surface_type"] = out["product_type"]
    if "source_urls" not in out and "evidence_refs" in out:
        out["source_urls"] = out["evidence_refs"]
    if "model_name" not in out and "writer_model" in out:
        out["model_name"] = out["writer_model"]
    for column in ["status", "quality_flags", "needs_manual_review", "visual_confidence"]:
        if column not in out:
            out[column] = ""
    out["status"] = out["status"].replace("", "Ready")
    out["needs_manual_review"] = out["needs_manual_review"].replace("", "no")
    return out


def _expected_gate_decision(human_decision: str) -> str:
    value = str(human_decision or "").strip().lower()
    if value == "send":
        return "Send"
    if value == "edit":
        return "Edit"
    if value == "reject":
        return "Reject"
    return "Unknown"


def evaluate_frozen_goldset(path: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    path = path or goldset_path("frozen_eval_set")
    if not path.exists():
        summary = pd.DataFrame(
            [
                {"metric": "frozen_eval_rows", "value": 0},
                {"metric": "status", "value": "No frozen eval set found yet."},
            ]
        )
        return summary, pd.DataFrame(columns=EVAL_DETAIL_COLUMNS)

    raw = pd.read_csv(path, dtype=str).fillna("")
    if raw.empty:
        summary = pd.DataFrame([{"metric": "frozen_eval_rows", "value": 0}])
        return summary, pd.DataFrame(columns=EVAL_DETAIL_COLUMNS)

    scored = apply_sendability_to_dataframe(_normalize_goldset(raw))
    expected = scored["human_decision"].map(_expected_gate_decision)
    gate = scored["sendability_decision"].fillna("")
    agreement = expected.eq(gate)
    false_send = gate.eq("Send") & ~scored["human_decision"].fillna("").str.lower().eq("send")
    gate_send = gate.eq("Send")
    human_send = scored["human_decision"].fillna("").str.lower().eq("send")
    human_reject = scored["human_decision"].fillna("").str.lower().eq("reject")
    gate_reject = gate.eq("Reject")

    send_precision = round(((gate_send & human_send).sum() / gate_send.sum()) * 100, 1) if gate_send.sum() else 0
    reject_recall = round(((gate_reject & human_reject).sum() / human_reject.sum()) * 100, 1) if human_reject.sum() else 0
    exact_agreement = round(agreement.mean() * 100, 1) if len(scored) else 0
    surface_correct_rate = (
        round(scored["surface_correctness"].fillna("").eq("Correct").mean() * 100, 1)
        if "surface_correctness" in scored
        else 0
    )

    summary_records: list[dict[str, Any]] = [
        {"metric": "frozen_eval_rows", "value": len(scored)},
        {"metric": "exact_gate_human_agreement_pct", "value": exact_agreement},
        {"metric": "send_precision_pct", "value": send_precision},
        {"metric": "reject_recall_pct", "value": reject_recall},
        {"metric": "false_send_rows", "value": int(false_send.sum())},
        {"metric": "surface_correct_rate_pct", "value": surface_correct_rate},
        {"metric": "avg_evidence_score", "value": round(pd.to_numeric(scored["evidence_score"], errors="coerce").mean(), 1)},
        {"metric": "avg_template_fit_score", "value": round(pd.to_numeric(scored["template_fit_score"], errors="coerce").mean(), 1)},
    ]
    for decision, count in gate.value_counts().items():
        summary_records.append({"metric": f"gate_{decision.lower()}_rows", "value": int(count)})
    for decision, count in scored["human_decision"].fillna("").str.lower().value_counts().items():
        if decision:
            summary_records.append({"metric": f"human_{decision}_rows", "value": int(count)})

    detail = scored.copy()
    detail["gate_decision"] = gate
    detail["agreement"] = agreement.map({True: "yes", False: "no"})
    detail["false_send"] = false_send.map({True: "yes", False: "no"})
    for column in EVAL_DETAIL_COLUMNS:
        if column not in detail:
            detail[column] = ""
    return pd.DataFrame(summary_records), detail[EVAL_DETAIL_COLUMNS]


def export_frozen_eval_report(output_path: Path | None = None) -> Path:
    output_path = output_path or OUTPUT_DIR / "evals" / f"frozen_eval_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary, detail = evaluate_frozen_goldset()
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary.to_excel(writer, index=False, sheet_name="Summary")
        detail.to_excel(writer, index=False, sheet_name="Details")
        for sheet_name in ["Summary", "Details"]:
            ws = writer.book[sheet_name]
            for idx, cell in enumerate(ws[1], 1):
                ws.column_dimensions[cell.column_letter].width = 34 if sheet_name == "Summary" else 24
            if sheet_name == "Details":
                for column in ["original_line", "preferred_line", "hard_fail_reasons", "soft_edit_reasons"]:
                    if column in detail.columns:
                        col_idx = list(detail.columns).index(column) + 1
                        ws.column_dimensions[ws.cell(1, col_idx).column_letter].width = 62
            for row in ws.iter_rows():
                for cell in row:
                    cell.alignment = cell.alignment.copy(wrap_text=True, vertical="top")
    return output_path


def main() -> None:
    path = export_frozen_eval_report()
    print(path)


if __name__ == "__main__":
    main()
