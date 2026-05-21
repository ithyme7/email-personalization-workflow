from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
import zipfile
from typing import Any

import pandas as pd

from config import OUTPUT_DIR
from delivery_policy import CLIENT_SAFE_DELIVERY_COLUMNS, split_delivery_review_needed
from privacy_scan import (
    HARD_CLIENT_SAFE_LEAKS,
    SENSITIVE_VALUE_PATTERNS,
    scan_image_for_pii,
    scan_text,
    sanitize_text,
    screenshot_ocr_required,
)


CLIENT_SAFE_COLUMNS = CLIENT_SAFE_DELIVERY_COLUMNS + [
    "delivery_inclusion_reason",
]

REVIEW_NEEDED_COLUMNS = [
    "company",
    "person",
    "role",
    "website",
    "personalized_line",
    "sendability_decision",
    "human_decision",
    "delivery_exclusion_reason",
    "review_priority_score",
    "review_priority_reason",
    "review_action_recommendation",
    "sendability_reasons",
    "duplicate_company_opener",
    "mismatch_reason",
]


def _split_items(value: Any) -> list[str]:
    return [item.strip() for item in str(value or "").replace("\n", "|").split("|") if item.strip()]


def _resolve_file(value: str, base_dir: Path | None = None) -> Path | None:
    path = Path(value)
    candidates = [path]
    if base_dir and not path.is_absolute():
        candidates.append(base_dir / path)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _scan_safe_dataframe(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []
    blob = "\n".join(df.astype(str).fillna("").agg(" ".join, axis=1).tolist())
    return scan_text(blob)


def _copy_screenshots(row: pd.Series, screenshots_dir: Path, base_dir: Path | None = None) -> tuple[str, list[str], list[str]]:
    copied: list[str] = []
    flags: list[str] = []
    notes: list[str] = []
    for column in ["shareable_screenshots", "screenshots"]:
        for item in _split_items(row.get(column, "")):
            source = _resolve_file(item, base_dir)
            if not source or source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            image_scan = scan_image_for_pii(source)
            if image_scan.flags:
                flags.extend([f"screenshot_{flag}" for flag in image_scan.flags])
                notes.extend(image_scan.notes)
                hard_image_flags = {"email_address", "phone_number", "api_key_like"}
                if screenshot_ocr_required():
                    hard_image_flags.update({"ocr_unavailable", "ocr_failed"})
                if any(
                    flag in HARD_CLIENT_SAFE_LEAKS
                    or flag in hard_image_flags
                    for flag in image_scan.flags
                ):
                    notes.append(f"Screenshot skipped because privacy scan flagged {source.name}.")
                    continue
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            safe_name = f"{str(row.get('company', 'company')).strip().replace(' ', '_')}_{source.name}"
            target = screenshots_dir / safe_name
            if not target.exists():
                shutil.copy2(source, target)
            copied.append(str(Path("screenshots") / target.name))
    return " | ".join(dict.fromkeys(copied)), sorted(set(flags)), list(dict.fromkeys(notes))


def client_safe_dataframe(df: pd.DataFrame, base_dir: Path | None = None, screenshots_dir: Path | None = None) -> pd.DataFrame:
    prepared, _, _ = split_delivery_review_needed(df)
    prepared = prepared.copy()
    if prepared.empty:
        prepared = prepared.head(0).copy()
    prepared["delivery_inclusion_reason"] = "sendability_send_or_human_approved_final"

    if screenshots_dir:
        screenshot_results = prepared.apply(lambda row: _copy_screenshots(row, screenshots_dir, base_dir), axis=1)
        prepared["safe_screenshots"] = screenshot_results.apply(lambda result: result[0])
        prepared["privacy_scan_flags"] = screenshot_results.apply(lambda result: " | ".join(result[1]))
        prepared["screenshot_privacy_notes"] = screenshot_results.apply(lambda result: " | ".join(result[2]))
    else:
        prepared["safe_screenshots"] = ""
        prepared["privacy_scan_flags"] = ""
        prepared["screenshot_privacy_notes"] = ""

    prepared["client_safe_notes"] = "Debug traces, raw detector output, local paths, and internal audit details excluded."
    for column in CLIENT_SAFE_COLUMNS:
        if column not in prepared:
            prepared[column] = ""
    safe = prepared[CLIENT_SAFE_COLUMNS].copy().fillna("").astype(str)
    for idx, row in safe.iterrows():
        row_flags: list[str] = []
        for column in safe.columns:
            if column == "privacy_scan_flags":
                continue
            scan_result = sanitize_text(row[column])
            safe.at[idx, column] = scan_result.sanitized_text
            row_flags.extend(scan_result.flags)
        existing_flags = str(safe.at[idx, "privacy_scan_flags"] or "").split("|")
        row_flags.extend([flag.strip() for flag in existing_flags if flag.strip()])
        if row_flags:
            unique_flags = " | ".join(sorted(set(row_flags)))
            safe.at[idx, "privacy_scan_flags"] = unique_flags
            safe.at[idx, "client_safe_notes"] = f"{safe.at[idx, 'client_safe_notes']} Potential sensitive values were redacted: {unique_flags}."
    return safe


def create_client_safe_package(df: pd.DataFrame, output_dir: Path | None = None, base_dir: Path | None = None, name: str = "client_safe_delivery") -> Path:
    output_dir = output_dir or OUTPUT_DIR / "client_safe"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    package_root = output_dir / f"{name}_{stamp}"
    screenshots_dir = package_root / "screenshots"
    package_root.mkdir(parents=True, exist_ok=True)

    _, review_needed_df, delivery_audit = split_delivery_review_needed(df)
    safe_df = client_safe_dataframe(df, base_dir=base_dir, screenshots_dir=screenshots_dir)
    remaining_flags = _scan_safe_dataframe(safe_df)
    hard_leaks = [flag for flag in remaining_flags if flag in HARD_CLIENT_SAFE_LEAKS]
    if hard_leaks:
        raise ValueError(f"Client-safe package blocked because sensitive values remain after sanitizing: {', '.join(hard_leaks)}")
    csv_path = package_root / "client_safe_delivery.csv"
    xlsx_path = package_root / "client_safe_delivery.xlsx"
    review_needed_path = package_root / "review_needed.csv"
    safe_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    for column in REVIEW_NEEDED_COLUMNS:
        if column not in review_needed_df:
            review_needed_df[column] = ""
    review_needed_df[REVIEW_NEEDED_COLUMNS].to_csv(review_needed_path, index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        safe_df.to_excel(writer, index=False, sheet_name="Client Delivery")
        ws = writer.book["Client Delivery"]
        for idx, column in enumerate(safe_df.columns, 1):
            width = 70 if column in {"personalized_line", "evidence_found"} else 24
            ws.column_dimensions[ws.cell(1, idx).column_letter].width = width
        for row in ws.iter_rows():
            for cell in row:
                cell.alignment = cell.alignment.copy(wrap_text=True, vertical="top")

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "package_name": package_root.name,
        "input_rows": int(len(df)),
        "client_rows": int(len(safe_df)),
        "review_needed_rows": int(len(review_needed_df)),
        "delivery_audit": delivery_audit.to_dict(),
        "filter_policy": "strict: sendability Send or human-approved final opener only; Reject/Edit-without-final and policy-blocked rows excluded",
        "included_files": ["client_safe_delivery.csv", "client_safe_delivery.xlsx", "review_needed.csv"],
        "screenshots_included": int(len(list(screenshots_dir.glob("*"))) if screenshots_dir.exists() else 0),
        "excluded_artifacts": [
            "Playwright traces",
            "raw detector output",
            "local filesystem paths",
            "internal audit details",
            "raw cache files",
        ],
        "privacy_sanitizers": sorted(SENSITIVE_VALUE_PATTERNS.keys()) + ["secret_query_parameter"],
        "screenshot_ocr_required": screenshot_ocr_required(),
        "remaining_privacy_scan_flags": remaining_flags,
        "status": "blocked" if hard_leaks else "client_safe",
    }
    manifest_path = package_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    zip_path = output_dir / f"{name}_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(csv_path, csv_path.relative_to(package_root))
        archive.write(xlsx_path, xlsx_path.relative_to(package_root))
        archive.write(review_needed_path, review_needed_path.relative_to(package_root))
        archive.write(manifest_path, manifest_path.relative_to(package_root))
        if screenshots_dir.exists():
            for file_path in screenshots_dir.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(package_root))
    return zip_path
