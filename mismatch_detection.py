from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import urlparse


GENERIC_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "hotmail.com",
    "icloud.com",
    "live.com",
    "me.com",
    "outlook.com",
    "proton.me",
    "protonmail.com",
    "yahoo.com",
}

TRUSTED_EVIDENCE_DOMAINS = {
    "apps.apple.com",
    "itunes.apple.com",
    "play.google.com",
    "linkedin.com",
    "www.linkedin.com",
}

BRAND_STOPWORDS = {
    "app",
    "apps",
    "co",
    "com",
    "company",
    "health",
    "inc",
    "io",
    "llc",
    "ltd",
    "mental",
    "pro",
    "the",
    "www",
}


def _text(value: Any) -> str:
    try:
        if value != value:
            return ""
    except Exception:
        pass
    return str(value or "").strip()


def _bool_text(value: bool) -> str:
    return "yes" if value else "no"


def _host(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    parsed = urlparse(text if "://" in text else f"https://{text}")
    return parsed.netloc.lower().removeprefix("www.")


def _domain_label(value: Any) -> str:
    host = _host(value)
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "net", "org"}:
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else parts[0]


def _brand_tokens(value: Any) -> set[str]:
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", _text(value).lower())
        if len(token) >= 3 and token not in BRAND_STOPWORDS
    }
    return tokens


def _first_non_empty(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = _text(row.get(key))
        if value:
            return value
    return ""


def _email_domain(row: Mapping[str, Any]) -> str:
    for key in ["email", "Email", "work_email", "input__Email", "input__email", "input__Work Email"]:
        email = _text(row.get(key))
        match = re.search(r"@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", email)
        if match:
            return match.group(1).lower().removeprefix("www.")
    return ""


def _domains_from_urls(value: Any) -> set[str]:
    domains: set[str] = set()
    for item in re.split(r"[|\s\n]+", _text(value)):
        if not item:
            continue
        host = _host(item)
        if host:
            domains.add(host)
    return domains


def _looks_company_website_mismatch(company: str, website: str) -> bool:
    if not company or not website:
        return False
    company_tokens = _brand_tokens(company)
    domain_token = _domain_label(website)
    domain_tokens = _brand_tokens(domain_token)
    if not company_tokens or not domain_tokens:
        return False
    compact_company = "".join(sorted(company_tokens))
    compact_domain = "".join(sorted(domain_tokens)) or domain_token.lower()
    natural_company = "".join(re.findall(r"[a-z0-9]+", company.lower()))
    if domain_token.lower() in {compact_company, natural_company} or domain_token.lower() in natural_company:
        return False
    return not bool(company_tokens.intersection(domain_tokens))


def _opener_brand_mismatch(row: Mapping[str, Any], company: str, website: str) -> bool:
    line = _first_non_empty(row, "final_delivery_line", "selected_opener", "personalized_line", "opening_line")
    if not line:
        return False
    allowed = _brand_tokens(company) | _brand_tokens(_domain_label(website))
    if not allowed:
        return False
    opener_brands = set()
    for pattern in [
        r"\bchecking\s+(?:the\s+)?([A-Z][A-Za-z0-9'\-]{2,})\s+(?:app|App Store|Google Play|website)\b",
        r"\bthe\s+([A-Z][A-Za-z0-9'\-]{2,})\s+(?:app|App Store|Google Play|website)\b",
    ]:
        opener_brands.update(match.group(1).lower() for match in re.finditer(pattern, line))
    return bool(opener_brands and not opener_brands.intersection(allowed))


def evaluate_mismatch(row: Mapping[str, Any]) -> dict[str, str]:
    company = _first_non_empty(row, "company", "company_name", "input__Company Name", "input__company")
    website = _first_non_empty(row, "website", "website_url", "input__Website", "input__website")
    website_host = _host(website)
    reasons: list[str] = []

    company_website = _looks_company_website_mismatch(company, website)
    if company_website:
        reasons.append("company_name_does_not_match_website_domain")

    email_domain = _email_domain(row)
    person_company = bool(
        email_domain
        and website_host
        and email_domain not in GENERIC_EMAIL_DOMAINS
        and not email_domain.endswith(website_host)
        and not website_host.endswith(email_domain)
    )
    if person_company:
        reasons.append("contact_email_domain_does_not_match_company_website")

    source_domains = _domains_from_urls(
        _first_non_empty(
            row,
            "opener_option_1_source_url",
            "source_urls",
            "research_revenue_model_source_url",
            "research_target_customer_source_url",
        )
    )
    unexpected_sources = []
    for domain in source_domains:
        if domain in TRUSTED_EVIDENCE_DOMAINS or any(domain.endswith("." + trusted) for trusted in TRUSTED_EVIDENCE_DOMAINS):
            continue
        if website_host and (domain.endswith(website_host) or website_host.endswith(domain)):
            continue
        unexpected_sources.append(domain)
    if unexpected_sources:
        reasons.append("source_url_domain_does_not_match_company_domain")

    if _opener_brand_mismatch(row, company, website):
        reasons.append("opener_mentions_brand_that_does_not_match_company_or_domain")

    warning = bool(reasons)
    return {
        "company_website_mismatch": _bool_text(company_website),
        "person_company_mismatch": _bool_text(person_company),
        "input_mapping_warning": _bool_text(warning),
        "mismatch_reason": " | ".join(dict.fromkeys(reasons)),
    }


def apply_mismatch_to_row(row: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out.update(evaluate_mismatch(out))
    return out
