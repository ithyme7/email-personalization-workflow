from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

import requests

from config import DATA_DIR, RESOURCE_DIR, SCREENSHOT_DIR, Settings


TRACE_DIR = DATA_DIR / "traces"
LIGHTHOUSE_DIR = DATA_DIR / "lighthouse"
AXE_CORE_PATH = RESOURCE_DIR / "vendor" / "axe.min.js"


@dataclass
class AdvancedDetectorResult:
    flags: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    dead_link_checks: list[str] = field(default_factory=list)
    screenshot_paths: list[str] = field(default_factory=list)
    trace_files: list[str] = field(default_factory=list)
    reviewer_notes: list[str] = field(default_factory=list)


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned[:60] or "company"


def _asset_path(folder: Path, url: str, label: str, suffix: str, company_name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(f"{url}:{label}".encode("utf-8")).hexdigest()[:10]
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return folder / f"{_slug(company_name)}_{label}_{stamp}_{digest}.{suffix}"


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys([value for value in values if str(value).strip()]))


def run_advanced_detectors(url: str, company_name: str, settings: Settings) -> AdvancedDetectorResult:
    result = AdvancedDetectorResult()
    if settings.advanced_detectors in {"0", "false", "no", "off", "disabled"}:
        return result

    playwright_result = _run_playwright_checks(url, company_name, settings)
    result.flags.extend(playwright_result.flags)
    result.findings.extend(playwright_result.findings)
    result.dead_link_checks.extend(playwright_result.dead_link_checks)
    result.screenshot_paths.extend(playwright_result.screenshot_paths)
    result.trace_files.extend(playwright_result.trace_files)
    result.reviewer_notes.extend(playwright_result.reviewer_notes)

    if settings.lighthouse_review not in {"0", "false", "no", "off", "disabled"}:
        lighthouse_result = _run_lighthouse_checks(url, company_name, settings)
        result.flags.extend(lighthouse_result.flags)
        result.findings.extend(lighthouse_result.findings)
        result.reviewer_notes.extend(lighthouse_result.reviewer_notes)

    result.flags = _dedupe(result.flags)
    result.findings = _dedupe(result.findings)
    result.dead_link_checks = _dedupe(result.dead_link_checks)
    result.screenshot_paths = _dedupe(result.screenshot_paths)
    result.trace_files = _dedupe(result.trace_files)
    result.reviewer_notes = _dedupe(result.reviewer_notes)
    return result


def _run_playwright_checks(url: str, company_name: str, settings: Settings) -> AdvancedDetectorResult:
    result = AdvancedDetectorResult()
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        result.reviewer_notes.append("Playwright is not installed, advanced browser detectors skipped.")
        return result

    viewports = [
        ("desktop_full", {"width": 1440, "height": 1200, "is_mobile": False}),
        ("mobile_full", {"width": 390, "height": 844, "is_mobile": True}),
    ]
    trace_mode = os.getenv("PLAYWRIGHT_TRACES", "flagged").strip().lower()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for label, viewport in viewports:
                context = browser.new_context(
                    viewport={"width": viewport["width"], "height": viewport["height"]},
                    is_mobile=bool(viewport["is_mobile"]),
                    device_scale_factor=2 if viewport["is_mobile"] else 1,
                )
                trace_path = _asset_path(TRACE_DIR, url, label, "zip", company_name)
                collect_trace = trace_mode not in {"0", "false", "no", "off", "disabled", "none"}
                if collect_trace:
                    context.tracing.start(screenshots=True, snapshots=True, sources=True)
                page = context.new_page()
                failed_responses: list[str] = []
                flag_count_before = len(result.flags)
                had_playwright_error = False
                page.on(
                    "response",
                    lambda response: failed_responses.append(f"{response.status} {response.url}")
                    if response.status >= 400
                    else None,
                )
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=settings.request_timeout_seconds * 1000)
                    page.wait_for_timeout(int(settings.browser_wait_seconds * 1000))
                    screenshot_path = _asset_path(SCREENSHOT_DIR, url, label, "png", company_name)
                    page.screenshot(path=str(screenshot_path), full_page=True)
                    result.screenshot_paths.append(str(screenshot_path.resolve()))
                    result.findings.extend(_playwright_page_findings(page, label))
                    axe_flags, axe_findings = _run_axe_core_checks(page, label)
                    result.flags.extend(axe_flags)
                    result.findings.extend(axe_findings)
                    result.dead_link_checks.extend(_check_visible_links(page, url))
                    if failed_responses:
                        result.flags.append("playwright_failed_network_responses")
                        result.findings.append(f"{label}: {len(failed_responses[:8])} failed network response(s) detected.")
                        result.dead_link_checks.extend(failed_responses[:8])
                except (PlaywrightTimeoutError, PlaywrightError) as exc:
                    had_playwright_error = True
                    result.flags.append("playwright_check_failed")
                    result.reviewer_notes.append(f"Playwright check failed for {label}: {exc}")
                finally:
                    if collect_trace:
                        context.tracing.stop(path=str(trace_path))
                        new_flagged_evidence = (
                            had_playwright_error
                            or bool(failed_responses)
                            or len(result.flags) > flag_count_before
                        )
                        keep_trace = trace_mode in {"1", "true", "yes", "on", "always"} or new_flagged_evidence
                        if keep_trace:
                            result.trace_files.append(str(trace_path.resolve()))
                        else:
                            trace_path.unlink(missing_ok=True)
                    context.close()
            browser.close()
    except Exception as exc:
        result.flags.append("playwright_unavailable")
        result.reviewer_notes.append(f"Playwright unavailable or browser not installed: {exc}")
    return result


def _run_axe_core_checks(page, label: str) -> tuple[list[str], list[str]]:
    flags: list[str] = []
    findings: list[str] = []
    try:
        if AXE_CORE_PATH.exists():
            page.add_script_tag(path=str(AXE_CORE_PATH))
        else:
            page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.3/axe.min.js")
        results = page.evaluate(
            r"""
async () => {
  if (!window.axe) return {violations: []};
  return await window.axe.run(document, { runOnly: ['wcag2a', 'wcag2aa'] });
}
"""
        )
    except Exception as exc:
        return ["axe_core_unavailable"], [f"{label}: axe-core check skipped or blocked: {str(exc)[:140]}"]

    violations = results.get("violations", []) if isinstance(results, dict) else []
    high_value_ids = {"color-contrast", "target-size", "button-name", "link-name", "label", "aria-hidden-focus"}
    for violation in violations[:8]:
        if not isinstance(violation, dict):
            continue
        impact = str(violation.get("impact", "") or "unknown")
        rule_id = str(violation.get("id", "") or "axe")
        node_count = len(violation.get("nodes", []) or [])
        help_text = str(violation.get("help", "") or rule_id)
        if impact in {"critical", "serious"} or rule_id in high_value_ids:
            flags.append(f"axe_{rule_id}")
            findings.append(f"{label}: axe-core {impact} issue, {help_text} ({node_count} node(s)).")
    return flags, findings


def _playwright_page_findings(page, label: str) -> list[str]:
    script = r"""
() => {
  const vh = window.innerHeight;
  const vw = window.innerWidth;
  const words = /(start|get started|sign up|signup|join|try|book|schedule|download|install|subscribe|buy|pricing|contact|demo|quiz|free trial|continue|next|login|log in|create account)/i;
  const buttons = Array.from(document.querySelectorAll('a, button, [role="button"], input[type="button"], input[type="submit"]'))
    .map((el) => {
      const rect = el.getBoundingClientRect();
      const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
      const style = window.getComputedStyle(el);
      return {text, top: rect.top, width: rect.width, height: rect.height, visible: rect.width > 4 && rect.height > 4 && style.display !== 'none' && style.visibility !== 'hidden'};
    })
    .filter((item) => item.visible && words.test(item.text));
  const above = buttons.filter((item) => item.top >= -8 && item.top < vh);
  return {
    ctaCount: buttons.length,
    ctaAboveFold: above.length,
    firstCta: buttons[0] || null,
    horizontalOverflow: Math.max(0, document.documentElement.scrollWidth - vw),
    pageText: (document.body.innerText || '').trim().length,
  };
}
"""
    data = page.evaluate(script)
    findings: list[str] = []
    if data.get("horizontalOverflow", 0) > 32:
        findings.append(f"{label}: page has visible horizontal overflow, possible broken formatting on this viewport.")
    if data.get("ctaCount", 0) > 0 and data.get("ctaAboveFold", 0) == 0:
        findings.append(f"{label}: CTA exists but no CTA appears above the fold, possible conversion friction.")
    if data.get("ctaCount", 0) == 0 and data.get("pageText", 0) > 500:
        findings.append(f"{label}: content-rich page with no CTA-like action detected.")
    first_cta = data.get("firstCta") or {}
    if first_cta and (first_cta.get("width", 0) < 44 or first_cta.get("height", 0) < 36):
        findings.append(f"{label}: first CTA-like element looks small for touch interaction, use as manual-review signal.")
    return findings


def _check_visible_links(page, base_url: str, max_links: int = 10) -> list[str]:
    links = page.evaluate(
        r"""
() => Array.from(document.querySelectorAll('a[href]'))
  .map((a) => ({href: a.href, text: (a.innerText || a.getAttribute('aria-label') || '').trim()}))
  .filter((item) => item.href && !item.href.startsWith('mailto:') && !item.href.startsWith('tel:') && item.text.length)
  .slice(0, 20)
"""
    )
    results: list[str] = []
    for item in links[:max_links]:
        href = urljoin(base_url, item.get("href", ""))
        try:
            response = requests.head(href, allow_redirects=True, timeout=6)
            if response.status_code in {405, 403}:
                response = requests.get(href, allow_redirects=True, timeout=6, stream=True)
            if response.status_code >= 400:
                results.append(f"dead_link_candidate: {response.status_code} {href} ({item.get('text', '')[:80]})")
        except requests.RequestException:
            results.append(f"dead_link_check_failed: {href} ({item.get('text', '')[:80]})")
    return results


def _run_lighthouse_checks(url: str, company_name: str, settings: Settings) -> AdvancedDetectorResult:
    result = AdvancedDetectorResult()
    if shutil.which("npx") is None:
        result.reviewer_notes.append("npx is not available, Lighthouse checks skipped.")
        return result
    output_path = _asset_path(LIGHTHOUSE_DIR, url, "lighthouse_mobile", "json", company_name)
    command = [
        "npx",
        "--yes",
        "lighthouse",
        url,
        "--output=json",
        f"--output-path={output_path}",
        "--quiet",
        "--chrome-flags=--headless=new",
        "--only-categories=performance,accessibility,best-practices,seo",
        "--form-factor=mobile",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(DATA_DIR.parent),
            capture_output=True,
            text=True,
            timeout=max(75, settings.request_timeout_seconds * 5),
        )
    except Exception as exc:
        result.reviewer_notes.append(f"Lighthouse check skipped or failed: {exc}")
        return result
    if completed.returncode not in {0, 1} or not output_path.exists():
        result.reviewer_notes.append(f"Lighthouse did not return a usable report: {completed.stderr[:240]}")
        return result
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        result.reviewer_notes.append("Lighthouse report could not be parsed.")
        return result
    categories = data.get("categories", {})
    for key in ["performance", "accessibility", "best-practices", "seo"]:
        score = categories.get(key, {}).get("score")
        if isinstance(score, (int, float)):
            pct = round(score * 100)
            result.findings.append(f"Lighthouse mobile {key} score: {pct}/100.")
            if key in {"accessibility", "performance"} and pct < 70:
                result.flags.append(f"lighthouse_low_{key}")
    audits = data.get("audits", {})
    for audit_id in ["tap-targets", "color-contrast", "button-name", "link-name", "errors-in-console"]:
        audit = audits.get(audit_id, {})
        score = audit.get("score")
        title = audit.get("title", audit_id)
        if score == 0:
            result.flags.append(f"lighthouse_{audit_id}")
            result.findings.append(f"Lighthouse issue: {title}.")
    return result
