"""Vector-drawn diagram PDF -> nodes + edges. Deterministic (no model).

The schematics are vector PDFs: boxes are drawn paths, connections are stroked lines.
Topology is therefore recoverable EXACTLY from geometry, which beats asking a vision
model "what connects to what" (models hallucinate edges; geometry cannot).

Method:
  1. Node = a filled path (curve/rect) that contains text. Label = text inside the bbox.
  2. Edge = a stroked line segment. Each endpoint is snapped to the node whose bbox
     (expanded by TOL points) contains it; if none, the endpoint is recorded unresolved.
  3. Colour -> name (grey/purple/tan) and, if the drawing has a legend ("— purple lines:
     control/signal connections to PLC-03"), the legend meaning is attached to the edge.
  4. Text outside nodes = title / notes / legend.

Edges are UNDIRECTED here: the drawings carry no arrowheads.
"""
from __future__ import annotations

import re
from pathlib import Path

import pdfplumber

from ..schema import SegmentBuilder, Segment
from ..sources import SourceInfo
from ._common import Ctx, clean

TOL = 4.0
LEGEND = re.compile(r"^[—-]\s*(\w+)\s+lines?:\s*(.+)$")


def colour_name(rgb) -> str:
    if not rgb or len(rgb) < 3:
        return "unknown"
    r, g, b = rgb[:3]
    if max(r, g, b) - min(r, g, b) < 0.1:
        return "grey" if max(r, g, b) < 0.9 else "white"
    if r > g + 0.12 and b > g + 0.12:
        return "purple"
    if r > g > b and (r - b) > 0.25:
        return "tan"
    return "other"


def _inside(pt, bbox, tol=TOL):
    x, y = pt
    x0, top, x1, bottom = bbox
    return x0 - tol <= x <= x1 + tol and top - tol <= y <= bottom + tol


def _dist_to_bbox(pt, bbox):
    x, y = pt
    x0, top, x1, bottom = bbox
    dx = max(x0 - x, 0, x - x1)
    dy = max(top - y, 0, y - bottom)
    return (dx * dx + dy * dy) ** 0.5


def parse(info: SourceInfo, path: Path, ctx: Ctx) -> list[Segment]:
    b = SegmentBuilder(info.doc_id)
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        shapes = [o for o in (page.rects + page.curves) if o.get("fill")]
        nodes = []
        for sh in shapes:
            bbox = (sh["x0"], sh["top"], sh["x1"], sh["bottom"])
            inner = page.within_bbox(bbox)
            words = inner.extract_words(keep_blank_chars=False)
            if not words:
                continue
            lines: dict[int, list] = {}
            for w in words:
                lines.setdefault(round(w["top"] / 4), []).append(w)
            label = " ".join(" ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"]))
                             for _, ws in sorted(lines.items()))
            nodes.append({"label": clean(label), "bbox": bbox, "fill": colour_name(sh.get("non_stroking_color")),
                          "fill_rgb": [round(x, 2) for x in (sh.get("non_stroking_color") or [])]})

        # text outside every node: title, legend, notes
        def outside_nodes(obj):
            if obj["object_type"] != "char":
                return True
            c = ((obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2)
            return not any(_inside(c, n["bbox"], 0) for n in nodes)

        legend: dict[str, str] = {}
        free_lines = page.filter(outside_nodes).extract_text_lines(strip=True, return_chars=False)
        # group wrapped lines into paragraphs (gap rule) for notes
        para, prev_bottom = [], None
        paras = []
        for ln in free_lines:
            m = LEGEND.match(ln["text"])
            if m:
                legend[m.group(1).lower()] = clean(m.group(2))
                b.add("diagram_legend", ln["text"], {"page": 1, "top": round(ln["top"])},
                      data={"colour": m.group(1).lower(), "meaning": clean(m.group(2))})
                prev_bottom = ln["bottom"]
                continue
            if prev_bottom is not None and ln["top"] - prev_bottom > 5 and para:
                paras.append(para); para = []
            para.append(ln["text"]); prev_bottom = ln["bottom"]
        if para:
            paras.append(para)
        for i, p in enumerate(paras):
            txt = clean(" ".join(p))
            b.add("paragraph", txt, {"page": 1, "block": i + 1},
                  data={"role": "title" if i == 0 else "note"})

        for n in nodes:
            b.add("diagram_node", n["label"], {"page": 1, "bbox": [round(x) for x in n["bbox"]]},
                  data={"label": n["label"], "fill": n["fill"], "fill_rgb": n["fill_rgb"]})

        def snap(pt):
            hits = [(n, _dist_to_bbox(pt, n["bbox"])) for n in nodes if _inside(pt, n["bbox"])]
            if not hits:
                return None
            return min(hits, key=lambda h: h[1])[0]["label"]

        for ln in page.lines:
            pts = ln.get("pts") or [(ln["x0"], ln["top"]), (ln["x1"], ln["bottom"])]
            (p1, p2) = pts[0], pts[-1]
            a, c = snap(p1), snap(p2)
            col = colour_name(ln.get("stroking_color"))
            meaning = legend.get(col)
            text = f"{a or '?'} — {c or '?'} [{col}{': ' + meaning if meaning else ''}]"
            b.add("diagram_edge", text,
                  {"page": 1, "from_xy": [round(p1[0]), round(p1[1])], "to_xy": [round(p2[0]), round(p2[1])]},
                  data={"a": a, "b": c, "colour": col, "legend_meaning": meaning,
                        "resolved": bool(a and c), "directed": False})
    return b.segments
