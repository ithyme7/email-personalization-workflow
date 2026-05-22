from __future__ import annotations

from pathlib import Path
import tempfile

import feedback
from feedback import SendFeedback
from impact_analyzer import build_feedback_context


def _sample_feedback(row_id: str, converted: bool) -> SendFeedback:
    return SendFeedback(
        run_id="run-1",
        row_id=row_id,
        example_id=f"example-{row_id}",
        company_name="Demo",
        recipient_name="Alex",
        recipient_role="Founder",
        website_url="https://example.com",
        opening_line="I was checking the app reviews and the signup complaints could hurt activation.",
        tailored_insight="Signup complaints are a useful friction angle.",
        chosen_angle="app_review: signup friction",
        friction_type="signup friction",
        conversion_outcome="activation",
        surface_checked="app reviews",
        was_opened=True,
        got_reply=converted,
        converted=converted,
    )


def test_feedback_summary_and_patterns_queries_run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        original_db = feedback.FEEDBACK_DB
        try:
            feedback.FEEDBACK_DB = Path(tmp) / "feedback.sqlite3"
            feedback.init_feedback_db()
            assert feedback.save_feedback(_sample_feedback("1", converted=True))
            assert feedback.save_feedback(_sample_feedback("2", converted=False))

            summary = feedback.get_feedback_summary()
            assert summary["total_sends"] == 2
            assert summary["by_angle_category"][0]["angle_category"] == "app_review"

            success_patterns = feedback.get_success_patterns()
            assert success_patterns
            assert success_patterns[0]["times_used"] == 2

            failing_patterns = feedback.get_failing_patterns()
            assert isinstance(failing_patterns, list)
            assert "FEEDBACK FROM PREVIOUS SENDS" in build_feedback_context()
        finally:
            feedback.FEEDBACK_DB = original_db
