import json

import pytest
from google.genai import errors

from engine import db as db_module
from engine.build import runner as runner_module
from engine.models import STATUS_DRAFTED, STATUS_INGESTED, STATUS_PASSED, Signal, TriageResult


@pytest.fixture
def conn(tmp_path):
    path = str(tmp_path / "test.db")
    with db_module.connect(path) as c:
        yield c


def make_signal(id_, status=STATUS_PASSED) -> Signal:
    return Signal(
        id=id_, source="Test Source", sector="commodities", title="Copper stocks fall sharply",
        url=f"https://example.com/{id_}", dedup_key=f"key-{id_}",
        ingested_at="2026-08-04T00:00:00Z", summary="Six-week decline in LME warehouse stocks.",
        status=status,
    )


def bridge_json(**overrides):
    payload = {
        "observable": "o", "mechanism": "m", "assumption": "a", "consequence": "c", "falsifier": "f",
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_build_rejects_unknown_signal(conn):
    outcome = runner_module.build_one(conn, "nope", model="claude-opus-5")
    assert outcome.outcome == "error"


def test_build_rejects_signal_not_passed(conn):
    db_module.insert_signal_if_new(conn, make_signal("s1", status=STATUS_INGESTED))
    outcome = runner_module.build_one(conn, "s1", model="claude-opus-5")
    assert outcome.outcome == "error"
    assert "must be" in outcome.detail


def test_build_creates_draft_and_marks_signal_drafted(conn, monkeypatch):
    db_module.insert_signal_if_new(conn, make_signal("s2", status=STATUS_INGESTED))
    db_module.update_signal_status(conn, "s2", STATUS_PASSED, "2026-08-04T00:00:00Z")
    monkeypatch.setattr(runner_module, "generate_draft", lambda *a, **kw: bridge_json())

    outcome = runner_module.build_one(conn, "s2", model="claude-opus-5")
    assert outcome.outcome == "drafted"
    assert outcome.draft_id is not None

    row = db_module.get_signal(conn, "s2")
    assert row["status"] == STATUS_DRAFTED

    draft = db_module.get_draft(conn, outcome.draft_id)
    assert draft["falsifier"] == "f"
    assert draft["revision"] == 1


def test_build_includes_triage_context_in_prompt(conn, monkeypatch):
    db_module.insert_signal_if_new(conn, make_signal("s3", status=STATUS_INGESTED))
    db_module.update_signal_status(conn, "s3", STATUS_PASSED, "2026-08-04T00:00:00Z")
    db_module.insert_triage_result(conn, TriageResult(
        signal_id="s3", rules_prefilter_passed=True, gate1_pass=True, gate2_pass=True, gate3_pass=True,
        reasoning="strong mechanism", second_order_read="squeeze risk", suggested_falsifier="if stocks rebound",
        confidence=0.9, created_at="2026-08-04T00:00:00Z",
    ))

    captured = {}

    def fake_generate(signal, triage_reasoning, second_order_read, suggested_falsifier, model):
        captured["reasoning"] = triage_reasoning
        captured["second_order_read"] = second_order_read
        return bridge_json()

    monkeypatch.setattr(runner_module, "generate_draft", fake_generate)
    runner_module.build_one(conn, "s3", model="claude-opus-5")

    assert captured["reasoning"] == "strong mechanism"
    assert captured["second_order_read"] == "squeeze risk"


def test_build_allows_new_revision_on_already_drafted_signal(conn, monkeypatch):
    db_module.insert_signal_if_new(conn, make_signal("s4", status=STATUS_INGESTED))
    db_module.update_signal_status(conn, "s4", STATUS_PASSED, "2026-08-04T00:00:00Z")
    monkeypatch.setattr(runner_module, "generate_draft", lambda *a, **kw: bridge_json())

    first = runner_module.build_one(conn, "s4", model="claude-opus-5")
    second = runner_module.build_one(conn, "s4", model="claude-opus-5")

    assert first.outcome == "drafted"
    assert second.outcome == "drafted"
    assert db_module.latest_draft_revision(conn, "s4") == 2


def test_malformed_llm_output_leaves_signal_unchanged(conn, monkeypatch):
    db_module.insert_signal_if_new(conn, make_signal("s5", status=STATUS_INGESTED))
    db_module.update_signal_status(conn, "s5", STATUS_PASSED, "2026-08-04T00:00:00Z")
    monkeypatch.setattr(runner_module, "generate_draft", lambda *a, **kw: "not valid json")

    outcome = runner_module.build_one(conn, "s5", model="claude-opus-5")
    assert outcome.outcome == "skipped"

    row = db_module.get_signal(conn, "s5")
    assert row["status"] == STATUS_PASSED


def test_api_error_leaves_signal_passed_and_does_not_crash(conn, monkeypatch):
    db_module.insert_signal_if_new(conn, make_signal("s6", status=STATUS_INGESTED))
    db_module.update_signal_status(conn, "s6", STATUS_PASSED, "2026-08-04T00:00:00Z")

    def flaky(*a, **kw):
        raise errors.APIError(500, {"error": {"message": "simulated network failure"}})

    monkeypatch.setattr(runner_module, "generate_draft", flaky)

    outcome = runner_module.build_one(conn, "s6", model="claude-opus-5")
    assert outcome.outcome == "skipped"

    row = db_module.get_signal(conn, "s6")
    assert row["status"] == STATUS_PASSED
