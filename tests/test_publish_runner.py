import json

import httpx
import pytest
from google.genai import errors

from engine import db as db_module
from engine.models import (
    DRAFT_STATUS_APPROVED,
    DRAFT_STATUS_DRAFT,
    DRAFT_STATUS_PUBLISHED,
    STATUS_PUBLISHED,
    Draft,
    Signal,
)
from engine.publish import runner as runner_module


@pytest.fixture
def conn(tmp_path):
    path = str(tmp_path / "test.db")
    with db_module.connect(path) as c:
        yield c


def make_signal(id_) -> Signal:
    return Signal(
        id=id_, source="Test Source", sector="commodities", title="Copper stocks fall sharply",
        url=f"https://example.com/{id_}", dedup_key=f"key-{id_}",
        ingested_at="2026-08-04T00:00:00Z", summary="s",
    )


def make_approved_draft(conn, signal_id, draft_status=DRAFT_STATUS_APPROVED) -> int:
    db_module.insert_signal_if_new(conn, make_signal(signal_id))
    draft = Draft(
        signal_id=signal_id, revision=1, observable="o", mechanism="m",
        assumption="a", consequence="c", falsifier="f", created_at="2026-08-04T00:00:00Z",
        status=draft_status,
    )
    return db_module.insert_draft(conn, draft)


def publish_json(**overrides):
    payload = {
        "hook": "h", "context": "c", "falsifier_line": "fl", "payoff_line": "pl",
        "carousel_slides": ["s1", "s2", "s3"], "caption": "cap",
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_publish_rejects_unknown_draft(conn):
    outcome = runner_module.publish_one(conn, 999, model="claude-opus-5")
    assert outcome.outcome == "error"


def test_publish_rejects_unapproved_draft(conn):
    draft_id = make_approved_draft(conn, "s1", draft_status=DRAFT_STATUS_DRAFT)
    outcome = runner_module.publish_one(conn, draft_id, model="claude-opus-5")
    assert outcome.outcome == "error"
    assert "approve" in outcome.detail


def test_publish_creates_publication_and_marks_draft_and_signal_published(conn, monkeypatch):
    draft_id = make_approved_draft(conn, "s2")
    monkeypatch.setattr(runner_module, "generate_publication", lambda *a, **kw: publish_json())

    outcome = runner_module.publish_one(conn, draft_id, model="claude-opus-5")
    assert outcome.outcome == "published"
    assert outcome.publication_id is not None

    draft_row = db_module.get_draft(conn, draft_id)
    assert draft_row["status"] == DRAFT_STATUS_PUBLISHED

    signal_row = db_module.get_signal(conn, "s2")
    assert signal_row["status"] == STATUS_PUBLISHED

    pub_row = conn.execute("SELECT * FROM publications WHERE id = ?", (outcome.publication_id,)).fetchone()
    assert json.loads(pub_row["carousel_json"]) == ["s1", "s2", "s3"]
    assert pub_row["caption_text"] == "cap"


def test_malformed_llm_output_leaves_draft_approved(conn, monkeypatch):
    draft_id = make_approved_draft(conn, "s3")
    monkeypatch.setattr(runner_module, "generate_publication", lambda *a, **kw: "not valid json")

    outcome = runner_module.publish_one(conn, draft_id, model="claude-opus-5")
    assert outcome.outcome == "skipped"

    draft_row = db_module.get_draft(conn, draft_id)
    assert draft_row["status"] == DRAFT_STATUS_APPROVED


def test_api_error_leaves_draft_approved_and_does_not_crash(conn, monkeypatch):
    draft_id = make_approved_draft(conn, "s4")

    def flaky(*a, **kw):
        raise errors.APIError(500, {"error": {"message": "simulated network failure"}})

    monkeypatch.setattr(runner_module, "generate_publication", flaky)

    outcome = runner_module.publish_one(conn, draft_id, model="claude-opus-5")
    assert outcome.outcome == "skipped"

    draft_row = db_module.get_draft(conn, draft_id)
    assert draft_row["status"] == DRAFT_STATUS_APPROVED


def test_network_error_leaves_draft_approved_and_does_not_crash(conn, monkeypatch):
    # A connection-level failure surfaces as a raw httpx error, not
    # google.genai.errors.APIError — this must be caught too.
    draft_id = make_approved_draft(conn, "s5")

    def flaky_network(*a, **kw):
        raise httpx.ConnectError("simulated unreachable network")

    monkeypatch.setattr(runner_module, "generate_publication", flaky_network)

    outcome = runner_module.publish_one(conn, draft_id, model="claude-opus-5")
    assert outcome.outcome == "skipped"

    draft_row = db_module.get_draft(conn, draft_id)
    assert draft_row["status"] == DRAFT_STATUS_APPROVED
