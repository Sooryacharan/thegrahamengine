"""Data model for the Graham Engine pipeline.

Plain dataclasses, not an ORM — the schema is small and the query layer in
db.py is thin enough that an ORM would add indirection without buying much.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Valid values for signals.sector — enforced at config-load time (see
# config.py) so a typo in sources.yaml fails fast instead of silently
# producing an unrecognized sector downstream.
SECTORS = (
    "geopolitics",
    "commodities",
    "long_duration_compounders",
    "catastrophe_driven",
    "money_flows",
)

# signals.status lifecycle: ingested -> discarded|passed -> drafted -> published
STATUS_INGESTED = "ingested"
STATUS_DISCARDED = "discarded"
STATUS_PASSED = "passed"
STATUS_DRAFTED = "drafted"
STATUS_PUBLISHED = "published"

# drafts.status lifecycle: draft -> approved -> published
# A human must explicitly approve a draft (`engine approve <draft_id>`)
# before PUBLISH will touch it — nothing gets posted without review.
DRAFT_STATUS_DRAFT = "draft"
DRAFT_STATUS_APPROVED = "approved"
DRAFT_STATUS_PUBLISHED = "published"


@dataclass
class Signal:
    id: str
    source: str
    sector: str
    title: str
    url: str
    dedup_key: str
    ingested_at: str
    summary: str = ""
    published_at: Optional[str] = None
    raw_payload: str = "{}"
    status: str = STATUS_INGESTED


@dataclass
class TriageResult:
    signal_id: str
    rules_prefilter_passed: bool
    created_at: str
    rules_prefilter_reason: Optional[str] = None
    gate1_pass: Optional[bool] = None
    gate2_pass: Optional[bool] = None
    gate3_pass: Optional[bool] = None
    reasoning: Optional[str] = None
    second_order_read: Optional[str] = None
    suggested_falsifier: Optional[str] = None
    confidence: Optional[float] = None
    failing_gate: Optional[str] = None
    llm_raw_response: Optional[str] = None
    id: Optional[int] = None


@dataclass
class Draft:
    signal_id: str
    revision: int
    observable: str
    mechanism: str
    assumption: str
    consequence: str
    falsifier: str
    created_at: str
    status: str = "draft"
    id: Optional[int] = None


@dataclass
class Publication:
    draft_id: int
    hook: str
    context: str
    falsifier_line: str
    payoff_line: str
    carousel_json: str
    caption_text: str
    created_at: str
    id: Optional[int] = None


@dataclass
class ScanSourceReport:
    """Per-source outcome of a single scan run."""
    name: str
    sector: str
    fetched: int = 0
    inserted: int = 0
    duplicates: int = 0
    error: Optional[str] = None


@dataclass
class ScanReport:
    sources: list = field(default_factory=list)

    @property
    def total_fetched(self) -> int:
        return sum(s.fetched for s in self.sources)

    @property
    def total_inserted(self) -> int:
        return sum(s.inserted for s in self.sources)

    @property
    def total_duplicates(self) -> int:
        return sum(s.duplicates for s in self.sources)

    @property
    def failed_sources(self) -> list:
        return [s for s in self.sources if s.error]
