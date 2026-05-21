from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config import CACHE_DIR, SCREENSHOT_DIR, Settings


MAX_RENDERED_TEXT_CHARS = 6500


@dataclass
class RenderedPage:
    url: str
    title: str
    text: str
    links: list[str] = field(default_factory=list)


@dataclass
class VisualReview:
    observations: list[str] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)
    confidence: str = ""
    confidence_score: int = 0
    confidence_reasons: list[str] = field(default_factory=list)
    screenshot_paths: list[str] = field(default_factory=list)


def _render_cache_path(url: str) -> Path:
    digest = hashlib.sha256(f"rendered:{url}".encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def _clean_text_and_links(html: str, base_url: str) -> tuple[str, str, list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href).split("#", 1)[0].rstrip("/")
        if absolute not in links:
            links.append(absolute)

    for element in soup(["script", "style", "noscript", "svg", "form", "header", "footer", "nav"]):
        element.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    return title, text[:MAX_RENDERED_TEXT_CHARS], links


class BrowserRenderer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright = None
        self.browser = None

    def __enter__(self) -> "BrowserRenderer":
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        launch_options: dict[str, object] = {"headless": True}
        if self.settings.browser_proxy_url:
            launch_options["proxy"] = {"server": self.settings.browser_proxy_url}
        self.browser = self._playwright.chromium.launch(**launch_options)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.browser:
            self.browser.close()
            self.browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def _new_page(self, width: int = 1440, height: int = 1200, is_mobile: bool = False):
        if not self.browser:
            raise RuntimeError("BrowserRenderer must be used as a context manager")
        context_options: dict[str, object] = {
            "viewport": {"width": width, "height": height},
            "is_mobile": is_mobile,
            "device_scale_factor": 2 if is_mobile else 1,
            "locale": self.settings.browser_locale,
            "timezone_id": self.settings.browser_timezone,
        }
        if self.settings.browser_user_agent:
            context_options["user_agent"] = self.settings.browser_user_agent
        context = self.browser.new_context(**context_options)
        page = context.new_page()
        return context, page

    def _retry_delay(self, attempt: int) -> float:
        return min(8.0, 0.75 * (2 ** max(0, attempt - 1)))

    def _goto_with_retry(self, page, url: str) -> None:
        last_error: Exception | None = None
        attempts = max(1, self.settings.browser_retry_attempts)
        for attempt in range(1, attempts + 1):
            try:
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.settings.request_timeout_seconds * 1000,
                )
                status = response.status if response else 0
                if status in {403, 408, 429, 500, 502, 503, 504}:
                    raise RuntimeError(f"HTTP {status}")
                return
            except Exception as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                delay = self._retry_delay(attempt)
                logging.info("Browser render retry %s/%s for %s after %s: waiting %.1fs", attempt + 1, attempts, url, exc, delay)
                time.sleep(delay)
        raise last_error or RuntimeError("Browser navigation failed")

    def fetch(self, url: str) -> RenderedPage | None:
        cached = _read_render_cache(url)
        if cached:
            return cached

        context = None
        try:
            context, page = self._new_page()
            self._goto_with_retry(page, url)
            page.wait_for_timeout(int(self.settings.browser_wait_seconds * 1000))
            final_url = page.url or url
            title, text, links = _clean_text_and_links(page.content(), final_url)
            page_result = RenderedPage(url=final_url, title=title, text=text, links=links)
            _write_render_cache(url, page_result)
            return page_result
        except Exception as exc:
            logging.warning("Browser render failed for %s: %s", url, exc)
            return None
        finally:
            if context:
                context.close()

    def visual_review(self, url: str, company_name: str = "") -> VisualReview:
        result = VisualReview()
        viewports = [
            ("desktop", 1440, 1200, False),
            ("mobile", 390, 844, True),
        ]
        context = None
        try:
            # Eerste viewport: nieuwe context aanmaken + navigeren
            label, width, height, is_mobile = viewports[0]
            context, page = self._new_page(width, height, is_mobile)
            self._goto_with_retry(page, url)
            page.wait_for_timeout(int(self.settings.browser_wait_seconds * 1000))

            # Beide viewports verwerken op dezelfde context (hergebruik!)
            for label, width, height, is_mobile in viewports:
                page.set_viewport_size({"width": width, "height": height})
                final_url = page.url or url
                screenshot_path = _screenshot_path(final_url, label, company_name)
                page.screenshot(path=str(screenshot_path), full_page=True)
                result.screenshot_paths.append(str(screenshot_path.resolve()))
                analysis = page.evaluate(_VISUAL_ANALYSIS_SCRIPT.replace("return ", "", 1))
                observations, flags, confidence_reasons, confidence_scores = _visual_observations(label, analysis or {})
                result.observations.extend(observations)
                result.quality_flags.extend(flags)
                result.confidence_reasons.extend(confidence_reasons)
                result.confidence_score = max([result.confidence_score] + confidence_scores)
        except Exception as exc:
            logging.warning("Visual review failed for %s: %s", url, exc)
            result.quality_flags.append("visual_review_failed")
            result.observations.append(f"visual review failed, manual check needed: {exc}")
            result.confidence_reasons.append("visual review failed, so confidence is low.")
        finally:
            if context:
                context.close()

        result.quality_flags = list(dict.fromkeys(result.quality_flags))
        result.observations = list(dict.fromkeys(result.observations))
        result.confidence_reasons = list(dict.fromkeys(result.confidence_reasons))
        result.confidence = _confidence_label(result.confidence_score, result.quality_flags)
        return result


def _read_render_cache(url: str) -> RenderedPage | None:
    cache_file = _render_cache_path(url)
    if not cache_file.exists():
        return None
    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        return RenderedPage(
            url=cached.get("url", url),
            title=cached.get("title", ""),
            text=cached.get("text", ""),
            links=[str(link) for link in cached.get("links", [])],
        )
    except (json.JSONDecodeError, OSError, TypeError):
        logging.warning("Ignoring unreadable browser render cache for %s", url)
        return None


def _write_render_cache(original_url: str, page: RenderedPage) -> None:
    cache_file = _render_cache_path(original_url)
    cache_file.write_text(
        json.dumps(
            {"url": page.url, "title": page.title, "text": page.text, "links": page.links},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def browser_rendering_enabled(settings: Settings) -> bool:
    return settings.browser_rendering not in {"0", "false", "no", "off", "disabled"}


def visual_review_enabled(settings: Settings) -> bool:
    return settings.visual_review not in {"0", "false", "no", "off", "disabled"}


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned[:60] or "company"


def _screenshot_path(url: str, viewport: str, company_name: str) -> Path:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(f"{url}:{viewport}".encode("utf-8")).hexdigest()[:10]
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return SCREENSHOT_DIR / f"{_slug(company_name)}_{viewport}_{stamp}_{digest}.png"


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _confidence_label(score: int, flags: list[str] | None = None) -> str:
    flags = flags or []
    if "visual_review_failed" in flags and score <= 0:
        return "failed"
    if score >= 80:
        return "high"
    if score >= 60:
        return "medium"
    if score > 0:
        return "low"
    return "none"


def _visual_observations(viewport: str, analysis: dict) -> tuple[list[str], list[str], list[str], list[int]]:
    observations: list[str] = []
    flags: list[str] = []
    confidence_reasons: list[str] = []
    confidence_scores: list[int] = []
    overflow_x = _safe_float(analysis.get("horizontalOverflowPx"))
    offscreen_elements = int(_safe_float(analysis.get("offscreenElementCount")))
    max_right_overflow = _safe_float(analysis.get("maxRightOverflowPx"))
    cta_count = int(_safe_float(analysis.get("ctaCount")))
    ctas_above_fold = int(_safe_float(analysis.get("ctaAboveFoldCount")))
    hidden_signup = int(_safe_float(analysis.get("hiddenSignupLoginCount")))
    small_tap_targets = int(_safe_float(analysis.get("smallTapTargetCount")))
    body_text_length = int(_safe_float(analysis.get("bodyTextLength")))
    primary = analysis.get("primaryCta") if isinstance(analysis.get("primaryCta"), dict) else {}
    primary_text = str(primary.get("text", "")).strip()
    contrast = _safe_float(primary.get("contrastRatio"))
    primary_top = _safe_float(primary.get("top"))
    background_reliable = bool(primary.get("backgroundReliable"))
    viewport_height = _safe_float(analysis.get("viewportHeight"), 0)

    if overflow_x > 32 and (offscreen_elements > 0 or max_right_overflow > 24):
        flags.append("visual_horizontal_overflow")
        score = 90 if offscreen_elements >= 2 or max_right_overflow > 64 else 82
        confidence_scores.append(score)
        confidence_reasons.append(
            f"{viewport}: high-confidence overflow signal ({int(overflow_x)}px document overflow, {offscreen_elements} visible offscreen elements)."
        )
        observations.append(
            f"{viewport}: page has {int(overflow_x)}px horizontal overflow with {offscreen_elements} visible offscreen element(s), which is a stronger broken-formatting signal than scroll width alone."
        )
    elif overflow_x > 32:
        confidence_reasons.append(
            f"{viewport}: ignored low-confidence overflow signal ({int(overflow_x)}px overflow but no clear visible offscreen element)."
        )

    if cta_count == 0 and body_text_length > 500:
        flags.append("visual_no_clear_cta")
        confidence_scores.append(62)
        confidence_reasons.append(
            f"{viewport}: medium-confidence CTA signal (no CTA-like button/link detected on a content-rich page)."
        )
        observations.append(f"{viewport}: no clear CTA button/link was detected on the rendered page.")
    elif cta_count == 0:
        confidence_reasons.append(
            f"{viewport}: ignored low-confidence CTA signal (no CTA detected, but the page has limited text/context)."
        )
    elif ctas_above_fold == 0 and primary_top > viewport_height * 1.05:
        flags.append("visual_no_cta_above_fold")
        confidence_scores.append(72)
        confidence_reasons.append(
            f"{viewport}: medium-confidence fold signal (CTA exists but starts below the first viewport)."
        )
        observations.append(
            f"{viewport}: no clear CTA appears above the fold, which could delay signup, booking, download, or activation."
        )
    if primary_text and background_reliable and 0 < contrast < 3:
        flags.append("visual_low_contrast_cta")
        score = 72 if contrast < 2.5 else 60
        confidence_scores.append(score)
        confidence_reasons.append(
            f"{viewport}: medium-confidence contrast signal (primary CTA '{primary_text}' measured at {contrast:.1f}:1 against a resolved background)."
        )
        observations.append(
            f"{viewport}: primary CTA '{primary_text}' appears low contrast at roughly {contrast:.1f}:1, which could hurt conversion."
        )
    elif primary_text and 0 < contrast < 3:
        confidence_reasons.append(
            f"{viewport}: ignored low-confidence contrast signal (CTA contrast looked low, but background could not be resolved reliably)."
        )
    if primary_text and primary_top > viewport_height * 1.05:
        flags.append("visual_primary_cta_below_fold")
        confidence_scores.append(72)
        confidence_reasons.append(
            f"{viewport}: medium-confidence CTA position signal (primary CTA starts below the first viewport)."
        )
        observations.append(
            f"{viewport}: primary CTA '{primary_text}' starts below the first viewport, which may delay conversion."
        )
    if hidden_signup:
        flags.append("visual_signup_login_below_fold")
        confidence_scores.append(68)
        confidence_reasons.append(
            f"{viewport}: medium-confidence signup visibility signal ({hidden_signup} signup/login CTA-like item(s) below the fold)."
        )
        observations.append(
            f"{viewport}: {hidden_signup} signup/login-related CTA or link appears below the fold, which could hurt signup completion."
        )
    if viewport == "mobile" and small_tap_targets >= 2:
        flags.append("visual_small_mobile_tap_targets")
        confidence_scores.append(48)
        confidence_reasons.append(
            f"{viewport}: low-confidence tap-target signal ({small_tap_targets} CTA-like elements below common mobile size guidance)."
        )
        observations.append(
            f"{viewport}: {small_tap_targets} CTA-like elements look smaller than common mobile tap-target guidance, which can add friction."
        )
    if ctas_above_fold > 6:
        flags.append("visual_too_many_ctas_above_fold")
        confidence_scores.append(62)
        confidence_reasons.append(
            f"{viewport}: medium-confidence clarity signal ({ctas_above_fold} CTA-like elements above the fold)."
        )
        observations.append(
            f"{viewport}: {ctas_above_fold} CTA-like elements appear above the fold, which may make the first action less obvious."
        )
    if not observations and primary_text:
        observations.append(
            f"{viewport}: primary CTA detected as '{primary_text}' with no obvious automated visual friction flags."
        )
    return observations, flags, confidence_reasons, confidence_scores


_VISUAL_ANALYSIS_SCRIPT = r"""
return (() => {
  const vw = window.innerWidth || document.documentElement.clientWidth;
  const vh = window.innerHeight || document.documentElement.clientHeight;
  const doc = document.documentElement;
  const ctaWords = /(start|get started|sign up|signup|join|try|book|schedule|download|install|subscribe|buy|pricing|contact|demo|quiz|free trial|continue|next|login|log in|create account)/i;
  const rgba = (value) => {
    const match = String(value || '').match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([0-9.]+))?/i);
    if (!match) return null;
    return [Number(match[1]), Number(match[2]), Number(match[3]), match[4] === undefined ? 1 : Number(match[4])];
  };
  const lum = (rgbValue) => {
    if (!rgbValue) return null;
    const vals = rgbValue.map((v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * vals[0] + 0.7152 * vals[1] + 0.0722 * vals[2];
  };
  const contrast = (fg, bg) => {
    const a = lum(rgba(fg));
    const b = lum(rgba(bg));
    if (a === null || b === null) return 0;
    const hi = Math.max(a, b);
    const lo = Math.min(a, b);
    return (hi + 0.05) / (lo + 0.05);
  };
  const nearestBackground = (el) => {
    let node = el;
    while (node && node !== document.documentElement) {
      const bg = window.getComputedStyle(node).backgroundColor;
      const parsed = rgba(bg);
      if (parsed && parsed[3] > 0.05) return { color: bg, reliable: true };
      node = node.parentElement;
    }
    return { color: 'rgb(255,255,255)', reliable: false };
  };
  const visibleElementRects = Array.from(document.body.querySelectorAll('*'))
    .map((el) => {
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      const visible = rect.width > 24 && rect.height > 12 && style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity || 1) > 0 && rect.bottom > -20 && rect.top < vh * 1.6;
      return { rect, style, visible };
    })
    .filter((item) => item.visible && item.style.position !== 'fixed');
  const offscreenElements = visibleElementRects.filter((item) => item.rect.right > vw + 16 || item.rect.left < -16);
  const maxRightOverflowPx = offscreenElements.reduce((max, item) => Math.max(max, item.rect.right - vw), 0);
  const candidates = Array.from(document.querySelectorAll('a, button, [role="button"], input[type="button"], input[type="submit"]'))
    .map((el) => {
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      const bg = nearestBackground(el);
      const text = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim().replace(/\s+/g, ' ');
      const visible = rect.width > 4 && rect.height > 4 && style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity || 1) > 0;
      const isCta = visible && ctaWords.test(text);
      return {
        text,
        top: rect.top,
        left: rect.left,
        width: rect.width,
        height: rect.height,
        visible,
        isCta,
        aboveFold: visible && rect.top >= -8 && rect.top < vh,
        contrastRatio: contrast(style.color, bg.color),
        backgroundReliable: bg.reliable,
      };
    })
    .filter((item) => item.visible && item.text);
  const ctas = candidates.filter((item) => item.isCta);
  const ctasAboveFold = ctas.filter((item) => item.aboveFold);
  const primaryCta = (ctasAboveFold[0] || ctas[0] || null);
  return {
    viewportWidth: vw,
    viewportHeight: vh,
    bodyTextLength: (document.body.innerText || '').trim().length,
    horizontalOverflowPx: Math.max(0, (doc.scrollWidth || 0) - vw),
    offscreenElementCount: offscreenElements.length,
    maxRightOverflowPx,
    ctaCount: ctas.length,
    ctaAboveFoldCount: ctasAboveFold.length,
    hiddenSignupLoginCount: ctas.filter((item) => /(sign up|signup|login|log in|create account)/i.test(item.text) && item.top > vh * 1.05).length,
    smallTapTargetCount: ctas.filter((item) => item.width < 44 || item.height < 36).length,
    primaryCta,
    topCtas: ctas.slice(0, 8),
  };
})();
"""