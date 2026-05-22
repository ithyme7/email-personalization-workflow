from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import Settings
from deliverability import deliverability_flags
from grounding import grounding_flags
from llm_client import LLMBudgetExceeded, LLMClient
from models import EvidenceFact, EvidenceResult, LeadInput, PersonalizationDraft
from copy_guardrails import local_personalization_flags, sanitize_personalization_draft
from deep_research import _cluster_review_themes


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
        "max_workers": 4,
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


def test_gemini_quota_error_is_not_retryable() -> None:
    class Response:
        status_code = 429

        def __init__(self) -> None:
            self.payload = {
                "error": {
                    "code": 429,
                    "message": "You exceeded your current quota. Quota exceeded for free_tier_requests.",
                    "status": "RESOURCE_EXHAUSTED",
                }
            }
            self.text = json.dumps(self.payload)

        def json(self) -> dict:
            return self.payload

    assert LLMClient._is_gemini_quota_exhausted(Response())


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


def test_download_claim_is_flagged() -> None:
    draft = PersonalizationDraft(
        opening_line="I downloaded the example app and the signup step could cost activation.",
        tailored_insight="",
        chosen_angle="",
        evidence_used_for_copy=["The app listing mentions signup."],
    )
    flags = local_personalization_flags(draft)
    assert "download_claim" in flags


def test_placeholder_tokens_are_flagged() -> None:
    draft = PersonalizationDraft(
        opening_line="I opened the {company_name} app and noticed {app_flow_observation}, which could hurt activation.",
        tailored_insight="",
        chosen_angle="",
        evidence_used_for_copy=["App listing mentions signup friction."],
    )
    flags = local_personalization_flags(draft)
    assert "placeholder_token" in flags


def test_sanitizer_replaces_download_claim_and_lowercases_brand() -> None:
    lead = LeadInput(company_name="Rosebud", website_url="https://rosebud.app")
    draft = PersonalizationDraft(
        opening_line="I downloaded the Rosebud app and saw signup friction that could hurt activation.",
        tailored_insight="Rosebud should review the flow.",
        chosen_angle="Rosebud signup friction",
        evidence_used_for_copy=["Rosebud listing mentions signup."],
    )
    cleaned = sanitize_personalization_draft(draft, lead)
    assert "downloaded" not in cleaned.opening_line.lower()
    assert "I checked the rosebud app" in cleaned.opening_line
    assert "Rosebud" not in cleaned.tailored_insight


def test_review_complaints_are_clustered_into_user_feedback_themes() -> None:
    themes = _cluster_review_themes(
        [
            "Apple review (1 stars): Paywall appears before I understand the app and the subscription is confusing.",
            "Apple review (2 stars): Login does not work and I cannot access my account.",
            "Apple review (3 stars): The app crashed during signup.",
        ]
    )
    assert any("pricing/paywall friction" in theme for theme in themes)
    assert any("login/signup/access friction" in theme for theme in themes)
    assert any("bugs/crashes/stability" in theme for theme in themes)


if __name__ == "__main__":
    test_budget_circuit_breaker_blocks_before_api_call()
    test_deliverability_flags_html_and_spam()
    test_grounding_flags_unsupported_line()
    test_download_claim_is_flagged()
    test_sanitizer_replaces_download_claim_and_lowercases_brand()
    test_review_complaints_are_clustered_into_user_feedback_themes()
    print("guardrail_tests_ok")
