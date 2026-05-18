from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import Settings
from export import _client_rows
from export_mappings import sending_tool_dataframe
from preflight import has_blocking_failures, run_preflight
from prompt_versions import prompt_hashes


def _settings(**overrides) -> Settings:
    base = {
        "llm_provider": "gemini",
        "openai_api_key": "",
        "deepseek_api_key": "",
        "openrouter_api_key": "",
        "gemini_api_key": "",
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
        "max_batch_cost_usd": 0,
        "max_llm_calls_per_batch": 0,
    }
    base.update(overrides)
    return Settings(**base)


def test_preflight_without_api_key_is_not_blocking() -> None:
    with TemporaryDirectory() as tmp:
        checks = run_preflight(
            _settings(),
            output_dir=Path(tmp),
            check_api=True,
            check_proxy=False,
            check_ocr=False,
        )
    assert not has_blocking_failures(checks)
    assert any(check.name == "LLM API" and check.status == "warn" for check in checks)


def test_prompt_hashes_are_stable_shape() -> None:
    hashes = prompt_hashes()
    for key in ["prompt_set_hash", "evidence_prompt_hash", "write_prompt_hash", "qc_prompt_hash"]:
        assert key in hashes
        assert len(hashes[key]) == 64


def test_sending_tool_mapping_prefers_approved_edit() -> None:
    df = pd.DataFrame(
        [
            {
                "company": "Example Co",
                "person": "Jane Doe",
                "role": "Founder",
                "website": "https://example.com",
                "personalized_line": "Original line",
                "human_decision": "edit",
                "edited_line": "Edited sendable line",
            }
        ]
    )
    mapped = sending_tool_dataframe(df, preset="lemlist")
    assert mapped.loc[0, "firstName"] == "Jane"
    assert mapped.loc[0, "lastName"] == "Doe"
    assert mapped.loc[0, "icebreaker"] == "Edited sendable line"


def test_client_review_export_includes_multishot_options() -> None:
    review_rows, _ = _client_rows(
        [
            {
                "company_name": "example",
                "recipient_name": "Jane",
                "website_url": "https://example.com",
                "opening_line": "I was checking out the example app and saw one friction point.",
                "opening_line_option_1": "Option one",
                "confidence_score_option_1": 9,
                "quality_flags_option_1": "",
                "needs_manual_review_option_1": False,
                "opening_line_option_2": "Option two",
                "confidence_score_option_2": 8,
                "quality_flags_option_2": "soft_edit",
                "needs_manual_review_option_2": True,
                "opening_line_option_3": "Option three",
                "confidence_score_option_3": 7,
                "quality_flags_option_3": "manual_review_needed",
                "needs_manual_review_option_3": True,
            }
        ]
    )
    row = review_rows[0]
    assert row["option_1_line"] == "Option one"
    assert row["option_1_qc_score"] == 9
    assert row["option_2_line"] == "Option two"
    assert row["option_2_needs_review"] == "yes"
    assert row["option_3_line"] == "Option three"


if __name__ == "__main__":
    test_preflight_without_api_key_is_not_blocking()
    test_prompt_hashes_are_stable_shape()
    test_sending_tool_mapping_prefers_approved_edit()
    test_client_review_export_includes_multishot_options()
    print("preflight_and_export_tests_ok")
