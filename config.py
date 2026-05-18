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

REGION_CONFIG = {
    "us": {"country": "us", "locale": "en-US", "timezone": "America/New_York"},
    "uk": {"country": "gb", "locale": "en-GB", "timezone": "Europe/London"},
    "gb": {"country": "gb", "locale": "en-GB", "timezone": "Europe/London"},
    "nl": {"country": "nl", "locale": "nl-NL", "timezone": "Europe/Amsterdam"},
    "ca": {"country": "ca", "locale": "en-CA", "timezone": "America/Toronto"},
    "au": {"country": "au", "locale": "en-AU", "timezone": "Australia/Sydney"},
    "de": {"country": "de", "locale": "de-DE", "timezone": "Europe/Berlin"},
}


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
    browser_retry_attempts: int
    browser_proxy_url: str
    browser_user_agent: str
    visual_review: str
    advanced_detectors: str
    lighthouse_review: str
    tone_profile: str
    max_batch_cost_usd: float
    max_llm_calls_per_batch: int
    personalization_options: int = 3
    research_region: str = "us"
    app_store_country: str = "us"
    browser_locale: str = "en-US"
    browser_timezone: str = "America/New_York"

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
    region = os.getenv("RESEARCH_REGION", os.getenv("APP_STORE_COUNTRY", "us")).strip().lower() or "us"
    region_settings = REGION_CONFIG.get(region, REGION_CONFIG["us"])
    app_store_country = os.getenv("APP_STORE_COUNTRY", region_settings["country"]).strip().lower() or region_settings["country"]
    browser_locale = os.getenv("BROWSER_LOCALE", region_settings["locale"]).strip() or region_settings["locale"]
    browser_timezone = os.getenv("BROWSER_TIMEZONE", region_settings["timezone"]).strip() or region_settings["timezone"]
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
        browser_retry_attempts=max(1, _int_env("BROWSER_RETRY_ATTEMPTS", 3)),
        browser_proxy_url=os.getenv("BROWSER_PROXY_URL", "").strip(),
        browser_user_agent=os.getenv("BROWSER_USER_AGENT", "").strip(),
        visual_review=os.getenv("VISUAL_REVIEW", "auto").strip().lower(),
        advanced_detectors=os.getenv("ADVANCED_DETECTORS", "auto").strip().lower(),
        lighthouse_review=os.getenv("LIGHTHOUSE_REVIEW", "off").strip().lower(),
        tone_profile=os.getenv("TONE_PROFILE", "friction_first").strip() or "friction_first",
        max_batch_cost_usd=max(0.0, _float_env("MAX_BATCH_COST_USD", 0.0)),
        max_llm_calls_per_batch=max(0, _int_env("MAX_LLM_CALLS_PER_BATCH", 0)),
        personalization_options=max(1, min(3, _int_env("PERSONALIZATION_OPTIONS", 3))),
        research_region=region,
        app_store_country=app_store_country,
        browser_locale=browser_locale,
        browser_timezone=browser_timezone,
    )


def ensure_directories() -> None:
    for directory in [DATA_DIR, INPUT_DIR, OUTPUT_DIR, CACHE_DIR, SCREENSHOT_DIR, CUSTOM_TONE_PROFILES_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
