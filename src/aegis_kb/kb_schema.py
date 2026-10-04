"""Layer 1-2 records (see docs/schema.md). Plain dataclasses, JSON round-trippable."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

# Claim.status vocabulary
STATUSES = {
    "asserted",                  # a source states it as fact
    "planned",                   # source itself labels it planned / not yet in effect
    "observation",               # observed on one unit at one moment (screenshots, calibration record)
    "low_trust_observation",     # unreviewed / uncalibrated / undated observation
    "inferred",                  # we linked two vocabularies; no document states the link
    "explicitly_not_specified",  # a source says the value is not specified (absence stated, not assumed)
}


@dataclass
class Entity:
    id: str
    name: str
    type: str                                # component | alarm | software | diagram_part | ...
    aliases: list = field(default_factory=list)
    location: str | None = None
    status: str | None = None
    notes: str | None = None
    registered: bool = True                  # False => seen only in a drawing/slide, not in the register
    evidence: list = field(default_factory=list)


@dataclass
class AliasDecision:
    surface: str                             # the label as found
    entity_id: str | None
    relation: str      # same_as | variant_of | corresponds_to | superseded_by | distinct_from | related_not_same
    decision: str      # accepted | rejected
    reason: str
    evidence: list = field(default_factory=list)
    confidence: float = 1.0


@dataclass
class Claim:
    id: str
    subject: str
    predicate: str
    value: object
    unit: str | None
    applies_when: dict
    evidence: list
    docs: list
    trust_rank: int                          # best (lowest) rank among supporting docs
    status: str = "asserted"
    note: str | None = None
    reading_confidence: float = 1.0          # worst reading confidence among evidence segments
    extraction: str = "rule"


@dataclass
class Conflict:
    id: str
    kind: str          # scoped_coexistence | conflict | observation_disagrees | ambiguity
    subject: str
    predicate: str
    claim_ids: list
    description: str
    resolution: str


@dataclass
class Gap:
    id: str
    topic: str
    terms: list
    entity_aliases: list
    segments_searched: int
    hits: list                               # segments that actually answer it (empty => not in corpus)
    near_misses: list                        # segments that matched loosely but do NOT answer it
    finding: str                             # not_found | explicitly_not_specified
    related_claims: list
    note: str
    doc_scope: list = field(default_factory=list)


@dataclass
class KB:
    entities: list
    decisions: list
    claims: list
    conflicts: list
    gaps: list
    meta: dict = field(default_factory=dict)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def load(path: Path) -> "KB":
        d = json.loads(path.read_text(encoding="utf-8"))
        return KB([Entity(**x) for x in d["entities"]], [AliasDecision(**x) for x in d["decisions"]],
                  [Claim(**x) for x in d["claims"]], [Conflict(**x) for x in d["conflicts"]],
                  [Gap(**x) for x in d["gaps"]], d.get("meta", {}))
