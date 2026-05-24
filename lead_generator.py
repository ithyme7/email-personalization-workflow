from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup
import pandas as pd
import requests


SEARCH_URL = "https://duckduckgo.com/html/"
APP_STORE_SEARCH_URL = "https://itunes.apple.com/search"

DIRECTORY_DOMAINS = {
    "apps.apple.com",
    "crunchbase.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "play.google.com",
    "twitter.com",
    "x.com",
    "youtube.com",
}

NOISE_TITLE_TERMS = {
    "login",
    "sign in",
    "privacy policy",
    "terms",
    "support",
    "contact",
}


@dataclass(frozen=True)
class GeneratedLead:
    organization_name: str
    website: str
    app_store_url: str
    source: str
    discovery_query: str
    source_title: str
    source_snippet: str
    lead_score: int
    lead_notes: str


def build_lead_search_queries(
    niche: str,
    target_customer: str = "",
    region: str = "",
    extra_keywords: str = "",
) -> list[str]:
    base = " ".join(part.strip() for part in [niche, target_customer, region] if part.strip())
    extras = [item.strip() for item in re.split(r"[\n,]+", extra_keywords or "") if item.strip()]
    anchors = extras or [
        "app",
        "startup",
        "platform",
        "booking",
        "onboarding",
        "pricing",
        "founder",
    ]
    queries = []
    for anchor in anchors:
        query = " ".join(part for part in [base, anchor, "-jobs", "-blog"] if part).strip()
        if query and query not in queries:
            queries.append(query)
    return queries


def build_app_store_terms(niche: str, extra_keywords: str = "") -> list[str]:
    terms = [item.strip() for item in re.split(r"[\n,]+", extra_keywords or "") if item.strip()]
    if not terms and niche.strip():
        terms = [niche.strip()]
    elif niche.strip():
        terms = [f"{niche.strip()} {term}" for term in terms]
    return list(dict.fromkeys(term for term in terms if term))


def generate_app_store_leads(
    terms: Iterable[str],
    country: str = "us",
    max_leads: int = 50,
    timeout_seconds: int = 15,
    session: requests.Session | None = None,
) -> list[GeneratedLead]:
    active_session = session or requests.Session()
    leads: list[GeneratedLead] = []
    seen_keys: set[str] = set()
    for term in terms:
        if len(leads) >= max_leads:
            break
        response = active_session.get(
            APP_STORE_SEARCH_URL,
            params={
                "term": term,
                "entity": "software",
                "country": (country or "us").lower(),
                "limit": min(200, max(max_leads * 2, 25)),
            },
            timeout=timeout_seconds,
            headers={"User-Agent": "email-personalization-workflow/lead-generator"},
        )
        response.raise_for_status()
        payload = response.json()
        for lead in app_store_payload_to_leads(payload, term):
            if len(leads) >= max_leads:
                break
            key = lead.app_store_url or lead.website or lead.organization_name.lower()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            leads.append(lead)
    return leads


def app_store_payload_to_leads(payload: dict, discovery_query: str) -> list[GeneratedLead]:
    leads: list[GeneratedLead] = []
    for item in payload.get("results", []):
        track_name = _clean_text(item.get("trackName", ""))
        seller_name = _clean_text(item.get("sellerName", ""))
        app_store_url = _clean_text(item.get("trackViewUrl", ""))
        seller_url = _clean_text(item.get("sellerUrl", ""))
        if not track_name or not app_store_url:
            continue
        website = normalize_company_url(seller_url) if seller_url else app_store_url
        title = track_name if not seller_name else f"{track_name} by {seller_name}"
        genre = _clean_text(item.get("primaryGenreName", ""))
        snippet = _clean_text(item.get("description", ""))[:500]
        company = app_store_brand_name(track_name, seller_name)
        score, notes = score_app_store_lead(track_name, seller_name, genre, snippet, discovery_query, seller_url)
        if seller_name:
            notes.append(f"seller:{seller_name}")
        leads.append(
            GeneratedLead(
                organization_name=company,
                website=website,
                app_store_url=app_store_url,
                source="apple_app_store_search",
                discovery_query=discovery_query,
                source_title=title,
                source_snippet=snippet,
                lead_score=score,
                lead_notes=" | ".join(notes),
            )
        )
    return leads


def generate_leads(
    queries: Iterable[str],
    max_leads: int = 50,
    timeout_seconds: int = 15,
    session: requests.Session | None = None,
) -> list[GeneratedLead]:
    active_session = session or requests.Session()
    leads: list[GeneratedLead] = []
    seen_hosts: set[str] = set()
    for query in queries:
        if len(leads) >= max_leads:
            break
        for item in _search_web(query, active_session, timeout_seconds=timeout_seconds):
            if len(leads) >= max_leads:
                break
            website = normalize_company_url(item["url"])
            host = _host(website)
            if not host or host in seen_hosts or _is_noise_host(host):
                continue
            company = company_name_from_result(item["title"], website)
            score, notes = score_lead(company, website, item["title"], item["snippet"], query)
            if score < 35:
                continue
            seen_hosts.add(host)
            leads.append(
                GeneratedLead(
                    organization_name=company,
                    website=website,
                    app_store_url="",
                    source="public_web_search",
                    discovery_query=query,
                    source_title=item["title"],
                    source_snippet=item["snippet"],
                    lead_score=score,
                    lead_notes=" | ".join(notes),
                )
            )
    return leads


def generated_leads_dataframe(leads: Iterable[GeneratedLead]) -> pd.DataFrame:
    rows = [
        {
            "Organization Name": lead.organization_name,
            "Website": lead.website,
            "App Store URL": lead.app_store_url,
            "Person Name": "",
            "Role": "",
            "Email": "",
            "Source": lead.source,
            "Discovery Query": lead.discovery_query,
            "Lead Score": lead.lead_score,
            "Lead Notes": lead.lead_notes,
            "Source Title": lead.source_title,
            "Source Snippet": lead.source_snippet,
        }
        for lead in leads
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "Organization Name",
            "Website",
            "App Store URL",
            "Person Name",
            "Role",
            "Email",
            "Source",
            "Discovery Query",
            "Lead Score",
            "Lead Notes",
            "Source Title",
            "Source Snippet",
        ],
    )


def _search_web(query: str, session: requests.Session, timeout_seconds: int) -> list[dict[str, str]]:
    response = session.get(
        SEARCH_URL,
        params={"q": query},
        timeout=timeout_seconds,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            )
        },
    )
    response.raise_for_status()
    return parse_search_results(response.text)


def parse_search_results(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    results: list[dict[str, str]] = []
    for result in soup.select(".result"):
        link = result.select_one("a.result__a") or result.select_one("a[href]")
        if not link:
            continue
        url = _decode_result_url(str(link.get("href", "")))
        if not url.startswith(("http://", "https://")):
            continue
        title = _clean_text(link.get_text(" ", strip=True))
        snippet_node = result.select_one(".result__snippet")
        snippet = _clean_text(snippet_node.get_text(" ", strip=True) if snippet_node else "")
        if title:
            results.append({"url": url, "title": title, "snippet": snippet})
    return results


def normalize_company_url(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    host = parsed.netloc.lower().removeprefix("www.")
    return f"https://{host}"


def company_name_from_result(title: str, website: str) -> str:
    title_prefix = re.split(r"\s[-|–—]\s", _clean_text(title or ""))[0].strip()
    title_prefix = re.sub(r"\b(home|homepage|official site)\b", "", title_prefix, flags=re.IGNORECASE).strip()
    if title_prefix and len(title_prefix) <= 60 and not _contains_noise_term(title_prefix):
        return title_prefix
    label = _host(website).split(".")[0]
    label = re.sub(r"^(get|join|try|use|my)", "", label)
    label = re.sub(r"(app|hq)$", "", label)
    return " ".join(part.capitalize() for part in re.split(r"[-_]+", label) if part) or _host(website)


def app_store_brand_name(track_name: str, seller_name: str = "") -> str:
    name = _clean_text(track_name)
    name = re.split(r"\s[-|–—]\s|:", name, maxsplit=1)[0].strip()
    name = re.sub(r"\b(app|mobile app)\b$", "", name, flags=re.IGNORECASE).strip()
    if name and 2 <= len(name) <= 50:
        return name
    return _clean_text(seller_name) or _clean_text(track_name)


def score_lead(company: str, website: str, title: str, snippet: str, query: str) -> tuple[int, list[str]]:
    text = " ".join([company, website, title, snippet]).lower()
    query_tokens = {token for token in re.findall(r"[a-z0-9]+", query.lower()) if len(token) >= 4}
    score = 45
    notes: list[str] = ["public_web_result"]
    if any(term in text for term in ["app", "platform", "software", "mobile"]):
        score += 15
        notes.append("product_or_app_signal")
    if any(term in text for term in ["pricing", "book", "signup", "download", "trial", "onboarding"]):
        score += 10
        notes.append("conversion_surface_signal")
    if query_tokens and any(token in text for token in query_tokens):
        score += 10
        notes.append("matches_query_terms")
    if _contains_noise_term(title):
        score -= 20
        notes.append("low_value_page_title")
    if _is_noise_host(_host(website)):
        score -= 50
        notes.append("directory_or_social_domain")
    return max(0, min(100, score)), notes


def score_app_store_lead(
    track_name: str,
    seller_name: str,
    genre: str,
    description: str,
    query: str,
    seller_url: str,
) -> tuple[int, list[str]]:
    text = " ".join([track_name, seller_name, genre, description]).lower()
    query_tokens = {token for token in re.findall(r"[a-z0-9]+", query.lower()) if len(token) >= 4}
    score = 55
    notes = ["app_store_result", "app_first_lead"]
    if seller_url:
        score += 10
        notes.append("seller_website_available")
    if query_tokens and any(token in text for token in query_tokens):
        score += 15
        notes.append("matches_query_terms")
    if any(term in text for term in ["health", "therapy", "wellness", "mental", "sleep", "anxiety", "adhd"]):
        score += 10
        notes.append("health_or_wellness_signal")
    if genre:
        notes.append(f"genre:{genre}")
    return max(0, min(100, score)), notes


def _decode_result_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    params = parse_qs(parsed.query)
    if "uddg" in params and params["uddg"]:
        return unquote(params["uddg"][0])
    return href


def _host(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return parsed.netloc.lower().removeprefix("www.")


def _is_noise_host(host: str) -> bool:
    if not host:
        return True
    return any(host == domain or host.endswith("." + domain) for domain in DIRECTORY_DOMAINS)


def _contains_noise_term(value: str) -> bool:
    lower = value.lower()
    return any(term in lower for term in NOISE_TITLE_TERMS)


def _clean_text(value: str) -> str:
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
