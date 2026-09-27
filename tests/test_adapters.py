import json
from pathlib import Path

import pytest

from engine.config import SourceConfig
from engine.scan.adapters import AdapterError, parse_json_api, parse_rss, parse_scraper

FIXTURES = Path(__file__).parent / "fixtures"


def make_source(**overrides) -> SourceConfig:
    defaults = dict(name="test-source", type="rss", url="https://example.com", sector="geopolitics", poll_interval=900, extra={})
    defaults.update(overrides)
    return SourceConfig(**defaults)


# --- RSS -------------------------------------------------------------------

def test_parse_rss_extracts_all_items():
    content = (FIXTURES / "sample.rss").read_bytes()
    items = parse_rss(content, make_source(type="rss"))
    assert len(items) == 2
    assert items[0]["title"] == "OPEC+ signals surprise supply cut starting Q3"
    assert items[0]["url"] == "https://example.com/articles/opec-supply-cut"
    assert "OPEC+" in items[0]["summary"] or "reduce output" in items[0]["summary"]
    assert items[0]["published_at"]


def test_parse_rss_malformed_content_raises_adapter_error():
    with pytest.raises(AdapterError):
        parse_rss(b"this is not xml or a feed at all &&&", make_source())


# --- JSON API ----------------------------------------------------------

def test_parse_json_api_default_items_key():
    payload = json.loads((FIXTURES / "sample_json.json").read_text())
    items = parse_json_api(payload, make_source(type="json_api"))
    assert len(items) == 2
    assert items[0]["title"] == "Sovereign wealth fund rotates $4B out of long-duration bonds"
    assert items[0]["url"].startswith("https://")
    assert items[1]["summary"]


def test_parse_json_api_with_custom_items_path_and_field_map():
    payload = {
        "features": [
            {"properties": {"place": "M6.8 - Japan", "url": "https://usgs.gov/x", "time": 123}},
        ]
    }
    source = make_source(type="json_api", extra={
        "items_path": "features",
        "field_map": {"title": "properties.place", "url": "properties.url", "published_at": "properties.time"},
    })
    items = parse_json_api(payload, source)
    assert len(items) == 1
    assert items[0]["title"] == "M6.8 - Japan"
    assert items[0]["url"] == "https://usgs.gov/x"
    assert items[0]["published_at"] == "123"


def test_parse_json_api_skips_items_missing_title_or_url():
    payload = {"items": [{"title": "", "url": "https://x.com"}, {"title": "ok", "url": ""}]}
    items = parse_json_api(payload, make_source(type="json_api"))
    assert items == []


def test_parse_json_api_raises_when_no_list_found():
    payload = {"nope": "not a list of items anywhere"}
    with pytest.raises(AdapterError):
        parse_json_api(payload, make_source(type="json_api"))


# --- Scraper (HTML fallback) ---------------------------------------------

def test_parse_scraper_extracts_items_with_links():
    html = (FIXTURES / "sample.html").read_text()
    source = make_source(type="scraper", extra={
        "item_selector": "article",
        "title_selector": "h2 a",
        "url_selector": "h2 a",
        "summary_selector": "p.summary",
    })
    items = parse_scraper(html, source)
    # the third <article> has no link and must be skipped, not crash the run
    assert len(items) == 2
    assert items[0]["title"] == "Reinsurer takes reserve charge after cat losses"
    assert items[0]["url"] == "https://example.com/articles/insurer-reserve-charge"
    assert items[0]["summary"]


def test_parse_scraper_raises_when_selector_matches_nothing():
    html = (FIXTURES / "sample.html").read_text()
    source = make_source(type="scraper", extra={"item_selector": ".does-not-exist"})
    with pytest.raises(AdapterError):
        parse_scraper(html, source)
