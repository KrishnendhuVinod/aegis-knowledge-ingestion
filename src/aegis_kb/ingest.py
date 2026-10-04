"""Run every registered parser over the dataset and write the segment store.

    python -m aegis_kb.ingest --data data/raw/aegis-dataset --out data/processed

Outputs:
  segments.jsonl   every segment from every file (the Layer-0 store)
  manifest.json    per-document stats, parser, method mix, errors, trust tier
One parser failing never aborts the run; it is recorded in the manifest instead.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from .llm import Gemini
from .parsers import PARSERS
from .parsers.image_parser import ocr_available
from .parsers._common import Ctx
from .schema import write_jsonl
from .sources import REGISTRY


def run(data: Path, out: Path, cache: Path, use_llm: bool = True) -> dict:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    gem = Gemini(cache) if use_llm else None
    ctx = Ctx(root=data, gemini=gem)
    all_segments, manifest = [], {"documents": [], "unregistered_files": [], "llm": None,
                                    "ocr_available": ocr_available()}

    on_disk = {p.relative_to(data).as_posix() for p in data.rglob("*") if p.is_file()}
    registered = {s.path for s in REGISTRY}
    manifest["unregistered_files"] = sorted(on_disk - registered)

    for info in REGISTRY:
        entry = {**info.to_dict(), "segments": 0, "methods": {}, "kinds": {}, "error": None}
        path = data / info.path
        t0 = time.time()
        if not path.exists():
            entry["error"] = "FILE_MISSING"
        else:
            try:
                segs = PARSERS[info.parser](info, path, ctx)
                all_segments += segs
                entry["segments"] = len(segs)
                entry["methods"] = dict(Counter(s.method for s in segs))
                entry["kinds"] = dict(Counter(s.kind for s in segs))
            except Exception as e:                    # isolate failures, keep going
                entry["error"] = f"{type(e).__name__}: {e}"
        entry["seconds"] = round(time.time() - t0, 2)
        manifest["documents"].append(entry)

    if gem:
        manifest["llm"] = {"model": gem.model, "api_key_present": gem.can_call_api, **gem.stats}
    write_jsonl(all_segments, out / "segments.jsonl")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/raw/aegis-dataset")
    ap.add_argument("--out", default="data/processed")
    ap.add_argument("--cache", default="data/cache/llm")
    ap.add_argument("--no-llm", action="store_true", help="OCR/deterministic only; never call or read the model cache")
    a = ap.parse_args(argv)
    m = run(Path(a.data), Path(a.out), Path(a.cache), use_llm=not a.no_llm)

    print(f"{'doc_id':24}{'parser':18}{'tier':22}{'segs':>5}  methods")
    for d in m["documents"]:
        flag = f"  !! {d['error']}" if d["error"] else ""
        print(f"{d['doc_id']:24}{d['parser']:18}{d['trust_tier']:22}{d['segments']:>5}  {d['methods']}{flag}")
    print(f"\ntotal segments: {sum(d['segments'] for d in m['documents'])}")
    if not m["ocr_available"]:
        print("NOTE: Tesseract not found -> images/scans use the Gemini reading only (no OCR cross-check).")
    image_docs = [d for d in m["documents"] if d["parser"] in ("pdf_scan", "image_screenshot", "image_diagram")]
    empty = [d["doc_id"] for d in image_docs if d["segments"] == 0]
    if empty:
        print("WARNING: no text obtained for", empty, "- need Tesseract or a working GEMINI_API_KEY / cache.")
    if m["unregistered_files"]:
        print("UNREGISTERED FILES ON DISK:", m["unregistered_files"])
    if m["llm"]:
        print("llm:", m["llm"])
    return 1 if any(d["error"] for d in m["documents"]) else 0


if __name__ == "__main__":
    sys.exit(main())
