"""Gemini API call for the BUILD Bridge-draft generation pass. Renders
prompts/bridge.md, calls the Gemini API with a JSON-schema output
constraint for strict JSON, and hands the raw response text to
engine.build.bridge for defensive parsing — this module never interprets
the content itself, only fetches it.
"""
from __future__ import annotations

from pathlib import Path

from google import genai
from google.genai import types

from engine.config import gemini_api_key
from engine.models import Signal

PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "bridge.md"

MAX_OUTPUT_TOKENS = 2048

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
    """Calls the Gemini API and returns the raw response text.

    Raises google.genai.errors.APIError (or a subclass) on transport/API
    failure — callers decide how to handle that. Whether the *content* is
    valid JSON is never checked here; that defensive parsing lives in
    bridge.py so it can be unit-tested without a network call.
    """
    client = genai.Client(api_key=gemini_api_key())
    prompt = render_prompt(signal, triage_reasoning, second_order_read, suggested_falsifier)

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=BRIDGE_JSON_SCHEMA,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        ),
    )

    return response.text or "{}"  # blocked/empty response -> bridge.py records it as a failed draft
