import json

import pytest
from google.genai import errors

from engine import db as db_module
from engine.models import STATUS_DISCARDED, STATUS_INGESTED, STATUS_PASSED, Signal
from engine.triage import runner as runner_module


@pytest.fixture
def conn(tmp_path):
    path = str(tmp_path / "test.db")
    with db_module.connect(path) as c:
        yield c


def make_signal(id_, title, summary="A substantive summary with real content about markets.") -> Signal:
    return Signal(
        id=id_, source="Test Source", sector="geopolitics", title=title,
        url=f"https://example.com/{id_}", dedup_key=f"key-{id_}",
        ingested_at="2026-08-04T00:00:00Z", summary=summary,
    )


def llm_json(g1=True, g2=True, g3=True, confidence=0.9):
    return json.dumps({
        "gate1_pass": g1, "gate2_pass": g2, "gate3_pass": g3,
        "reasoning": "r", "second_order_read": "s", "suggested_falsifier": "f", "confidence": confidence,
    })


def test_rules_prefilter_discard_never_calls_llm(conn, monkeypatch):
    db_module.insert_signal_if_new(conn, make_signal("s1", "Top 10 stocks to buy now", "clickbait"))

    def fail_if_called(*a, **kw):
        raise AssertionError("LLM should not be called for a rules-prefilter failure")

    monkeypatch.setattr(runner_module, "score_signal", fail_if_called)

    outcomes = runner_module.run_triage(conn, model="claude-opus-5")
    assert len(outcomes) == 1
    assert outcomes[0].outcome == "discarded"

    row = db_module.get_signal(conn, "s1")
    assert row["status"] == STATUS_DISCARDED

    triage_row = conn.execute("SELECT * FROM triage_results WHERE signal_id = 's1'").fetchone()
    assert triage_row["rules_prefilter_passed"] == 0
    assert triage_row["failing_gate"] == "rules_prefilter"


def test_llm_pass_marks_signal_passed(conn, monkeypatch):
    db_module.insert_signal_if_new(conn, make_signal("s2", "OPEC+ signals surprise supply cut"))
    monkeypatch.setattr(runner_module, "score_signal", lambda signal, model: llm_json(True, True, True))

    outcomes = runner_module.run_triage(conn, model="claude-opus-5")
    assert outcomes[0].outcome == "passed"

    row = db_module.get_signal(conn, "s2")
    assert row["status"] == STATUS_PASSED

    triage_row = conn.execute("SELECT * FROM triage_results WHERE signal_id = 's2'").fetchone()
    assert triage_row["rules_prefilter_passed"] == 1
    assert triage_row["gate1_pass"] == 1
    assert triage_row["failing_gate"] is None


def test_llm_gate_failure_marks_signal_discarded(conn, monkeypatch):
    db_module.insert_signal_if_new(conn, make_signal("s3", "Central bank holds rates steady"))
    monkeypatch.setattr(runner_module, "score_signal", lambda signal, model: llm_json(True, False, True))

    outcomes = runner_module.run_triage(conn, model="claude-opus-5")
    assert outcomes[0].outcome == "discarded"
    assert outcomes[0].detail == "gate2_non_consensus"

    row = db_module.get_signal(conn, "s3")
    assert row["status"] == STATUS_DISCARDED


def test_malformed_llm_output_discards_and_never_crashes(conn, monkeypatch):
    db_module.insert_signal_if_new(conn, make_signal("s4", "Copper inventories hit five-year low"))
    monkeypatch.setattr(runner_module, "score_signal", lambda signal, model: "not valid json at all")

    outcomes = runner_module.run_triage(conn, model="claude-opus-5")
    assert outcomes[0].outcome == "discarded"
    assert outcomes[0].detail == "malformed_llm_output"

    triage_row = conn.execute("SELECT * FROM triage_results WHERE signal_id = 's4'").fetchone()
    assert triage_row["llm_raw_response"] == "not valid json at all"


def test_api_error_leaves_signal_ingested_and_does_not_crash_run(conn, monkeypatch):
    db_module.insert_signal_if_new(conn, make_signal("s5", "Federal Reserve press release on rates"))
    db_module.insert_signal_if_new(conn, make_signal("s6", "Sovereign fund rotates out of bonds"))

    def flaky(signal, model):
        if signal.id == "s5":
            raise errors.APIError(500, {"error": {"message": "simulated network failure"}})
        return llm_json(True, True, True)

    monkeypatch.setattr(runner_module, "score_signal", flaky)

    outcomes = runner_module.run_triage(conn, model="claude-opus-5")
    by_id = {o.signal_id: o for o in outcomes}
    assert by_id["s5"].outcome == "skipped"
    assert by_id["s6"].outcome == "passed"

    # skipped signal is left untouched for a future run
    row = db_module.get_signal(conn, "s5")
    assert row["status"] == STATUS_INGESTED
