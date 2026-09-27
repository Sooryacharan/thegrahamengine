"""Source adapters for the three supported source types.

Each adapter is split into fetch_* (network I/O, async) and parse_*
(pure, synchronous) so the parsing logic can be unit-tested with canned
content and no network access.

A "raw item" is a plain dict: {title, url, summary, published_at, raw_payload}.
raw_payload is itself a JSON-serializable dict — the runner json.dumps()s it
before storing.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin

import feedparser
import httpx
from bs4 import BeautifulSoup

from engine.config import SourceConfig

DEFAULT_TIMEOUT = 15.0
USER_AGENT = "GrahamEngine/0.1 (+market intelligence pipeline; scan bot)"


class AdapterError(Exception):
    """Raised when a source can't be fetched or parsed. Callers catch this
    per-source so one bad source never aborts the whole scan run."""


# --- RSS / Atom ----------------------------------------------------------

async def fetch_rss(client: httpx.AsyncClient, source: SourceConfig) -> list[dict[str, Any]]:
    try:
        resp = await client.get(source.url, timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise AdapterError(f"fetch failed: {e}") from e
    return parse_rss(resp.content, source)


def parse_rss(content: bytes | str, source: SourceConfig) -> list[dict[str, Any]]:
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise AdapterError(f"unparseable feed: {parsed.get('bozo_exception')}")

    items = []
    for entry in parsed.entries:
        title = entry.get("title", "").strip()
        url = entry.get("link", "").strip()
        if not title or not url:
            continue
        summary = entry.get("summary", entry.get("description", "")) or ""
        published_at = entry.get("published") or entry.get("updated") or None
        raw_payload = {k: str(v) for k, v in entry.items() if isinstance(v, (str, int, float))}
        items.append({
            "title": title,
            "url": url,
            "summary": summary,
            "published_at": published_at,
            "raw_payload": raw_payload,
        })
    return items


# --- Generic JSON REST endpoint -------------------------------------------

def _get_by_path(obj: Any, path: str) -> Any:
    """Resolve a dotted path like 'data.articles' against a parsed JSON
    object. Returns None if any segment is missing."""
    current = obj
    for segment in path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return None
    return current


_COMMON_LIST_KEYS = ("items", "articles", "results", "data", "entries")


def _find_item_list(payload: Any, items_path: str | None) -> list[Any]:
    if items_path:
        found = _get_by_path(payload, items_path)
        if isinstance(found, list):
            return found
        raise AdapterError(f"items_path {items_path!r} did not resolve to a list")

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in _COMMON_LIST_KEYS:
            if isinstance(payload.get(key), list):
                return payload[key]
    raise AdapterError(
        "could not locate an item list in the JSON response; "
        "set 'items_path' in sources.yaml for this source"
    )


async def fetch_json_api(client: httpx.AsyncClient, source: SourceConfig) -> list[dict[str, Any]]:
    try:
        resp = await client.get(source.url, timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPError as e:
        raise AdapterError(f"fetch failed: {e}") from e
    except json.JSONDecodeError as e:
        raise AdapterError(f"response was not valid JSON: {e}") from e
    return parse_json_api(payload, source)


def parse_json_api(payload: Any, source: SourceConfig) -> list[dict[str, Any]]:
    # field_map values are dot-paths (e.g. "properties.place") resolved with
    # _get_by_path, so both flat and nested item shapes work without adapter
    # changes — the source config carries the shape knowledge, not the code.
    field_map = source.extra.get("field_map", {})
    title_key = field_map.get("title", "title")
    url_key = field_map.get("url", "url")
    summary_key = field_map.get("summary", "summary")
    published_key = field_map.get("published_at", "published_at")

    raw_items = _find_item_list(payload, source.extra.get("items_path"))

    items = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        title = str(_get_by_path(raw, title_key) or "").strip()
        url = str(_get_by_path(raw, url_key) or "").strip()
        if not title or not url:
            continue
        summary = str(_get_by_path(raw, summary_key) or "")
        published_at = _get_by_path(raw, published_key)
        items.append({
            "title": title,
            "url": url,
            "summary": summary,
            "published_at": str(published_at) if published_at is not None else None,
            "raw_payload": raw,
        })
    return items


# --- HTML scrape fallback -------------------------------------------------

async def fetch_scraper(client: httpx.AsyncClient, source: SourceConfig) -> list[dict[str, Any]]:
    try:
        resp = await client.get(source.url, timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise AdapterError(f"fetch failed: {e}") from e
    return parse_scraper(resp.text, source)


def parse_scraper(html: str, source: SourceConfig) -> list[dict[str, Any]]:
    item_selector = source.extra.get("item_selector", "article")
    title_selector = source.extra.get("title_selector", "a")
    url_selector = source.extra.get("url_selector", "a")
    summary_selector = source.extra.get("summary_selector")

    soup = BeautifulSoup(html, "html.parser")
    elements = soup.select(item_selector)
    if not elements:
        raise AdapterError(f"item_selector {item_selector!r} matched nothing")

    items = []
    for el in elements:
        title_el = el.select_one(title_selector)
        url_el = el.select_one(url_selector)
        if title_el is None or url_el is None or not url_el.get("href"):
            continue
        title = title_el.get_text(strip=True)
        url = urljoin(source.url, url_el["href"])
        if not title or not url:
            continue
        summary = ""
        if summary_selector:
            summary_el = el.select_one(summary_selector)
            summary = summary_el.get_text(strip=True) if summary_el else ""
        items.append({
            "title": title,
            "url": url,
            "summary": summary,
            "published_at": None,
            "raw_payload": {"html_snippet": str(el)[:2000]},
        })
    return items


ADAPTERS = {
    "rss": fetch_rss,
    "json_api": fetch_json_api,
    "scraper": fetch_scraper,
}
