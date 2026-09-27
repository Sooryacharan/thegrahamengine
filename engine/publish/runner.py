"""Orchestrates PUBLISH: assemble one approved draft into a publication.
Mirrors TRIAGE/BUILD — a transient API failure or malformed LLM response
never crashes the run and never fabricates a publication; the draft
stays 'approved' for a future `engine publish` retry.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from google.genai import errors

from engine import db as db_module
from engine.models import DRAFT_STATUS_APPROVED, DRAFT_STATUS_PUBLISHED, STATUS_PUBLISHED, Publication
from engine.publish.assembly import evaluate_publication
from engine.publish.llm import generate_publication

logger = logging.getLogger("engine.publish")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PublishOutcome:
    def __init__(self, draft_id: int, outcome: str, detail: str = "", publication_id: Optional[int] = None):
        self.draft_id = draft_id
        self.outcome = outcome  # "published" | "skipped" | "error"
        self.detail = detail
        self.publication_id = publication_id


def publish_one(conn: sqlite3.Connection, draft_id: int, model: str) -> PublishOutcome:
    draft_row = db_module.get_draft(conn, draft_id)
    if draft_row is None:
        return PublishOutcome(draft_id, "error", f"no draft with id {draft_id}")

    if draft_row["status"] != DRAFT_STATUS_APPROVED:
        return PublishOutcome(
            draft_id, "error",
            f"draft {draft_id} has status {draft_row['status']!r}; must be {DRAFT_STATUS_APPROVED!r} "
            f"(run `engine approve {draft_id}` first)",
        )

    signal_row = db_module.get_signal(conn, draft_row["signal_id"])
    if signal_row is None:
        return PublishOutcome(draft_id, "error", f"draft {draft_id} references missing signal {draft_row['signal_id']!r}")

    now = _now_iso()
    try:
        raw_response = generate_publication(
            sector=signal_row["sector"], source=signal_row["source"], title=signal_row["title"],
            observable=draft_row["observable"], mechanism=draft_row["mechanism"],
            assumption=draft_row["assumption"], consequence=draft_row["consequence"],
            falsifier=draft_row["falsifier"], model=model,
        )
    except errors.APIError as e:
        logger.warning(
            "LLM call failed for draft %s: %s - leaving as %r for a future run",
            draft_id, e, DRAFT_STATUS_APPROVED,
        )
        return PublishOutcome(draft_id, "skipped", str(e))

    evaluation = evaluate_publication(raw_response)
    if not evaluation.ok:
        logger.warning("malformed publication for draft %s - leaving as %r for a future run", draft_id, DRAFT_STATUS_APPROVED)
        return PublishOutcome(draft_id, "skipped", evaluation.error or "malformed LLM output")

    pub = Publication(
        draft_id=draft_id, hook=evaluation.hook, context=evaluation.context,
        falsifier_line=evaluation.falsifier_line, payoff_line=evaluation.payoff_line,
        carousel_json=evaluation.carousel_json, caption_text=evaluation.caption_text,
        created_at=now,
    )
    pub_id = db_module.insert_publication(conn, pub)
    db_module.update_draft_status(conn, draft_id, DRAFT_STATUS_PUBLISHED)
    db_module.update_signal_status(conn, signal_row["id"], STATUS_PUBLISHED, now)
    return PublishOutcome(draft_id, "published", publication_id=pub_id)
