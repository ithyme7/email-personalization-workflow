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
            df = run_history.load_run_history()
            assert len(df) == 1
            assert int(df.iloc[0]["rows"]) == 3
            assert df.iloc[0]["output_file"] == "out.xlsx"
        finally:
            run_history.HISTORY_DIR = original_dir
            run_history.HISTORY_DB = original_db
            run_history.HISTORY_FILE = original_file


if __name__ == "__main__":
    test_sqlite_run_history_roundtrip()
    print("run_history_tests_ok")
