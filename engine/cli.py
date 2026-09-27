"""Command-line entrypoint: `engine scan|triage|build|publish|run`.

This is the primary interface (the web dashboard in Phase 5 is a thin layer
over this same logic). Every subcommand ensures the DB schema exists before
doing anything else.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from engine import config, db as db_module
from engine.models import DRAFT_STATUS_APPROVED, DRAFT_STATUS_DRAFT, STATUS_PASSED
from engine.scan.runner import run_scan


def _setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, config.log_level(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_scan(args: argparse.Namespace) -> int:
    sources = config.load_sources(args.sources)
    logging.getLogger("engine.cli").info("loaded %d sources from %s", len(sources), args.sources or config.DEFAULT_SOURCES_PATH)

    with db_module.connect(config.db_path()) as conn:
        report = asyncio.run(run_scan(sources, conn))

    print()
    print(f"{'SOURCE':<38} {'SECTOR':<26} {'FETCHED':>8} {'NEW':>6} {'DUP':>6}  STATUS")
    for s in report.sources:
        status = "OK" if not s.error else f"FAILED: {s.error}"
        print(f"{s.name:<38} {s.sector:<26} {s.fetched:>8} {s.inserted:>6} {s.duplicates:>6}  {status}")
    print()
    print(
        f"Total: {report.total_fetched} fetched, {report.total_inserted} new signals stored, "
        f"{report.total_duplicates} duplicates skipped, {len(report.failed_sources)} source(s) failed."
    )
    return 0


def cmd_triage(args: argparse.Namespace) -> int:
    if not config.anthropic_api_key():
        with db_module.connect(config.db_path()) as conn:
            pending = len(db_module.list_signals(conn, status="ingested"))
        print("ANTHROPIC_API_KEY not set - skipping LLM triage stage.")
        print(f"{pending} signal(s) remain in 'ingested' status. Set ANTHROPIC_API_KEY and re-run `engine triage` to process them.")
        return 0

    from engine.triage.runner import run_triage

    with db_module.connect(config.db_path()) as conn:
        outcomes = run_triage(conn, model=config.anthropic_model())

    if not outcomes:
        print("No signals in 'ingested' status to triage. Run `engine scan` first.")
        return 0

    print()
    print(f"{'SIGNAL':<62} {'OUTCOME':<10} DETAIL")
    for o in outcomes:
        title = (o.title[:59] + "...") if len(o.title) > 62 else o.title
        print(f"{title:<62} {o.outcome:<10} {o.detail}")

    passed = sum(1 for o in outcomes if o.outcome == "passed")
    discarded = sum(1 for o in outcomes if o.outcome == "discarded")
    skipped = sum(1 for o in outcomes if o.outcome == "skipped")
    print()
    print(f"Total: {len(outcomes)} triaged - {passed} passed, {discarded} discarded, {skipped} skipped (transient API errors, left as 'ingested').")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    if not config.anthropic_api_key():
        print("ANTHROPIC_API_KEY not set - cannot run BUILD (needs the Anthropic API).")
        return 0

    from engine.build.runner import build_one

    with db_module.connect(config.db_path()) as conn:
        outcome = build_one(conn, args.signal_id, model=config.anthropic_model())

    if outcome.outcome == "drafted":
        print(f"Draft #{outcome.draft_id} created for signal {args.signal_id!r}. Review it, then `engine approve {outcome.draft_id}`.")
    elif outcome.outcome == "skipped":
        print(f"Could not draft signal {args.signal_id!r} this run: {outcome.detail}")
    else:
        print(f"engine build: {outcome.detail}")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    with db_module.connect(config.db_path()) as conn:
        row = db_module.get_draft(conn, args.draft_id)
        if row is None:
            print(f"engine approve: no draft with id {args.draft_id}")
            return 0
        if row["status"] != DRAFT_STATUS_DRAFT:
            print(f"engine approve: draft {args.draft_id} has status {row['status']!r}, expected {DRAFT_STATUS_DRAFT!r}")
            return 0
        db_module.update_draft_status(conn, args.draft_id, DRAFT_STATUS_APPROVED)

    print(f"Draft #{args.draft_id} approved. Run `engine publish {args.draft_id}` to assemble it.")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    if not config.anthropic_api_key():
        print("ANTHROPIC_API_KEY not set - cannot run PUBLISH (needs the Anthropic API).")
        return 0

    from engine.publish.runner import publish_one

    with db_module.connect(config.db_path()) as conn:
        outcome = publish_one(conn, args.draft_id, model=config.anthropic_model())

    if outcome.outcome == "published":
        print(f"Publication #{outcome.publication_id} assembled for draft #{args.draft_id}. Ready to paste.")
    elif outcome.outcome == "skipped":
        print(f"Could not publish draft #{args.draft_id} this run: {outcome.detail}")
    else:
        print(f"engine publish: {outcome.detail}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    rc = cmd_scan(args)
    if rc != 0:
        return rc
    rc = cmd_triage(args)
    if rc != 0:
        return rc

    with db_module.connect(config.db_path()) as conn:
        passed = db_module.list_signals(conn, status=STATUS_PASSED)
        awaiting_approval = db_module.list_drafts(conn, status=DRAFT_STATUS_DRAFT)
        awaiting_publish = db_module.list_drafts(conn, status=DRAFT_STATUS_APPROVED)

    print()
    if not (passed or awaiting_approval or awaiting_publish):
        print("Nothing waiting on BUILD or PUBLISH right now.")
        return 0

    def _list(rows, cmd_name, description):
        print(f"{len(rows)} {description}:")
        for row in rows[:10]:
            print(f"  engine {cmd_name} {row['id']}")
        if len(rows) > 10:
            print(f"  ...and {len(rows) - 10} more")

    if passed:
        _list(passed, "build", "signal(s) passed triage, ready to build")
    if awaiting_approval:
        _list(awaiting_approval, "approve", "draft(s) awaiting approval")
    if awaiting_publish:
        _list(awaiting_publish, "publish", "draft(s) approved, ready to publish")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="engine", description="The Graham Engine - market intelligence & content pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="fetch all configured sources and store new signals")
    p_scan.add_argument("--sources", default=None, help="path to sources.yaml (default: ./sources.yaml)")
    p_scan.set_defaults(func=cmd_scan)

    p_triage = sub.add_parser("triage", help="run the triage gates over ingested signals")
    p_triage.set_defaults(func=cmd_triage)

    p_build = sub.add_parser("build", help="generate a Bridge draft for a passed signal")
    p_build.add_argument("signal_id")
    p_build.set_defaults(func=cmd_build)

    p_approve = sub.add_parser("approve", help="approve a draft, clearing it for publish")
    p_approve.add_argument("draft_id", type=int)
    p_approve.set_defaults(func=cmd_approve)

    p_publish = sub.add_parser("publish", help="assemble an approved draft into publish-ready output")
    p_publish.add_argument("draft_id", type=int)
    p_publish.set_defaults(func=cmd_publish)

    p_run = sub.add_parser("run", help="run the full pipeline sweep (scan -> triage -> build -> publish)")
    p_run.add_argument("--sources", default=None, help="path to sources.yaml (default: ./sources.yaml)")
    p_run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    config.load_env()
    _setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
