from __future__ import annotations

from pathlib import Path
import sys
import tempfile

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import campaign_feedback


def test_campaign_feedback_import_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        original_dir = campaign_feedback.CAMPAIGN_FEEDBACK_DIR
        original_file = campaign_feedback.CAMPAIGN_FEEDBACK_FILE
        try:
            campaign_feedback.CAMPAIGN_FEEDBACK_DIR = Path(tmp)
            campaign_feedback.CAMPAIGN_FEEDBACK_FILE = Path(tmp) / "campaign_results.csv"
            source = pd.DataFrame(
                [
                    {
                        "campaign_name": "pilot",
                        "company": "Demo",
                        "person": "Alex",
                        "website": "https://example.com",
                        "delivered_line": "I was checking the app and signup looks slow.",
                        "sent": "yes",
                        "opened": "yes",
                        "replied": "yes",
                        "positive_reply": "yes",
                        "booked": "no",
                    }
                ]
            )
            input_path = Path(tmp) / "input.csv"
            source.to_csv(input_path, index=False)
            path, count, normalized = campaign_feedback.append_campaign_feedback(input_path)
            assert path.exists()
            assert count == 1
            assert normalized.iloc[0]["replied"] == "yes"
            loaded = campaign_feedback.load_campaign_feedback()
            assert len(loaded) == 1
        finally:
            campaign_feedback.CAMPAIGN_FEEDBACK_DIR = original_dir
            campaign_feedback.CAMPAIGN_FEEDBACK_FILE = original_file


if __name__ == "__main__":
    test_campaign_feedback_import_roundtrip()
    print("campaign_feedback_tests_ok")
