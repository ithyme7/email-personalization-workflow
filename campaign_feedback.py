from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

from config import DATA_DIR


CAMPAIGN_FEEDBACK_DIR = DATA_DIR / "campaign_feedback"
CAMPAIGN_FEEDBACK_FILE = CAMPAIGN_FEEDBACK_DIR / "campaign_results.csv"

CAMPAIGN_FEEDBACK_COLUMNS = [
    "campaign_name",
    "company",
    "person",
    "role",
    "website",
    "delivered_line",
    "sent",
    "opened",
    "replied",
    "positive_reply",
    "booked",
    "bad_fit_or_bounce",
    "notes",
    "imported_at",
]


def blank_campaign_feedback_template(row_count: int = 25) -> pd.DataFrame:
    return pd.DataFrame([{column: "" for column in CAMPAIGN_FEEDBACK_COLUMNS} for _ in range(row_count)])


def review_df_to_campaign_feedback_template(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["campaign_name"] = ""
    out["company"] = df.get("company", "")
    out["person"] = df.get("person", "")
    out["role"] = df.get("role", "")
    out["website"] = df.get("website", "")
    edited = df.get("edited_line", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str)
    personalized = df.get("personalized_line", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str)
    line = edited.where(edited.str.strip().ne(""), personalized)
    out["delivered_line"] = line
    for column in ["sent", "opened", "replied", "positive_reply", "booked", "bad_fit_or_bounce", "notes", "imported_at"]:
        out[column] = ""
    return out[CAMPAIGN_FEEDBACK_COLUMNS].fillna("")


def campaign_feedback_template_bytes(df: pd.DataFrame | None = None) -> bytes:
    template = review_df_to_campaign_feedback_template(df) if df is not None and not df.empty else blank_campaign_feedback_template()
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        template.to_excel(writer, index=False, sheet_name="Campaign Results")
        notes = pd.DataFrame(
            [
                {"field": "sent/opened/replied/positive_reply/booked", "how_to_fill": "Use yes/no, true/false, 1/0, or leave blank if unknown."},
                {"field": "bad_fit_or_bounce", "how_to_fill": "Mark yes if the lead bounced, was irrelevant, or should not be used for learning."},
                {"field": "notes", "how_to_fill": "Optional qualitative context from the campaign."},
            ]
        )
        notes.to_excel(writer, index=False, sheet_name="Instructions")
        ws = writer.book["Campaign Results"]
        widths = {
            "campaign_name": 24,
            "company": 24,
            "person": 22,
            "role": 24,
            "website": 34,
            "delivered_line": 84,
            "notes": 52,
        }
        for idx, column in enumerate(template.columns, 1):
            ws.column_dimensions[ws.cell(1, idx).column_letter].width = widths.get(column, 16)
    return buffer.getvalue()


def read_campaign_feedback(uploaded_or_path: Any) -> pd.DataFrame:
    if hasattr(uploaded_or_path, "getvalue"):
        name = str(getattr(uploaded_or_path, "name", "campaign_results.xlsx")).lower()
        data = BytesIO(uploaded_or_path.getvalue())
        if name.endswith(".csv"):
            return pd.read_csv(data, dtype=str).fillna("")
        return pd.read_excel(data, sheet_name="Campaign Results", dtype=str).fillna("")
    path = Path(uploaded_or_path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, dtype=str).fillna("")
    return pd.read_excel(path, sheet_name="Campaign Results", dtype=str).fillna("")


def normalize_campaign_feedback(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy().fillna("")
    for column in CAMPAIGN_FEEDBACK_COLUMNS:
        if column not in normalized:
            normalized[column] = ""
    normalized = normalized[CAMPAIGN_FEEDBACK_COLUMNS].copy()
    normalized["imported_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    has_signal = normalized[["sent", "opened", "replied", "positive_reply", "booked", "bad_fit_or_bounce"]].astype(str).apply(
        lambda row: any(value.strip() for value in row),
        axis=1,
    )
    return normalized.loc[has_signal].fillna("")


def append_campaign_feedback(uploaded_or_path: Any) -> tuple[Path, int, pd.DataFrame]:
    normalized = normalize_campaign_feedback(read_campaign_feedback(uploaded_or_path))
    CAMPAIGN_FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    if normalized.empty:
        return CAMPAIGN_FEEDBACK_FILE, 0, normalized
    if CAMPAIGN_FEEDBACK_FILE.exists():
        existing = pd.read_csv(CAMPAIGN_FEEDBACK_FILE, dtype=str).fillna("")
        combined = pd.concat([existing, normalized], ignore_index=True)
    else:
        combined = normalized
    combined = combined.drop_duplicates(subset=["campaign_name", "company", "person", "delivered_line"], keep="last")
    combined.to_csv(CAMPAIGN_FEEDBACK_FILE, index=False, encoding="utf-8-sig")
    return CAMPAIGN_FEEDBACK_FILE, len(normalized), normalized


def load_campaign_feedback(limit: int = 100) -> pd.DataFrame:
    if not CAMPAIGN_FEEDBACK_FILE.exists():
        return pd.DataFrame(columns=CAMPAIGN_FEEDBACK_COLUMNS)
    return pd.read_csv(CAMPAIGN_FEEDBACK_FILE, dtype=str).fillna("").tail(limit)
