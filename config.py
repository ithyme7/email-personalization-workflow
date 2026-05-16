from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


if getattr(sys, "frozen", False):
    ROOT_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", ROOT_DIR))
else:
    ROOT_DIR = Path(__file__).resolve().parent
    RESOURCE_DIR = ROOT_DIR

load_dotenv(ROOT_DIR / ".env")
load_dotenv()

DATA_DIR = ROOT_DIR / "data"
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
CACHE_DIR = DATA_DIR / "cache"
SCREENSHOT_DIR = DATA_DIR / "screenshots"
CUSTOM_TONE_PROFILES_DIR = DATA_DIR / "custom_tone_profiles"
PROMPTS_DIR = RESOURCE_DIR / "prompts"
TONE_PROFILES_DIR = RESOURCE_DIR / "tone_profiles"


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    openai_api_key: str
    deepseek_api_key: str
    openrouter_api_key: str
    gemini_api_key: str
    model_name: str
    max_pages_per_company: int
    request_timeout_seconds: int
    request_delay_seconds: float
    browser_rendering: str
    browser_wait_seconds: float
    visual_review: str
    advanced_detectors: str
    lighthouse_review: str
    tone_profile: str

    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key.strip())

    @property
    def has_deepseek_key(self) -> bool:
        return bool(self.deepseek_api_key.strip())

    @property
    def has_openrouter_key(self) -> bool:
        return bool(self.openrouter_api_key.strip())

    @property
    def has_gemini_key(self) -> bool:
        return bool(self.gemini_api_key.strip())

    @property
    def has_active_llm_key(self) -> bool:
        if self.llm_provider == "gemini":
            return self.has_gemini_key
        if self.llm_provider == "openrouter":
            return self.has_openrouter_key
        if self.llm_provider == "deepseek":
            return self.has_deepseek_key
        return self.has_openai_key


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def load_settings() -> Settings:
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    if provider not in {"openai", "deepseek", "openrouter", "gemini"}:
        provider = "gemini"
    if provider == "deepseek":
        default_model = "deepseek-chat"
    elif provider == "openrouter":
        default_model = "openai/gpt-4o-mini"
    elif provider == "gemini":
        default_model = "gemini-3.1-flash-lite"
    else:
        default_model = "gpt-4o-mini"
    return Settings(
        llm_provider=provider,
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        model_name=os.getenv("MODEL_NAME", default_model),
        max_pages_per_company=max(1, _int_env("MAX_PAGES_PER_COMPANY", 5)),
        request_timeout_seconds=max(3, _int_env("REQUEST_TIMEOUT_SECONDS", 15)),
        request_delay_seconds=max(0.0, _float_env("REQUEST_DELAY_SECONDS", 0.75)),
        browser_rendering=os.getenv("BROWSER_RENDERING", "auto").strip().lower(),
        browser_wait_seconds=max(0.5, _float_env("BROWSER_WAIT_SECONDS", 2.0)),
        visual_review=os.getenv("VISUAL_REVIEW", "auto").strip().lower(),
        advanced_detectors=os.getenv("ADVANCED_DETECTORS", "auto").strip().lower(),
        lighthouse_review=os.getenv("LIGHTHOUSE_REVIEW", "off").strip().lower(),
        tone_profile=os.getenv("TONE_PROFILE", "friction_first").strip() or "friction_first",
    )


def ensure_directories() -> None:
    for directory in [DATA_DIR, INPUT_DIR, OUTPUT_DIR, CACHE_DIR, SCREENSHOT_DIR, CUSTOM_TONE_PROFILES_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
