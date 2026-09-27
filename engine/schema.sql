-- The Graham Engine — SQLite schema.
-- Applied idempotently (CREATE TABLE IF NOT EXISTS) on every startup; this is
-- the entire "migration" system for v1. If the schema ever needs a real
-- migration tool, swap this file out for alembic at that point — not before.

CREATE TABLE IF NOT EXISTS signals (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    sector          TEXT NOT NULL,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL,
    summary         TEXT,
    published_at    TEXT,
    raw_payload     TEXT,
    ingested_at     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'ingested',
    dedup_key       TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
CREATE INDEX IF NOT EXISTS idx_signals_sector ON signals(sector);

-- Every status transition a signal goes through, so the full lifecycle
-- (ingested -> discarded|passed -> drafted -> published) is auditable.
CREATE TABLE IF NOT EXISTS status_transitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id       TEXT NOT NULL REFERENCES signals(id),
    from_status     TEXT,
    to_status       TEXT NOT NULL,
    transitioned_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transitions_signal ON status_transitions(signal_id);

CREATE TABLE IF NOT EXISTS triage_results (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id               TEXT NOT NULL REFERENCES signals(id),
    rules_prefilter_passed  INTEGER NOT NULL,
    rules_prefilter_reason  TEXT,
    gate1_pass              INTEGER,
    gate2_pass              INTEGER,
    gate3_pass              INTEGER,
    reasoning               TEXT,
    second_order_read       TEXT,
    suggested_falsifier     TEXT,
    confidence              REAL,
    failing_gate            TEXT,
    llm_raw_response        TEXT,
    created_at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_triage_signal ON triage_results(signal_id);

-- A signal can have multiple draft revisions; history is never overwritten.
CREATE TABLE IF NOT EXISTS drafts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id    TEXT NOT NULL REFERENCES signals(id),
    revision     INTEGER NOT NULL,
    observable   TEXT NOT NULL,
    mechanism    TEXT NOT NULL,
    assumption   TEXT NOT NULL,
    consequence  TEXT NOT NULL,
    falsifier    TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'draft',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_drafts_signal ON drafts(signal_id);

CREATE TABLE IF NOT EXISTS publications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id        INTEGER NOT NULL REFERENCES drafts(id),
    hook            TEXT NOT NULL,
    context         TEXT NOT NULL,
    falsifier_line  TEXT NOT NULL,
    payoff_line     TEXT NOT NULL,
    carousel_json   TEXT NOT NULL,
    caption_text    TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_publications_draft ON publications(draft_id);
