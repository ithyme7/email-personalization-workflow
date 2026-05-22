"""Feedback module — koppelt daadwerkelijke send-resultaten terug aan de pipeline.

Stelt de gebruiker in staat om per lead open/reply/conversion resultaten
in te voeren, slaat ze op in SQLite, en analyseert succespatronen die
bij volgende runs als extra LLM-context worden meegestuurd.
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from config import DATA_DIR


FEEDBACK_DB = DATA_DIR / "feedback.sqlite3"


@dataclass
class SendFeedback:
    """Resultaat van een daadwerkelijk verstuurde email."""
    run_id: str
    row_id: str
    example_id: str
    company_name: str
    recipient_name: str
    recipient_role: str
    website_url: str
    opening_line: str
    tailored_insight: str
    chosen_angle: str
    friction_type: str
    conversion_outcome: str
    surface_checked: str
    # Feedback
    was_opened: bool = False
    got_reply: bool = False
    reply_text: str = ""
    converted: bool = False
    conversion_type: str = ""  # "meeting", "demo", "trial", "sale", "partnership"
    conversion_notes: str = ""
    time_to_reply_minutes: int = 0
    sent_at: str = ""  # ISO format
    reviewed_at: str = ""  # ISO format, wanneer feedback werd ingevoerd

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Zorg dat booleans als 0/1 worden opgeslagen voor SQLite
        d["was_opened"] = 1 if d["was_opened"] else 0
        d["got_reply"] = 1 if d["got_reply"] else 0
        d["converted"] = 1 if d["converted"] else 0
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SendFeedback":
        bool_fields = {"was_opened", "got_reply", "converted"}
        for bf in bool_fields:
            if bf in d:
                d[bf] = bool(d[bf]) if not isinstance(d[bf], bool) else d[bf]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _connect() -> sqlite3.Connection:
    FEEDBACK_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(FEEDBACK_DB))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_feedback_db() -> None:
    """Maakt de feedback-tabel aan als die nog niet bestaat."""
    conn = _connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS send_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                row_id TEXT NOT NULL,
                example_id TEXT NOT NULL,
                company_name TEXT NOT NULL,
                recipient_name TEXT,
                recipient_role TEXT,
                website_url TEXT,
                opening_line TEXT,
                tailored_insight TEXT,
                chosen_angle TEXT,
                friction_type TEXT,
                conversion_outcome TEXT,
                surface_checked TEXT,
                was_opened INTEGER DEFAULT 0,
                got_reply INTEGER DEFAULT 0,
                reply_text TEXT,
                converted INTEGER DEFAULT 0,
                conversion_type TEXT,
                conversion_notes TEXT,
                time_to_reply_minutes INTEGER DEFAULT 0,
                sent_at TEXT,
                reviewed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(run_id, row_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_feedback_company
            ON send_feedback(company_name)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_feedback_run
            ON send_feedback(run_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_feedback_converted
            ON send_feedback(converted)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_feedback_friction
            ON send_feedback(friction_type)
        """)
        conn.commit()
    finally:
        conn.close()


def save_feedback(feedback: SendFeedback) -> bool:
    """Slaat feedback op of update bestaande record.

    Returns True als het opgeslagen is, False als het genegegeerd werd.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    d = feedback.to_dict()
    d["updated_at"] = now

    conn = _connect()
    try:
        # Check of er al een record bestaat voor deze run_id + row_id
        existing = conn.execute(
            "SELECT id FROM send_feedback WHERE run_id = ? AND row_id = ?",
            (feedback.run_id, feedback.row_id),
        ).fetchone()

        if existing:
            # Update bestaand record (behoud originele created_at)
            conn.execute(
                """UPDATE send_feedback SET
                    company_name = ?, recipient_name = ?, recipient_role = ?,
                    website_url = ?, opening_line = ?, tailored_insight = ?,
                    chosen_angle = ?, friction_type = ?, conversion_outcome = ?,
                    surface_checked = ?, was_opened = ?, got_reply = ?,
                    reply_text = ?, converted = ?, conversion_type = ?,
                    conversion_notes = ?, time_to_reply_minutes = ?,
                    sent_at = ?, reviewed_at = ?, updated_at = ?
                WHERE run_id = ? AND row_id = ?""",
                (
                    d["company_name"], d["recipient_name"], d["recipient_role"],
                    d["website_url"], d["opening_line"], d["tailored_insight"],
                    d["chosen_angle"], d["friction_type"], d["conversion_outcome"],
                    d["surface_checked"], d["was_opened"], d["got_reply"],
                    d["reply_text"], d["converted"], d["conversion_type"],
                    d["conversion_notes"], d["time_to_reply_minutes"],
                    d.get("sent_at", ""), d.get("reviewed_at", ""),
                    d["updated_at"], feedback.run_id, feedback.row_id,
                ),
            )
            conn.commit()
            return True
        else:
            # Insert nieuw record
            d["created_at"] = now
            columns = ", ".join(d.keys())
            placeholders = ", ".join("?" * len(d))
            conn.execute(
                f"INSERT INTO send_feedback ({columns}) VALUES ({placeholders})",
                list(d.values()),
            )
            conn.commit()
            return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def save_feedback_batch(feedbacks: list[SendFeedback]) -> int:
    """Slaat een batch feedback op. Returns aantal succesvol opgeslagen."""
    init_feedback_db()
    saved = 0
    for fb in feedbacks:
        if save_feedback(fb):
            saved += 1
    return saved


def load_feedback(run_id: str | None = None) -> list[SendFeedback]:
    """Laadt feedback, optionaal gefilterd op run_id."""
    init_feedback_db()
    conn = _connect()
    try:
        if run_id:
            rows = conn.execute(
                "SELECT * FROM send_feedback WHERE run_id = ? ORDER BY updated_at DESC",
                (run_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM send_feedback ORDER BY updated_at DESC"
            ).fetchall()

        columns = [desc[0] for desc in conn.execute("SELECT * FROM send_feedback LIMIT 1").description]
        feedbacks = []
        for row in rows:
            d = dict(zip(columns, row))
            feedbacks.append(SendFeedback.from_dict(d))
        return feedbacks
    finally:
        conn.close()


def get_feedback_summary() -> dict[str, Any]:
    """Geeft een samenvatting van alle feedback voor analyse."""
    init_feedback_db()
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM send_feedback").fetchone()[0]
        opened = conn.execute("SELECT COUNT(*) FROM send_feedback WHERE was_opened = 1").fetchone()[0]
        replied = conn.execute("SELECT COUNT(*) FROM send_feedback WHERE got_reply = 1").fetchone()[0]
        converted = conn.execute("SELECT COUNT(*) FROM send_feedback WHERE converted = 1").fetchone()[0]

        # Success rates per friction type
        friction_stats = conn.execute("""
            SELECT friction_type,
                   COUNT(*) as total,
                   SUM(was_opened) as opened,
                   SUM(got_reply) as replied,
                   SUM(converted) as converted
            FROM send_feedback
            WHERE friction_type != ''
            GROUP BY friction_type
            ORDER BY converted DESC
        """).fetchall()

        # Success rates per angle
        angle_stats = conn.execute("""
            SUBSTR(chosen_angle, 1, INSTR(chosen_angle, ':') - 1) as angle_category,
            COUNT(*) as total,
            SUM(converted) as converted,
            SUM(got_reply) as replied
            FROM send_feedback
            WHERE chosen_angle != ''
            GROUP BY angle_category
            ORDER BY converted DESC
        """).fetchall()

        # Avg reply time
        avg_reply_time = conn.execute(
            "SELECT AVG(time_to_reply_minutes) FROM send_feedback WHERE time_to_reply_minutes > 0"
        ).fetchone()[0] or 0

        return {
            "total_sends": total,
            "opened": opened,
            "replied": replied,
            "converted": converted,
            "open_rate": round(opened / total * 100, 1) if total else 0,
            "reply_rate": round(replied / total * 100, 1) if total else 0,
            "conversion_rate": round(converted / total * 100, 1) if total else 0,
            "avg_reply_time_minutes": round(avg_reply_time),
            "by_friction_type": [
                {
                    "friction_type": r[0],
                    "total": r[1],
                    "opened": r[2],
                    "replied": r[3],
                    "converted": r[4],
                    "conversion_rate": round(r[4] / r[1] * 100, 1) if r[1] else 0,
                }
                for r in friction_stats
            ],
            "by_angle_category": [
                {
                    "angle_category": r[0],
                    "total": r[1],
                    "converted": r[2],
                    "replied": r[3],
                    "conversion_rate": round(r[2] / r[1] * 100, 1) if r[1] else 0,
                }
                for r in angle_stats
            ],
        }
    finally:
        conn.close()


def get_success_patterns(limit: int = 20) -> list[dict[str, Any]]:
    """Haalt de meest succesvolle email patronen op voor LLM-context.

    Returns een lijst van patronen die als 'succes signals' in de
    generatieprompt kunnen worden meegestuurd.
    """
    init_feedback_db()
    conn = _connect()
    try:
        # Patronen: wat werkt er het best per combinatie van angle + surface + tone
        patterns = conn.execute("""
            SELECT
                chosen_angle,
                friction_type,
                surface_checked,
                conversion_outcome,
                product_surface_type,
                COUNT(*) as times_used,
                SUM(converted) as conversions,
                SUM(got_reply) as replies,
                SUM(was_opened) as opens,
                ROUND(CAST(SUM(converted) AS FLOAT) / COUNT(*) * 100, 1) as conv_rate,
                GROUP_CONCAT(DISTINCT opening_line) as example_opening_lines
            FROM send_feedback
            WHERE chosen_angle != '' AND times_used >= 1
            GROUP BY chosen_angle, friction_type, surface_checked
            HAVING COUNT(*) >= 1
            ORDER BY conversions DESC, conv_rate DESC
            LIMIT ?
        """, (limit,)).fetchall()

        columns = [
            "chosen_angle", "friction_type", "surface_checked",
            "conversion_outcome", "product_surface_type", "times_used",
            "conversions", "replies", "opens", "conv_rate",
            "example_opening_lines",
        ]

        result = []
        for row in patterns:
            d = dict(zip(columns, row))
            d["conv_rate"] = float(d["conv_rate"] or 0)
            result.append(d)
        return result
    finally:
        conn.close()


def get_failing_patterns(limit: int = 20) -> list[dict[str, Any]]:
    """Haalt de meest falende email patronen op — wat moeten we vermijden."""
    init_feedback_db()
    conn = _connect()
    try:
        patterns = conn.execute("""
            SELECT
                chosen_angle,
                friction_type,
                surface_checked,
                count(*) as times_used,
                SUM(converted) as conversions,
                ROUND(CAST(SUM(converted) AS FLOAT) / COUNT(*) * 100, 1) as conv_rate
            FROM send_feedback
            WHERE chosen_angle != ''
            GROUP BY chosen_angle, friction_type, surface_checked
            HAVING COUNT(*) >= 2 AND SUM(converted) = 0
            ORDER BY times_used DESC
            LIMIT ?
        """, (limit,)).fetchall()

        columns = ["chosen_angle", "friction_type", "surface_checked", "times_used", "conversions", "conv_rate"]
        return [dict(zip(columns, row)) for row in patterns]
    finally:
        conn.close()


def store_generated_emails(rows: list[dict[str, Any]]) -> int:
    """Slaat gegenereerde emails op als feedback records (pending status).

    Dit wordt aangeroepen na elke run zodat de emails later
    bijgewerkt kunnen worden met daadwerkelijke open/reply/conversion data.
    """
    init_feedback_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stored = 0
    conn = _connect()
    try:
        for row in rows:
            opening_line = str(row.get("final_delivery_line") or row.get("opening_line") or "")
            if not opening_line or opening_line.startswith("["):
                continue

            fb = SendFeedback(
                run_id=str(row.get("run_id", "")),
                row_id=str(row.get("row_id", "")),
                example_id=str(row.get("example_id", "")),
                company_name=str(row.get("company_name", "")),
                recipient_name=str(row.get("recipient_name", "")),
                recipient_role=str(row.get("role", "")),
                website_url=str(row.get("website_url", "")),
                opening_line=opening_line,
                tailored_insight=str(row.get("tailored_insight", "")),
                chosen_angle=str(row.get("chosen_angle", "")),
                friction_type=str(row.get("friction_type", "")),
                conversion_outcome=str(row.get("conversion_outcome", "")),
                surface_checked=str(row.get("surface_checked", "")),
                sent_at=now,
            )
            if save_feedback(fb):
                stored += 1
        return stored
    finally:
        conn.close()


def ingest_feedback_results(
    run_id: str,
    results: list[dict[str, Any]],
) -> int:
    """Verwerk daadwerkelijke send-resultaten terug naar de feedback-database.

    Args:
        run_id: De run_id van de batch run
        results: Lijst van dicts met keys: row_id/example_id,
                 was_opened, got_reply, reply_text, converted,
                 conversion_type, conversion_notes, time_to_reply_minutes

    Returns:
        Aantal bijgewerkte records.
    """
    init_feedback_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updated = 0
    conn = _connect()
    try:
        for r in results:
            ident = r.get("example_id", "") or r.get("row_id", "")
            if not ident:
                continue

            row = conn.execute(
                "SELECT id FROM send_feedback WHERE run_id = ? AND row_id = ?",
                (run_id, str(ident)),
            ).fetchone()

            if not row:
                continue

            setters: list[str] = []
            values: list[Any] = []

            if "was_opened" in r:
                setters.append("was_opened = ?")
                values.append(1 if r["was_opened"] else 0)
            if "got_reply" in r:
                setters.append("got_reply = ?")
                values.append(1 if r["got_reply"] else 0)
            if "reply_text" in r:
                setters.append("reply_text = ?")
                values.append(str(r["reply_text"]))
            if "converted" in r:
                setters.append("converted = ?")
                values.append(1 if r["converted"] else 0)
            if "conversion_type" in r:
                setters.append("conversion_type = ?")
                values.append(str(r["conversion_type"]))
            if "conversion_notes" in r:
                setters.append("conversion_notes = ?")
                values.append(str(r["conversion_notes"]))
            if "time_to_reply_minutes" in r:
                setters.append("time_to_reply_minutes = ?")
                values.append(int(r["time_to_reply_minutes"]))

            if not setters:
                continue

            setters.append("reviewed_at = ?")
            values.append(now)
            values.extend([run_id, str(ident)])

            conn.execute(
                f"UPDATE send_feedback SET {', '.join(setters)} WHERE run_id = ? AND row_id = ?",
                values,
            )
            updated += 1

        conn.commit()
        return updated
    finally:
        conn.close()