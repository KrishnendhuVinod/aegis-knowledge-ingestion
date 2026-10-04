"""Layer 0 representation: the *Segment*.

Every parser, whatever the file format, emits Segments. A Segment is the smallest
unit that we can point at in a source ("operator_manual, page 1, section 4.3,
bullet 2"). Facts extracted later (Day 2) reference segment_ids, so provenance is
structural: a claim cannot exist without pointing at the segment(s) it came from.

Two separate numbers are kept on purpose:
  * `confidence`  -> how faithfully we READ the source (OCR/vision can be wrong)
  * trust tier (sources.py) -> how much the SOURCE should be believed
A perfectly-read field note is still a low-trust source; a blurry scan of an
official record is a high-trust source read with low fidelity.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

# How the text was obtained. Drives the "deterministic vs model-based" report.
METHOD_DETERMINISTIC = "deterministic"   # rule-based parsing of a digital format
METHOD_OCR = "ocr"                        # tesseract (classical, offline)
METHOD_VISION = "vision_llm"              # Gemini reading an image

SEGMENT_KINDS = {
    "heading", "paragraph", "bullet", "table_row", "kv", "json_leaf",
    "slide_text", "footnote", "metadata",
    "diagram_node", "diagram_edge", "diagram_legend",
    "ocr_text", "vision_field", "vision_edge", "vision_text", "vision_table_row",
}


@dataclass
class Segment:
    segment_id: str            # stable: "<doc_id>::<nnn>"
    doc_id: str
    kind: str
    text: str                  # human-readable rendering of the segment
    location: dict             # page / section / sheet+row / slide / json_path ...
    method: str                # one of METHOD_*
    confidence: float          # reading fidelity, 0..1 (NOT truth of the content)
    data: dict = field(default_factory=dict)   # structured payload (row dict, edge, ...)

    def __post_init__(self):
        assert self.kind in SEGMENT_KINDS, f"unknown segment kind {self.kind}"
        assert 0.0 <= self.confidence <= 1.0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class SegmentBuilder:
    """Hands out stable sequential ids for one document."""

    def __init__(self, doc_id: str):
        self.doc_id = doc_id
        self.segments: list[Segment] = []

    def add(self, kind: str, text: str, location: dict, method: str = METHOD_DETERMINISTIC,
            confidence: float = 1.0, data: dict | None = None) -> Segment:
        text = text.strip()
        seg = Segment(
            segment_id=f"{self.doc_id}::{len(self.segments) + 1:03d}",
            doc_id=self.doc_id, kind=kind, text=text, location=location,
            method=method, confidence=confidence, data=data or {},
        )
        self.segments.append(seg)
        return seg


def write_jsonl(segments: list[Segment], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for s in segments:
            f.write(s.to_json() + "\n")


def read_jsonl(path: Path) -> list[Segment]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(Segment(**json.loads(line)))
    return out
