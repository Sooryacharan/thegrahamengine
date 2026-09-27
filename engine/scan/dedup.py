"""Dedup key computation, kept separate so it can be unit-tested without
touching the database or network."""
from __future__ import annotations

import hashlib
import re

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize_title(title: str) -> str:
    t = title.strip().lower()
    t = _PUNCT_RE.sub("", t)
    t = _WHITESPACE_RE.sub(" ", t)
    return t.strip()


def compute_dedup_key(source_name: str, title: str, url: str) -> str:
    """Dedup on (source + normalized title + url), per the SCAN spec."""
    normalized = f"{source_name}|{normalize_title(title)}|{url.strip().lower()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
