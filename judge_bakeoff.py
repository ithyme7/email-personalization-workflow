from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config import OUTPUT_DIR, load_settings
from llm_client import LLMClient, LLMError, load_prompt
from sendability import goldset_path


def _normalize_decision(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"send", "edit", "reject"}:
        return text
    return "unknown"


def _candidate_line(row: pd.Series) -> str:
    for column in ["original_line", "model_opening_line", "personalized_line", "opening_line", "current_opening_line"]:
        value = str(row.get(column, "") or "").strip()
        if value:
            return value
    return ""


def _judge_row(client: LLMClient, row: pd.Series) -> dict[str, Any]:
    prompt = load_prompt("judge_sendability.txt")
    payload = {
        "company": row.get("company", ""),
        "person": row.get("person", ""),
        "role": row.get("role", ""),
        "website": row.get("website", ""),
        "product_surface_type": row.get("product_type", row.get("product_surface_type", "")),
        "surface_used": row.get("surface_used", row.get("surface_checked", "")),
        "campaign_template": "Hey [Name]\n{personalized_line}\nWe help mobile app teams with this type of work, figure out where users drop off and why.",
        "candidate_line": _candidate_line(row),
        "evidence_found": row.get("evidence_found", ""),
        "evidence_refs": row.get("evidence_refs", row.get("source_urls", "")),
        "human_decision": row.get("human_decision", ""),
        "preferred_line": row.get("preferred_line", ""),
        "non_preferred_line": row.get("non_preferred_line", ""),
    }
    raw = client.complete_json(prompt, payload)
    decision = _normalize_decision(raw.get("decision"))
    return {
        "judge_decision": decision,
        "judge_evidence_score": raw.get("evidence_score", ""),
        "judge_copy_quality_score": raw.get("copy_quality_score", ""),
        "judge_outcome_alignment_score": raw.get("outcome_alignment_score", ""),
        "judge_template_fit_score": raw.get("template_fit_score", ""),
        "judge_surface_correctness_score": raw.get("surface_correctness_score", ""),
        "judge_reasons": " | ".join(str(reason) for reason in raw.get("reasons", []) if str(reason).strip()),
        "judge_preferred_rewrite": str(raw.get("preferred_rewrite", "") or ""),
    }


def run_bakeoff(goldset: Path | None = None, models: list[str] | None = None, output: Path | None = None) -> Path:
    goldset = goldset or goldset_path("frozen_eval_set")
    output = output or OUTPUT_DIR / "evals" / f"judge_bakeoff_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    output.parent.mkdir(parents=True, exist_ok=True)
    if not goldset.exists():
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            pd.DataFrame([{"status": "missing_goldset", "message": f"Goldset not found: {goldset}"}]).to_excel(
                writer, index=False, sheet_name="Summary"
            )
        return output
    source = pd.read_csv(goldset, dtype=str).fillna("")
    if source.empty:
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            pd.DataFrame([{"status": "empty_goldset", "message": f"Goldset is empty: {goldset}"}]).to_excel(
                writer, index=False, sheet_name="Summary"
            )
        return output

    original_model = os.environ.get("MODEL_NAME", "")
    models = models or [original_model or load_settings().model_name]
    all_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    try:
        for model in models:
            if model:
                os.environ["MODEL_NAME"] = model
            settings = load_settings()
            client = LLMClient(settings)
            if not client.available:
                for _, row in source.iterrows():
                    all_rows.append(
                        {
                            "model": settings.model_name,
                            "company": row.get("company", ""),
                            "human_decision": row.get("human_decision", ""),
                            "candidate_line": _candidate_line(row),
                            "judge_decision": "unavailable",
                            "judge_reasons": f"{settings.llm_provider} API key missing",
                            "agreement": "no",
                        }
                    )
                summary_rows.append({"model": settings.model_name, "rows": len(source), "agreement_pct": 0, "status": "api_key_missing"})
                continue

            agreements = 0
            for _, row in source.iterrows():
                record = {
                    "model": settings.model_name,
                    "company": row.get("company", ""),
                    "person": row.get("person", ""),
                    "human_decision": _normalize_decision(row.get("human_decision")),
                    "candidate_line": _candidate_line(row),
                    "preferred_line": row.get("preferred_line", ""),
                }
                try:
                    judged = _judge_row(client, row)
                    record.update(judged)
                except LLMError as exc:
                    record.update({"judge_decision": "error", "judge_reasons": str(exc)})
                record["agreement"] = "yes" if record.get("judge_decision") == record.get("human_decision") else "no"
                agreements += 1 if record["agreement"] == "yes" else 0
                all_rows.append(record)
            summary_rows.append(
                {
                    "model": settings.model_name,
                    "rows": len(source),
                    "agreement_pct": round((agreements / len(source)) * 100, 1),
                    "status": "ok",
                    **client.usage_summary(),
                }
            )
    finally:
        if original_model:
            os.environ["MODEL_NAME"] = original_model
        else:
            os.environ.pop("MODEL_NAME", None)

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(summary_rows).to_excel(writer, index=False, sheet_name="Summary")
        pd.DataFrame(all_rows).to_excel(writer, index=False, sheet_name="Details")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Run judge-model bakeoffs against a goldset.")
    parser.add_argument("--goldset", type=Path, default=None)
    parser.add_argument("--models", default="", help="Comma-separated model names to test with the configured provider.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    models = [item.strip() for item in args.models.split(",") if item.strip()] or None
    print(run_bakeoff(args.goldset, models, args.output))


if __name__ == "__main__":
    main()
