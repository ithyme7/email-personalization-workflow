from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config import DATA_DIR, OUTPUT_DIR
from sendability import apply_sendability_to_dataframe, goldset_path

DEFAULT_BASELINE_PATH = DATA_DIR / "goldset" / "frozen_eval_baseline.json"
DEFAULT_THRESHOLDS = {
    "min_send_precision": 90.0,
    "min_exact_agreement": 78.0,
    "max_false_sends": 0,
    "min_surface_correct_rate": 85.0,
    "min_app_first_surface_correct_rate": 90.0,
}

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
    "product_type",
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
    app_first = scored.get("product_type", scored.get("product_surface_type", pd.Series([""] * len(scored), index=scored.index))).fillna("").astype(str).str.lower().eq("app_first_product")
    app_first_surface_correct_rate = (
        round(scored.loc[app_first, "surface_correctness"].fillna("").eq("Correct").mean() * 100, 1)
        if app_first.any() and "surface_correctness" in scored
        else 0
    )

    summary_records: list[dict[str, Any]] = [
        {"metric": "frozen_eval_rows", "value": len(scored)},
        {"metric": "exact_gate_human_agreement_pct", "value": exact_agreement},
        {"metric": "send_precision_pct", "value": send_precision},
        {"metric": "reject_recall_pct", "value": reject_recall},
        {"metric": "false_send_rows", "value": int(false_send.sum())},
        {"metric": "surface_correct_rate_pct", "value": surface_correct_rate},
        {"metric": "app_first_surface_correct_rate_pct", "value": app_first_surface_correct_rate},
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


def export_frozen_eval_report(output_path: Path | None = None, goldset_path_arg: Path | None = None) -> Path:
    output_path = output_path or OUTPUT_DIR / "evals" / f"frozen_eval_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary, detail = evaluate_frozen_goldset(goldset_path_arg)
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


def _summary_dict(summary: pd.DataFrame) -> dict[str, Any]:
    return {str(row["metric"]): row["value"] for _, row in summary.iterrows()}


def _float_metric(metrics: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(metrics.get(key, default))
    except (TypeError, ValueError):
        return default


def _int_metric(metrics: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(float(metrics.get(key, default)))
    except (TypeError, ValueError):
        return default


def write_baseline(path: Path | None = None, goldset_path_arg: Path | None = None) -> Path:
    path = path or DEFAULT_BASELINE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    summary, _ = evaluate_frozen_goldset(goldset_path_arg)
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "metrics": _summary_dict(summary),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def evaluate_release_gate(
    summary: pd.DataFrame,
    baseline_path: Path | None = None,
    fail_on_regression: bool = False,
    thresholds: dict[str, float] | None = None,
) -> tuple[bool, list[str]]:
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    metrics = _summary_dict(summary)
    failures: list[str] = []

    if _int_metric(metrics, "frozen_eval_rows") == 0:
        failures.append("No frozen eval rows available.")
        return False, failures
    if _float_metric(metrics, "send_precision_pct") < thresholds["min_send_precision"]:
        failures.append(f"send_precision_pct below {thresholds['min_send_precision']}: {metrics.get('send_precision_pct')}")
    if _float_metric(metrics, "exact_gate_human_agreement_pct") < thresholds["min_exact_agreement"]:
        failures.append(f"exact_gate_human_agreement_pct below {thresholds['min_exact_agreement']}: {metrics.get('exact_gate_human_agreement_pct')}")
    if _int_metric(metrics, "false_send_rows") > thresholds["max_false_sends"]:
        failures.append(f"false_send_rows above {thresholds['max_false_sends']}: {metrics.get('false_send_rows')}")
    if _float_metric(metrics, "surface_correct_rate_pct") < thresholds["min_surface_correct_rate"]:
        failures.append(f"surface_correct_rate_pct below {thresholds['min_surface_correct_rate']}: {metrics.get('surface_correct_rate_pct')}")
    app_first_rate = _float_metric(metrics, "app_first_surface_correct_rate_pct")
    if app_first_rate and app_first_rate < thresholds["min_app_first_surface_correct_rate"]:
        failures.append(
            f"app_first_surface_correct_rate_pct below {thresholds['min_app_first_surface_correct_rate']}: {metrics.get('app_first_surface_correct_rate_pct')}"
        )

    baseline_path = baseline_path or DEFAULT_BASELINE_PATH
    if fail_on_regression and baseline_path.exists():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8")).get("metrics", {})
        no_regression_metrics = [
            "send_precision_pct",
            "exact_gate_human_agreement_pct",
            "reject_recall_pct",
            "surface_correct_rate_pct",
            "app_first_surface_correct_rate_pct",
        ]
        for metric in no_regression_metrics:
            current = _float_metric(metrics, metric)
            previous = _float_metric(baseline, metric)
            if previous and current < previous:
                failures.append(f"{metric} regressed from {previous} to {current}")
        current_false_sends = _int_metric(metrics, "false_send_rows")
        previous_false_sends = _int_metric(baseline, "false_send_rows")
        if current_false_sends > previous_false_sends:
            failures.append(f"false_send_rows regressed from {previous_false_sends} to {current_false_sends}")

    return not failures, failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Run frozen evals and optionally enforce release-gate thresholds.")
    parser.add_argument("--goldset", type=Path, default=None, help="Path to frozen_eval_set.csv")
    parser.add_argument("--output", type=Path, default=None, help="Optional eval report XLSX path")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE_PATH, help="Baseline JSON path")
    parser.add_argument("--write-baseline", action="store_true", help="Write current metrics as the baseline and exit")
    parser.add_argument("--enforce-gate", action="store_true", help="Exit with code 1 when current metrics fail the release gate")
    parser.add_argument("--fail-on-regression", action="store_true", help="Fail if metrics regress against the baseline JSON")
    parser.add_argument("--min-send-precision", type=float, default=DEFAULT_THRESHOLDS["min_send_precision"])
    parser.add_argument("--min-exact-agreement", type=float, default=DEFAULT_THRESHOLDS["min_exact_agreement"])
    parser.add_argument("--max-false-sends", type=int, default=DEFAULT_THRESHOLDS["max_false_sends"])
    parser.add_argument("--min-surface-correct-rate", type=float, default=DEFAULT_THRESHOLDS["min_surface_correct_rate"])
    parser.add_argument("--min-app-first-surface-correct-rate", type=float, default=DEFAULT_THRESHOLDS["min_app_first_surface_correct_rate"])
    args = parser.parse_args()

    if args.write_baseline:
        path = write_baseline(args.baseline, args.goldset)
        print(f"Baseline written: {path}")
        return

    summary, _ = evaluate_frozen_goldset(args.goldset)
    output_path = export_frozen_eval_report(args.output, args.goldset)
    thresholds = {
        "min_send_precision": args.min_send_precision,
        "min_exact_agreement": args.min_exact_agreement,
        "max_false_sends": args.max_false_sends,
        "min_surface_correct_rate": args.min_surface_correct_rate,
        "min_app_first_surface_correct_rate": args.min_app_first_surface_correct_rate,
    }
    passed, failures = evaluate_release_gate(summary, args.baseline, args.fail_on_regression, thresholds)
    print(f"Eval report: {output_path}")
    if passed:
        print("Release gate: PASS")
    else:
        print("Release gate: FAIL" if (args.enforce_gate or args.fail_on_regression) else "Release gate: WARN")
        for failure in failures:
            print(f"- {failure}")
        if args.enforce_gate or args.fail_on_regression:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
