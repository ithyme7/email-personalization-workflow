from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import requests

from config import PROMPTS_DIR, Settings


class LLMError(RuntimeError):
    pass


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    return path.read_text(encoding="utf-8")


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
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.call_count = 0
        self.estimated_input_tokens = 0
        self.estimated_output_tokens = 0

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

    @staticmethod
    def _estimate_tokens(value: Any) -> int:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return max(1, round(len(text) / 4))

    def _record_usage(self, system_prompt: str, user_payload: dict[str, Any], response_text: str) -> None:
        self.call_count += 1
        self.estimated_input_tokens += self._estimate_tokens(system_prompt) + self._estimate_tokens(user_payload)
        self.estimated_output_tokens += self._estimate_tokens(response_text)

    def usage_summary(self) -> dict[str, int]:
        return {
            "llm_calls": self.call_count,
            "estimated_input_tokens": self.estimated_input_tokens,
            "estimated_output_tokens": self.estimated_output_tokens,
        }

    def _retry_delay_seconds(self, response: requests.Response) -> float:
        text = response.text
        retry_match = re.search(r"retry in ([0-9.]+)s", text, flags=re.IGNORECASE)
        if retry_match:
            return min(max(float(retry_match.group(1)) + 3.0, 5.0), 120.0)

        try:
            data = response.json()
        except ValueError:
            data = {}
        details = data.get("error", {}).get("details", []) if isinstance(data, dict) else []
        for detail in details:
            if not isinstance(detail, dict):
                continue
            retry_delay = str(detail.get("retryDelay", ""))
            delay_match = re.match(r"([0-9.]+)s", retry_delay)
            if delay_match:
                return min(max(float(delay_match.group(1)) + 3.0, 5.0), 120.0)

        if response.status_code == 429:
            return 45.0
        if response.status_code in {500, 502, 503, 504}:
            return 20.0
        return 0.0

    def _post_gemini_with_retry(self, request_json: dict[str, Any]) -> requests.Response:
        max_attempts = 5
        retryable_statuses = {429, 500, 502, 503, 504}
        for attempt in range(1, max_attempts + 1):
            response = requests.post(
                self._endpoint(),
                params={"key": self._api_key()},
                headers={"Content-Type": "application/json"},
                json=request_json,
                timeout=90,
            )
            if response.status_code < 400:
                return response
            if response.status_code not in retryable_statuses or attempt == max_attempts:
                return response

            delay = self._retry_delay_seconds(response)
            logging.warning(
                "Gemini rate/high-demand response %s. Waiting %.0f seconds before retry %s/%s.",
                response.status_code,
                delay,
                attempt + 1,
                max_attempts,
            )
            time.sleep(delay)
        return response

    def _complete_json_gemini(self, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        request_json: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": json.dumps(user_payload, ensure_ascii=False)}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
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

    def complete_json(self, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        if not self.available:
            if self.settings.llm_provider == "gemini":
                raise LLMError("GEMINI_API_KEY is missing")
            if self.settings.llm_provider == "openrouter":
                raise LLMError("OPENROUTER_API_KEY is missing")
            if self.settings.llm_provider == "deepseek":
                raise LLMError("DEEPSEEK_API_KEY is missing")
            raise LLMError("OPENAI_API_KEY is missing")

        if self.settings.llm_provider == "gemini":
            return self._complete_json_gemini(system_prompt, user_payload)

        request_json: dict[str, Any] = {
            "model": self.settings.model_name,
            "temperature": 0.2,
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

        response = requests.post(
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
        return parse_json_object(content)


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
