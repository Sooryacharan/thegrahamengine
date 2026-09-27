import sqlite3

import pytest

from engine import db as db_module
from engine.config import SourceConfig
from engine.scan import runner as runner_module
from engine.scan.adapters import AdapterError


@pytest.fixture
def conn(tmp_path):
    path = str(tmp_path / "test.db")
    with db_module.connect(path) as c:
        yield c


def make_source(name, type_="rss", sector="geopolitics") -> SourceConfig:
    return SourceConfig(name=name, type=type_, url=f"https://example.com/{name}", sector=sector, poll_interval=900, extra={})


async def _ok_adapter(items):
    async def fetch(client, source):
        return items
    return fetch


@pytest.mark.asyncio
async def test_run_scan_stores_new_signals(conn, monkeypatch):
    items = [
        {"title": "A", "url": "https://x.com/a", "summary": "", "published_at": None, "raw_payload": {}},
        {"title": "B", "url": "https://x.com/b", "summary": "", "published_at": None, "raw_payload": {}},
    ]

    async def fake_fetch_rss(client, source):
        return items

    monkeypatch.setitem(runner_module.ADAPTERS, "rss", fake_fetch_rss)

    source = make_source("feed-1")
    report = await runner_module.run_scan([source], conn)

    assert report.total_fetched == 2
    assert report.total_inserted == 2
    assert report.total_duplicates == 0

    rows = db_module.list_signals(conn)
    assert len(rows) == 2
    assert {r["status"] for r in rows} == {"ingested"}


@pytest.mark.asyncio
async def test_run_scan_deduplicates_across_runs(conn, monkeypatch):
    items = [{"title": "Same story", "url": "https://x.com/a", "summary": "", "published_at": None, "raw_payload": {}}]

    async def fake_fetch_rss(client, source):
        return items

    monkeypatch.setitem(runner_module.ADAPTERS, "rss", fake_fetch_rss)

    source = make_source("feed-1")
    first = await runner_module.run_scan([source], conn)
    second = await runner_module.run_scan([source], conn)

    assert first.total_inserted == 1
    assert second.total_inserted == 0
    assert second.total_duplicates == 1
    assert len(db_module.list_signals(conn)) == 1


@pytest.mark.asyncio
async def test_run_scan_one_failing_source_does_not_kill_the_run(conn, monkeypatch):
    good_items = [{"title": "Good item", "url": "https://x.com/good", "summary": "", "published_at": None, "raw_payload": {}}]

    async def fake_fetch_rss(client, source):
        if source.name == "broken-feed":
            raise AdapterError("simulated network failure")
        return good_items

    monkeypatch.setitem(runner_module.ADAPTERS, "rss", fake_fetch_rss)

    sources = [make_source("broken-feed"), make_source("healthy-feed")]
    report = await runner_module.run_scan(sources, conn)

    assert len(report.failed_sources) == 1
    assert report.failed_sources[0].name == "broken-feed"
    assert report.total_inserted == 1
    assert len(db_module.list_signals(conn)) == 1


@pytest.mark.asyncio
async def test_run_scan_unexpected_exception_in_one_source_does_not_kill_the_run(conn, monkeypatch):
    async def fake_fetch_rss(client, source):
        if source.name == "buggy-feed":
            raise RuntimeError("boom")
        return [{"title": "Fine", "url": "https://x.com/fine", "summary": "", "published_at": None, "raw_payload": {}}]

    monkeypatch.setitem(runner_module.ADAPTERS, "rss", fake_fetch_rss)

    sources = [make_source("buggy-feed"), make_source("fine-feed")]
    report = await runner_module.run_scan(sources, conn)

    assert len(report.failed_sources) == 1
    assert report.total_inserted == 1
