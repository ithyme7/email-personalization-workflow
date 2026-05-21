from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from batch_runner import _select_recommended_opener
from models import PersonalizationDraft, QCResult
from sales_principles import evaluate_sales_principles


def _variant(index: int, line: str, decision: str, sendability_score: int, sales_score_line: str | None = None):
    sales = evaluate_sales_principles(
        sales_score_line or line,
        evidence="The app listing mentions signup confusion and activation drop-off.",
        source_url="https://example.com",
        angle="signup friction",
    )
    return {
        "index": index,
        "draft": PersonalizationDraft(opening_line=line),
        "qc": QCResult(score=9, passed=True, quality_flags=[]),
        "sales": sales,
        "sendability": {
            "sendability_decision": decision,
            "sendability_score": sendability_score,
            "hard_fail_reasons": "",
            "soft_edit_reasons": "",
            "sales_principles_summary": sales.sales_principles_summary,
        },
        "needs_review": decision != "Send",
    }


def test_recommended_opener_chooses_strongest_sendable_option() -> None:
    row = {}
    variants = [
        _variant(1, "Weak edit option", "Edit", 78),
        _variant(2, "I was checking the app listing and the signup confusion looks like a place where users could drop off before activation.", "Send", 91),
        _variant(3, "Another send option", "Send", 87),
    ]
    _select_recommended_opener(row, variants)
    assert row["recommended_opener_option"] == "option_2"
    assert row["selected_opener"] == variants[1]["draft"].opening_line


def test_no_sendable_option_when_all_options_are_weak() -> None:
    row = {}
    variants = [
        _variant(1, "Weak reject option", "Reject", 55),
        _variant(2, "Weak edit option", "Edit", 75),
    ]
    _select_recommended_opener(row, variants)
    assert row["recommended_opener"] == ""
    assert row["recommended_opener_option"] == "no_sendable_option"
    assert row["selected_opener"] == ""


if __name__ == "__main__":
    test_recommended_opener_chooses_strongest_sendable_option()
    test_no_sendable_option_when_all_options_are_weak()
    print("multishot_selection_tests_ok")
