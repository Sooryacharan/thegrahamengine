"""Pure functions that turn the LLM's raw JSON response into a triage
verdict. No I/O here — network calls live in llm.py. Kept pure and
defensively parsed so a malformed model response can never crash a run;
a response that doesn't match the expected shape is always treated as a
fail, never as a crash or a silent pass.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

GATE1_MECHANISM = "gate1_mechanism"
GATE2_NON_CONSENSUS = "gate2_non_consensus"
GATE3_REUSABLE_LENS = "gate3_reusable_lens"
MALFORMED = "malformed_llm_output"

REQUIRED_KEYS = (
    "gate1_pass", "gate2_pass", "gate3_pass",
    "reasoning", "second_order_read", "suggested_falsifier", "confidence",
)


@dataclass
class GateEvaluation:
    passed: bool
    malformed: bool
    gate1_pass: Optional[bool] = None
    gate2_pass: Optional[bool] = None
    gate3_pass: Optional[bool] = None
    reasoning: Optional[str] = None
    second_order_read: Optional[str] = None
    suggested_falsifier: Optional[str] = None
    confidence: Optional[float] = None
    failing_gate: Optional[str] = None
    error: Optional[str] = None
    raw_response: str = ""


def parse_llm_response(raw_text: str) -> Optional[dict[str, Any]]:
    """Defensively parse and validate the model's JSON. Returns None
    (never raises) if the text isn't valid JSON or doesn't match the
    expected triage schema."""
    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, dict):
        return None
    if any(key not in data for key in REQUIRED_KEYS):
        return None
    if not all(isinstance(data[k], bool) for k in ("gate1_pass", "gate2_pass", "gate3_pass")):
        return None

    confidence = data.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    if not (0.0 <= float(confidence) <= 1.0):
        return None

    for k in ("reasoning", "second_order_read", "suggested_falsifier"):
        if not isinstance(data[k], str):
            return None

    return data


def gate1_mechanism(parsed: dict[str, Any]) -> bool:
    return bool(parsed["gate1_pass"])


def gate2_non_consensus(parsed: dict[str, Any]) -> bool:
    return bool(parsed["gate2_pass"])


def gate3_reusable_lens(parsed: dict[str, Any]) -> bool:
    return bool(parsed["gate3_pass"])


def evaluate_gates(raw_text: str) -> GateEvaluation:
    """The single entry point: parse raw LLM output and apply all three
    gates in order. A signal must pass every gate to survive; the first
    gate that fails is recorded as `failing_gate`. Malformed output is
    always treated as a fail (never a crash, never a silent pass)."""
    parsed = parse_llm_response(raw_text)
    if parsed is None:
        return GateEvaluation(
            passed=False,
            malformed=True,
            failing_gate=MALFORMED,
            error="LLM response was not valid JSON matching the expected triage schema",
            raw_response=raw_text,
        )

    g1 = gate1_mechanism(parsed)
    g2 = gate2_non_consensus(parsed)
    g3 = gate3_reusable_lens(parsed)

    failing_gate = None
    if not g1:
        failing_gate = GATE1_MECHANISM
    elif not g2:
        failing_gate = GATE2_NON_CONSENSUS
    elif not g3:
        failing_gate = GATE3_REUSABLE_LENS

    return GateEvaluation(
        passed=g1 and g2 and g3,
        malformed=False,
        gate1_pass=g1,
        gate2_pass=g2,
        gate3_pass=g3,
        reasoning=parsed["reasoning"],
        second_order_read=parsed["second_order_read"],
        suggested_falsifier=parsed["suggested_falsifier"],
        confidence=float(parsed["confidence"]),
        failing_gate=failing_gate,
        raw_response=raw_text,
    )
