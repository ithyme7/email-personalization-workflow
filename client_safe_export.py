from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import zipfile
from typing import Any

import pandas as pd

from config import OUTPUT_DIR
from sendability import apply_sendability_to_dataframe


CLIENT_SAFE_COLUMNS = [
    "status",
    "sendability_decision",
    "human_decision",
    "company",
    "person",
    "role",
    "website",
    "personalized_line",
    "evidence_found",
    "source_urls",
    "surface_correctness",
    "evidence_score",
    "visual_reliability_score",
    "viewport_scope",
    "safe_screenshots",
    "client_safe_notes",
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


def _copy_screenshots(row: pd.Series, screenshots_dir: Path, base_dir: Path | None = None) -> str:
    copied: list[str] = []
    for column in ["shareable_screenshots", "screenshots"]:
        for item in _split_items(row.get(column, "")):
            source = _resolve_file(item, base_dir)
            if not source or source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            safe_name = f"{str(row.get('company', 'company')).strip().replace(' ', '_')}_{source.name}"
            target = screenshots_dir / safe_name
            if not target.exists():
                shutil.copy2(source, target)
            copied.append(str(Path("screenshots") / target.name))
    return " | ".join(dict.fromkeys(copied))


def _delivery_filter(df: pd.DataFrame) -> pd.Series:
    human = df.get("human_decision", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str).str.lower()
    if human.isin({"send", "edit"}).any():
        return human.isin({"send", "edit"})
    return df.get("sendability_decision", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str).eq("Send")


def client_safe_dataframe(df: pd.DataFrame, base_dir: Path | None = None, screenshots_dir: Path | None = None) -> pd.DataFrame:
    prepared = apply_sendability_to_dataframe(df)
    prepared = prepared[_delivery_filter(prepared)].copy()
    if prepared.empty:
        prepared = apply_sendability_to_dataframe(df).head(0).copy()

    if {"human_decision", "edited_line", "personalized_line"}.issubset(prepared.columns):
        use_edit = (
            prepared["human_decision"].fillna("").astype(str).str.lower().isin({"send", "edit"})
            & prepared["edited_line"].fillna("").astype(str).str.strip().ne("")
        )
        prepared.loc[use_edit, "personalized_line"] = prepared.loc[use_edit, "edited_line"]

    if screenshots_dir:
        prepared["safe_screenshots"] = prepared.apply(lambda row: _copy_screenshots(row, screenshots_dir, base_dir), axis=1)
    else:
        prepared["safe_screenshots"] = ""

    prepared["client_safe_notes"] = "Debug traces, raw detector output, local paths, and internal audit details excluded."
    for column in CLIENT_SAFE_COLUMNS:
        if column not in prepared:
            prepared[column] = ""
    safe = prepared[CLIENT_SAFE_COLUMNS].copy()
    for column in safe.columns:
        safe[column] = safe[column].astype(str).str.replace(r"C:\\Users\\[^|;\n]+", "[local path removed]", regex=True)
    return safe


def create_client_safe_package(df: pd.DataFrame, output_dir: Path | None = None, base_dir: Path | None = None, name: str = "client_safe_delivery") -> Path:
    output_dir = output_dir or OUTPUT_DIR / "client_safe"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    package_root = output_dir / f"{name}_{stamp}"
    screenshots_dir = package_root / "screenshots"
    package_root.mkdir(parents=True, exist_ok=True)

    safe_df = client_safe_dataframe(df, base_dir=base_dir, screenshots_dir=screenshots_dir)
    csv_path = package_root / "client_safe_delivery.csv"
    xlsx_path = package_root / "client_safe_delivery.xlsx"
    safe_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        safe_df.to_excel(writer, index=False, sheet_name="Client Delivery")
        ws = writer.book["Client Delivery"]
        for idx, column in enumerate(safe_df.columns, 1):
            width = 70 if column in {"personalized_line", "evidence_found"} else 24
            ws.column_dimensions[ws.cell(1, idx).column_letter].width = width
        for row in ws.iter_rows():
            for cell in row:
                cell.alignment = cell.alignment.copy(wrap_text=True, vertical="top")

    zip_path = output_dir / f"{name}_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(csv_path, csv_path.relative_to(package_root))
        archive.write(xlsx_path, xlsx_path.relative_to(package_root))
        if screenshots_dir.exists():
            for file_path in screenshots_dir.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(package_root))
    return zip_path
