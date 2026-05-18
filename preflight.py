from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests

from advanced_detectors import check_detector_readiness
from config import OUTPUT_DIR, Settings, ensure_directories, load_settings
from llm_client import LLMClient
from privacy_scan import ocr_available, screenshot_ocr_required
from run_history import sqlite_is_writable


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: str
    message: str
    blocking: bool = False


def _ok(name: str, message: str) -> PreflightCheck:
    return PreflightCheck(name=name, status="ok", message=message)


def _warn(name: str, message: str) -> PreflightCheck:
    return PreflightCheck(name=name, status="warn", message=message)


def _fail(name: str, message: str) -> PreflightCheck:
    return PreflightCheck(name=name, status="fail", message=message, blocking=True)


def _check_output_writable(output_dir: Path) -> PreflightCheck:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        probe = output_dir / ".preflight_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return _ok("Output folder", f"Writable: {output_dir}")
    except Exception as exc:
        return _fail("Output folder", f"Not writable: {exc}")


def _check_sqlite() -> PreflightCheck:
    ok, detail = sqlite_is_writable()
    if ok:
        return _ok("SQLite history", detail)
    return _fail("SQLite history", detail)


def _check_api(settings: Settings) -> PreflightCheck:
    client = LLMClient(settings)
    if not client.available:
        return _warn("LLM API", "No API key set. Research-only mode can still run, but AI writing/QC will be disabled.")
    ok, detail = client.validate_access()
    if ok:
        return _ok("LLM API", detail)
    return _fail("LLM API", detail)


def _check_proxy(settings: Settings) -> PreflightCheck:
    if not settings.browser_proxy_url:
        return _ok("Browser proxy", "No proxy configured.")
    proxies = {"http": settings.browser_proxy_url, "https": settings.browser_proxy_url}
    try:
        response = requests.get("https://example.com", proxies=proxies, timeout=settings.request_timeout_seconds)
        if response.status_code >= 400:
            return _fail("Browser proxy", f"Proxy responded with HTTP {response.status_code}.")
        return _ok("Browser proxy", "Proxy can reach https://example.com.")
    except Exception as exc:
        return _fail("Browser proxy", f"Proxy check failed: {exc}")


def _check_ocr() -> PreflightCheck:
    if not screenshot_ocr_required():
        return _warn("Screenshot OCR", "REQUIRE_SCREENSHOT_OCR=false. Screenshots can be delivered without OCR blocking.")
    ok, detail = ocr_available()
    if ok:
        return _ok("Screenshot OCR", detail)
    return _warn("Screenshot OCR", detail)


def _detector_preflight(settings: Settings) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []
    for readiness in check_detector_readiness(settings):
        if readiness.status == "ok":
            checks.append(_ok(readiness.name, readiness.message))
        elif readiness.status == "fail" and readiness.blocking:
            checks.append(_fail(readiness.name, readiness.message))
        else:
            checks.append(_warn(readiness.name, readiness.message))
    return checks


def run_preflight(
    settings: Settings | None = None,
    output_dir: Path | None = None,
    *,
    check_api: bool = True,
    check_proxy: bool = True,
    check_ocr: bool = True,
    check_detectors: bool = True,
) -> list[PreflightCheck]:
    settings = settings or load_settings()
    ensure_directories()
    checks = [
        _check_output_writable(output_dir or OUTPUT_DIR),
        _check_sqlite(),
    ]
    if check_proxy:
        checks.append(_check_proxy(settings))
    if check_api:
        checks.append(_check_api(settings))
    if check_ocr:
        checks.append(_check_ocr())
    if check_detectors:
        checks.extend(_detector_preflight(settings))
    return checks


def has_blocking_failures(checks: Iterable[PreflightCheck]) -> bool:
    return any(check.blocking for check in checks)


def preflight_summary(checks: Iterable[PreflightCheck]) -> str:
    return "\n".join(f"[{check.status.upper()}] {check.name}: {check.message}" for check in checks)
