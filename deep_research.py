from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from threading import local
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from cache import cache_path, read_cached_json, write_cached_json
from config import CACHE_DIR, Settings
from models import DeepResearchResult, LeadInput


APP_STORE_DOMAINS = ("apps.apple.com", "play.google.com")
MAX_APP_STORE_TEXT_CHARS = 2200
MAX_REVIEW_COMPLAINTS = 4
COMPLAINT_TERMS = {
    "crash",
    "bug",
    "broken",
    "can't",
    "cannot",
    "login",
    "sign in",
    "signup",
    "subscription",
    "paywall",
    "payment",
    "slow",
    "stuck",
    "confusing",
    "doesn't work",
    "not working",
    "access code",
    "permission",
}

REVIEW_THEME_TERMS = {
    "pricing/paywall friction": {
        "paywall",
        "price",
        "pricing",
        "subscription",
        "trial",
        "payment",
        "charged",
        "refund",
        "expensive",
    },
    "login/signup/access friction": {
        "login",
        "log in",
        "sign in",
        "signup",
        "sign up",
        "account",
        "access code",
        "password",
        "verify",
    },
    "bugs/crashes/stability": {
        "crash",
        "bug",
        "broken",
        "doesn't work",
        "not working",
        "stuck",
        "freeze",
        "frozen",
        "error",
    },
    "onboarding/confusion": {
        "confusing",
        "unclear",
        "hard to use",
        "complicated",
        "onboarding",
        "tutorial",
        "where to start",
    },
    "notifications/retention friction": {
        "notification",
        "notifications",
        "reminder",
        "too many",
        "spam",
        "daily",
        "streak",
    },
    "support/trust friction": {
        "support",
        "customer service",
        "help",
        "response",
        "trust",
        "privacy",
        "data",
    },
}

# Thread-local session voor connection pooling
_local = local()


def _get_session() -> requests.Session:
    """Retourneert een per-thread requests.Session met connection pooling."""
    if not hasattr(_local, "session") or _local.session is None:
        _local.session = requests.Session()
    return _local.session


def _clear_session() -> None:
    """Sluit en verwijderd de thread-local session."""
    if hasattr(_local, "session") and _local.session is not None:
        _local.session.close()
        _local.session = None


def _app_store_rank(url: str) -> tuple[int, str]:
    normalized = str(url or "").lower()
    if "apps.apple.com" in normalized:
        return (0, normalized)
    if "play.google.com" in normalized:
        return (1, normalized)
    return (9, normalized)


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (compatible; EmailPersonalizationResearchBot/1.0; +local-review-tool)",
        "Accept-Language": f"{settings.browser_locale},en;q=0.8",
    }


def _clean_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    for element in soup(["script", "style", "noscript", "svg", "form", "header", "footer", "nav"]):
        element.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    return title, text


def _fetch_public_text(url: str, settings: Settings) -> tuple[str, str] | None:
    """Haalt publieke tekst op, met gedeelde cache (web + deep namespace) en TTL."""
    # Probeer eerst web-research cache (zonder prefix)
    cf_web = cache_path(url, prefix="")
    cached = read_cached_json(cf_web)
    if cached:
        return cached.get("title", ""), cached.get("text", "")

    # Probeer deep-research cache
    cf_deep = cache_path(url, prefix="deep:")
    cached = read_cached_json(cf_deep)
    if cached:
        return cached.get("title", ""), cached.get("text", "")[:MAX_APP_STORE_TEXT_CHARS]

    # Fallback: HTTP-fetch via gedeelde session
    session = _get_session()
    try:
        response = session.get(
            url,
            headers=_headers(settings),
            timeout=settings.request_timeout_seconds,
        )
        if response.status_code >= 400:
            return None
        title, text = _clean_text(response.text)
        text = text[:MAX_APP_STORE_TEXT_CHARS]
        # Schrijf naar deep-namespace cache met TTL
        write_cached_json(
            cf_deep,
            {"title": title, "text": text},
        )
        return title, text
    except requests.RequestException as exc:
        logging.info("Deep research fetch failed for %s: %s", url, exc)
        return None


def _discover_app_store_links(lead: LeadInput, settings: Settings) -> list[str]:
    links: list[str] = []
    if lead.app_store_url:
        links.append(lead.app_store_url)

    session = _get_session()
    try:
        response = session.get(
            lead.website_url,
            headers=_headers(settings),
            timeout=settings.request_timeout_seconds,
        )
        if response.status_code >= 400:
            return links
        soup = BeautifulSoup(response.text, "html.parser")
        for anchor in soup.find_all("a", href=True):
            absolute = urljoin(lead.website_url, str(anchor["href"]).strip())
            if any(domain in absolute for domain in APP_STORE_DOMAINS) and absolute not in links:
                links.append(absolute)
    except requests.RequestException:
        return links
    return sorted(dict.fromkeys(links), key=_app_store_rank)[:3]


def _apple_app_id(url: str) -> str:
    match = re.search(r"/id([0-9]+)", url)
    return match.group(1) if match else ""


def _fetch_apple_review_complaints(app_store_url: str, settings: Settings) -> list[str]:
    app_id = _apple_app_id(app_store_url)
    if not app_id:
        return []
    parsed = urlparse(app_store_url)
    country_match = re.search(r"apps\.apple\.com/([a-z]{2})/", parsed.netloc + parsed.path)
    configured_country = str(getattr(settings, "app_store_country", "") or "").strip().lower()
    country = configured_country if configured_country and configured_country != "auto" else (country_match.group(1) if country_match else "us")
    rss_url = f"https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortBy=mostRecent/json"
    session = _get_session()
    try:
        response = session.get(
            rss_url,
            headers=_headers(settings),
            timeout=settings.request_timeout_seconds,
        )
        if response.status_code >= 400:
            return []
        data = response.json()
    except (requests.RequestException, ValueError):
        return []
    entries = data.get("feed", {}).get("entry", [])
    if isinstance(entries, dict):
        entries = [entries]
    complaints: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or "im:name" in entry:
            continue
        title = entry.get("title", {}).get("label", "")
        content = entry.get("content", {}).get("label", "")
        rating = entry.get("im:rating", {}).get("label", "")
        text = f"{title}: {content}".strip(": ")
        lower = text.lower()
        if text and (rating in {"1", "2", "3"} or any(term in lower for term in COMPLAINT_TERMS)):
            complaints.append(f"Apple review ({rating or 'unknown'} stars): {text[:260]}")
        if len(complaints) >= MAX_REVIEW_COMPLAINTS:
            break
    return complaints


def _cluster_review_themes(complaints: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    examples: dict[str, str] = {}
    for complaint in complaints:
        lower = complaint.lower()
        for theme, terms in REVIEW_THEME_TERMS.items():
            if any(term in lower for term in terms):
                counts[theme] = counts.get(theme, 0) + 1
                examples.setdefault(theme, complaint[:180])
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        f"{theme}: {count} public review signal(s), e.g. {examples[theme]}"
        for theme, count in ranked[:4]
    ]


def _build_friction_checklist(lead: LeadInput, app_store_summary: str) -> list[str]:
    combined = " ".join(
        [
            lead.optional_notes,
            lead.linkedin_observation,
            lead.app_flow_observation,
            lead.recent_news_note,
            lead.competitor_context,
            app_store_summary,
        ]
    ).lower()
    checks: list[str] = []
    patterns = {
        "manual LinkedIn observation provided": lead.linkedin_observation,
        "manual app/onboarding observation provided": lead.app_flow_observation,
        "screenshot reference provided": lead.screenshot_url,
        "public app-store evidence found": app_store_summary,
        "recent news/product note provided": lead.recent_news_note or lead.recent_news_url,
        "signup/onboarding angle available": "signup|onboard|quiz|account|register|start",
        "paywall/pricing angle available": "paywall|price|pricing|subscription|trial|checkout|cart",
        "booking/scheduling angle available": "book|booking|schedule|slot|appointment",
        "retention/habit loop angle available": "habit|streak|daily|return|retention|reward",
        "proof/trust angle available": "review|rating|testimonial|case study|trusted|clinical|validated",
    }
    for label, signal in patterns.items():
        if not signal:
            continue
        if isinstance(signal, str) and "|" in signal:
            if re.search(signal, combined):
                checks.append(label)
        elif str(signal).strip():
            checks.append(label)
    if not checks:
        checks.append("no deep-personalization evidence supplied beyond website crawl")
    return checks


def collect_deep_research(lead: LeadInput, settings: Settings) -> DeepResearchResult:
    result = DeepResearchResult(
        app_store_url=lead.app_store_url,
        linkedin_observation=lead.linkedin_observation,
        linkedin_source_note=lead.linkedin_source_note,
        app_flow_observation=lead.app_flow_observation,
        app_flow_source_note=lead.app_flow_source_note,
        screenshot_url=lead.screenshot_url,
        recent_news_url=lead.recent_news_url,
        recent_news_note=lead.recent_news_note,
        competitor_context=lead.competitor_context,
    )

    app_links = _discover_app_store_links(lead, settings)
    if app_links:
        result.app_store_url = app_links[0]
    app_summaries: list[str] = []
    for url in app_links:
        fetched = _fetch_public_text(url, settings)
        if not fetched:
            result.reviewer_notes.append(f"Could not fetch public app-store page: {url}")
            continue
        title, text = fetched
        result.source_urls.append(url)
        if not result.app_store_url:
            result.app_store_url = url
        app_summaries.append(f"Source: {url}\nTitle: {title}\nText: {text[:1000]}")
        if "apps.apple.com" in url:
            complaints = _fetch_apple_review_complaints(url, settings)
            if complaints:
                result.review_complaints.extend(complaints)
                result.source_urls.append(f"Apple public customer reviews for {settings.app_store_country.upper()} region: {url}")

    result.app_store_summary = "\n\n".join(app_summaries)
    if result.review_complaints:
        result.app_review_themes = _cluster_review_themes(result.review_complaints)
        result.app_store_summary = (
            result.app_store_summary
            + "\n\nPublic review complaint signals:\n"
            + "\n".join(f"- {complaint}" for complaint in result.review_complaints)
        ).strip()
        if result.app_review_themes:
            result.app_store_summary = (
                result.app_store_summary
                + "\n\nPublic review theme clusters:\n"
                + "\n".join(f"- {theme}" for theme in result.app_review_themes)
            ).strip()
    result.friction_checklist = _build_friction_checklist(lead, result.app_store_summary)

    _clear_session()
    return result