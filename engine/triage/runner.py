"""Orchestrates a triage run: cheap rules prefilter first, then LLM gate
scoring for anything that survives it. Each signal's outcome — discarded
at the rules layer, discarded at a gate, passed, or skipped due to a
transient API error — is independent; one signal's failure never aborts
the run.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from google.genai import errors

from engine import db as db_module
from engine.models import STATUS_DISCARDED, STATUS_PASSED, Signal, TriageResult
from engine.triage.gates import evaluate_gates
from engine.triage.llm import score_signal
from engine.triage.rules import rules_prefilter

logger = logging.getLogger("engine.triage")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TriageOutcome:
    def __init__(self, signal_id: str, title: str, outcome: str, detail: str = ""):
        self.signal_id = signal_id
        self.title = title
        self.outcome = outcome  # "discarded" | "passed" | "skipped"
        self.detail = detail


def _row_to_signal(row: sqlite3.Row) -> Signal:
    return Signal(
        id=row["id"], source=row["source"], sector=row["sector"],
        title=row["title"], url=row["url"], dedup_key=row["dedup_key"],
        ingested_at=row["ingested_at"], summary=row["summary"] or "",
        published_at=row["published_at"], raw_payload=row["raw_payload"],
        status=row["status"],
    )


def triage_one(conn: sqlite3.Connection, signal_row: sqlite3.Row, model: str) -> TriageOutcome:
    signal_id = signal_row["id"]
    title = signal_row["title"]
    now = _now_iso()

    rules_result = rules_prefilter(title, signal_row["summary"] or "")
    if not rules_result.passed:
        db_module.insert_triage_result(conn, TriageResult(
            signal_id=signal_id,
            rules_prefilter_passed=False,
            rules_prefilter_reason=rules_result.reason,
            failing_gate="rules_prefilter",
            created_at=now,
        ))
        db_module.update_signal_status(conn, signal_id, STATUS_DISCARDED, now)
        return TriageOutcome(signal_id, title, "discarded", rules_result.reason or "")

    try:
        raw_response = score_signal(_row_to_signal(signal_row), model=model)
    except errors.APIError as e:
        logger.warning("LLM call failed for signal %s (%r): %s - leaving as ingested for a future run", signal_id, title, e)
        return TriageOutcome(signal_id, title, "skipped", str(e))

    evaluation = evaluate_gates(raw_response)
    db_module.insert_triage_result(conn, TriageResult(
        signal_id=signal_id,
        rules_prefilter_passed=True,
        gate1_pass=evaluation.gate1_pass,
        gate2_pass=evaluation.gate2_pass,
        gate3_pass=evaluation.gate3_pass,
        reasoning=evaluation.reasoning,
        second_order_read=evaluation.second_order_read,
        suggested_falsifier=evaluation.suggested_falsifier,
        confidence=evaluation.confidence,
        failing_gate=evaluation.failing_gate,
        llm_raw_response=evaluation.raw_response,
        created_at=now,
    ))

    new_status = STATUS_PASSED if evaluation.passed else STATUS_DISCARDED
    db_module.update_signal_status(conn, signal_id, new_status, now)
    detail = evaluation.failing_gate or "" if not evaluation.passed else ""
    return TriageOutcome(signal_id, title, "passed" if evaluation.passed else "discarded", detail)


def run_triage(conn: sqlite3.Connection, model: str) -> list[TriageOutcome]:
    ingested = db_module.list_signals(conn, status="ingested")
    return [triage_one(conn, row, model) for row in ingested]
