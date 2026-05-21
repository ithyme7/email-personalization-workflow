from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import client_workspaces
from client_workspaces import ClientWorkspace, list_client_workspaces, load_client_workspace, save_client_workspace
from config import Settings
from delivery_policy import strict_delivery_dataframe
from export import _client_rows
from export import export_delivery_rows
from export import export_rows
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
                "opener_option_1": "Option one",
                "opener_option_1_sendability": "Send",
                "opener_option_1_sendability_score": 91,
                "opener_option_1_sales_principles_summary": "Send: specific",
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
    assert row["opener_option_1"] == "Option one"
    assert row["opener_option_1_sendability"] == "Send"
    assert row["opener_option_1_sales_principles_summary"] == "Send: specific"
    assert row["option_1_qc_score"] == 9
    assert row["option_2_line"] == "Option two"
    assert row["option_2_needs_review"] == "yes"
    assert row["option_3_line"] == "Option three"


def test_export_preserves_original_input_columns_first_and_prefixes_collision() -> None:
    with TemporaryDirectory() as tmp:
        output = Path(tmp) / "out.csv"
        export_rows(
            [
                {
                    "company_name": "Workflow Company",
                    "website_url": "https://workflow.example",
                    "opening_line": "Generated line",
                    "input__website_url": "https://original.example",
                    "input__Custom Column": "custom",
                    "input__company_name": "Original Company",
                }
            ],
            output,
        )
        df = pd.read_csv(output, dtype=str).fillna("")
    assert df.columns[:3].tolist() == ["website_url", "Custom Column", "company_name"]
    assert df.loc[0, "website_url"] == "https://original.example"
    assert df.loc[0, "workflow__website_url"] == "https://workflow.example"
    assert df.loc[0, "workflow__company_name"] == "Workflow Company"


def test_review_export_includes_all_rows_but_delivery_export_is_strict() -> None:
    rows = [
        {
            "company_name": "Example",
            "website_url": "https://example.com",
            "opening_line": "I was checking the app listing and reviews say signup is unclear, which could add friction before activation.",
            "evidence_used_for_copy": "App listing reviews say signup is unclear.",
            "source_urls": "https://example.com/app",
            "product_surface_type": "app_first_product",
            "sendability_decision": "Send",
            "human_decision": "unreviewed",
        },
        {
            "company_name": "Needs Edit",
            "website_url": "https://needsedit.com",
            "opening_line": "I was checking the app listing and saw login friction.",
            "evidence_used_for_copy": "App listing mentions login friction.",
            "source_urls": "https://needsedit.com/app",
            "product_surface_type": "app_first_product",
            "sendability_decision": "Edit",
            "human_decision": "unreviewed",
        },
        {
            "company_name": "Rejected",
            "website_url": "https://rejected.com",
            "opening_line": "I was checking the app listing and saw traffic doubled after the new paywall, which could lift conversion.",
            "evidence_used_for_copy": "The listing mentions a paywall.",
            "source_urls": "https://rejected.com/app",
            "product_surface_type": "app_first_product",
            "sendability_decision": "Reject",
            "human_decision": "reject",
        },
        {
            "company_name": "Approved Edit",
            "website_url": "https://approvededit.com",
            "opening_line": "I was checking the app listing and saw login friction.",
            "edited_final_opener": "I was checking the app listing and reviews say login is unclear, which could add friction before activation.",
            "evidence_used_for_copy": "App listing reviews say login is unclear.",
            "source_urls": "https://approvededit.com/app",
            "product_surface_type": "app_first_product",
            "sendability_decision": "Edit",
            "human_decision": "edit",
        },
    ]
    review_rows, _ = _client_rows(rows)
    delivery, review_needed, audit = strict_delivery_dataframe(pd.DataFrame(review_rows))
    assert len(review_rows) == 4
    assert audit.input_rows == 4
    assert len(delivery) == 2
    assert len(review_needed) == 2
    assert set(delivery["company"]) == {"Example", "Approved Edit"}


def test_duplicate_company_opener_is_blocked_from_delivery() -> None:
    line = "I was checking the app listing and reviews say signup is unclear, which could add friction before activation."
    rows = [
        {
            "company": "Example",
            "person": "Ava",
            "website": "https://example.com",
            "personalized_line": line,
            "evidence_found": "App listing reviews say signup is unclear.",
            "source_urls": "https://apps.apple.com/us/app/example/id123",
            "product_surface_type": "app_first_product",
            "human_decision": "unreviewed",
        },
        {
            "company": "Example",
            "person": "Ben",
            "website": "https://example.com",
            "personalized_line": line,
            "evidence_found": "App listing reviews say signup is unclear.",
            "source_urls": "https://apps.apple.com/us/app/example/id123",
            "product_surface_type": "app_first_product",
            "human_decision": "unreviewed",
        },
    ]
    delivery, review_needed, audit = strict_delivery_dataframe(pd.DataFrame(rows))
    assert len(delivery) == 0
    assert audit.excluded_policy_rows == 2
    assert set(review_needed["duplicate_company_opener"]) == {"yes"}
    assert all("duplicate_company_opener" in value for value in review_needed["delivery_exclusion_reason"])
    assert set(review_needed["review_action_recommendation"]) == {"make_contact_or_company_specific"}


def test_review_needed_has_priority_columns_and_is_sorted() -> None:
    rows = [
        {
            "company": "Reflectlyapp",
            "website": "https://reflectlyapp.com",
            "personalized_line": "I was checking out the website and noticed the download buttons are hard to read, which could cost app installs.",
            "evidence_found": "App Store reviews mention onboarding and paywall friction.",
            "source_urls": "https://apps.apple.com/us/app/reflectly/id123",
            "product_surface_type": "app_first_product",
            "app_review_themes": "paywall friction | onboarding confusion",
        },
        {
            "company": "Reflectly Pro",
            "website": "https://breathwrk.com",
            "personalized_line": "I was checking the Breathwrk App Store listing and saw paywall complaints.",
            "evidence_found": "App listing mentions paywall complaints.",
            "source_urls": "https://apps.apple.com/us/app/breathwrk/id123",
            "product_surface_type": "app_first_product",
        },
    ]
    _, review_needed, _ = strict_delivery_dataframe(pd.DataFrame(rows))
    assert {"review_priority_score", "review_priority_reason", "review_action_recommendation"}.issubset(review_needed.columns)
    assert review_needed.iloc[0]["review_action_recommendation"] == "replace_with_app_or_review_surface"
    assert int(review_needed.iloc[0]["review_priority_score"]) > int(review_needed.iloc[1]["review_priority_score"])
    assert review_needed.iloc[1]["review_action_recommendation"] == "fix_input_mapping_before_copy_review"


def test_delivery_export_writes_review_needed_file() -> None:
    with TemporaryDirectory() as tmp:
        delivery_path = Path(tmp) / "delivery.xlsx"
        review_needed_path = Path(tmp) / "review_needed.xlsx"
        audit = export_delivery_rows(
            [
                {
                    "company_name": "Example",
                    "website_url": "https://example.com",
                    "opening_line": "I was checking the app listing and reviews say signup is unclear, which could add friction before activation.",
                    "evidence_used_for_copy": "App listing reviews say signup is unclear.",
                    "source_urls": "https://example.com/app",
                    "product_surface_type": "app_first_product",
                    "human_decision": "unreviewed",
                },
                {
                    "company_name": "Reject Me",
                    "website_url": "https://rejectme.com",
                    "opening_line": "I downloaded the app and loved it.",
                    "evidence_used_for_copy": "App listing exists.",
                    "source_urls": "https://rejectme.com/app",
                    "product_surface_type": "app_first_product",
                    "human_decision": "reject",
                },
            ],
            delivery_path,
            review_needed_path,
        )
        delivery_df = pd.read_excel(delivery_path, sheet_name="Delivery", dtype=str).fillna("")
        review_needed_df = pd.read_excel(review_needed_path, sheet_name="Review Needed", dtype=str).fillna("")
    assert audit.input_rows == 2
    assert len(delivery_df) == 1
    assert len(review_needed_df) == 1
    assert delivery_df.loc[0, "company"] == "Example"
    assert "review_action_recommendation" in review_needed_df.columns


def test_client_workspace_roundtrip() -> None:
    with TemporaryDirectory() as tmp:
        original_dir = client_workspaces.CLIENT_WORKSPACES_DIR
        client_workspaces.CLIENT_WORKSPACES_DIR = Path(tmp)
        try:
            save_client_workspace(
                ClientWorkspace(
                    client_id="William Mathews",
                    display_name="William Mathews",
                    tone_profile="friction_first",
                    default_campaign_context="Context",
                    default_research_region="us",
                    default_export_preset="generic",
                )
            )
            loaded = load_client_workspace("william_mathews")
            assert loaded is not None
            assert loaded.default_campaign_context == "Context"
            assert [workspace.client_id for workspace in list_client_workspaces()] == ["william_mathews"]
        finally:
            client_workspaces.CLIENT_WORKSPACES_DIR = original_dir


if __name__ == "__main__":
    test_preflight_without_api_key_is_not_blocking()
    test_prompt_hashes_are_stable_shape()
    test_sending_tool_mapping_prefers_approved_edit()
    test_client_review_export_includes_multishot_options()
    test_export_preserves_original_input_columns_first_and_prefixes_collision()
    test_review_export_includes_all_rows_but_delivery_export_is_strict()
    test_duplicate_company_opener_is_blocked_from_delivery()
    test_review_needed_has_priority_columns_and_is_sorted()
    test_delivery_export_writes_review_needed_file()
    test_client_workspace_roundtrip()
    print("preflight_and_export_tests_ok")
