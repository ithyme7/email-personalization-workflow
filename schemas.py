from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def stable_hash(*values: Any) -> str:
    payload = "\n".join(clean_text(value).lower() for value in values if clean_text(value))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16] if payload else ""


def _first_non_empty(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = clean_text(row.get(key))
        if value:
            return value
    return ""


class EvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    evidence_found: str = ""
    evidence_points: str = ""
    evidence_used_for_copy: str = ""
    source_urls: str = ""
    screenshots: str = ""
    shareable_screenshots: str = ""
    trace_files: str = ""
    ux_validator_findings: str = ""
    advanced_detector_flags: str = ""
    visual_confidence: str = ""
    visual_confidence_score: str = ""
    visual_confidence_reasons: str = ""
    viewport_scope: str = ""
    evidence_scope: str = ""

    @field_validator("*", mode="before")
    @classmethod
    def stringify(cls, value: Any) -> Any:
        return clean_text(value)


class RunRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    row_id: str = ""
    run_id: str = ""
    example_id: str = ""
    company: str = ""
    person: str = ""
    role: str = ""
    website: str = ""
    status: str = "Ready"
    product_surface_type: str = ""
    surface_checked: str = ""
    research_priority: str = ""
    model_opening_line: str = ""
    current_opening_line: str = ""
    final_delivery_line: str = ""
    personalized_line: str = ""
    opening_line: str = ""
    template_preview: str = ""
    edited_line: str = ""
    human_decision: Literal["unreviewed", "send", "edit", "reject"] = "unreviewed"
    edit_reason_category: str = "not_reviewed"
    edit_notes: str = ""
    quality_flags: str = ""
    needs_manual_review: str = "no"
    reviewer_notes: str = ""
    tone_profile: str = ""
    model_provider: str = ""
    model_name: str = ""
    source_kind: str = "run_output"
    origin_run_id: str = ""
    origin_row_id: str = ""
    label_source: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    evidence: EvidenceBundle = Field(default_factory=EvidenceBundle)

    @field_validator("*", mode="before")
    @classmethod
    def stringify(cls, value: Any, info: ValidationInfo) -> Any:
        if info.field_name == "evidence":
            return value
        if isinstance(value, EvidenceBundle):
            return value
        return clean_text(value)

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any], fallback_row_id: int | None = None, run_id: str = "") -> "RunRow":
        row = dict(mapping)
        company = _first_non_empty(row, "company", "company_name")
        person = _first_non_empty(row, "person", "recipient_name")
        role = _first_non_empty(row, "role", "recipient_role")
        website = _first_non_empty(row, "website", "website_url")
        current_line = _first_non_empty(row, "personalized_line", "opening_line", "current_opening_line")
        model_line = _first_non_empty(row, "model_opening_line", "original_line", "non_preferred_line") or current_line
        human_decision = clean_text(row.get("human_decision")).lower() or "unreviewed"
        if human_decision not in {"unreviewed", "send", "edit", "reject"}:
            human_decision = "unreviewed"
        edited_line = clean_text(row.get("edited_line"))
        final_line = edited_line if human_decision in {"send", "edit"} and edited_line else current_line
        row_id = clean_text(row.get("row_id")) or (str(fallback_row_id) if fallback_row_id is not None else "")
        resolved_run_id = clean_text(row.get("run_id")) or run_id
        example_id = clean_text(row.get("example_id")) or stable_hash(
            resolved_run_id,
            row_id,
            company,
            person,
            website,
            model_line,
        )
        evidence = EvidenceBundle(
            evidence_found=_first_non_empty(row, "evidence_found", "evidence_used_for_copy", "evidence_points"),
            evidence_points=clean_text(row.get("evidence_points")),
            evidence_used_for_copy=clean_text(row.get("evidence_used_for_copy")),
            source_urls=clean_text(row.get("source_urls")),
            screenshots=_first_non_empty(row, "screenshots", "screenshot_paths"),
            shareable_screenshots=_first_non_empty(row, "shareable_screenshots", "shareable_screenshot_files"),
            trace_files=clean_text(row.get("trace_files")),
            ux_validator_findings=clean_text(row.get("ux_validator_findings")),
            advanced_detector_flags=clean_text(row.get("advanced_detector_flags")),
            visual_confidence=clean_text(row.get("visual_confidence")),
            visual_confidence_score=clean_text(row.get("visual_confidence_score")),
            visual_confidence_reasons=clean_text(row.get("visual_confidence_reasons")),
            viewport_scope=clean_text(row.get("viewport_scope")),
            evidence_scope=clean_text(row.get("evidence_scope")),
        )
        payload = {
            **row,
            "row_id": row_id,
            "run_id": resolved_run_id,
            "example_id": example_id,
            "company": company,
            "person": person,
            "role": role,
            "website": website,
            "personalized_line": current_line,
            "opening_line": _first_non_empty(row, "opening_line", "personalized_line"),
            "model_opening_line": model_line,
            "current_opening_line": current_line,
            "final_delivery_line": final_line,
            "human_decision": human_decision,
            "edited_line": edited_line,
            "edit_reason_category": clean_text(row.get("edit_reason_category")) or "not_reviewed",
            "status": clean_text(row.get("status")) or "Ready",
            "needs_manual_review": clean_text(row.get("needs_manual_review")) or "no",
            "source_kind": clean_text(row.get("source_kind")) or "run_output",
            "origin_run_id": clean_text(row.get("origin_run_id")) or resolved_run_id,
            "origin_row_id": clean_text(row.get("origin_row_id")) or row_id,
            "evidence": evidence,
        }
        return cls(**payload)

    def to_flat_dict(self) -> dict[str, Any]:
        data = self.model_dump(exclude={"evidence"})
        evidence_data = self.evidence.model_dump()
        for key, value in evidence_data.items():
            if key not in data or not clean_text(data.get(key)):
                data[key] = value
        data.setdefault("evidence_found", self.evidence.evidence_found)
        data.setdefault("source_urls", self.evidence.source_urls)
        data.setdefault("screenshots", self.evidence.screenshots)
        data.setdefault("shareable_screenshots", self.evidence.shareable_screenshots)
        data.setdefault("trace_files", self.evidence.trace_files)
        return data


def canonicalize_row(row: dict[str, Any], fallback_row_id: int | None = None, run_id: str = "") -> dict[str, Any]:
    return RunRow.from_mapping(row, fallback_row_id=fallback_row_id, run_id=run_id).to_flat_dict()


def canonicalize_dataframe(df: pd.DataFrame, run_id: str = "") -> pd.DataFrame:
    if df.empty:
        return df.copy()
    rows = [canonicalize_row(row.to_dict(), fallback_row_id=i + 1, run_id=run_id) for i, (_, row) in enumerate(df.iterrows())]
    out = pd.DataFrame(rows)
    for column in df.columns:
        if column not in out:
            out[column] = df[column].values
    return out
