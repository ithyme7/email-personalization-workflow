from __future__ import annotations

from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_history


def test_sqlite_run_history_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        original_dir = run_history.HISTORY_DIR
        original_db = run_history.HISTORY_DB
        original_file = run_history.HISTORY_FILE
        try:
            run_history.HISTORY_DIR = Path(tmp)
            run_history.HISTORY_DB = Path(tmp) / "runs.sqlite3"
            run_history.HISTORY_FILE = Path(tmp) / "history.jsonl"
            run_history.append_run_history({"rows": 3, "output_file": Path("out.xlsx")})
            run_history.append_generated_email_rows(
                [
                    {
                        "run_id": "run1",
                        "row_id": "1",
                        "example_id": "ex1",
                        "company_name": "Example Co",
                        "recipient_name": "Jane Doe",
                        "website_url": "https://example.com",
                        "model_provider": "gemini",
                        "model_name": "gemini-3.1-flash-lite",
                        "tone_profile": "friction_first",
                        "prompt_set_hash": "a" * 64,
                        "write_prompt_hash": "b" * 64,
                        "opening_line": "I was checking the app and noticed the CTA is easy to miss.",
                    }
                ]
            )
            df = run_history.load_run_history()
            assert len(df) == 1
            assert int(df.iloc[0]["rows"]) == 3
            conn = run_history.sqlite3.connect(run_history.HISTORY_DB)
            try:
                stored = conn.execute("SELECT prompt_set_hash, write_prompt_hash FROM generated_emails").fetchone()
            finally:
                conn.close()
            assert stored == ("a" * 64, "b" * 64)
            assert df.iloc[0]["output_file"] == "out.xlsx"
        finally:
            run_history.HISTORY_DIR = original_dir
            run_history.HISTORY_DB = original_db
            run_history.HISTORY_FILE = original_file


if __name__ == "__main__":
    test_sqlite_run_history_roundtrip()
    print("run_history_tests_ok")
