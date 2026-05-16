from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config import DATA_DIR


HISTORY_DIR = DATA_DIR / "run_history"
HISTORY_FILE = HISTORY_DIR / "history.jsonl"


def _as_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    return value


def append_run_history(record: dict[str, Any]) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **{key: _as_jsonable(value) for key, value in record.items()},
    }
    with HISTORY_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_run_history(limit: int = 50) -> pd.DataFrame:
    if not HISTORY_FILE.exists():
        return pd.DataFrame()
    records: list[dict[str, Any]] = []
    with HISTORY_FILE.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    records = records[-limit:]
    records.reverse()
    return pd.DataFrame(records)
