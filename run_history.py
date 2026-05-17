from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config import DATA_DIR


HISTORY_DIR = DATA_DIR / "run_history"
HISTORY_FILE = HISTORY_DIR / "history.jsonl"
HISTORY_DB = HISTORY_DIR / "runs.sqlite3"


def _as_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    return value


def _connect() -> sqlite3.Connection:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(HISTORY_DB)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at)")
    return conn


def append_run_history(record: dict[str, Any]) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **{key: _as_jsonable(value) for key, value in record.items()},
    }
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO runs (created_at, payload_json) VALUES (?, ?)",
            (payload["created_at"], json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def _load_jsonl_history(limit: int) -> pd.DataFrame:
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


def load_run_history(limit: int = 50) -> pd.DataFrame:
    if HISTORY_DB.exists():
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT payload_json FROM runs ORDER BY id DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        finally:
            conn.close()
        records: list[dict[str, Any]] = []
        for (payload_json,) in rows:
            try:
                records.append(json.loads(payload_json))
            except json.JSONDecodeError:
                continue
        return pd.DataFrame(records)
    return _load_jsonl_history(limit)
