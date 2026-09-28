"""Gemini API call for the TRIAGE gate-scoring pass. Renders
prompts/triage.md, calls the Gemini API in JSON mode, and hands the raw
response text to engine.triage.gates for defensive parsing — this module
never interprets the content itself, only fetches it.
"""
from __future__ import annotations

from pathlib import Path

from google import genai
from google.genai import types

from engine.config import gemini_api_key
from engine.models import Signal

PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "triage.md"

MAX_OUTPUT_TOKENS = 2048


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
    """Calls the Gemini API and returns the raw response text.

    Raises google.genai.errors.APIError (or a subclass) on transport/API
    failure — callers decide how to handle that. Whether the *content* is
    valid JSON is never checked here; that defensive parsing lives in
    gates.py so it can be unit-tested without a network call.
    """
    client = genai.Client(api_key=gemini_api_key())
    prompt = render_prompt(signal)

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=MAX_OUTPUT_TOKENS,
        ),
    )

    return response.text or "{}"  # blocked/empty response -> gates.py records it as discarded
