import pytest

from engine.config import ConfigError, load_sources


def write_yaml(tmp_path, text):
    p = tmp_path / "sources.yaml"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_load_real_sources_yaml_from_repo_root():
    # The actual seed file shipped with the repo must load cleanly.
    sources = load_sources()
    assert len(sources) >= 5
    assert {s.type for s in sources} == {"rss", "json_api", "scraper"}


def test_missing_required_field_raises(tmp_path):
    path = write_yaml(tmp_path, """
sources:
  - name: "Bad Source"
    type: rss
    sector: geopolitics
    poll_interval: 900
""")
    with pytest.raises(ConfigError):
        load_sources(path)


def test_invalid_type_raises(tmp_path):
    path = write_yaml(tmp_path, """
sources:
  - name: "Bad Source"
    type: carrier_pigeon
    url: "https://example.com"
    sector: geopolitics
    poll_interval: 900
""")
    with pytest.raises(ConfigError):
        load_sources(path)


def test_invalid_sector_raises(tmp_path):
    path = write_yaml(tmp_path, """
sources:
  - name: "Bad Source"
    type: rss
    url: "https://example.com"
    sector: crypto
    poll_interval: 900
""")
    with pytest.raises(ConfigError):
        load_sources(path)


def test_duplicate_name_raises(tmp_path):
    path = write_yaml(tmp_path, """
sources:
  - name: "Dup"
    type: rss
    url: "https://example.com/a"
    sector: geopolitics
    poll_interval: 900
  - name: "Dup"
    type: rss
    url: "https://example.com/b"
    sector: commodities
    poll_interval: 900
""")
    with pytest.raises(ConfigError):
        load_sources(path)


def test_extra_keys_land_in_extra(tmp_path):
    path = write_yaml(tmp_path, """
sources:
  - name: "With extra"
    type: json_api
    url: "https://example.com/api"
    sector: money_flows
    poll_interval: 900
    items_path: hits
    field_map:
      title: headline
""")
    sources = load_sources(path)
    assert sources[0].extra["items_path"] == "hits"
    assert sources[0].extra["field_map"]["title"] == "headline"
