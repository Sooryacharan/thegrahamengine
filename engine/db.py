"""SQLite access layer. Thin wrapper functions, no ORM.

Every function takes an explicit `sqlite3.Connection` — callers own the
connection lifecycle via `connect()`. This keeps the module trivially
testable with an in-memory or temp-file database.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from engine.models import Draft, Publication, Signal, TriageResult

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


@contextmanager
def connect(db_path: str) -> Iterator[sqlite3.Connection]:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        init_db(conn)
        yield conn
    finally:
        conn.close()


# --- signals -----------------------------------------------------------

def insert_signal_if_new(conn: sqlite3.Connection, signal: Signal) -> bool:
    """Insert a signal, ignoring it if dedup_key already exists.

    Returns True if a new row was inserted, False if it was a duplicate.
    Relies on the UNIQUE constraint on dedup_key rather than a separate
    SELECT-then-INSERT, so this is race-free under sequential use.
    """
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO signals
            (id, source, sector, title, url, summary, published_at,
             raw_payload, ingested_at, status, dedup_key)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            signal.id, signal.source, signal.sector, signal.title, signal.url,
            signal.summary, signal.published_at, signal.raw_payload,
            signal.ingested_at, signal.status, signal.dedup_key,
        ),
    )
    conn.commit()
    inserted = cur.rowcount > 0
    if inserted:
        record_transition(conn, signal.id, None, signal.status, signal.ingested_at)
    return inserted


def get_signal(conn: sqlite3.Connection, signal_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()


def list_signals(conn: sqlite3.Connection, status: Optional[str] = None) -> list[sqlite3.Row]:
    if status is None:
        return conn.execute("SELECT * FROM signals ORDER BY ingested_at DESC").fetchall()
    return conn.execute(
        "SELECT * FROM signals WHERE status = ? ORDER BY ingested_at DESC", (status,)
    ).fetchall()


def update_signal_status(conn: sqlite3.Connection, signal_id: str, new_status: str, timestamp: str) -> None:
    row = get_signal(conn, signal_id)
    if row is None:
        raise ValueError(f"no signal with id {signal_id}")
    old_status = row["status"]
    conn.execute("UPDATE signals SET status = ? WHERE id = ?", (new_status, signal_id))
    record_transition(conn, signal_id, old_status, new_status, timestamp)
    conn.commit()


def record_transition(conn: sqlite3.Connection, signal_id: str, from_status: Optional[str], to_status: str, timestamp: str) -> None:
    conn.execute(
        "INSERT INTO status_transitions (signal_id, from_status, to_status, transitioned_at) VALUES (?, ?, ?, ?)",
        (signal_id, from_status, to_status, timestamp),
    )
    conn.commit()


# --- triage_results ------------------------------------------------------

def insert_triage_result(conn: sqlite3.Connection, result: TriageResult) -> int:
    cur = conn.execute(
        """
        INSERT INTO triage_results
            (signal_id, rules_prefilter_passed, rules_prefilter_reason,
             gate1_pass, gate2_pass, gate3_pass, reasoning, second_order_read,
             suggested_falsifier, confidence, failing_gate, llm_raw_response, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result.signal_id, int(result.rules_prefilter_passed), result.rules_prefilter_reason,
            result.gate1_pass, result.gate2_pass, result.gate3_pass, result.reasoning,
            result.second_order_read, result.suggested_falsifier, result.confidence,
            result.failing_gate, result.llm_raw_response, result.created_at,
        ),
    )
    conn.commit()
    return cur.lastrowid


# --- drafts ----------------------------------------------------------------

def latest_draft_revision(conn: sqlite3.Connection, signal_id: str) -> int:
    row = conn.execute(
        "SELECT MAX(revision) AS max_rev FROM drafts WHERE signal_id = ?", (signal_id,)
    ).fetchone()
    return row["max_rev"] or 0


def insert_draft(conn: sqlite3.Connection, draft: Draft) -> int:
    if not draft.falsifier or not draft.falsifier.strip():
        raise ValueError("draft rejected: falsifier is required and cannot be empty")
    cur = conn.execute(
        """
        INSERT INTO drafts
            (signal_id, revision, observable, mechanism, assumption, consequence, falsifier, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            draft.signal_id, draft.revision, draft.observable, draft.mechanism,
            draft.assumption, draft.consequence, draft.falsifier, draft.status, draft.created_at,
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_draft(conn: sqlite3.Connection, draft_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()


def list_drafts(conn: sqlite3.Connection, status: Optional[str] = None) -> list[sqlite3.Row]:
    if status is None:
        return conn.execute("SELECT * FROM drafts ORDER BY created_at DESC").fetchall()
    return conn.execute(
        "SELECT * FROM drafts WHERE status = ? ORDER BY created_at DESC", (status,)
    ).fetchall()


def update_draft_status(conn: sqlite3.Connection, draft_id: int, new_status: str) -> None:
    conn.execute("UPDATE drafts SET status = ? WHERE id = ?", (new_status, draft_id))
    conn.commit()


# --- publications ------------------------------------------------------

def insert_publication(conn: sqlite3.Connection, pub: Publication) -> int:
    cur = conn.execute(
        """
        INSERT INTO publications
            (draft_id, hook, context, falsifier_line, payoff_line, carousel_json, caption_text, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pub.draft_id, pub.hook, pub.context, pub.falsifier_line,
            pub.payoff_line, pub.carousel_json, pub.caption_text, pub.created_at,
        ),
    )
    conn.commit()
    return cur.lastrowid
