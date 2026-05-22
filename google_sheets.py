from __future__ import annotations

import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

import pandas as pd


class GoogleSheetsError(RuntimeError):
    pass


def _spreadsheet_id(sheet_url: str) -> str:
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", sheet_url)
    if match:
        return match.group(1)
    cleaned = sheet_url.strip()
    if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", cleaned):
        return cleaned
    raise GoogleSheetsError("Could not find a Google Sheets spreadsheet ID in the URL.")


def _gid_from_url(sheet_url: str) -> str:
    parsed = urlparse(sheet_url)
    query_gid = parse_qs(parsed.query).get("gid", [""])[0]
    if query_gid:
        return query_gid
    fragment_match = re.search(r"gid=([0-9]+)", parsed.fragment or "")
    return fragment_match.group(1) if fragment_match else "0"


def public_csv_export_url(sheet_url: str, worksheet_name: str = "") -> str:
    sheet_id = _spreadsheet_id(sheet_url)
    if worksheet_name.strip():
        return (
            f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?"
            + urlencode({"tqx": "out:csv", "sheet": worksheet_name.strip()})
        )
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={_gid_from_url(sheet_url)}"


def read_public_sheet(sheet_url: str, worksheet_name: str = "") -> pd.DataFrame:
    try:
        return pd.read_csv(public_csv_export_url(sheet_url, worksheet_name), dtype=str).fillna("")
    except Exception as exc:
        raise GoogleSheetsError(
            "Could not read the public Google Sheet. Make sure sharing is enabled or use a service-account JSON file."
        ) from exc


def _gspread_client(service_account_json_path: str):
    try:
        import gspread
    except ImportError as exc:
        raise GoogleSheetsError("gspread is not installed. Run: pip install -r requirements.txt") from exc
    return gspread.service_account(filename=service_account_json_path)


def read_private_sheet(sheet_url: str, service_account_json_path: str, worksheet_name: str = "") -> pd.DataFrame:
    try:
        spreadsheet = _gspread_client(service_account_json_path).open_by_url(sheet_url)
        worksheet = spreadsheet.worksheet(worksheet_name) if worksheet_name.strip() else spreadsheet.sheet1
        values = worksheet.get_all_values()
    except Exception as exc:
        raise GoogleSheetsError(
            "Could not read Google Sheet with the service account. Check sharing, URL, worksheet name, and JSON file."
        ) from exc
    if not values:
        return pd.DataFrame()
    header = values[0]
    return pd.DataFrame(values[1:], columns=header).fillna("")


def export_dataframe_to_sheet(
    df: pd.DataFrame,
    sheet_url: str,
    service_account_json_path: str,
    worksheet_name: str = "Review",
) -> None:
    try:
        spreadsheet = _gspread_client(service_account_json_path).open_by_url(sheet_url)
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
        except Exception:  # Sheet doesn't exist yet - create it
            worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=max(len(df) + 10, 100), cols=max(len(df.columns), 20))
        values = [df.columns.tolist()] + df.fillna("").astype(str).values.tolist()
        worksheet.clear()
        worksheet.update(values, "A1")
    except Exception as exc:
        raise GoogleSheetsError(
            "Could not export to Google Sheets. Check service-account access and worksheet permissions."
        ) from exc


def dataframe_to_temp_csv(df: pd.DataFrame, folder: Path, prefix: str = "google_sheet") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=prefix, suffix=".csv", dir=folder, delete=False) as handle:
        path = Path(handle.name)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path
