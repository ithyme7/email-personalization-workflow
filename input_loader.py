from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pandas as pd

from models import LeadInput


def _compute_research_depth(lead: LeadInput) -> float:
    """Bereken een research-depth score (0.0–1.0) op basis van lead-kwaliteit.

    Signalen die zwaarder wegen:
      - Bedrijfsgrootte / funding indicaties
      - LinkedIn profiel beschikbaar
      - App Store presence
      - Specifieke campaign context
      - Concurrentie/competitor context
    """
    score = 0.3  # baseline

    # LinkedIn data
    if lead.linkedin_url.strip():
        score += 0.1
    if lead.linkedin_observation.strip():
        score += 0.075
    if lead.recipient_role.strip():
        score += 0.05

    # App Store / product signals
    if lead.app_store_url.strip():
        score += 0.075
    if lead.app_flow_observation.strip():
        score += 0.05

    # Campaign context diepgang
    ctx = lead.campaign_context.strip().lower()
    if ctx:
        # Specifieke context is waardevoller dan generiek
        generic_phrases = {
            " " + w
            for w in (
                "outreach",
                "email",
                "cold email",
                "personalization",
                "prospect",
                "lead",
                "contact",
                "follow up",
                "follow-up",
            )
        }
        has_specific = not any(ctx.endswith(p) or p in ctx for p in generic_phrases)
        score += 0.1 if has_specific else 0.04

    # Competitor context
    if lead.competitor_context.strip():
        score += 0.075

    # Optional notes als extra signaal
    if lead.optional_notes.strip():
        score += 0.05

    # Funding/enterprise indicatoren in company naam of notes
    combined = (lead.company_name + " " + lead.optional_notes + " " + lead.campaign_context).lower()
    enterprise_markers = {
        "enterprise",
        "series a",
        "series b",
        "series c",
        "series d",
        "seed round",
        "funding",
        "raised",
        "fortune",
        "inc 5000",
        "unicorn",
        "b2b",
    }
    if any(m in combined for m in enterprise_markers):
        score += 0.1

    return min(1.0, max(0.0, round(score, 2)))


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

CLIENT_COLUMN_ALIASES = {
    "Organization Name": "company_name",
    "Organization Name.1": "company_name",
    "Company Name": "company_name",
    "Company": "company_name",
    "Website": "website_url",
    "Website URL": "website_url",
    "Company Website": "website_url",
    "Domain": "website_url",
    "Linkedin": "linkedin_url",
    "LinkedIn": "linkedin_url",
    "LinkedIn URL": "linkedin_url",
    "App Store": "app_store_url",
    "App Store URL": "app_store_url",
    "Google Play": "app_store_url",
    "Google Play URL": "app_store_url",
    "First Name": "recipient_name",
    "Name": "recipient_name",
    "Full Name": "recipient_name",
    "Contact Name": "recipient_name",
    "Person Name": "recipient_name",
    "Job Title": "recipient_role",
    "Job Tile": "recipient_role",
    "Title": "recipient_role",
    "Role": "recipient_role",
}

CANONICAL_COLUMN_SOURCES = {
    "company_name": ["company_name", "Company Name", "Organization Name", "Company", "Organization Name.1"],
    "website_url": ["website_url", "Website", "Website URL", "Company Website", "Domain"],
    # Person-level LinkedIn exports often use "Linkedin"; company-level columns often use "LinkedIn".
    "linkedin_url": ["linkedin_url", "Linkedin", "LinkedIn URL", "Person Linkedin", "Person LinkedIn", "LinkedIn"],
    "recipient_name": ["recipient_name", "Person Name", "Full Name", "Contact Name", "First Name", "Name"],
    "recipient_role": ["recipient_role", "Role", "Job Title", "Job Tile", "Title"],
    "app_store_url": ["app_store_url", "App Store URL", "Google Play URL", "App Store", "Google Play"],
    "linkedin_observation": ["linkedin_observation", "LinkedIn Observation"],
    "linkedin_source_note": ["linkedin_source_note", "LinkedIn Source Note"],
    "app_flow_observation": ["app_flow_observation", "App Flow Observation", "Manual App Observation"],
    "app_flow_source_note": ["app_flow_source_note", "App Flow Source Note"],
    "screenshot_url": ["screenshot_url", "Screenshot URL", "Screenshot"],
    "recent_news_url": ["recent_news_url", "Recent News URL"],
    "recent_news_note": ["recent_news_note", "Recent News Note", "Product Update Note"],
    "competitor_context": ["competitor_context", "Competitor Context"],
}


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
        value = str(row.get(candidate, "")).replace("\r", " ").replace("\n", " ").strip()
        if candidate in row.index and value not in {"", "—"}:
            return " ".join(value.split())
    return ""


def _prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    working = _clean_dataframe(df)
    _fill_down_company_context(working)
    _apply_canonical_columns(working)
    _fill_down_company_context(working)
    return working


def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    working.columns = [str(column).strip() for column in working.columns]
    working = working.apply(
        lambda column: column.map(
            lambda value: str(value).replace("\r", " ").replace("\n", " ").strip() if pd.notna(value) else ""
        )
    )
    return working


def _fill_down_company_context(working: pd.DataFrame) -> None:
    company_source_columns = [
        "company_name",
        "Organization Name",
        "Company Name",
        "Last Funding Amount",
        "Approx USD Equivalent",
        "website_url",
        "Website",
        "Twitter",
        "Facebook",
        "linkedin_url",
        "Linkedin",
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


def _has_value(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().replace("—", "").ne("")


def _apply_canonical_columns(working: pd.DataFrame) -> None:
    for target, candidates in CANONICAL_COLUMN_SOURCES.items():
        present = [candidate for candidate in candidates if candidate in working.columns]
        if not present:
            continue
        if target not in working.columns:
            working[target] = ""
        for source_column in present:
            source = working[source_column].fillna("").astype(str)
            target_blank = ~_has_value(working[target])
            source_has_value = _has_value(source)
            working.loc[target_blank & source_has_value, target] = source[target_blank & source_has_value]


def _company_from_website(website_url: str) -> str:
    parsed = urlparse(website_url)
    domain = parsed.netloc.lower().removeprefix("www.")
    if not domain:
        return ""
    stem = domain.split(".")[0].replace("-", " ").replace("_", " ")
    return " ".join(part.capitalize() for part in stem.split())


def _row_original_columns(row: pd.Series) -> dict[str, str]:
    return {
        str(column).strip(): " ".join(str(row.get(column, "") or "").replace("\r", " ").replace("\n", " ").split())
        for column in row.index
        if str(column).strip()
    }


def load_leads(
    csv_path: str | Path,
    default_campaign_context: str = "",
    deduplicate: bool = True,
) -> list[LeadInput]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Input CSV not found: {path}")

    raw_df = _clean_dataframe(pd.read_csv(path, dtype=str).fillna(""))
    original_df = raw_df.copy()
    df = _prepare_dataframe(raw_df)
    has_standard_columns = all(column in df.columns for column in REQUIRED_COLUMNS)
    has_client_columns = "Organization Name" in df.columns and "Website" in df.columns
    has_alias_columns = "company_name" in df.columns and "website_url" in df.columns
    if not has_standard_columns and not has_client_columns and not has_alias_columns:
        raise ValueError(
            "Input CSV missing required columns. Use company_name/website_url, or client columns such as Organization Name/Website or Company Name/Website."
        )

    for column in OPTIONAL_COLUMNS:
        if column not in df.columns:
            df[column] = ""

    leads: list[LeadInput] = []
    seen: set[str] = set()

    for index, row in df.iterrows():
        errors: list[str] = []
        website_url, url_error = normalize_url(_first_present(row, ["website_url", "Website"]))
        if url_error:
            errors.append(url_error)
        company_name = _first_present(row, ["company_name", "Organization Name", "Organization Name.1"]) or _company_from_website(website_url)
        if not company_name:
            errors.append("company_name is required")

        campaign_context = _first_present(row, ["campaign_context"]) or default_campaign_context
        original_row = original_df.iloc[index] if index < len(original_df) else row
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
            app_store_url=_first_present(row, ["app_store_url", "App Store URL", "Google Play URL", "App Store"]),
            app_flow_observation=_first_present(row, ["app_flow_observation", "App Flow Observation", "Manual App Observation"]),
            app_flow_source_note=_first_present(row, ["app_flow_source_note", "App Flow Source Note"]),
            screenshot_url=_first_present(row, ["screenshot_url", "Screenshot URL", "Screenshot"]),
            recent_news_url=_first_present(row, ["recent_news_url", "Recent News URL"]),
            recent_news_note=_first_present(row, ["recent_news_note", "Recent News Note", "Product Update Note"]),
            competitor_context=_first_present(row, ["competitor_context", "Competitor Context"]),
            is_valid=not errors,
            validation_errors=errors,
            original_columns=_row_original_columns(original_row),
        )

        # Bereken research depth score voor lead-weighted research
        lead.research_depth = _compute_research_depth(lead)

        if lead.is_valid and deduplicate:
            parsed = urlparse(lead.website_url)
            domain = parsed.netloc.lower().removeprefix("www.")
            key = f"site:{domain}" if domain else f"name:{lead.company_name.strip().lower()}"
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
