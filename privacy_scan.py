from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SENSITIVE_VALUE_PATTERNS = {
    "local_windows_path": re.compile(r"[A-Za-z]:\\Users\\[^|;\n\r\t]+", re.IGNORECASE),
    "local_unix_user_path": re.compile(r"/Users/[^|;\n\r\t]+|/home/[^|;\n\r\t]+", re.IGNORECASE),
    "email_address": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    "phone_number": re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)"),
    "api_key_like": re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,}|[A-Za-z0-9_-]{32,})\b"),
    "trace_file": re.compile(r"\.trace\.zip\b|trace_[^|;\n\r\t]+\.zip\b|\.zip\b", re.IGNORECASE),
}

QUERY_SECRET_PATTERN = re.compile(
    r"([?&](?:api[_-]?key|key|token|access[_-]?token|auth|authorization|signature|sig|secret|expires|x-amz-[^=\s&|]+)=)[^&\s|]+",
    re.IGNORECASE,
)

HARD_CLIENT_SAFE_LEAKS = {
    "local_windows_path",
    "local_unix_user_path",
    "api_key_like",
    "trace_file",
    "secret_query_parameter",
}

COMMON_TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


@dataclass
class PrivacyScanResult:
    flags: list[str] = field(default_factory=list)
    sanitized_text: str = ""
    notes: list[str] = field(default_factory=list)
    ocr_used: bool = False


def _truthy_env(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def screenshot_ocr_required() -> bool:
    return _truthy_env("REQUIRE_SCREENSHOT_OCR", True)


def configure_tesseract() -> tuple[bool, str]:
    try:
        import pytesseract  # type: ignore
    except Exception as exc:
        return False, f"pytesseract is not installed: {exc}"

    configured = os.getenv("TESSERACT_CMD", "").strip()
    candidates = [configured] if configured else []
    which = shutil.which("tesseract")
    if which:
        candidates.append(which)
    candidates.extend(COMMON_TESSERACT_PATHS)
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            pytesseract.pytesseract.tesseract_cmd = candidate
            return True, candidate
    return False, "Tesseract executable was not found. Install Tesseract OCR or set TESSERACT_CMD."


def ocr_available() -> tuple[bool, str]:
    ok, detail = configure_tesseract()
    if not ok:
        return ok, detail
    try:
        import pytesseract  # type: ignore

        version = pytesseract.get_tesseract_version()
        return True, f"Tesseract OCR available: {version}"
    except Exception as exc:
        return False, f"Tesseract OCR could not run: {exc}"


def sanitize_text(value: Any) -> PrivacyScanResult:
    text = str(value or "")
    flags: list[str] = []
    for flag, pattern in SENSITIVE_VALUE_PATTERNS.items():
        if flag == "trace_file":
            continue
        if pattern.search(text):
            flags.append(flag)
            replacement = "[redacted email]" if flag == "email_address" else "[redacted]"
            text = pattern.sub(replacement, text)
    if QUERY_SECRET_PATTERN.search(text):
        flags.append("secret_query_parameter")
        text = QUERY_SECRET_PATTERN.sub(r"\1[redacted]", text)
    return PrivacyScanResult(flags=sorted(set(flags)), sanitized_text=text)


def scan_text(value: Any, ignore_redacted_query_params: bool = True) -> list[str]:
    text = str(value or "")
    if ignore_redacted_query_params:
        text = re.sub(
            r"([?&](?:api[_-]?key|key|token|access[_-]?token|auth|authorization|signature|sig|secret|expires|x-amz-[^=\s&|]+)=)\[redacted\]",
            "",
            text,
            flags=re.IGNORECASE,
        )
    flags: set[str] = set()
    for flag, pattern in SENSITIVE_VALUE_PATTERNS.items():
        if pattern.search(text):
            flags.add(flag)
    if QUERY_SECRET_PATTERN.search(text):
        flags.add("secret_query_parameter")
    return sorted(flags)


def scan_image_for_pii(path: str | Path, require_ocr: bool | None = None) -> PrivacyScanResult:
    image_path = Path(path)
    filename_flags = scan_text(str(image_path))
    notes: list[str] = []
    require_ocr = screenshot_ocr_required() if require_ocr is None else require_ocr
    if not image_path.exists():
        return PrivacyScanResult(flags=filename_flags + ["image_missing"], notes=["Screenshot file does not exist."])

    ok, ocr_detail = configure_tesseract()
    if not ok:
        flags = filename_flags + (["ocr_unavailable"] if require_ocr else [])
        notes.append(ocr_detail)
        if require_ocr:
            notes.append("Screenshot skipped because REQUIRE_SCREENSHOT_OCR is enabled.")
        else:
            notes.append("OCR unavailable; only screenshot filename/path was privacy-scanned.")
        return PrivacyScanResult(flags=sorted(set(flags)), notes=notes, ocr_used=False)

    try:
        from PIL import Image  # type: ignore
    except ImportError:
        flags = filename_flags + (["ocr_unavailable"] if require_ocr else [])
        notes.append("Pillow is not installed, so screenshot OCR could not run.")
        if require_ocr:
            notes.append("Screenshot skipped because REQUIRE_SCREENSHOT_OCR is enabled.")
        return PrivacyScanResult(flags=sorted(set(flags)), notes=notes, ocr_used=False)

    try:
        import pytesseract  # type: ignore

        text = pytesseract.image_to_string(Image.open(image_path))
    except Exception as exc:
        notes.append(f"OCR failed: {str(exc)[:120]}")
        flags = filename_flags + ["ocr_failed"]
        if require_ocr:
            notes.append("Screenshot skipped because REQUIRE_SCREENSHOT_OCR is enabled.")
        return PrivacyScanResult(flags=sorted(set(flags)), notes=notes, ocr_used=False)

    flags = sorted(set(filename_flags + scan_text(text)))
    return PrivacyScanResult(flags=flags, sanitized_text=text, notes=notes, ocr_used=True)
