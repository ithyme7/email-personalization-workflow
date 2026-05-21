from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client_safe_export import create_client_safe_package
from eval_runner import evaluate_frozen_goldset, evaluate_release_gate


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "frozen_eval_set.csv"


def test_frozen_eval_fixture_gate() -> None:
    summary, detail = evaluate_frozen_goldset(FIXTURE)
    passed, failures = evaluate_release_gate(
        summary,
        baseline_path=Path("__missing_baseline__.json"),
        thresholds={
            "min_send_precision": 90.0,
            "min_exact_agreement": 90.0,
            "max_false_sends": 0,
            "min_surface_correct_rate": 80.0,
            "min_app_first_surface_correct_rate": 90.0,
        },
    )
    assert passed, failures
    assert len(detail) == 3


def test_client_safe_package_redacts_sensitive_values() -> None:
    output_dir = Path(tempfile.mkdtemp(prefix="client_safe_test_"))
    try:
        df = pd.DataFrame(
            [
                {
                    "status": "Ready",
                    "human_decision": "send",
                    "company": "Example",
                    "person": "Taylor",
                    "role": "Founder",
                    "website": "https://example.com/path?token=secret-token-12345678901234567890",
                    "personalized_line": "I was checking the example app and signup comes before value, which could cost activation.",
                    "edited_line": "",
                    "evidence_found": "Source says contact test@example.com and API key abcdefghijklmnopqrstuvwxyz123456 were visible.",
                    "source_urls": "https://example.com/case?api_key=secret-token-12345678901234567890",
                    "product_surface_type": "app_first_product",
                    "sendability_decision": "Send",
                }
            ]
        )
        zip_path = create_client_safe_package(df, output_dir=output_dir, name="privacy_test")
        with zipfile.ZipFile(zip_path) as archive:
            csv_text = archive.read("client_safe_delivery.csv").decode("utf-8-sig")
            manifest = archive.read("manifest.json").decode("utf-8")
        combined = f"{csv_text}\n{manifest}"
        assert "test@example.com" not in combined
        assert "abcdefghijklmnopqrstuvwxyz123456" not in combined
        assert "secret-token-12345678901234567890" not in combined
        assert "[redacted" in combined
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def test_client_safe_package_excludes_unapproved_edit_and_reject_rows() -> None:
    output_dir = Path(tempfile.mkdtemp(prefix="client_safe_filter_test_"))
    try:
        df = pd.DataFrame(
            [
                {
                    "company": "Sendable",
                    "person": "Sam",
                    "website": "https://sendable.com",
                    "personalized_line": "I was checking the app listing and reviews say signup is unclear, which could add friction before activation.",
                    "evidence_found": "Reviews say signup is unclear.",
                    "source_urls": "https://sendable.com/app",
                    "product_surface_type": "app_first_product",
                    "sendability_decision": "Send",
                    "human_decision": "unreviewed",
                },
                {
                    "company": "Needs Edit",
                    "person": "Eli",
                    "website": "https://needsedit.com",
                    "personalized_line": "I was checking the app listing and saw login friction.",
                    "evidence_found": "App listing mentions login friction.",
                    "source_urls": "https://needsedit.com/app",
                    "product_surface_type": "app_first_product",
                    "sendability_decision": "Edit",
                    "human_decision": "edit",
                    "edited_final_opener": "",
                },
                {
                    "company": "Rejected",
                    "person": "Rae",
                    "website": "https://rejected.com",
                    "personalized_line": "I downloaded the app and loved it.",
                    "evidence_found": "App listing exists.",
                    "source_urls": "https://rejected.com/app",
                    "product_surface_type": "app_first_product",
                    "sendability_decision": "Reject",
                    "human_decision": "reject",
                },
            ]
        )
        zip_path = create_client_safe_package(df, output_dir=output_dir, name="filter_test")
        with zipfile.ZipFile(zip_path) as archive:
            csv_text = archive.read("client_safe_delivery.csv").decode("utf-8-sig")
            review_needed = archive.read("review_needed.csv").decode("utf-8-sig")
        assert "Sendable" in csv_text
        assert "Needs Edit" not in csv_text
        assert "Rejected" not in csv_text
        assert "Needs Edit" in review_needed
        assert "Rejected" in review_needed
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


if __name__ == "__main__":
    test_frozen_eval_fixture_gate()
    test_client_safe_package_redacts_sensitive_values()
    test_client_safe_package_excludes_unapproved_edit_and_reject_rows()
    print("privacy_and_sendability_tests_ok")
