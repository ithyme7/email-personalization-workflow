from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web_app import _review_download_df, _rows_to_review_df


def test_web_app_review_download_preserves_original_input_columns() -> None:
    review_df = _rows_to_review_df(
        [
            {
                "company_name": "Workflow Company",
                "recipient_name": "Helen",
                "recipient_role": "Founder",
                "website_url": "https://workflow.example",
                "opening_line": "I was checking the workflow app listing and saw signup friction, which could slow activation.",
                "evidence_used_for_copy": "App listing mentions signup friction.",
                "source_urls": "https://workflow.example",
                "sendability_decision": "Send",
                "human_decision": "unreviewed",
                "input__company": "Original Company",
                "input__Website": "https://original.example",
                "input__Custom Column": "custom",
            }
        ]
    )

    assert "input__company" in review_df.columns
    assert "input__Website" in review_df.columns

    download_df = _review_download_df(review_df)
    assert download_df.columns[:3].tolist() == ["company", "Website", "Custom Column"]
    assert download_df.loc[0, "company"] == "Original Company"
    assert download_df.loc[0, "workflow__company"] == "Workflow Company"
    assert download_df.loc[0, "Website"] == "https://original.example"
