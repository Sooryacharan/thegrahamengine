"""Anthropic API call for the BUILD Bridge-draft generation pass. Renders
prompts/bridge.md, calls the Messages API with a JSON-schema output
constraint for strict JSON, and hands the raw response text to
engine.build.bridge for defensive parsing — this module never interprets
the content itself, only fetches it.
"""
from __future__ import annotations

from pathlib import Path

import anthropic

from engine.config import anthropic_api_key
from engine.models import Signal

PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "bridge.md"

MAX_TOKENS = 2048

BRIDGE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "observable": {"type": "string"},
        "mechanism": {"type": "string"},
        "assumption": {"type": "string"},
        "consequence": {"type": "string"},
        "falsifier": {"type": "string"},
    },
    "required": ["observable", "mechanism", "assumption", "consequence", "falsifier"],
    "additionalProperties": False,
}


def load_prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def render_prompt(
    signal: Signal, triage_reasoning: str, second_order_read: str, suggested_falsifier: str
) -> str:
    template = load_prompt_template()
    return (
        template
        .replace("{{sector}}", signal.sector)
        .replace("{{source}}", signal.source)
        .replace("{{title}}", signal.title)
        .replace("{{summary}}", signal.summary or "(no summary provided)")
        .replace("{{url}}", signal.url)
        .replace("{{triage_reasoning}}", triage_reasoning or "(none)")
        .replace("{{triage_second_order_read}}", second_order_read or "(none)")
        .replace("{{triage_suggested_falsifier}}", suggested_falsifier or "(none)")
    )


def generate_draft(
    signal: Signal,
    triage_reasoning: str,
    second_order_read: str,
    suggested_falsifier: str,
    model: str,
) -> str:
    """Calls the Anthropic API and returns the raw response text.

    Raises anthropic.APIError (or a subclass) on transport/API failure —
    callers decide how to handle that. Whether the *content* is valid JSON
    is never checked here; that defensive parsing lives in bridge.py so it
    can be unit-tested without a network call.
    """
    client = anthropic.Anthropic(api_key=anthropic_api_key())
    prompt = render_prompt(signal, triage_reasoning, second_order_read, suggested_falsifier)

    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        output_config={"format": {"type": "json_schema", "schema": BRIDGE_JSON_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )

    if response.stop_reason == "refusal":
        return "{}"  # deliberately malformed -> bridge.py records it as a failed draft

    for block in response.content:
        if block.type == "text":
            return block.text
    return "{}"
