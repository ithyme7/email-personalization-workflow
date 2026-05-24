from __future__ import annotations

from dataclasses import dataclass
from html import escape as html_escape
import re
import time
from typing import Iterable
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from bs4 import BeautifulSoup
import pandas as pd
import requests

from cache import cache_path, read_cached_json, write_cached_json


SEARCH_URL = "https://duckduckgo.com/html/"
APP_STORE_SEARCH_URL = "https://itunes.apple.com/search"
CONTACT_SEARCH_URL = "https://r.jina.ai/http://https://duckduckgo.com/html/"
DISCOVERY_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

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

TARGET_CONTACT_EXPORT_COLUMNS = [
    "First Name",
    "Copy",
    "Personalization Line",
    "Company Name",
    "LinkedIn Profile",
    "Personal Email",
    "Company Website",
]

PERSONAL_EMAIL_BLOCKLIST = {
    "admin",
    "billing",
    "careers",
    "contact",
    "customerservice",
    "data",
    "hello",
    "help",
    "hr",
    "info",
    "jobs",
    "legal",
    "marketing",
    "media",
    "news",
    "press",
    "privacy",
    "sales",
    "security",
    "support",
    "team",
}

TARGET_ROLE_TERMS = (
    "founder",
    "co-founder",
    "cofounder",
    "chief executive officer",
    "ceo",
    "chief technology officer",
    "cto",
)

PERSON_NAME_BLOCKLIST = {
    "ceo",
    "content",
    "co-founder",
    "cofounder",
    "duckduckgo",
    "founder",
    "markdown",
    "source",
    "title",
    "cto",
    "url",
}

CONTACT_PAGE_HINTS = (
    "about",
    "team",
    "founder",
    "founders",
    "leadership",
    "company",
    "contact",
)

EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
LINKEDIN_PROFILE_PATTERN = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9_%\-/?=&.]+", re.IGNORECASE)
LINKEDIN_COMPANY_PATTERN = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[A-Za-z0-9_%\-/?=&.]+", re.IGNORECASE)
PERSON_ROLE_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z'`-]+(?:\s+[A-Z][A-Za-z'`-]+){0,3})\b.{0,80}?\b("
    r"Co[-\s]?Founder|Founder|CEO|Chief Executive Officer|CTO|Chief Technology Officer"
    r")\b",
    re.IGNORECASE,
)
ROLE_PATTERN = re.compile(
    r"\b(Co[-\s]?Founder|Founder|CEO|Chief Executive Officer|CTO|Chief Technology Officer)\b",
    re.IGNORECASE,
)


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


@dataclass(frozen=True)
class ContactCandidate:
    first_name: str
    full_name: str = ""
    role: str = ""
    email: str = ""
    linkedin_url: str = ""
    source_url: str = ""
    confidence: int = 0
    notes: str = ""


@dataclass(frozen=True)
class CompanyLinkedInCandidate:
    url: str
    source_url: str = ""
    confidence: int = 0
    notes: str = ""


@dataclass
class DiscoveryCache:
    enabled: bool = True
    namespace: str = "lead_discovery"
    ttl_seconds: int = DISCOVERY_CACHE_TTL_SECONDS

    def read_text(self, kind: str, key: str) -> str | None:
        if not self.enabled or not key:
            return None
        data = read_cached_json(
            cache_path(key, prefix=f"{self.namespace}:{kind}:"),
            ttl_seconds=self.ttl_seconds,
        )
        value = data.get("text") if data else None
        return value if isinstance(value, str) else None

    def write_text(self, kind: str, key: str, text: str) -> None:
        if not self.enabled or not key or not text:
            return
        write_cached_json(
            cache_path(key, prefix=f"{self.namespace}:{kind}:"),
            {"text": text},
        )


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


def enrich_contacts_for_leads(
    leads: Iterable[GeneratedLead],
    max_contacts_per_company: int = 1,
    timeout_seconds: int = 12,
    use_search_fallback: bool = True,
    max_search_queries: int = 2,
    request_delay_seconds: float = 0.6,
    use_cache: bool = True,
    session: requests.Session | None = None,
) -> dict[str, list[ContactCandidate]]:
    active_session = session or requests.Session()
    cache = DiscoveryCache(enabled=use_cache)
    enriched: dict[str, list[ContactCandidate]] = {}
    for lead in leads:
        contacts = discover_contacts_for_lead(
            lead,
            max_contacts=max_contacts_per_company,
            timeout_seconds=timeout_seconds,
            use_search_fallback=use_search_fallback,
            max_search_queries=max_search_queries,
            request_delay_seconds=request_delay_seconds,
            cache=cache,
            session=active_session,
        )
        enriched[_lead_key(lead)] = contacts
    return enriched


def discover_contacts_for_lead(
    lead: GeneratedLead,
    max_contacts: int = 1,
    timeout_seconds: int = 12,
    use_search_fallback: bool = True,
    max_search_queries: int = 2,
    request_delay_seconds: float = 0.0,
    cache: DiscoveryCache | None = None,
    session: requests.Session | None = None,
) -> list[ContactCandidate]:
    website = normalize_company_url(lead.website)
    if not website or _is_noise_host(_host(website)) or "apps.apple.com" in _host(website):
        return []
    active_session = session or requests.Session()
    pages = fetch_contact_pages(website, timeout_seconds=timeout_seconds, session=active_session, cache=cache)
    company_linkedin = discover_company_linkedin(
        lead,
        pages=pages,
        timeout_seconds=timeout_seconds,
        use_search_fallback=use_search_fallback,
        request_delay_seconds=request_delay_seconds,
        cache=cache,
        session=active_session,
    )
    candidates: list[ContactCandidate] = []
    for page_url, html in pages:
        candidates.extend(parse_contact_candidates(html, page_url, company_domain=_host(website)))
    ranked = rank_contact_candidates(candidates)
    if use_search_fallback and len(ranked) < max_contacts:
        candidates.extend(
            search_contact_candidates(
                lead,
                timeout_seconds=timeout_seconds,
                session=active_session,
                cache=cache,
                max_search_queries=max_search_queries,
                request_delay_seconds=request_delay_seconds,
            )
        )
    ranked = rank_contact_candidates(candidates)
    if company_linkedin:
        ranked = [_with_candidate_note(candidate, f"company_linkedin_found:{company_linkedin.url}") for candidate in ranked]
    return ranked[:max_contacts]


def fetch_contact_pages(
    website: str,
    timeout_seconds: int = 12,
    session: requests.Session | None = None,
    max_pages: int = 5,
    cache: DiscoveryCache | None = None,
) -> list[tuple[str, str]]:
    active_session = session or requests.Session()
    homepage = normalize_company_url(website)
    urls = [homepage]
    html_by_url: dict[str, str] = {}
    homepage_html = _fetch_html_cached(homepage, active_session, timeout_seconds, cache=cache)
    if homepage_html:
        html_by_url[homepage] = homepage_html
        urls.extend(_candidate_contact_links(homepage, homepage_html))
    for path in ["/about", "/about-us", "/team", "/company", "/leadership", "/founders", "/contact"]:
        urls.append(homepage.rstrip("/") + path)

    pages: list[tuple[str, str]] = []
    seen: set[str] = set()
    for url in urls:
        normalized = url.split("#", 1)[0].rstrip("/")
        if normalized in seen or len(pages) >= max_pages:
            continue
        seen.add(normalized)
        html = html_by_url.get(normalized) or _fetch_html_cached(normalized, active_session, timeout_seconds, cache=cache)
        if html:
            pages.append((normalized, html))
    return pages


def discover_company_linkedin(
    lead: GeneratedLead,
    pages: list[tuple[str, str]] | None = None,
    timeout_seconds: int = 12,
    use_search_fallback: bool = True,
    request_delay_seconds: float = 0.0,
    cache: DiscoveryCache | None = None,
    session: requests.Session | None = None,
) -> CompanyLinkedInCandidate | None:
    candidates: list[CompanyLinkedInCandidate] = []
    for page_url, html in pages or []:
        for url in _linkedin_company_urls_from_html(html):
            candidates.append(
                CompanyLinkedInCandidate(
                    url=url,
                    source_url=page_url,
                    confidence=80,
                    notes="company_linkedin_on_owned_site",
                )
            )
    ranked = _rank_company_linkedin_candidates(candidates, lead.organization_name)
    if ranked or not use_search_fallback:
        return ranked[0] if ranked else None
    if not _clean_text(lead.organization_name):
        return None

    active_session = session or requests.Session()
    query = f'"{lead.organization_name}" site:linkedin.com/company'
    url = f"{CONTACT_SEARCH_URL}?q={quote_plus(query)}"
    text = _fetch_text_cached(
        url,
        active_session,
        timeout_seconds,
        cache=cache,
        request_delay_seconds=request_delay_seconds,
    )
    if not text:
        return None
    for title, link in _markdown_links(text):
        decoded = _decode_result_url(link)
        linkedin_url = _normalize_linkedin_url(decoded, kind="company")
        if not linkedin_url:
            continue
        confidence = 65
        if _company_slug_matches_name(linkedin_url, lead.organization_name) or lead.organization_name.lower() in title.lower():
            confidence += 15
        candidates.append(
            CompanyLinkedInCandidate(
                url=linkedin_url,
                source_url=url,
                confidence=min(95, confidence),
                notes="company_linkedin_public_search",
            )
        )
    return (_rank_company_linkedin_candidates(candidates, lead.organization_name) or [None])[0]


def parse_contact_candidates(html: str, source_url: str, company_domain: str = "") -> list[ContactCandidate]:
    soup = BeautifulSoup(html or "", "html.parser")
    text_lines = [_clean_text(line) for line in soup.get_text("\n", strip=True).splitlines()]
    text_lines = [line for line in text_lines if line]
    text_blob = "\n".join(text_lines)
    emails = [email for email in dict.fromkeys(EMAIL_PATTERN.findall(text_blob)) if _is_personal_email(email, company_domain)]
    linkedins = _linkedin_profiles_from_soup(soup)
    people = _people_from_role_lines(text_lines)

    candidates: list[ContactCandidate] = []
    for full_name, role in people:
        first_name = _first_name(full_name)
        email = _best_email_for_name(first_name, full_name, emails)
        linkedin_url = _best_linkedin_for_name(first_name, full_name, linkedins)
        confidence = 40
        notes = ["role_line_found"]
        if email:
            confidence += 30
            notes.append("personal_email_matched")
        if linkedin_url:
            confidence += 25
            notes.append("linkedin_profile_matched")
        candidates.append(
            ContactCandidate(
                first_name=first_name,
                full_name=full_name,
                role=role,
                email=email,
                linkedin_url=linkedin_url,
                source_url=source_url,
                confidence=min(100, confidence),
                notes=" | ".join(notes),
            )
        )

    used_emails = {candidate.email.lower() for candidate in candidates if candidate.email}
    for email in emails:
        if email.lower() in used_emails:
            continue
        local = email.split("@", 1)[0]
        first_name = _first_name_from_email_local(local)
        if not first_name:
            continue
        candidates.append(
            ContactCandidate(
                first_name=first_name,
                email=email,
                source_url=source_url,
                confidence=55,
                notes="personal_email_found_without_role",
            )
        )
    return rank_contact_candidates(candidates)


def search_contact_candidates(
    lead: GeneratedLead,
    timeout_seconds: int = 12,
    session: requests.Session | None = None,
    cache: DiscoveryCache | None = None,
    max_search_queries: int = 2,
    request_delay_seconds: float = 0.0,
) -> list[ContactCandidate]:
    active_session = session or requests.Session()
    search_texts: list[str] = []
    source_urls: list[str] = []
    for query in _contact_search_queries(lead)[: max(1, max_search_queries)]:
        url = f"{CONTACT_SEARCH_URL}?q={quote_plus(query)}"
        text = _fetch_text_cached(
            url,
            active_session,
            timeout_seconds,
            cache=cache,
            request_delay_seconds=request_delay_seconds,
        )
        if text:
            search_texts.append(f"Query: {query}\n{text}")
            source_urls.append(url)
    text = "\n\n".join(search_texts)
    if not text:
        return []
    decoded_links = [_decode_result_url(link) for _, link in _markdown_links(text)]
    linkedin_profiles = [
        _normalize_linkedin_url(profile, kind="profile")
        for link in decoded_links
        for profile in LINKEDIN_PROFILE_PATTERN.findall(link)
        if "/company/" not in profile.lower()
    ]
    linkedin_profiles = [profile for profile in linkedin_profiles if profile]
    company_domain = _host(lead.website)
    search_markup = "<html><body><pre>" + html_escape("\n".join([text, *linkedin_profiles])) + "</pre></body></html>"
    candidates = parse_contact_candidates(
        search_markup,
        source_urls[0] if source_urls else "",
        company_domain=company_domain,
    )
    candidates = [
        candidate
        for candidate in candidates
        if not _is_company_name_candidate(candidate.full_name, lead.organization_name)
    ]
    existing_profile_urls = {candidate.linkedin_url for candidate in candidates if candidate.linkedin_url}
    for title, link in _markdown_links(text):
        decoded = _normalize_linkedin_url(_decode_result_url(link), kind="profile")
        if not decoded or decoded in existing_profile_urls:
            continue
        full_name = _linked_profile_name_from_title(title)
        first_name = _first_name(full_name) or _first_name_from_linkedin_profile(decoded)
        if not first_name:
            continue
        candidates.append(
            ContactCandidate(
                first_name=first_name,
                full_name=full_name,
                linkedin_url=decoded,
                source_url=source_urls[0] if source_urls else "",
                confidence=50,
                notes="linkedin_profile_search_result",
            )
        )
    return [candidate for candidate in rank_contact_candidates(candidates) if candidate.email or candidate.linkedin_url]


def rank_contact_candidates(candidates: Iterable[ContactCandidate]) -> list[ContactCandidate]:
    best_by_key: dict[str, ContactCandidate] = {}
    for candidate in candidates:
        key = (candidate.email or candidate.linkedin_url or candidate.full_name or candidate.first_name).lower()
        if not key:
            continue
        existing = best_by_key.get(key)
        if not existing or candidate.confidence > existing.confidence:
            best_by_key[key] = candidate
    return sorted(
        best_by_key.values(),
        key=lambda candidate: (
            candidate.confidence,
            bool(candidate.email),
            bool(candidate.linkedin_url),
            _role_priority(candidate.role),
        ),
        reverse=True,
    )


def contact_export_dataframe(
    leads: Iterable[GeneratedLead],
    contact_lookup: dict[str, list[ContactCandidate]] | None = None,
    include_unmatched_companies: bool = False,
) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    lookup = contact_lookup or {}
    for lead in leads:
        contacts = lookup.get(_lead_key(lead), [])
        if not contacts and include_unmatched_companies:
            contacts = [ContactCandidate(first_name="", source_url=lead.source_title, confidence=0)]
        for contact in contacts:
            if not include_unmatched_companies and not (contact.email or contact.linkedin_url):
                continue
            rows.append(
                {
                    "First Name": contact.first_name,
                    "Copy": "",
                    "Personalization Line": "",
                    "Company Name": lead.organization_name,
                    "LinkedIn Profile": contact.linkedin_url,
                    "Personal Email": contact.email,
                    "Company Website": lead.website,
                }
            )
    return pd.DataFrame(rows, columns=TARGET_CONTACT_EXPORT_COLUMNS)


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


def _fetch_html(url: str, session: requests.Session, timeout_seconds: int) -> str:
    try:
        response = session.get(
            url,
            timeout=timeout_seconds,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
                )
            },
        )
        content_type = getattr(response, "headers", {}).get("content-type", "")
        if response.status_code >= 400 or ("html" not in content_type and content_type):
            return ""
        return response.text[:500_000]
    except requests.RequestException:
        return ""


def _fetch_text(url: str, session: requests.Session, timeout_seconds: int) -> str:
    try:
        response = session.get(
            url,
            timeout=timeout_seconds,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125 Safari/537.36"},
        )
        if response.status_code >= 400:
            return ""
        return response.text[:500_000]
    except requests.RequestException:
        return ""


def _fetch_html_cached(
    url: str,
    session: requests.Session,
    timeout_seconds: int,
    cache: DiscoveryCache | None = None,
) -> str:
    if cache:
        cached = cache.read_text("html", url)
        if cached is not None:
            return cached
    html = _fetch_html(url, session, timeout_seconds)
    if html and cache:
        cache.write_text("html", url, html)
    return html


def _fetch_text_cached(
    url: str,
    session: requests.Session,
    timeout_seconds: int,
    cache: DiscoveryCache | None = None,
    request_delay_seconds: float = 0.0,
) -> str:
    if cache:
        cached = cache.read_text("search", url)
        if cached is not None:
            return cached
    if request_delay_seconds > 0:
        time.sleep(request_delay_seconds)
    text = _fetch_text(url, session, timeout_seconds)
    if text and cache:
        cache.write_text("search", url, text)
    return text


def _candidate_contact_links(base_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    base = urlparse(base_url)
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        text = _clean_text(anchor.get_text(" ", strip=True)).lower()
        href = str(anchor.get("href", "")).strip()
        joined = _join_url(base_url, href)
        if not joined:
            continue
        parsed = urlparse(joined)
        if parsed.netloc.lower().removeprefix("www.") != base.netloc.lower().removeprefix("www."):
            continue
        haystack = f"{text} {parsed.path.lower()}"
        if any(hint in haystack for hint in CONTACT_PAGE_HINTS):
            links.append(joined)
    return list(dict.fromkeys(links))


def _join_url(base_url: str, href: str) -> str:
    if not href or href.startswith(("mailto:", "tel:", "javascript:")):
        return ""
    if href.startswith("//"):
        return "https:" + href
    if href.startswith(("http://", "https://")):
        return href
    parsed = urlparse(base_url)
    if href.startswith("/"):
        return f"{parsed.scheme}://{parsed.netloc}{href}"
    return f"{base_url.rstrip('/')}/{href}"


def _linkedin_profiles_from_soup(soup: BeautifulSoup) -> list[str]:
    profiles: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href", "")).strip()
        normalized = _normalize_linkedin_url(href, kind="profile")
        if normalized:
            profiles.append(normalized)
    text_profiles = [
        _normalize_linkedin_url(match.group(0), kind="profile")
        for match in LINKEDIN_PROFILE_PATTERN.finditer(soup.get_text(" ", strip=True))
    ]
    text_profiles = [profile for profile in text_profiles if profile]
    return list(dict.fromkeys(profiles + text_profiles))


def _linkedin_company_urls_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    urls: list[str] = []
    for anchor in soup.find_all("a", href=True):
        normalized = _normalize_linkedin_url(str(anchor.get("href", "")), kind="company")
        if normalized:
            urls.append(normalized)
    text_urls = [
        _normalize_linkedin_url(match.group(0), kind="company")
        for match in LINKEDIN_COMPANY_PATTERN.finditer(soup.get_text(" ", strip=True))
    ]
    return list(dict.fromkeys(url for url in [*urls, *text_urls] if url))


def _rank_company_linkedin_candidates(
    candidates: Iterable[CompanyLinkedInCandidate],
    company_name: str,
) -> list[CompanyLinkedInCandidate]:
    best_by_url: dict[str, CompanyLinkedInCandidate] = {}
    for candidate in candidates:
        if not candidate.url:
            continue
        score = candidate.confidence
        if _company_slug_matches_name(candidate.url, company_name):
            score += 10
        scored = CompanyLinkedInCandidate(
            url=candidate.url,
            source_url=candidate.source_url,
            confidence=min(100, score),
            notes=candidate.notes,
        )
        existing = best_by_url.get(scored.url)
        if not existing or scored.confidence > existing.confidence:
            best_by_url[scored.url] = scored
    return sorted(best_by_url.values(), key=lambda item: item.confidence, reverse=True)


def _normalize_linkedin_url(value: str, kind: str) -> str:
    decoded = _decode_result_url(value or "")
    pattern = LINKEDIN_PROFILE_PATTERN if kind == "profile" else LINKEDIN_COMPANY_PATTERN
    match = pattern.search(decoded)
    if not match:
        return ""
    parsed = urlparse(match.group(0))
    host = parsed.netloc.lower()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return ""
    path = parsed.path.rstrip("/")
    if kind == "profile" and not path.lower().startswith("/in/"):
        return ""
    if kind == "company" and not path.lower().startswith("/company/"):
        return ""
    return f"https://www.linkedin.com{path}"


def _company_slug_matches_name(linkedin_url: str, company_name: str) -> bool:
    slug = urlparse(linkedin_url).path.lower().split("/company/", 1)[-1].strip("/")
    slug_key = re.sub(r"[^a-z0-9]+", "", slug)
    company_key = re.sub(r"[^a-z0-9]+", "", (company_name or "").lower())
    if not slug_key or not company_key:
        return False
    return slug_key in company_key or company_key in slug_key


def _contact_search_queries(lead: GeneratedLead) -> list[str]:
    company = _clean_text(lead.organization_name)
    if not company:
        return []
    host = _host(lead.website)
    queries = [
        f'"{company}" founder CEO CTO email LinkedIn',
        f'"{company}" site:linkedin.com/in founder CEO CTO',
    ]
    if host:
        queries.insert(1, f'"{company}" "{host}" founder CEO CTO')
    return list(dict.fromkeys(queries))


def _with_candidate_note(candidate: ContactCandidate, note: str) -> ContactCandidate:
    notes = " | ".join(part for part in [candidate.notes, note] if part)
    return ContactCandidate(
        first_name=candidate.first_name,
        full_name=candidate.full_name,
        role=candidate.role,
        email=candidate.email,
        linkedin_url=candidate.linkedin_url,
        source_url=candidate.source_url,
        confidence=candidate.confidence,
        notes=notes,
    )


def _people_from_role_lines(lines: list[str]) -> list[tuple[str, str]]:
    people: list[tuple[str, str]] = []
    for line in lines:
        if not _contains_target_role(line):
            continue
        for match in ROLE_PATTERN.finditer(line):
            before_role = line[: match.start()].strip()
            name_match = re.search(
                r"([A-Z][A-Za-z'`-]+(?:\s+[A-Z][A-Za-z'`-]+){0,3})\s*$",
                before_role,
            )
            if not name_match:
                continue
            full_name = _clean_person_name(name_match.group(1))
            role = _clean_text(match.group(1))
            if full_name and _looks_like_person_name(full_name):
                people.append((full_name, role))
    return list(dict.fromkeys(people))


def _contains_target_role(value: str) -> bool:
    lower = value.lower()
    return any(term in lower for term in TARGET_ROLE_TERMS)


def _clean_person_name(value: str) -> str:
    cleaned = _clean_text(value)
    cleaned = re.sub(r"^(meet|by|from|with|our)\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" ,:-")


def _looks_like_person_name(value: str) -> bool:
    parts = value.split()
    lower_parts = [part.strip(" ,:-").lower() for part in parts]
    if value.strip().lower() in PERSON_NAME_BLOCKLIST or any(part in PERSON_NAME_BLOCKLIST for part in lower_parts):
        return False
    return 1 <= len(parts) <= 4 and all(part[:1].isalpha() for part in parts)


def _is_personal_email(email: str, company_domain: str = "") -> bool:
    local, _, domain = email.lower().partition("@")
    local_clean = re.sub(r"[^a-z0-9._+-]", "", local)
    domain = domain.removeprefix("www.")
    if not local_clean or local_clean in PERSONAL_EMAIL_BLOCKLIST:
        return False
    if any(local_clean.startswith(prefix + "+") or local_clean.startswith(prefix + ".") for prefix in PERSONAL_EMAIL_BLOCKLIST):
        return False
    if company_domain and domain and not (domain.endswith(company_domain) or company_domain.endswith(domain)):
        return False
    if re.search(r"\d{4,}", local_clean):
        return False
    return bool(re.search(r"[a-z]{2,}", local_clean))


def _best_email_for_name(first_name: str, full_name: str, emails: list[str]) -> str:
    compact_full = re.sub(r"[^a-z]", "", full_name.lower())
    first = first_name.lower()
    for email in emails:
        local = email.split("@", 1)[0].lower()
        compact_local = re.sub(r"[^a-z]", "", local)
        if compact_local == first or compact_local.startswith(first) or (compact_full and compact_local in compact_full):
            return email
    return ""


def _best_linkedin_for_name(first_name: str, full_name: str, profiles: list[str]) -> str:
    name_tokens = [token.lower() for token in re.findall(r"[A-Za-z]+", full_name)]
    first = first_name.lower()
    for profile in profiles:
        lower = profile.lower()
        if first and first in lower:
            return profile
        if name_tokens and all(token in lower for token in name_tokens[:2]):
            return profile
    return profiles[0] if len(profiles) == 1 else ""


def _first_name(value: str) -> str:
    parts = re.findall(r"[A-Za-z][A-Za-z'`-]*", value or "")
    return parts[0] if parts else ""


def _first_name_from_email_local(local: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z._-]", "", local or "")
    first_part = re.split(r"[._-]+", cleaned)[0]
    if len(first_part) < 2 or first_part.lower() in PERSONAL_EMAIL_BLOCKLIST:
        return ""
    return first_part[:1].upper() + first_part[1:].lower()


def _role_priority(role: str) -> int:
    lower = role.lower()
    if "founder" in lower:
        return 3
    if "ceo" in lower or "chief executive" in lower:
        return 2
    if "cto" in lower or "chief technology" in lower:
        return 1
    return 0


def _is_company_name_candidate(full_name: str, company_name: str) -> bool:
    person = re.sub(r"[^a-z0-9]+", "", (full_name or "").lower())
    company = re.sub(r"[^a-z0-9]+", "", (company_name or "").lower())
    if not person or not company:
        return False
    return person == company or person in company or company in person


def _markdown_links(text: str) -> list[tuple[str, str]]:
    return [
        (_clean_text(title), url.strip())
        for title, url in re.findall(r"\[([^\]]+)\]\((https?://[^)]+)\)", text or "")
    ]


def _linked_profile_name_from_title(title: str) -> str:
    name = re.split(r"\s[-|–—]\s", _clean_text(title or ""), maxsplit=1)[0].strip()
    if _looks_like_person_name(name):
        return name
    return ""


def _first_name_from_linkedin_profile(profile: str) -> str:
    path = urlparse(profile).path.lower()
    slug = path.split("/in/", 1)[-1].strip("/")
    slug = re.split(r"[/?#]", slug)[0]
    parts = [part for part in re.split(r"[-_]+", slug) if part and not part.isdigit()]
    if not parts:
        return ""
    first = parts[0]
    return first[:1].upper() + first[1:]


def _lead_key(lead: GeneratedLead) -> str:
    return (lead.app_store_url or lead.website or lead.organization_name).lower()


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
