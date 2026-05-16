from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pandas as pd

from models import LeadInput


REQUIRED_COLUMNS = ["company_name", "website_url"]
OPTIONAL_COLUMNS = [
    "linkedin_url",
    "recipient_name",
    "recipient_role",
    "campaign_context",
    "optional_notes",
    "linkedin_observation",
    "linkedin_source_note",
    "app_store_url",
    "app_flow_observation",
    "app_flow_source_note",
    "screenshot_url",
    "recent_news_url",
    "recent_news_note",
    "competitor_context",
]
ALL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS


def normalize_url(value: str) -> tuple[str, str | None]:
    raw = str(value or "").strip()
    if not raw:
        return "", "website_url is required"
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return raw, "website_url must be a valid http(s) URL"
    normalized_netloc = parsed.netloc.lower().removeprefix("www.")
    normalized_path = parsed.path.rstrip("/")
    normalized = urlunparse((parsed.scheme, normalized_netloc, normalized_path, "", "", ""))
    return normalized, None


def dedupe_key(lead: LeadInput) -> str:
    parsed = urlparse(lead.website_url)
    domain = parsed.netloc.lower().removeprefix("www.")
    if domain:
        return f"site:{domain}"
    return f"name:{lead.company_name.strip().lower()}"


def _first_present(row: pd.Series, candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate in row.index and str(row.get(candidate, "")).strip() not in {"", "—"}:
            return str(row.get(candidate, "")).strip()
    return ""


def _prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    company_source_columns = [
        "Organization Name",
        "Last Funding Amount",
        "Approx USD Equivalent",
        "Website",
        "Twitter",
        "Facebook",
        "LinkedIn",
        "Contact Email",
        "Number of Articles",
        "Number of Employees",
        "Number of Founders",
        "Founders",
        "icp_match",
        "b2c_category",
        "Organization Name.1",
    ]
    for column in company_source_columns:
        if column in working.columns:
            working[column] = working[column].replace("", pd.NA).ffill().fillna("")
    return working


def load_leads(
    csv_path: str | Path,
    default_campaign_context: str = "",
    deduplicate: bool = True,
) -> list[LeadInput]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Input CSV not found: {path}")

    df = _prepare_dataframe(pd.read_csv(path, dtype=str).fillna(""))
    has_standard_columns = all(column in df.columns for column in REQUIRED_COLUMNS)
    has_client_columns = "Organization Name" in df.columns and "Website" in df.columns
    if not has_standard_columns and not has_client_columns:
        raise ValueError(
            "Input CSV missing required columns. Use company_name/website_url, or the client sheet columns Organization Name/Website."
        )

    for column in OPTIONAL_COLUMNS:
        if column not in df.columns:
            df[column] = ""

    leads: list[LeadInput] = []
    seen: set[str] = set()

    for index, row in df.iterrows():
        errors: list[str] = []
        company_name = _first_present(row, ["company_name", "Organization Name", "Organization Name.1"])
        if not company_name:
            errors.append("company_name is required")

        website_url, url_error = normalize_url(_first_present(row, ["website_url", "Website"]))
        if url_error:
            errors.append(url_error)

        campaign_context = _first_present(row, ["campaign_context"]) or default_campaign_context
        lead = LeadInput(
            company_name=company_name,
            website_url=website_url,
            linkedin_url=_first_present(row, ["linkedin_url", "Linkedin", "LinkedIn"]),
            recipient_name=_first_present(row, ["recipient_name", "Person Name"]),
            recipient_role=_first_present(row, ["recipient_role", "Role"]),
            campaign_context=campaign_context,
            optional_notes=_first_present(row, ["optional_notes"]),
            linkedin_observation=_first_present(row, ["linkedin_observation", "LinkedIn Observation"]),
            linkedin_source_note=_first_present(row, ["linkedin_source_note", "LinkedIn Source Note"]),
            app_store_url=_first_present(row, ["app_store_url", "App Store URL", "Google Play URL"]),
            app_flow_observation=_first_present(row, ["app_flow_observation", "App Flow Observation", "Manual App Observation"]),
            app_flow_source_note=_first_present(row, ["app_flow_source_note", "App Flow Source Note"]),
            screenshot_url=_first_present(row, ["screenshot_url", "Screenshot URL", "Screenshot"]),
            recent_news_url=_first_present(row, ["recent_news_url", "Recent News URL"]),
            recent_news_note=_first_present(row, ["recent_news_note", "Recent News Note", "Product Update Note"]),
            competitor_context=_first_present(row, ["competitor_context", "Competitor Context"]),
            is_valid=not errors,
            validation_errors=errors,
        )

        if lead.is_valid and deduplicate:
            key = dedupe_key(lead)
            if key in seen:
                lead.is_valid = False
                lead.is_duplicate = True
                lead.validation_errors.append("Duplicate row by website/company")
            else:
                seen.add(key)

        if lead.validation_errors:
            logging.warning("Row %s validation issue: %s", index + 2, "; ".join(lead.validation_errors))
        leads.append(lead)

    return leads
