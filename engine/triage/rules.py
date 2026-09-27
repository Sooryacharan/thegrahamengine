"""Cheap, deterministic prefilter that drops obvious noise before paying
for an LLM call. Intentionally coarse — it exists to save API spend on
garbage, not to make the real triage judgment. Anything that isn't
obviously noise passes through to the LLM gate-scoring pass.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

MIN_CONTENT_LENGTH = 25

NOISE_PATTERNS = [
    r"\byou won'?t believe\b",
    r"\btop \d+\b",
    r"\bin pictures\b",
    r"\bphotos?:\s",
    r"\bwatch:\s",
    r"\bvideo:\s",
    r"\bhoroscope\b",
    r"\bquiz\b",
    r"\bcelebrity\b",
    r"\bobituary\b",
    r"\bfinal score\b",
    r"\bwins? \d+-\d+\b",
]
_NOISE_RE = re.compile("|".join(NOISE_PATTERNS), re.IGNORECASE)


@dataclass
class RulesResult:
    passed: bool
    reason: Optional[str] = None


def rules_prefilter(title: str, summary: str) -> RulesResult:
    content = f"{title} {summary}".strip()

    if len(content) < MIN_CONTENT_LENGTH:
        return RulesResult(passed=False, reason="content too short to carry a thesis")

    match = _NOISE_RE.search(content)
    if match:
        return RulesResult(passed=False, reason=f"matched noise pattern: {match.group(0)!r}")

    return RulesResult(passed=True)
