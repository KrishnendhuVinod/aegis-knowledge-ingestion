"""Build the knowledge base from the segment store.

    python -m aegis_kb.build_kb                 # reads data/processed/segments.jsonl, writes data/processed/kb.json
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from .conflicts import detect
from .entities import build_index
from .extractors import Extractor
from .gaps import find_gaps
from .kb_schema import KB
from .schema import read_jsonl, Segment

SKIP_KINDS = {"heading", "metadata", "ocr_text"}


def build(segs: list[Segment]) -> KB:
    idx = build_index(segs)
    claims = Extractor(segs, idx).run()
    conflicts = detect(claims, idx)
    gaps = find_gaps(segs, claims)
    cited = {e for c in claims for e in c.evidence}
    by_doc = Counter(s.doc_id for s in segs if s.kind not in SKIP_KINDS)
    used = Counter(s.doc_id for s in segs if s.kind not in SKIP_KINDS and s.segment_id in cited)
    cov = {d: {"content_segments": n, "cited_by_a_claim": used.get(d, 0)} for d, n in sorted(by_doc.items())}
    meta = {"segments": len(segs), "alias_collisions": idx.collisions, "coverage": cov}
    return KB(list(idx.entities.values()), idx.decisions, claims, conflicts, gaps, meta)


def summary(kb: KB) -> str:
    L = []
    reg = sum(e.registered for e in kb.entities)
    L.append(f"entities: {len(kb.entities)} ({reg} registered, {len(kb.entities) - reg} drawing-only)")
    dec = Counter((d.relation, d.decision) for d in kb.decisions)
    L.append("alias decisions: " + ", ".join(f"{r}/{d}={n}" for (r, d), n in sorted(dec.items())))
    L.append(f"claims: {len(kb.claims)}  by status: {dict(Counter(c.status for c in kb.claims))}")
    L.append(f"conflict records: {dict(Counter(c.kind for c in kb.conflicts))}")
    for c in kb.conflicts:
        L.append(f"  {c.id} [{c.kind}] {c.subject} / {c.predicate}")
    L.append("gaps:")
    for g in kb.gaps:
        L.append(f"  {g.id} {g.finding:24} hits={len(g.hits)} near_misses={len(g.near_misses)}  {g.topic}")
    L.append("coverage (content segments cited by at least one claim):")
    for d, v in kb.meta["coverage"].items():
        L.append(f"  {d:24} {v['cited_by_a_claim']:>3}/{v['content_segments']:<3}")
    if kb.meta["alias_collisions"]:
        L.append(f"ALIAS COLLISIONS: {kb.meta['alias_collisions']}")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments", default="data/processed/segments.jsonl")
    ap.add_argument("--out", default="data/processed/kb.json")
    a = ap.parse_args(argv)
    p = Path(a.segments)
    if not p.exists():
        sys.exit(f"{p} not found - run `python -m aegis_kb.ingest` first")
    kb = build(read_jsonl(p))
    kb.save(Path(a.out))
    print(summary(kb))
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
