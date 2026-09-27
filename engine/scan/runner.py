"""Orchestrates a scan run: fetch all sources concurrently, normalize each
item into a Signal, dedup on insert, and never let one dead source kill the
run.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone

import httpx

from engine.config import SourceConfig
from engine.scan.adapters import ADAPTERS, AdapterError
from engine.scan.dedup import compute_dedup_key
from engine import db as db_module
from engine.models import STATUS_INGESTED, ScanReport, ScanSourceReport, Signal

logger = logging.getLogger("engine.scan")

MAX_CONCURRENT_FETCHES = 8


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _fetch_one(client: httpx.AsyncClient, source: SourceConfig, semaphore: asyncio.Semaphore) -> ScanSourceReport:
    report = ScanSourceReport(name=source.name, sector=source.sector)
    adapter = ADAPTERS.get(source.type)
    if adapter is None:
        report.error = f"unknown source type {source.type!r}"
        return report

    try:
        async with semaphore:
            raw_items = await adapter(client, source)
    except AdapterError as e:
        report.error = str(e)
        logger.warning("source %r failed: %s", source.name, e)
        return report
    except Exception as e:  # noqa: BLE001 - a source must never take the run down
        report.error = f"unexpected error: {e}"
        logger.exception("source %r raised an unexpected error", source.name)
        return report

    report.fetched = len(raw_items)
    report.raw_items = raw_items  # type: ignore[attr-defined]
    return report


def _to_signal(source: SourceConfig, raw_item: dict) -> Signal:
    dedup_key = compute_dedup_key(source.name, raw_item["title"], raw_item["url"])
    return Signal(
        id=str(uuid.uuid4()),
        source=source.name,
        sector=source.sector,
        title=raw_item["title"],
        url=raw_item["url"],
        summary=raw_item.get("summary") or "",
        published_at=raw_item.get("published_at"),
        raw_payload=json.dumps(raw_item.get("raw_payload") or {}, default=str),
        ingested_at=_now_iso(),
        status=STATUS_INGESTED,
        dedup_key=dedup_key,
    )


async def run_scan(sources: list[SourceConfig], conn: sqlite3.Connection) -> ScanReport:
    """Fetch every source concurrently, then insert results sequentially
    (sqlite3 connections aren't safe for concurrent writes from multiple
    coroutines). Fetch is the slow, parallelizable part; insert is fast."""
    report = ScanReport()
    if not sources:
        return report

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        fetch_reports = await asyncio.gather(*[
            _fetch_one(client, source, semaphore) for source in sources
        ])

    for source, source_report in zip(sources, fetch_reports):
        raw_items = getattr(source_report, "raw_items", [])
        for raw_item in raw_items:
            try:
                signal = _to_signal(source, raw_item)
                inserted = db_module.insert_signal_if_new(conn, signal)
            except Exception as e:  # noqa: BLE001 - one bad item shouldn't drop the rest
                logger.warning("failed to store item from %r (%s): %s", source.name, raw_item.get("url"), e)
                continue
            if inserted:
                source_report.inserted += 1
            else:
                source_report.duplicates += 1
        report.sources.append(source_report)

    return report
