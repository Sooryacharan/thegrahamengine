"""Gemini API call for the PUBLISH assembly pass. Renders
prompts/publish.md, calls the Gemini API in JSON mode, and hands the raw
response text to engine.publish.assembly for defensive parsing — this
module never interprets the content itself, only fetches it.
"""
from __future__ import annotations

from pathlib import Path

from google import genai
from google.genai import types

from engine.config import gemini_api_key

PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "publish.md"

MAX_OUTPUT_TOKENS = 3072


def load_prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def render_prompt(
    sector: str, source: str, title: str,
    observable: str, mechanism: str, assumption: str, consequence: str, falsifier: str,
) -> str:
    template = load_prompt_template()
    return (
        template
        .replace("{{sector}}", sector)
        .replace("{{source}}", source)
        .replace("{{title}}", title)
        .replace("{{observable}}", observable)
        .replace("{{mechanism}}", mechanism)
        .replace("{{assumption}}", assumption)
        .replace("{{consequence}}", consequence)
        .replace("{{falsifier}}", falsifier)
    )


def generate_publication(
    sector: str, source: str, title: str,
    observable: str, mechanism: str, assumption: str, consequence: str, falsifier: str,
    model: str,
) -> str:
    """Calls the Gemini API and returns the raw response text.

    Raises google.genai.errors.APIError (or a subclass) on transport/API
    failure — callers decide how to handle that. Whether the *content* is
    valid JSON is never checked here; that defensive parsing lives in
    assembly.py so it can be unit-tested without a network call.
    """
    client = genai.Client(api_key=gemini_api_key())
    prompt = render_prompt(sector, source, title, observable, mechanism, assumption, consequence, falsifier)

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=MAX_OUTPUT_TOKENS,
        ),
    )

    return response.text or "{}"  # blocked/empty response -> assembly.py records it as a failed publication
