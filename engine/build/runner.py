"""Orchestrates BUILD: turn one 'passed' signal into a Bridge draft.
Mirrors the TRIAGE runner's philosophy — a transient API failure or a
malformed LLM response never crashes the run and never fabricates a
draft; the signal is simply left in its current status for a future
`engine build` retry.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from engine import db as db_module
from engine.build.bridge import evaluate_bridge
from engine.build.llm import generate_draft
from engine.llm_errors import TRANSIENT_LLM_ERRORS
from engine.models import STATUS_DRAFTED, STATUS_PASSED, Draft, Signal

logger = logging.getLogger("engine.build")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BuildOutcome:
    def __init__(self, signal_id: str, outcome: str, detail: str = "", draft_id: Optional[int] = None):
        self.signal_id = signal_id
        self.outcome = outcome  # "drafted" | "skipped" | "error"
        self.detail = detail
        self.draft_id = draft_id


def _row_to_signal(row: sqlite3.Row) -> Signal:
    return Signal(
        id=row["id"], source=row["source"], sector=row["sector"],
        title=row["title"], url=row["url"], dedup_key=row["dedup_key"],
        ingested_at=row["ingested_at"], summary=row["summary"] or "",
        published_at=row["published_at"], raw_payload=row["raw_payload"],
        status=row["status"],
    )


def _latest_triage_result(conn: sqlite3.Connection, signal_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT reasoning, second_order_read, suggested_falsifier FROM triage_results "
        "WHERE signal_id = ? ORDER BY id DESC LIMIT 1",
        (signal_id,),
    ).fetchone()


def build_one(conn: sqlite3.Connection, signal_id: str, model: str) -> BuildOutcome:
    row = db_module.get_signal(conn, signal_id)
    if row is None:
        return BuildOutcome(signal_id, "error", f"no signal with id {signal_id!r}")

    # A signal is buildable once it has passed triage, and stays buildable
    # afterwards so a new revision can be requested without re-triaging.
    if row["status"] not in (STATUS_PASSED, STATUS_DRAFTED):
        return BuildOutcome(
            signal_id, "error",
            f"signal {signal_id!r} has status {row['status']!r}; "
            f"must be {STATUS_PASSED!r} or {STATUS_DRAFTED!r} to build",
        )

    triage_row = _latest_triage_result(conn, signal_id)
    signal = _row_to_signal(row)
    now = _now_iso()

    try:
        raw_response = generate_draft(
            signal,
            triage_reasoning=triage_row["reasoning"] if triage_row else "",
            second_order_read=triage_row["second_order_read"] if triage_row else "",
            suggested_falsifier=triage_row["suggested_falsifier"] if triage_row else "",
            model=model,
        )
    except TRANSIENT_LLM_ERRORS as e:
        logger.warning(
            "LLM call failed for signal %s (%r): %s - leaving as %r for a future run",
            signal_id, signal.title, e, row["status"],
        )
        return BuildOutcome(signal_id, "skipped", str(e))

    evaluation = evaluate_bridge(raw_response)
    if not evaluation.ok:
        logger.warning(
            "malformed Bridge draft for signal %s - leaving as %r for a future run",
            signal_id, row["status"],
        )
        return BuildOutcome(signal_id, "skipped", evaluation.error or "malformed LLM output")

    revision = db_module.latest_draft_revision(conn, signal_id) + 1
    draft = Draft(
        signal_id=signal_id, revision=revision,
        observable=evaluation.observable, mechanism=evaluation.mechanism,
        assumption=evaluation.assumption, consequence=evaluation.consequence,
        falsifier=evaluation.falsifier, created_at=now,
    )
    draft_id = db_module.insert_draft(conn, draft)
    if row["status"] != STATUS_DRAFTED:
        db_module.update_signal_status(conn, signal_id, STATUS_DRAFTED, now)
    return BuildOutcome(signal_id, "drafted", draft_id=draft_id)
