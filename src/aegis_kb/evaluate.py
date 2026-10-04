"""Run the 23 evaluation questions (+ reworded variants) and score them.

    python -m aegis_kb.evaluate            # deterministic composer (reproducible baseline)
    python -m aegis_kb.evaluate --llm      # also run the Gemini composer (cached; validated; falls back if rejected)

Metrics (written to data/processed/eval_report.md and eval_results.json):
  pass rate overall / answerable / caveated / unanswerable(abstention), content recall, evidence-document recall,
  caveat/flag recall, numeric grounding (no number in an answer that is absent from its evidence), citation validity.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .answer import answer_question
from .gold import GOLD, PARAPHRASES
from .kb_schema import KB
from .llm import Gemini
from .retrieve import Retriever
from .schema import read_jsonl

NUM = re.compile(r"\d+(?:\.\d+)?")


def score(g, a, kb, segs):
    text = a["answer"] + " " + " ".join(a["caveats"])
    must = [bool(re.search(p, text, re.I | re.M)) for p in g["must"]]
    bad = [p for p in g.get("must_not", []) if re.search(p, text, re.I | re.M)]
    sup = {e["doc_id"] for e in a["evidence"] if e["role"] == "supports"}
    docs_ok = all(d in sup for d in g["docs"])
    pred = {x.id: x.predicate for x in kb.conflicts}
    got = {pred[i] for i in a["conflicts"] if i in pred}
    flags_ok = all(f in got for f in g.get("flags", []))
    ev_text = " ".join(segs[e["segment_id"]].text for e in a["evidence"] if e["segment_id"] in segs)
    claim_text = " ".join(f"{kb_c.value} {kb_c.note or ''}" for kb_c in kb.claims if kb_c.id in set(a["claims"]))
    allowed = set(NUM.findall(g["q"] + " " + a["question"] + " " + ev_text + " " + claim_text))
    allowed.add(str(kb.meta.get("segments")))          # 'searched N segments' is a statistic reported by the KB build
    ungrounded = sorted({n for n in NUM.findall(text) if n not in allowed})
    cites_ok = all(e["segment_id"] in segs for e in a["evidence"])
    ok = all(must) and not bad and docs_ok and flags_ok
    return {"pass": ok, "content": sum(must) / len(must), "missing": [p for p, m in zip(g["must"], must) if not m],
            "forbidden_hit": bad, "docs_ok": docs_ok, "flags_ok": flags_ok, "ungrounded_numbers": ungrounded,
            "citations_valid": cites_ok}


def run(kb, segs, llm=None):
    rt = Retriever(kb)
    rows = []
    items = [(qid, g["q"], g, "original") for qid, g in GOLD.items()] + \
            [(qid, q, GOLD[qid], "reworded") for qid, q in PARAPHRASES]
    for qid, q, g, setname in items:
        a = answer_question(q, kb, segs, rt, llm)
        s = score({**g, "q": q}, a, kb, segs)
        rows.append({"id": qid, "set": setname, "question": q, "kind": g["kind"], "intent": a["intent"],
                     "mode": a["mode"], "answer": a["answer"], "caveats": a["caveats"], "claims": a["claims"],
                     "conflicts": a["conflicts"], "gaps": a["gaps"], "evidence": a["evidence"],
                     "llm_rejected": a.get("llm_rejected"), "score": s})
    return rows


def metrics(rows):
    def rate(sel):
        sel = list(sel)
        return (sum(r["score"]["pass"] for r in sel), len(sel))
    out = {}
    for name, sel in (("original_all", [r for r in rows if r["set"] == "original"]),
                      ("original_answerable", [r for r in rows if r["set"] == "original" and r["kind"] == "answerable"]),
                      ("original_caveated", [r for r in rows if r["set"] == "original" and r["kind"] == "caveated"]),
                      ("original_unanswerable_abstention", [r for r in rows if r["set"] == "original" and r["kind"] == "unanswerable"]),
                      ("reworded_all", [r for r in rows if r["set"] == "reworded"])):
        p, n = rate(sel)
        out[name] = {"passed": p, "total": n, "rate": round(p / n, 3) if n else None}
    out["mean_content_recall"] = round(sum(r["score"]["content"] for r in rows) / len(rows), 3)
    out["numeric_grounding_rate"] = round(sum(not r["score"]["ungrounded_numbers"] for r in rows) / len(rows), 3)
    out["citation_validity_rate"] = round(sum(r["score"]["citations_valid"] for r in rows) / len(rows), 3)
    out["answers_with_llm_mode"] = sum(r["mode"] == "llm" for r in rows)
    out["llm_rejected"] = sum(bool(r["llm_rejected"]) for r in rows)
    return out


def report_md(rows, m, title):
    L = [f"# Evaluation report - {title}", "", "| Metric | Result |", "|---|---|"]
    for k, v in m.items():
        L.append(f"| {k} | {v['passed']}/{v['total']} ({v['rate']:.0%}) |" if isinstance(v, dict) else f"| {k} | {v} |")
    L += ["", "| ID | Set | Intent | Result | Issues |", "|---|---|---|---|---|"]
    for r in rows:
        s = r["score"]
        issues = []
        if s["missing"]:
            issues.append("missing: " + "; ".join(s["missing"]))
        if s["forbidden_hit"]:
            issues.append("forbidden: " + "; ".join(s["forbidden_hit"]))
        if not s["docs_ok"]:
            issues.append("evidence docs")
        if not s["flags_ok"]:
            issues.append("flag not surfaced")
        if s["ungrounded_numbers"]:
            issues.append(f"ungrounded numbers {s['ungrounded_numbers']}")
        L.append(f"| {r['id']} | {r['set']} | {r['intent']} | {'PASS' if s['pass'] else 'FAIL'} | {' / '.join(issues)} |")
    L += ["", "## Answers", ""]
    for r in rows:
        L += [f"### {r['id']} ({r['set']}): {r['question']}", "", r["answer"], ""]
        for c in r["caveats"]:
            L.append(f"- *Caveat:* {c}")
        docs = sorted({e['doc_id'] for e in r['evidence'] if e['role'] == 'supports'})
        L += [f"- *Supporting documents:* {', '.join(docs) or 'none'}  |  *claims:* {', '.join(r['claims']) or 'none'}  "
              f"|  *conflict records:* {', '.join(r['conflicts']) or 'none'}", ""]
    return "\n".join(L)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", default="data/processed/kb.json")
    ap.add_argument("--segments", default="data/processed/segments.jsonl")
    ap.add_argument("--out", default="data/processed")
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
    for label, llm in (("deterministic", None),) + ((("gemini", Gemini(Path(a.cache))),) if a.llm else ()):
        rows = run(kb, segs, llm)
        m = metrics(rows)
        out = Path(a.out)
        (out / f"eval_results_{label}.json").write_text(json.dumps({"metrics": m, "rows": rows}, indent=1, ensure_ascii=False),
                                                        encoding="utf-8")
        (out / f"eval_report_{label}.md").write_text(report_md(rows, m, label), encoding="utf-8")
        print(f"\n=== {label} ===")
        for r in rows:
            s = r["score"]
            print(f"{r['id']:4} {r['set']:9} {r['intent']:20} {'PASS' if s['pass'] else 'FAIL'}  {r['question'][:62]}")
        print(json.dumps(m, indent=1))
    print(f"\nwrote reports to {a.out}/")


if __name__ == "__main__":
    main()
