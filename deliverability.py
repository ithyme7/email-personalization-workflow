from __future__ import annotations

import re


SPAM_TRIGGER_PHRASES = {
    "act now",
    "buy now",
    "click here",
    "double your",
    "free money",
    "guaranteed",
    "limited time",
    "no obligation",
    "risk free",
    "special promotion",
    "urgent",
    "winner",
}


HTML_PATTERN = re.compile(r"<[^>\n]+>")


def deliverability_flags(text: str) -> list[str]:
    line = str(text or "")
    lowered = line.lower()
    flags: list[str] = []
    if HTML_PATTERN.search(line):
        flags.append("html_in_personalization_line")
    if any(phrase in lowered for phrase in SPAM_TRIGGER_PHRASES):
        flags.append("spam_trigger_language")
    return flags
