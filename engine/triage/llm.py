"""Anthropic API call for the TRIAGE gate-scoring pass. Renders
prompts/triage.md, calls the Messages API with a JSON-schema output
constraint for strict JSON, and hands the raw response text to
engine.triage.gates for defensive parsing — this module never interprets
the content itself, only fetches it.
"""
from __future__ import annotations

from pathlib import Path

import anthropic

from engine.config import anthropic_api_key
from engine.models import Signal

PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "triage.md"

MAX_TOKENS = 2048

TRIAGE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "gate1_pass": {"type": "boolean"},
        "gate2_pass": {"type": "boolean"},
        "gate3_pass": {"type": "boolean"},
        "reasoning": {"type": "string"},
        "second_order_read": {"type": "string"},
        "suggested_falsifier": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": [
        "gate1_pass", "gate2_pass", "gate3_pass",
        "reasoning", "second_order_read", "suggested_falsifier", "confidence",
    ],
    "additionalProperties": False,
}


def load_prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def render_prompt(signal: Signal) -> str:
    template = load_prompt_template()
    return (
        template
        .replace("{{sector}}", signal.sector)
        .replace("{{source}}", signal.source)
        .replace("{{title}}", signal.title)
        .replace("{{summary}}", signal.summary or "(no summary provided)")
        .replace("{{url}}", signal.url)
    )


def score_signal(signal: Signal, model: str) -> str:
    """Calls the Anthropic API and returns the raw response text.

    Raises anthropic.APIError (or a subclass) on transport/API failure —
    callers decide how to handle that. Whether the *content* is valid JSON
    is never checked here; that defensive parsing lives in gates.py so it
    can be unit-tested without a network call.
    """
    client = anthropic.Anthropic(api_key=anthropic_api_key())
    prompt = render_prompt(signal)

    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        output_config={"format": {"type": "json_schema", "schema": TRIAGE_JSON_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )

    if response.stop_reason == "refusal":
        return "{}"  # deliberately malformed -> gates.py records it as discarded

    for block in response.content:
        if block.type == "text":
            return block.text
    return "{}"
