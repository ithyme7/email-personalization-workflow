from __future__ import annotations

from difflib import SequenceMatcher
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
    "coach",
    "health",
    "foundation",
    "for",
    "inc",
    "io",
    "llc",
    "ltd",
    "mental",
    "pro",
    "the",
    "www",
}

DOMAIN_BRAND_PREFIXES = ("get", "join", "try", "use", "my", "go", "the")
DOMAIN_BRAND_SUFFIXES = ("app", "apps", "health", "hq", "io", "co", "org")

URL_PATTERN = re.compile(r"https?://[^\s|,;\"')\]]+", re.IGNORECASE)


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


def _compact_text(value: Any) -> str:
    return "".join(re.findall(r"[a-z0-9]+", _text(value).lower()))


def _brand_tokens(value: Any) -> set[str]:
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", _text(value).lower())
        if len(token) >= 3 and token not in BRAND_STOPWORDS
    }
    return tokens


def _domain_brand_variants(domain_token: str) -> set[str]:
    compact = _compact_text(domain_token)
    if not compact:
        return set()
    variants = {compact}
    for prefix in DOMAIN_BRAND_PREFIXES:
        if compact.startswith(prefix) and len(compact) > len(prefix) + 2:
            variants.add(compact[len(prefix):])
    for suffix in DOMAIN_BRAND_SUFFIXES:
        if compact.endswith(suffix) and len(compact) > len(suffix) + 2:
            variants.add(compact[: -len(suffix)])
    for prefix in DOMAIN_BRAND_PREFIXES:
        for suffix in DOMAIN_BRAND_SUFFIXES:
            if compact.startswith(prefix) and compact.endswith(suffix):
                middle = compact[len(prefix): -len(suffix)]
                if len(middle) >= 3:
                    variants.add(middle)
    return variants


def _acronyms(value: Any) -> set[str]:
    raw_tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", _text(value).lower())
        if len(token) >= 2
    ]
    significant_tokens = [token for token in raw_tokens if token not in BRAND_STOPWORDS]
    acronyms = set()
    if len(raw_tokens) >= 2:
        acronyms.add("".join(token[0] for token in raw_tokens))
    if len(significant_tokens) >= 2:
        acronyms.add("".join(token[0] for token in significant_tokens))
    return {acronym for acronym in acronyms if len(acronym) >= 2}


def _is_close_brand_variant(left: str, right: str) -> bool:
    if len(left) < 5 or len(right) < 5:
        return False
    return SequenceMatcher(None, left, right).ratio() >= 0.86


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
    for match in URL_PATTERN.finditer(_text(value)):
        host = _host(match.group(0).rstrip(".,;:"))
        if host:
            domains.add(host)
    return domains


def _looks_company_website_mismatch(company: str, website: str) -> bool:
    if not company or not website:
        return False
    company_tokens = _brand_tokens(company)
    domain_token = _domain_label(website)
    domain_variants = _domain_brand_variants(domain_token)
    if not company_tokens or not domain_variants:
        return False
    natural_company = _compact_text(company)
    compact_company_tokens = "".join(sorted(company_tokens))
    if natural_company in domain_variants or compact_company_tokens in domain_variants:
        return False
    if any(variant in natural_company or natural_company in variant for variant in domain_variants):
        return False
    if any(token in variant or variant in token for token in company_tokens for variant in domain_variants if len(token) >= 4):
        return False
    if any(acronym and any(variant.startswith(acronym) or acronym == variant for variant in domain_variants) for acronym in _acronyms(company)):
        return False
    if any(_is_close_brand_variant(token, variant) for token in company_tokens for variant in domain_variants):
        return False
    return True


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
