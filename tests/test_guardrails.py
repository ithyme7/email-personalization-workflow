from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import Settings
from deliverability import deliverability_flags
from grounding import grounding_flags
from llm_client import LLMBudgetExceeded, LLMClient
from models import EvidenceFact, EvidenceResult, PersonalizationDraft


def _settings(**overrides) -> Settings:
    base = {
        "llm_provider": "gemini",
        "openai_api_key": "",
        "deepseek_api_key": "",
        "openrouter_api_key": "",
        "gemini_api_key": "fake",
        "model_name": "gemini-3.1-flash-lite",
        "max_pages_per_company": 5,
        "request_timeout_seconds": 15,
        "request_delay_seconds": 0.75,
        "browser_rendering": "off",
        "browser_wait_seconds": 2.0,
        "browser_retry_attempts": 3,
        "browser_proxy_url": "",
        "browser_user_agent": "",
        "visual_review": "off",
        "advanced_detectors": "off",
        "lighthouse_review": "off",
        "tone_profile": "friction_first",
        "max_batch_cost_usd": 0.000001,
        "max_llm_calls_per_batch": 0,
    }
    base.update(overrides)
    return Settings(**base)


def test_budget_circuit_breaker_blocks_before_api_call() -> None:
    client = LLMClient(_settings())
    try:
        client.complete_json("Return JSON", {"large": "x" * 5000})
    except LLMBudgetExceeded:
        return
    raise AssertionError("Expected LLMBudgetExceeded before network call")


def test_deliverability_flags_html_and_spam() -> None:
    flags = deliverability_flags("<b>Act now</b> before this limited time offer ends")
    assert "html_in_personalization_line" in flags
    assert "spam_trigger_language" in flags


def test_grounding_flags_unsupported_line() -> None:
    evidence = EvidenceResult(
        facts=[
            EvidenceFact(
                fact="The app asks for an invite code before users can reach the first exercise.",
                why_it_matters="That can delay activation.",
                source_url="https://example.com",
                strength="strong",
                too_generic_to_use=False,
            )
        ]
    )
    draft = PersonalizationDraft(
        opening_line="I was checking the app and the pricing page says enterprise revenue doubled last quarter.",
        tailored_insight="",
        chosen_angle="",
        evidence_used_for_copy=["Pricing page says enterprise revenue doubled last quarter."],
    )
    flags = grounding_flags(draft, evidence)
    assert "line_not_grounded_in_evidence" in flags
    assert "evidence_used_not_in_extracted_facts" in flags


if __name__ == "__main__":
    test_budget_circuit_breaker_blocks_before_api_call()
    test_deliverability_flags_html_and_spam()
    test_grounding_flags_unsupported_line()
    print("guardrail_tests_ok")
