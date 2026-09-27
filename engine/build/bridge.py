"""Pure functions that turn the LLM's raw JSON response into a Bridge
draft. No I/O here — network calls live in llm.py. Kept pure and
defensively parsed so a malformed model response can never crash a run;
a response that doesn't match the expected shape is always treated as a
failure to draft, never a crash, never a fabricated draft.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

REQUIRED_KEYS = ("observable", "mechanism", "assumption", "consequence", "falsifier")


@dataclass
class BridgeEvaluation:
    ok: bool
    observable: Optional[str] = None
    mechanism: Optional[str] = None
    assumption: Optional[str] = None
    consequence: Optional[str] = None
    falsifier: Optional[str] = None
    error: Optional[str] = None
    raw_response: str = ""


def parse_llm_response(raw_text: str) -> Optional[dict[str, Any]]:
    """Defensively parse and validate the model's JSON. Returns None
    (never raises) if the text isn't valid JSON, doesn't match the
    expected Bridge schema, or any field is blank."""
    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, dict):
        return None
    if any(key not in data for key in REQUIRED_KEYS):
        return None
    if not all(isinstance(data[k], str) and data[k].strip() for k in REQUIRED_KEYS):
        return None

    return data


def evaluate_bridge(raw_text: str) -> BridgeEvaluation:
    """The single entry point: parse raw LLM output into a Bridge draft.
    Malformed output is always treated as a failure to draft, never a
    crash and never a draft with a blank field."""
    parsed = parse_llm_response(raw_text)
    if parsed is None:
        return BridgeEvaluation(
            ok=False,
            error="LLM response was not valid JSON matching the expected Bridge schema, or a field was blank",
            raw_response=raw_text,
        )

    return BridgeEvaluation(
        ok=True,
        observable=parsed["observable"],
        mechanism=parsed["mechanism"],
        assumption=parsed["assumption"],
        consequence=parsed["consequence"],
        falsifier=parsed["falsifier"],
        raw_response=raw_text,
    )
