# The Graham Engine

A local pipeline that turns raw market/geopolitical/commodity events into
publish-ready, forward-looking, falsifiable theses for an Instagram markets
page. Four stages, each a discrete module:

```
SCAN  ->  TRIAGE  ->  BUILD  ->  PUBLISH
```

- **SCAN** — pull from configured sources, normalize into `Signal` records, dedup, store.
- **TRIAGE** — gate every signal on mechanism / non-consensus / reusable-lens; discard weak candidates.
- **BUILD** — turn a passed signal into a Bridge draft (Observable → Mechanism → Assumption → Consequence → Falsifier).
- **PUBLISH** — assemble an approved draft into a carousel + caption, ready to paste.

**Status: Phase 1 (SCAN), Phase 2 (TRIAGE), Phase 3 (BUILD), and Phase 4
(PUBLISH) are built and working.** Only the web dashboard (Phase 5) remains
scaffolded but not yet implemented — see [Build status](#build-status)
below.

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows Git Bash / macOS / Linux
# .venv\Scripts\activate.bat       # Windows cmd.exe
# .venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -e ".[dev]"
cp .env.example .env               # optional for SCAN — see below
```

(`uv` works too: `uv venv && uv pip install -e ".[dev]"`.)

Then run the full pipeline sweep:

```bash
engine run
```

This works out of the box against the real sources seeded in
`sources.yaml` — no API keys required. `engine run` runs SCAN, then TRIAGE
(which skips itself cleanly if `GEMINI_API_KEY` isn't set), then prints
a punch list of anything waiting on BUILD/APPROVE/PUBLISH — those stages
act on one signal/draft at a time by explicit ID (see below), so `run`
never auto-drafts or auto-publishes on your behalf.

### About `.env` / `GEMINI_API_KEY`

SCAN needs nothing. TRIAGE, BUILD, and PUBLISH all call the **Gemini API**
(chosen specifically because it has a free tier — no credit card, no paid
plan required) and need `GEMINI_API_KEY` — when it's absent, each command
prints what's waiting and returns cleanly instead of erroring; nothing is
skipped silently. You don't need a `.env` file at all to run `engine scan`.

Get a free key at <https://aistudio.google.com/apikey> and put it in `.env`:

```
GEMINI_API_KEY=your-key-here
```

The model is `gemini-2.5-flash` by default (fast, and covered by the free
tier's generous daily quota); override with `GEMINI_MODEL` in `.env` if you
want a different one.

## Data flow

```
sources.yaml --> [adapter: rss | json_api | scraper] --> raw items
              --> normalize + dedup --> signals table (status=ingested)

signals (ingested) --> [TRIAGE: rules prefilter + LLM gates] --> status=discarded|passed
                                                              --> triage_results row

signals (passed) --> [BUILD: Bridge draft] --> drafts row (status=draft, revision N)
                                             --> signal status=drafted

drafts (draft) --> [engine approve <id>] --> drafts row status=approved

drafts (approved) --> [PUBLISH: assembly] --> publications row (carousel_json + caption_text)
                                            --> draft status=published, signal status=published
```

Every status change on a `signal` is recorded in `status_transitions`
(from_status, to_status, timestamp) — the full lifecycle is auditable, not
just the current state.

All four tables (`signals`, `triage_results`, `drafts`, `publications`) exist
in the schema now (`engine/schema.sql`), even though only `signals` is
populated until Phase 2/3/4 land. Migrations are just `CREATE TABLE IF NOT
EXISTS`, applied idempotently on every startup — enough for a single-file
SQLite app; swap in a real migration tool only if the schema outgrows this.

## Running each stage

```bash
engine scan                  # fetch all sources in sources.yaml, store new signals
engine scan --sources other.yaml   # use a different source config

engine triage                # gate every 'ingested' signal; needs GEMINI_API_KEY
engine build <signal_id>     # draft a Bridge for one 'passed' (or already 'drafted') signal
engine approve <draft_id>    # human sign-off: draft -> approved, clears it for publish
engine publish <draft_id>    # assemble one 'approved' draft into carousel + caption

engine run                   # full sweep: scan, then triage, then a punch list of what's
                              # ready for build/approve/publish (those stages are per-item,
                              # by design — nothing gets drafted or posted automatically)
```

## Adding a source

Add an entry to `sources.yaml` — nothing in `engine/` hardcodes sources.

```yaml
sources:
  - name: "Some Feed"
    type: rss                 # rss | json_api | scraper
    url: "https://example.com/feed.xml"
    sector: commodities        # geopolitics | commodities | long_duration_compounders
                                # | catastrophe_driven | money_flows
    poll_interval: 900         # seconds (not yet used by a scheduler — reserved for
                                # a future `engine watch`/cron wrapper)
```

Any other key you add becomes adapter-specific config, read from
`source.extra`:

- **`json_api`**: `items_path` (dot-path to the list of items in the JSON
  response, e.g. `features` or `data.articles`) and `field_map` (dot-paths
  per field, e.g. `{title: properties.place, url: properties.url}`).
  Without `items_path`, the adapter tries the response itself if it's a
  list, then common keys (`items`, `articles`, `results`, `data`,
  `entries`). Without `field_map`, it assumes top-level `title` / `url` /
  `summary` / `published_at` keys.
- **`scraper`**: `item_selector`, `title_selector`, `url_selector`,
  `summary_selector` — CSS selectors, resolved with BeautifulSoup.
  `item_selector` defaults to `article`; `title_selector` / `url_selector`
  default to `a`.

A misconfigured `sources.yaml` (missing field, unknown `type`, unknown
`sector`, duplicate name) fails fast at load time with a clear error — it
does not fail silently mid-scan.

Sources are fetched concurrently (bounded by a semaphore) but inserted
sequentially. **One dead source never aborts the run** — its error is
logged and shown in the per-source report table, and every other source
still completes. `sources.yaml` currently ships with 11 real, working,
no-API-key sources across all five sectors and all three adapter types, so
`engine scan` produces real signals on first run.

Dedup is on `(source name + normalized title + url)` — enforced by a
`UNIQUE` constraint on `signals.dedup_key`, so re-running `engine scan`
never inserts the same signal twice.

## How TRIAGE works

Every `ingested` signal goes through two layers, in order:

1. **Rules prefilter** (`engine/triage/rules.py`) — cheap, deterministic,
   no network call. Drops obvious noise (listicles, clickbait patterns,
   celebrity/sports/obituary content, anything too short to carry a
   thesis). A signal that fails here is `discarded` with
   `failing_gate = "rules_prefilter"` and the LLM is never called for it —
   this is the whole point of having a cheap layer first.
2. **LLM gate scoring** (`engine/triage/llm.py` + `engine/triage/gates.py`)
   — anything that survives the prefilter gets scored by the Gemini API
   against the three gates from the spec (mechanism, non-consensus,
   reusable lens), via a JSON-schema-constrained response. The gate
   evaluation logic itself (`engine/triage/gates.py`) is pure — no I/O —
   so it's unit-tested directly against hand-written JSON strings, including
   malformed ones, without touching the network.

A signal passes only if all three gates pass; the first gate that fails
becomes `failing_gate` on its `triage_results` row. A response that isn't
valid JSON, or doesn't match the expected shape, is always treated as a
fail (`failing_gate = "malformed_llm_output"`) — never a crash, never a
silent pass. A transient API error (network failure, rate limit, auth
issue) leaves the signal in `ingested` status for a future `engine triage`
run rather than either crashing the whole batch or wrongly discarding it.

## How BUILD works

`engine build <signal_id>` turns one `passed` signal into a Bridge draft
(Observable → Mechanism → Assumption → Consequence → Falsifier), pulling in
that signal's `triage_results` row (reasoning, second-order read, suggested
falsifier) as context for the prompt. As with TRIAGE, the network call
(`engine/build/llm.py`) is separate from the pure response parsing
(`engine/build/bridge.py`), so a malformed or refused LLM response is
always treated as a failed draft — never a crash, never a draft with a
blank field. A transient API error or malformed response leaves the signal
in its current status for a future `engine build` retry; a successful
draft advances the signal to `drafted` and inserts a new `drafts` row
(revision N+1 if one already exists, so history is never overwritten).

BUILD is deliberately per-signal, not a batch sweep like TRIAGE — drafting
is the expensive, creative step, and picking which passed signals are
worth drafting is an editorial call `engine run` surfaces but doesn't make
for you.

## Human approval, then PUBLISH

A draft can't go straight from BUILD to PUBLISH — `engine approve
<draft_id>` is a required, explicit human sign-off that flips a draft from
`draft` to `approved`. This is intentional: nothing should reach an
Instagram caption without a person reading it first. `engine publish
<draft_id>` refuses (with a clear message pointing at `engine approve`)
if the draft isn't `approved` yet.

Once approved, `engine publish <draft_id>` assembles the draft into a
carousel + caption (`hook`, `context`, `falsifier_line`, `payoff_line`,
`carousel_slides`, `caption`) via `prompts/publish.md`. The same
network/pure-parsing split applies (`engine/publish/llm.py` +
`engine/publish/assembly.py`): a malformed or failed call leaves the draft
`approved` for a retry; success inserts a `publications` row and marks
both the draft and its signal `published`.

## Editing a prompt

Every LLM prompt lives in `prompts/*.md` — never inline in Python:

- `prompts/triage.md` — TRIAGE gate-scoring prompt (Phase 2)
- `prompts/bridge.md` — BUILD Bridge-draft prompt (Phase 3)
- `prompts/publish.md` — PUBLISH assembly prompt (Phase 4)

Each is loaded and rendered at runtime by its stage's `llm.py` — edit one
and the next run of that stage picks up the change with no code edit. They
use simple `{{field}}` placeholders (e.g. `{{sector}}`, `{{title}}`,
`{{observable}}` — see each prompt file for its exact set).

## Build status

| Phase | Stage | Status |
|---|---|---|
| 1 | SCAN | Done — adapters (rss/json_api/scraper), dedup, resilient concurrent fetch, `engine scan` |
| 2 | TRIAGE | Done — rules prefilter, pure gate-evaluation functions, LLM scoring via `gemini-2.5-flash`, `engine triage` |
| 3 | BUILD | Done — Bridge draft generation, falsifier validation at the DB layer, revision history, `engine build <signal_id>` |
| 4 | PUBLISH | Done — human-approval gate (`engine approve`) + carousel/caption assembly, `engine publish <draft_id>` |
| 5 | Web dashboard | Not started — FastAPI + single page over the same CLI logic |

## Testing

```bash
python -m pytest
```

89 tests, covering:
- `tests/test_dedup.py` — dedup key normalization and determinism
- `tests/test_adapters.py` — RSS/JSON-API/scraper parsing against fixtures, including malformed-content and no-match error paths
- `tests/test_config.py` — `sources.yaml` validation (missing fields, invalid type/sector, duplicate names)
- `tests/test_scan_runner.py` — end-to-end scan against a temp SQLite DB: storage, cross-run dedup, and resilience when one source raises
- `tests/test_db.py` — status transition recording, the falsifier-required guard on drafts, and draft status updates/filtering
- `tests/test_rules.py` — the cheap noise prefilter
- `tests/test_gates.py` — pure gate-evaluation logic: all-pass, fail-each-gate-individually, and a dozen malformed-LLM-output shapes (not JSON, wrong types, out-of-range confidence, missing keys) — none of it touches the network
- `tests/test_triage_runner.py` — end-to-end triage against a temp SQLite DB: rules-prefilter discard skips the LLM call entirely, LLM pass/fail updates signal status correctly, malformed output discards without crashing, and a simulated API error leaves a signal `ingested` without aborting the batch
- `tests/test_bridge.py` — pure Bridge-response parsing: well-formed, malformed JSON, missing/blank/wrong-typed fields, never raises on garbage input
- `tests/test_build_runner.py` — end-to-end build against a temp SQLite DB: rejects unknown/not-yet-passed signals, creates a draft and advances signal status, carries triage context into the prompt, supports re-drafting into a new revision, and never crashes on malformed output or a transient API error
- `tests/test_assembly.py` — pure publish-response parsing: well-formed, malformed JSON, missing/blank fields, malformed `carousel_slides`, never raises on garbage input
- `tests/test_publish_runner.py` — end-to-end publish against a temp SQLite DB: rejects unknown/unapproved drafts, creates a publication and advances draft+signal status, and never crashes on malformed output or a transient API error

## Project layout

```
engine/
  cli.py            entrypoint: engine scan|triage|build|approve|publish|run
  config.py         .env + sources.yaml loading & validation
  db.py             SQLite access layer
  models.py         dataclasses for Signal / TriageResult / Draft / Publication
  schema.sql         table definitions
  scan/
    adapters.py      rss / json_api / scraper fetch + parse
    dedup.py         dedup key computation
    runner.py        concurrent fetch orchestration
  triage/
    rules.py         cheap heuristic prefilter (no network)
    gates.py         pure gate-evaluation logic + defensive JSON parsing
    llm.py           Gemini API call + prompts/triage.md rendering
    runner.py        orchestrates rules -> LLM -> persist, per signal
  build/
    bridge.py        pure Bridge-response parsing + defensive JSON parsing
    llm.py            Gemini API call + prompts/bridge.md rendering
    runner.py         orchestrates LLM -> persist, per signal
  publish/
    assembly.py       pure publish-response parsing + defensive JSON parsing
    llm.py             Gemini API call + prompts/publish.md rendering
    runner.py          orchestrates LLM -> persist, per draft
prompts/             editable *.md LLM prompt templates
sources.yaml         source registry (no source URLs in code)
tests/
data/                SQLite DB lives here (gitignored)
```
