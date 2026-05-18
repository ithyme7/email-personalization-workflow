from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from advanced_detectors import run_advanced_detectors
from browser_research import BrowserRenderer, RenderedPage, browser_rendering_enabled, visual_review_enabled
from config import CACHE_DIR, Settings
from models import LeadInput, PageText, ResearchResult


PRIORITY_PATH_TERMS = [
    "about",
    "service",
    "solution",
    "case",
    "customer",
    "testimonial",
    "pricing",
    "blog",
    "news",
    "career",
    "industry",
]

MIN_USEFUL_TEXT_CHARS = 500
MAX_PAGE_TEXT_CHARS = 5500


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "User-Agent": settings.browser_user_agent
        or "Mozilla/5.0 (compatible; EmailPersonalizationResearchBot/1.0; +local-review-tool)",
        "Accept-Language": f"{settings.browser_locale},en;q=0.8",
    }


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def _same_domain(base_url: str, candidate_url: str) -> bool:
    base_domain = urlparse(base_url).netloc.lower().removeprefix("www.")
    candidate_domain = urlparse(candidate_url).netloc.lower().removeprefix("www.")
    return base_domain == candidate_domain


def _clean_text(soup: BeautifulSoup) -> str:
    for element in soup(["script", "style", "noscript", "svg", "form", "header", "footer", "nav"]):
        element.decompose()
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _fetch_page(url: str, settings: Settings) -> PageText | None:
    cache_file = _cache_path(url)
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            return PageText(url=cached["url"], title=cached.get("title", ""), text=cached.get("text", ""))
        except (json.JSONDecodeError, KeyError, OSError):
            logging.warning("Ignoring unreadable cache file for %s", url)

    headers = _headers(settings)
    for attempt in range(2):
        try:
            response = requests.get(url, headers=headers, timeout=settings.request_timeout_seconds)
            if response.status_code >= 400:
                logging.warning("Fetch failed for %s with HTTP %s", url, response.status_code)
                return None
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                return None
            soup = BeautifulSoup(response.text, "html.parser")
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            text = _clean_text(soup)
            page = PageText(url=url, title=title, text=text[:MAX_PAGE_TEXT_CHARS])
            cache_file.write_text(
                json.dumps({"url": page.url, "title": page.title, "text": page.text}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            time.sleep(settings.request_delay_seconds)
            return page
        except requests.RequestException as exc:
            logging.warning("Fetch attempt %s failed for %s: %s", attempt + 1, url, exc)
            time.sleep(0.5)
    return None


def _page_from_rendered(page: RenderedPage) -> PageText:
    return PageText(url=page.url, title=page.title, text=page.text[:MAX_PAGE_TEXT_CHARS])


def _fetch_rendered_page(url: str, renderer: BrowserRenderer | None) -> PageText | None:
    if not renderer:
        return None
    rendered = renderer.fetch(url)
    if not rendered:
        return None
    return _page_from_rendered(rendered)


def _prioritize_links(homepage_url: str, links: list[str]) -> list[str]:
    candidates: list[tuple[int, str]] = []
    for absolute in links:
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or not _same_domain(homepage_url, absolute):
            continue
        normalized = parsed._replace(fragment="", query="").geturl().rstrip("/")
        haystack = parsed.path.lower()
        matches = [term for term in PRIORITY_PATH_TERMS if term in haystack]
        if matches:
            candidates.append((len(matches), normalized))

    unique: list[str] = []
    for _, url in sorted(candidates, reverse=True):
        if url not in unique and url != homepage_url:
            unique.append(url)
    return unique


def _discover_priority_links(homepage_url: str, settings: Settings, rendered_links: list[str] | None = None) -> list[str]:
    if rendered_links:
        return _prioritize_links(homepage_url, rendered_links)[: settings.max_pages_per_company - 1]

    try:
        response = requests.get(
            homepage_url,
            headers=_headers(settings),
            timeout=settings.request_timeout_seconds,
        )
        soup = BeautifulSoup(response.text, "html.parser")
    except requests.RequestException:
        return []

    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(homepage_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or not _same_domain(homepage_url, absolute):
            continue
        normalized = parsed._replace(fragment="", query="").geturl().rstrip("/")
        label = anchor.get_text(" ", strip=True)
        links.append(f"{normalized} {label}")

    candidates: list[tuple[int, str]] = []
    for item in links:
        url, _, label = item.partition(" ")
        parsed = urlparse(url)
        haystack = f"{parsed.path} {label}".lower()
        matches = [term for term in PRIORITY_PATH_TERMS if term in haystack]
        if matches:
            candidates.append((len(matches), url))

    unique: list[str] = []
    for _, url in sorted(candidates, reverse=True):
        if url not in unique and url != homepage_url:
            unique.append(url)
        if len(unique) >= settings.max_pages_per_company - 1:
            break
    return unique


def research_company(lead: LeadInput, settings: Settings) -> ResearchResult:
    if not lead.is_valid:
        return ResearchResult(
            needs_manual_review=True,
            reviewer_notes=lead.validation_errors.copy(),
        )

    result = ResearchResult()
    homepage = _fetch_page(lead.website_url, settings)
    rendered_homepage_links: list[str] = []
    renderer: BrowserRenderer | None = None

    def get_renderer() -> BrowserRenderer | None:
        nonlocal renderer
        if renderer:
            return renderer
        if not browser_rendering_enabled(settings):
            return None
        try:
            renderer = BrowserRenderer(settings).__enter__()
            return renderer
        except Exception as exc:
            logging.warning("Browser-rendered fallback unavailable: %s", exc)
            result.reviewer_notes.append(f"Browser-rendered fallback unavailable: {exc}")
            return None

    browser_forced = settings.browser_rendering == "always"
    should_render_homepage = browser_forced or homepage is None or len(homepage.text) < MIN_USEFUL_TEXT_CHARS
    if should_render_homepage and browser_rendering_enabled(settings):
        active_renderer = get_renderer()
        if active_renderer:
            rendered_homepage = active_renderer.fetch(lead.website_url)
            if rendered_homepage:
                rendered_homepage_links = rendered_homepage.links
                rendered_page = _page_from_rendered(rendered_homepage)
                if homepage is None or len(rendered_page.text) > len(homepage.text):
                    homepage = rendered_page
                    result.reviewer_notes.append("Browser-rendered fallback used for homepage")

    if not homepage:
        result.needs_manual_review = True
        result.reviewer_notes.append("Website could not be accessed or did not return readable HTML")
        if renderer:
            renderer.__exit__(None, None, None)
        return result

    try:
        result.pages.append(homepage)
        for link in _discover_priority_links(lead.website_url, settings, rendered_homepage_links):
            if len(result.pages) >= settings.max_pages_per_company:
                break
            page = _fetch_page(link, settings)
            if browser_rendering_enabled(settings) and (
                browser_forced or page is None or len(page.text) < 180
            ):
                rendered_page = _fetch_rendered_page(link, get_renderer())
                if rendered_page and (page is None or len(rendered_page.text) > len(page.text)):
                    page = rendered_page
                    result.reviewer_notes.append(f"Browser-rendered fallback used for {link}")
            if page and len(page.text) > 120:
                result.pages.append(page)

        if visual_review_enabled(settings):
            active_renderer = get_renderer()
            visual = active_renderer.visual_review(lead.website_url, lead.company_name) if active_renderer else None
            if visual:
                result.visual_observations = visual.observations
                result.visual_quality_flags = visual.quality_flags
                result.visual_confidence = visual.confidence
                result.visual_confidence_score = visual.confidence_score
                result.visual_confidence_reasons = visual.confidence_reasons
                result.screenshot_paths = visual.screenshot_paths
                if visual.quality_flags:
                    result.reviewer_notes.append(
                        "Automated visual review found possible website/app-page friction: "
                        + ", ".join(visual.quality_flags)
                        + f" | confidence: {visual.confidence} ({visual.confidence_score}/100)"
                    )
        if renderer:
            renderer.__exit__(None, None, None)
            renderer = None
        advanced = run_advanced_detectors(lead.website_url, lead.company_name, settings)
        if advanced.findings or advanced.flags or advanced.screenshot_paths or advanced.reviewer_notes:
            result.advanced_detector_flags = advanced.flags
            result.ux_validator_findings = advanced.findings
            result.dead_link_checks = advanced.dead_link_checks
            result.trace_files = advanced.trace_files
            result.screenshot_paths = list(dict.fromkeys(result.screenshot_paths + advanced.screenshot_paths))
            result.reviewer_notes.extend(advanced.reviewer_notes)
            if advanced.flags:
                result.reviewer_notes.append(
                    "Advanced detector found internal UX validation signals: " + ", ".join(advanced.flags[:8])
                )
            elif advanced.screenshot_paths:
                result.reviewer_notes.append("Advanced detector completed with no high-confidence UX flags.")
    finally:
        if renderer:
            renderer.__exit__(None, None, None)

    result.source_urls = [page.url for page in result.pages]
    combined = " ".join(page.text for page in result.pages)
    if len(combined) < MIN_USEFUL_TEXT_CHARS:
        result.needs_manual_review = True
        result.reviewer_notes.append("Website has very little extractable public text")

    page_summaries = []
    for page in result.pages:
        label = page.title or page.url
        excerpt = page.text[:700]
        page_summaries.append(f"Source: {page.url}\nTitle: {label}\nText: {excerpt}")
    if result.visual_observations:
        page_summaries.append(
            "Visual review evidence:\n"
            + "\n".join(f"- {observation}" for observation in result.visual_observations)
            + "\nVisual confidence: "
            + f"{result.visual_confidence or 'none'} ({result.visual_confidence_score}/100)"
            + "\nVisual confidence reasons:\n"
            + "\n".join(f"- {reason}" for reason in result.visual_confidence_reasons)
            + "\nScreenshot paths:\n"
            + "\n".join(result.screenshot_paths)
        )
    if result.ux_validator_findings or result.dead_link_checks:
        page_summaries.append(
            "Internal UX validator evidence. Use these as detection criteria, not as technical wording in copy:\n"
            + "\n".join(f"- {finding}" for finding in result.ux_validator_findings[:10])
            + ("\nDead link checks:\n" + "\n".join(f"- {item}" for item in result.dead_link_checks[:10]) if result.dead_link_checks else "")
            + ("\nTrace files:\n" + "\n".join(result.trace_files[:4]) if result.trace_files else "")
        )
    result.summary = "\n\n".join(page_summaries)
    return result
