import pytest

from engine import db as db_module
from engine.models import Draft, Signal


@pytest.fixture
def conn(tmp_path):
    path = str(tmp_path / "test.db")
    with db_module.connect(path) as c:
        yield c


def make_signal(**overrides) -> Signal:
    defaults = dict(
        id="sig-1", source="Test Source", sector="geopolitics", title="Title",
        url="https://x.com/a", dedup_key="key-1", ingested_at="2026-08-04T00:00:00Z",
    )
    defaults.update(overrides)
    return Signal(**defaults)


def test_insert_signal_records_initial_transition(conn):
    db_module.insert_signal_if_new(conn, make_signal())
    rows = conn.execute("SELECT * FROM status_transitions WHERE signal_id = 'sig-1'").fetchall()
    assert len(rows) == 1
    assert rows[0]["from_status"] is None
    assert rows[0]["to_status"] == "ingested"


def test_update_signal_status_records_transition(conn):
    db_module.insert_signal_if_new(conn, make_signal())
    db_module.update_signal_status(conn, "sig-1", "discarded", "2026-08-04T01:00:00Z")

    row = db_module.get_signal(conn, "sig-1")
    assert row["status"] == "discarded"

    transitions = conn.execute(
        "SELECT * FROM status_transitions WHERE signal_id = 'sig-1' ORDER BY id"
    ).fetchall()
    assert len(transitions) == 2
    assert transitions[1]["from_status"] == "ingested"
    assert transitions[1]["to_status"] == "discarded"


def test_draft_without_falsifier_is_rejected(conn):
    db_module.insert_signal_if_new(conn, make_signal())
    draft = Draft(
        signal_id="sig-1", revision=1, observable="X", mechanism="Y",
        assumption="Z", consequence="W", falsifier="   ", created_at="2026-08-04T00:00:00Z",
    )
    with pytest.raises(ValueError):
        db_module.insert_draft(conn, draft)


def test_draft_with_falsifier_is_accepted(conn):
    db_module.insert_signal_if_new(conn, make_signal())
    draft = Draft(
        signal_id="sig-1", revision=1, observable="X", mechanism="Y",
        assumption="Z", consequence="W",
        falsifier="If Brent has not fallen below $70 by 2026-12-31, thesis is wrong.",
        created_at="2026-08-04T00:00:00Z",
    )
    draft_id = db_module.insert_draft(conn, draft)
    assert draft_id is not None
    assert db_module.latest_draft_revision(conn, "sig-1") == 1


def test_update_draft_status(conn):
    db_module.insert_signal_if_new(conn, make_signal())
    draft = Draft(
        signal_id="sig-1", revision=1, observable="X", mechanism="Y",
        assumption="Z", consequence="W", falsifier="F", created_at="2026-08-04T00:00:00Z",
    )
    draft_id = db_module.insert_draft(conn, draft)

    db_module.update_draft_status(conn, draft_id, "approved")
    row = db_module.get_draft(conn, draft_id)
    assert row["status"] == "approved"


def test_list_drafts_filters_by_status(conn):
    db_module.insert_signal_if_new(conn, make_signal())
    d1 = Draft(
        signal_id="sig-1", revision=1, observable="X", mechanism="Y",
        assumption="Z", consequence="W", falsifier="F1", created_at="2026-08-04T00:00:00Z",
    )
    d2 = Draft(
        signal_id="sig-1", revision=2, observable="X", mechanism="Y",
        assumption="Z", consequence="W", falsifier="F2", created_at="2026-08-04T00:01:00Z",
    )
    id1 = db_module.insert_draft(conn, d1)
    db_module.insert_draft(conn, d2)
    db_module.update_draft_status(conn, id1, "approved")

    approved = db_module.list_drafts(conn, status="approved")
    assert [r["id"] for r in approved] == [id1]
    assert len(db_module.list_drafts(conn)) == 2
