"""Ask one question.   python -m aegis_kb.ask "Is PS-04 the same component as PS-04A?"  [--llm]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .answer import answer_question
from .kb_schema import KB
from .llm import Gemini
from .schema import read_jsonl


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--kb", default="data/processed/kb.json")
    ap.add_argument("--segments", default="data/processed/segments.jsonl")
    ap.add_argument("--cache", default="data/cache/llm")
    ap.add_argument("--llm", action="store_true")
    a = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    kb = KB.load(Path(a.kb))
    segs = {s.segment_id: s for s in read_jsonl(Path(a.segments))}
    r = answer_question(a.question, kb, segs, llm=Gemini(Path(a.cache)) if a.llm else None)
    print(f"\nQ: {r['question']}\n[intent: {r['intent']} | mode: {r['mode']}]\n\n{r['answer']}\n")
    for c in r["caveats"]:
        print(f"CAVEAT: {c}")
    print(f"\nclaims: {', '.join(r['claims']) or '-'} | conflict records: {', '.join(r['conflicts']) or '-'} | gaps: {', '.join(r['gaps']) or '-'}")
    print("evidence:")
    for e in r["evidence"][:10]:
        print(f"  [{e['role']}] {e['segment_id']}  {e['location']}\n      {e['snippet']}")
    if r.get("llm_rejected"):
        print(f"\n(LLM answer rejected, deterministic answer shown: {r['llm_rejected']})")


if __name__ == "__main__":
    main()
