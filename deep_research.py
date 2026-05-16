from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import CACHE_DIR, Settings
from models import DeepResearchResult, LeadInput


APP_STORE_DOMAINS = ("apps.apple.com", "play.google.com")
MAX_APP_STORE_TEXT_CHARS = 2200


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(f"deep:{url}".encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def _clean_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    for element in soup(["script", "style", "noscript", "svg", "form", "header", "footer", "nav"]):
        element.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    return title, text


def _fetch_public_text(url: str, settings: Settings) -> tuple[str, str] | None:
    cache_file = _cache_path(url)
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            return cached.get("title", ""), cached.get("text", "")
        except (json.JSONDecodeError, OSError):
            logging.warning("Ignoring unreadable deep research cache for %s", url)

    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; EmailPersonalizationResearchBot/1.0; +local-review-tool)"},
            timeout=settings.request_timeout_seconds,
        )
        if response.status_code >= 400:
            return None
        title, text = _clean_text(response.text)
        text = text[:MAX_APP_STORE_TEXT_CHARS]
        cache_file.write_text(json.dumps({"title": title, "text": text}, ensure_ascii=False, indent=2), encoding="utf-8")
        return title, text
    except requests.RequestException as exc:
        logging.info("Deep research fetch failed for %s: %s", url, exc)
        return None


def _discover_app_store_links(lead: LeadInput, settings: Settings) -> list[str]:
    links: list[str] = []
    if lead.app_store_url:
        links.append(lead.app_store_url)

    try:
        response = requests.get(
            lead.website_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; EmailPersonalizationResearchBot/1.0; +local-review-tool)"},
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
    return links[:2]


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

    result.app_store_summary = "\n\n".join(app_summaries)
    result.friction_checklist = _build_friction_checklist(lead, result.app_store_summary)

    return result
