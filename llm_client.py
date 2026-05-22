from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Mapping

import requests

from cache import read_cached_json, write_cached_json
from config import CACHE_DIR, PROMPTS_DIR, Settings
from cost_estimator import price_for_model
from rate_limiter import RateLimiter
from retry import ExponentialBackoff


class LLMError(RuntimeError):
    pass


class LLMBudgetExceeded(LLMError):
    pass


class RateLimitedError(LLMError):
    pass


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    return path.read_text(encoding="utf-8")


def load_prompt_pair(name: str) -> tuple[str, str]:
    """Load a (system_prompt, user_template) pair from
    prompts/<name>_system.txt and prompts/<name>_user.txt."""
    system = PROMPTS_DIR / f"{name}_system.txt"
    user = PROMPTS_DIR / f"{name}_user.txt"
    return system.read_text(encoding="utf-8"), user.read_text(encoding="utf-8")


def render_prompt_template(template: str, values: Mapping[str, Any]) -> str:
    """Render {name} prompt placeholders without disturbing JSON examples.

    Several prompt files intentionally contain literal JSON braces in examples.
    Using str.format would require escaping all of those braces and string.Template
    would leave the project's {name} placeholders untouched. This replaces only
    known simple placeholders supplied in values.
    """

    def _stringify(value: Any) -> str:
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            return match.group(0)
        return _stringify(values[key])

    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, template)


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise LLMError("Model response did not contain a JSON object")
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LLMError(f"Could not parse model JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMError("Model JSON was not an object")
    return parsed


class LLMClient:
    def __init__(self, settings: Settings, rate_limiter: RateLimiter | None = None) -> None:
        self.settings = settings
        self.rate_limiter = rate_limiter
        self.call_count = 0
        self.estimated_input_tokens = 0
        self.estimated_output_tokens = 0
        # Connection pooling: herbruikbare TCP-verbindingen via Session
        self._session = requests.Session()

    @property
    def available(self) -> bool:
        return self.settings.has_active_llm_key

    @property
    def provider_name(self) -> str:
        return self.settings.llm_provider

    def validate_access(self) -> tuple[bool, str]:
        if not self.available:
            if self.settings.llm_provider == "gemini":
                return False, "GEMINI_API_KEY is missing"
            if self.settings.llm_provider == "openrouter":
                return False, "OPENROUTER_API_KEY is missing"
            if self.settings.llm_provider == "deepseek":
                return False, "DEEPSEEK_API_KEY is missing"
            return False, "OPENAI_API_KEY is missing"

        try:
            self.complete_json(
                "Return only valid JSON. Return exactly {\"ok\": true}.",
                {"preflight": "check API access before processing the batch"},
            )
            return True, "API access OK"
        except LLMError as exc:
            return False, str(exc)

    def _endpoint(self) -> str:
        if self.settings.llm_provider == "gemini":
            model = self.settings.model_name.removeprefix("models/")
            return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        if self.settings.llm_provider == "openrouter":
            return "https://openrouter.ai/api/v1/chat/completions"
        if self.settings.llm_provider == "deepseek":
            return "https://api.deepseek.com/chat/completions"
        return "https://api.openai.com/v1/chat/completions"

    def _api_key(self) -> str:
        if self.settings.llm_provider == "gemini":
            return self.settings.gemini_api_key
        if self.settings.llm_provider == "openrouter":
            return self.settings.openrouter_api_key
        if self.settings.llm_provider == "deepseek":
            return self.settings.deepseek_api_key
        return self.settings.openai_api_key

    def close(self) -> None:
        """Sluit de onderliggende HTTP-sessie om verbindingen netjes vrij te geven."""
        self._session.close()

    def _cache_key(self, system_prompt: str, user_payload: dict[str, Any], temperature: float) -> str:
        """Berekent een deterministische cache key op basis van model, prompts en temperature."""
        payload_str = json.dumps(user_payload, sort_keys=True, ensure_ascii=False)
        raw = f"{self.settings.llm_provider}:{self.settings.model_name}:{temperature}:{system_prompt}:{payload_str}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_path(self, cache_key: str) -> Path:
        return CACHE_DIR / f"llm_response_{cache_key}.json"

    def _call_cached(self, cache_key: str, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any] | None:
        """Probeert een gecachte LLM-response te lezen. Retourneert None als cache miss of verlopen."""
        try:
            cached = read_cached_json(self._cache_path(cache_key), ttl_seconds=self.settings.cache_ttl_seconds)
            if cached is not None:
                self._record_usage(system_prompt, user_payload, cached.get("content", ""))
                return cached
        except Exception:
            pass  # Cache miss — not an error; fall through to LLM call
        return None

    def _wait_for_rate_limit(self) -> None:
        """Wacht op een beschikbare rate-limit token voordat een API-call wordt gemaakt.

        Als er geen rate limiter is geconfigureerd, wordt direct doorgaan.
        """
        if self.rate_limiter is not None:
            self.rate_limiter.acquire(blocking=True)

    @staticmethod
    def _estimate_tokens(value: Any) -> int:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return max(1, round(len(text) / 4))

    def _record_usage(self, system_prompt: str, user_payload: dict[str, Any], response_text: str) -> None:
        self.call_count += 1
        self.estimated_input_tokens += self._estimate_tokens(system_prompt) + self._estimate_tokens(user_payload)
        self.estimated_output_tokens += self._estimate_tokens(response_text)

    def _projected_cost_usd(self, next_input_tokens: int = 0, next_output_tokens: int = 1200) -> float:
        input_price, output_price = price_for_model(self.settings.model_name)
        input_tokens = self.estimated_input_tokens + next_input_tokens
        output_tokens = self.estimated_output_tokens + next_output_tokens
        return (input_tokens / 1_000_000 * input_price) + (output_tokens / 1_000_000 * output_price)

    def _enforce_budget(self, system_prompt: str, user_payload: dict[str, Any]) -> None:
        max_calls = self.settings.max_llm_calls_per_batch
        if max_calls and self.call_count + 1 > max_calls:
            raise LLMBudgetExceeded(
                f"LLM call limit reached: {self.call_count + 1} would exceed MAX_LLM_CALLS_PER_BATCH={max_calls}"
            )

        max_cost = self.settings.max_batch_cost_usd
        if max_cost:
            next_input_tokens = self._estimate_tokens(system_prompt) + self._estimate_tokens(user_payload)
            projected = self._projected_cost_usd(next_input_tokens=next_input_tokens)
            if projected > max_cost:
                raise LLMBudgetExceeded(
                    f"LLM budget limit reached: projected ${projected:.4f} would exceed MAX_BATCH_COST_USD=${max_cost:.4f}"
                )

    def usage_summary(self) -> dict[str, int]:
        return {
            "llm_calls": self.call_count,
            "estimated_input_tokens": self.estimated_input_tokens,
            "estimated_output_tokens": self.estimated_output_tokens,
        }

    def _retry_delay_seconds(self, response: requests.Response) -> float:
        """Parseert Retry-After header of response body voor een specifieke delay."""
        try:
            data = response.json()
        except ValueError:
            data = {}
        details = data.get("error", {}).get("details", []) if isinstance(data, dict) else []

        retry_match = re.search(r"retry in ([0-9.]+)s", response.text, flags=re.IGNORECASE)
        if retry_match:
            return min(max(float(retry_match.group(1)) + 3.0, 5.0), 120.0)

        for detail in details:
            if not isinstance(detail, dict):
                continue
            retry_delay = str(detail.get("retryDelay", ""))
            delay_match = re.match(r"([0-9.]+)s", retry_delay)
            if delay_match:
                return min(max(float(delay_match.group(1)) + 3.0, 5.0), 120.0)

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(float(retry_after) + 3.0, 120.0)
                except ValueError:
                    pass
            return 45.0
        if response.status_code in {500, 502, 503, 504}:
            return 20.0
        return 0.0

    @staticmethod
    def _is_gemini_quota_exhausted(response: requests.Response) -> bool:
        if response.status_code != 429:
            return False
        try:
            payload = response.json()
            text = json.dumps(payload, ensure_ascii=False).lower()
        except ValueError:
            text = response.text.lower()
        quota_markers = [
            "resource_exhausted",
            "quota",
            "free_tier",
            "free tier",
            "generate_content_free_tier_requests",
            "exceeded your current quota",
        ]
        return any(marker in text for marker in quota_markers)

    def _post_gemini_with_retry(self, request_json: dict[str, Any]) -> requests.Response:
        """Verzendt Gemini request met exponential backoff via retry module."""
        backoff = ExponentialBackoff(
            max_attempts=5,
            base_delay=1.0,
            max_delay=60.0,
        )
        retryable_statuses = {429, 500, 502, 503, 504}

        for attempt, delay in backoff.attempts():
            self._wait_for_rate_limit()
            response = self._session.post(
                self._endpoint(),
                params={"key": self._api_key()},
                headers={"Content-Type": "application/json"},
                json=request_json,
                timeout=90,
            )
            if response.status_code < 400:
                return response
            if self._is_gemini_quota_exhausted(response):
                logging.error("Gemini quota exhausted; skipping retry backoff for this request.")
                return response
            if response.status_code not in retryable_statuses or attempt >= backoff.max_attempts:
                return response
            logging.warning(
                "Gemini rate/high-demand response %s. Waiting %.1fs before retry %s/%s.",
                response.status_code,
                delay,
                attempt + 1,
                backoff.max_attempts,
            )
            time.sleep(delay)

        return response

    def _complete_json_gemini(self, system_prompt: str, user_payload: dict[str, Any], temperature: float) -> dict[str, Any]:
        request_json: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": json.dumps(user_payload, ensure_ascii=False)}],
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
            },
        }

        response = self._post_gemini_with_retry(request_json)
        if response.status_code >= 400:
            logging.error("%s API error: %s %s", self.provider_name, response.status_code, response.text[:500])
            message = _extract_error_message(response)
            raise LLMError(f"{self.provider_name} API error {response.status_code}: {message}")

        data = response.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            content = "".join(str(part.get("text", "")) for part in parts).strip()
        except (KeyError, IndexError, TypeError) as exc:
            logging.error("Unexpected Gemini response: %s", json.dumps(data)[:500])
            raise LLMError("Gemini response did not contain text content") from exc
        self._record_usage(system_prompt, user_payload, content)
        return parse_json_object(content)

    def complete_json(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        temperature: float = 0.2,
        skip_cache: bool = False,
    ) -> dict[str, Any]:
        if not self.available:
            if self.settings.llm_provider == "gemini":
                raise LLMError("GEMINI_API_KEY is missing")
            if self.settings.llm_provider == "openrouter":
                raise LLMError("OPENROUTER_API_KEY is missing")
            if self.settings.llm_provider == "deepseek":
                raise LLMError("DEEPSEEK_API_KEY is missing")
            raise LLMError("OPENAI_API_KEY is missing")

        # --- Cache checks ---
        cache_key = self._cache_key(system_prompt, user_payload, temperature)
        if not skip_cache:
            cached = self._call_cached(cache_key, system_prompt, user_payload)
            if cached is not None:
                logging.debug("LLM cache hit (%s)", cache_key[:12])
                return cached

        self._enforce_budget(system_prompt, user_payload)
        self._wait_for_rate_limit()

        if self.settings.llm_provider == "gemini":
            result = self._complete_json_gemini(system_prompt, user_payload, temperature)
        else:
            request_json: dict[str, Any] = {
                "model": self.settings.model_name,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
            }
            if self.settings.llm_provider == "openai":
                request_json["response_format"] = {"type": "json_object"}

            headers = {
                "Authorization": f"Bearer {self._api_key()}",
                "Content-Type": "application/json",
            }
            if self.settings.llm_provider == "openrouter":
                headers["HTTP-Referer"] = "https://local.email-personalizer"
                headers["X-OpenRouter-Title"] = "Email Personalization Workflow"

            response = self._session.post(
                self._endpoint(),
                headers=headers,
                json=request_json,
                timeout=90,
            )
            if response.status_code >= 400:
                logging.error("%s API error: %s %s", self.provider_name, response.status_code, response.text[:500])
                message = _extract_error_message(response)
                raise LLMError(f"{self.provider_name} API error {response.status_code}: {message}")

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            self._record_usage(system_prompt, user_payload, content)
            result = parse_json_object(content)

        # --- Schrijf naar cache ---
        try:
            write_cached_json(self._cache_path(cache_key), {"content": result})
        except Exception:
            logging.debug("Kon LLM-response niet cachen")

        return result


OpenAIClient = LLMClient


def _extract_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:240]
    if not isinstance(data, dict):
        return response.text[:240]
    error = data.get("error", {})
    if isinstance(error, dict):
        message = str(error.get("message", "")).strip()
        status = str(error.get("status", "")).strip()
        if message and status:
            return f"{message} ({status})"
        if message:
            return message
    return response.text[:240]
