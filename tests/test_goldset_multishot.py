from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sendability import rows_for_goldset


def test_goldset_stores_selected_and_non_selected_options() -> None:
    df = pd.DataFrame(
        [
            {
                "row_id": "1",
                "run_id": "run",
                "company": "Example",
                "person": "Jane",
                "website": "https://example.com",
                "personalized_line": "Option one",
                "selected_opener": "Option two",
                "selected_opener_source": "option_2",
                "edited_final_opener": "Edited final opener",
                "human_decision": "edit",
                "edit_reason_category": "tone",
                "edit_notes": "More natural.",
                "opener_option_1": "Option one",
                "opener_option_1_angle": "proof gap",
                "opener_option_1_evidence": "Evidence one",
                "opener_option_1_sendability": "Edit",
                "opener_option_1_sales_principles_summary": "Edit: weak bridge",
                "opener_option_2": "Option two",
                "opener_option_2_angle": "signup friction",
                "opener_option_2_evidence": "Evidence two",
                "opener_option_2_sendability": "Send",
                "opener_option_2_sales_principles_summary": "Send: specific",
                "opener_option_3": "Option three",
                "opener_option_3_angle": "target customer",
                "opener_option_3_evidence": "Evidence three",
                "opener_option_3_sendability": "Reject",
                "opener_option_3_sales_principles_summary": "Reject: unsupported",
                "source_urls": "https://example.com",
                "evidence_found": "Evidence two",
            }
        ]
    )
    goldset = rows_for_goldset(df, split="reviewed_examples")
    row = goldset.iloc[0]
    assert row["selected_opener"] == "Option two"
    assert row["selected_opener_source"] == "option_2"
    assert row["edited_final_opener"] == "Edited final opener"
    assert row["opener_option_1"] == "Option one"
    assert row["opener_option_3"] == "Option three"
    assert "Option one" in row["non_selected_opener_options"]
    assert "Option three" in row["non_selected_opener_options"]
    assert row["edit_reason_category"] == "tone"


if __name__ == "__main__":
    test_goldset_stores_selected_and_non_selected_options()
    print("goldset_multishot_tests_ok")
