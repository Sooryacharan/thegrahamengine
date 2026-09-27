"""Loads .env and sources.yaml, and validates source configs.

Nothing in the pipeline should read `os.environ` or open `sources.yaml`
directly outside of this module — it's the single seam for configuration.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

from engine.models import SECTORS

SOURCE_TYPES = ("rss", "json_api", "scraper")

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_SOURCES_PATH = REPO_ROOT / "sources.yaml"


class ConfigError(ValueError):
    """Raised for malformed sources.yaml — fails fast at load time."""


@dataclass
class SourceConfig:
    name: str
    type: str
    url: str
    sector: str
    poll_interval: int
    # Adapter-specific knobs (field_map / items_path for json_api,
    # item_selector / title_selector / etc. for scraper). Left as a free
    # dict so adding a new knob never requires a schema change here.
    extra: dict[str, Any] = field(default_factory=dict)


def load_env(dotenv_path: Optional[str] = None) -> None:
    load_dotenv(dotenv_path or (REPO_ROOT / ".env"))


def anthropic_api_key() -> Optional[str]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return key or None


def anthropic_model() -> str:
    return os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")


def db_path() -> str:
    return os.environ.get("DB_PATH", str(REPO_ROOT / "data" / "engine.db"))


def log_level() -> str:
    return os.environ.get("LOG_LEVEL", "INFO").upper()


def load_sources(path: Optional[str] = None) -> list[SourceConfig]:
    p = Path(path) if path else DEFAULT_SOURCES_PATH
    if not p.exists():
        raise ConfigError(f"sources.yaml not found at {p}")

    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    entries = raw.get("sources")
    if not isinstance(entries, list):
        raise ConfigError("sources.yaml must have a top-level 'sources' list")

    sources: list[SourceConfig] = []
    seen_names: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigError(f"sources.yaml entry #{i} is not a mapping")

        missing = [k for k in ("name", "type", "url", "sector", "poll_interval") if k not in entry]
        if missing:
            raise ConfigError(f"sources.yaml entry #{i} ({entry.get('name', '?')!r}) missing fields: {missing}")

        name, type_, url, sector, poll_interval = (
            entry["name"], entry["type"], entry["url"], entry["sector"], entry["poll_interval"],
        )

        if type_ not in SOURCE_TYPES:
            raise ConfigError(f"source {name!r}: type {type_!r} must be one of {SOURCE_TYPES}")
        if sector not in SECTORS:
            raise ConfigError(f"source {name!r}: sector {sector!r} must be one of {SECTORS}")
        if not isinstance(poll_interval, int) or poll_interval <= 0:
            raise ConfigError(f"source {name!r}: poll_interval must be a positive integer (seconds)")
        if name in seen_names:
            raise ConfigError(f"duplicate source name {name!r} in sources.yaml")
        seen_names.add(name)

        extra = {k: v for k, v in entry.items() if k not in ("name", "type", "url", "sector", "poll_interval")}
        sources.append(SourceConfig(name=name, type=type_, url=url, sector=sector, poll_interval=poll_interval, extra=extra))

    return sources
