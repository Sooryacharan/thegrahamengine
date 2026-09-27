"""Pure functions that turn the LLM's raw JSON response into a
Publication. No I/O here — network calls live in llm.py. Kept pure and
defensively parsed so a malformed model response can never crash a run,
never fabricate a publication, and never silently pass.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

REQUIRED_STRING_KEYS = ("hook", "context", "falsifier_line", "payoff_line", "caption")


@dataclass
class PublicationEvaluation:
    ok: bool
    hook: Optional[str] = None
    context: Optional[str] = None
    falsifier_line: Optional[str] = None
    payoff_line: Optional[str] = None
    carousel_json: Optional[str] = None
    caption_text: Optional[str] = None
    error: Optional[str] = None
    raw_response: str = ""


def parse_llm_response(raw_text: str) -> Optional[dict[str, Any]]:
    """Defensively parse and validate the model's JSON. Returns None
    (never raises) if the text isn't valid JSON, doesn't match the
    expected publish schema, or any field is blank/empty."""
    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, dict):
        return None
    if any(key not in data for key in REQUIRED_STRING_KEYS):
        return None
    if not all(isinstance(data[k], str) and data[k].strip() for k in REQUIRED_STRING_KEYS):
        return None

    slides = data.get("carousel_slides")
    if not isinstance(slides, list) or not slides:
        return None
    if not all(isinstance(s, str) and s.strip() for s in slides):
        return None

    return data


def evaluate_publication(raw_text: str) -> PublicationEvaluation:
    """The single entry point: parse raw LLM output into a Publication.
    Malformed output is always treated as a failure to assemble, never a
    crash and never a publication with a blank field."""
    parsed = parse_llm_response(raw_text)
    if parsed is None:
        return PublicationEvaluation(
            ok=False,
            error="LLM response was not valid JSON matching the expected publish schema, or a field was blank",
            raw_response=raw_text,
        )

    return PublicationEvaluation(
        ok=True,
        hook=parsed["hook"],
        context=parsed["context"],
        falsifier_line=parsed["falsifier_line"],
        payoff_line=parsed["payoff_line"],
        carousel_json=json.dumps(parsed["carousel_slides"]),
        caption_text=parsed["caption"],
        raw_response=raw_text,
    )
