"""PNG screenshots / raster diagrams / scanned PDFs -> segments.

Up to TWO independent readings of every image, kept side by side as separate segments:
  1. OCR  (tesseract, classical, offline, reproducible)    method="ocr"      (optional: needs Tesseract installed)
  2. Vision LLM (Gemini, cached to disk)                    method="vision_llm"
They are never merged, and no automatic cross-check between them is implemented: when Tesseract is
unavailable only the vision reading exists, and its reading confidence is a fixed prior (VISION_CONF).

Why two readings when possible: models can hallucinate plausible text, while OCR fails on rotated /
low-contrast / dark-theme text (it does, here). Keeping both makes reading loss measurable by hand.

Prompts demand verbatim transcription: identifier variants such as 'P.S.04-A' are
evidence (they are the alias being tested), so they must NOT be "corrected".
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import pypdfium2 as pdfium
import pytesseract
from PIL import Image, ImageOps, ImageStat

from ..schema import (SegmentBuilder, Segment, METHOD_OCR, METHOD_VISION)
from ..sources import SourceInfo
from ._common import Ctx, clean

VISION_CONF = 0.8       # fixed prior for model readings (not calibrated; no OCR cross-check is computed)

_COMMON = (
    "You are transcribing a technical image for a documentation database. "
    "Copy every identifier EXACTLY as printed, keeping punctuation, spacing and case "
    "(for example 'P.S.04-A' must stay 'P.S.04-A'; never normalise, correct or guess). "
    "If something is illegible or you are unsure, put it in 'uncertain' instead of guessing. "
    "Return ONLY JSON with these keys (use empty lists/strings when not applicable): "
    '{"title": str, "fields": [{"label": str, "value": str}], '
    '"tables": [{"columns": [str], "rows": [[str]]}], '
    '"nodes": [str], "edges": [{"from": str, "to": str}], '
    '"text_blocks": [str], "uncertain": [str]}. '
)
PROMPTS = {
    "screenshot": _COMMON + "This is a screenshot of an industrial HMI. Put each label/value pair in "
                  "'fields' (label exactly as shown, value exactly as shown, including units). "
                  "Put free text (notes, footers, banners) in 'text_blocks'. Leave nodes/edges empty.",
    "diagram": _COMMON + "This is a schematic diagram. List every box label in 'nodes' and every "
               "visible line between two boxes in 'edges' (only if a line visibly connects them). "
               "Include rotated or faint annotations in 'text_blocks'. Leave fields/tables empty.",
    "scan": _COMMON + "This is a scanned (skewed, noisy) record. Put header key/value pairs in 'fields', "
            "any table in 'tables' (one entry per table, columns + rows verbatim), and notes/paragraphs "
            "in 'text_blocks'. Transcribe signature/date lines too, noting if they are blank.",
}


def _prep(im: Image.Image, scale: int) -> Image.Image:
    g = ImageOps.autocontrast(im.convert("L"))
    if ImageStat.Stat(g).mean[0] < 110:                         # dark theme -> invert for tesseract
        g = ImageOps.invert(g)
    return g.resize((g.width * scale, g.height * scale), Image.LANCZOS)


def ocr_available() -> bool:
    """True if the tesseract executable can be run. OCR is OPTIONAL: without it the vision reading stands alone."""
    if os.getenv("TESSERACT_CMD"):
        pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _ocr(builder: SegmentBuilder, im: Image.Image, base_loc: dict, psm: int, scale: int) -> bool:
    if not ocr_available():
        return False
    g = _prep(im, scale)
    d = pytesseract.image_to_data(g, config=f"--psm {psm}", output_type=pytesseract.Output.DICT)
    lines: dict[tuple, list] = {}
    for i, w in enumerate(d["text"]):
        if w.strip() and float(d["conf"][i]) >= 0:
            lines.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(i)
    for key in sorted(lines):
        idx = lines[key]
        text = clean(" ".join(d["text"][i] for i in idx))
        conf = sum(float(d["conf"][i]) for i in idx) / len(idx) / 100
        top = min(d["top"][i] for i in idx) // scale
        left = min(d["left"][i] for i in idx) // scale
        builder.add("ocr_text", text, {**base_loc, "xy": [left, top]}, method=METHOD_OCR,
                    confidence=round(min(conf, 0.95), 2), data={"ocr_conf_pct": round(conf * 100, 1)})
    return True


def _vision(builder: SegmentBuilder, ctx: Ctx, png: bytes, role: str, base_loc: dict):
    if ctx.gemini is None:
        return "disabled"
    resp = ctx.gemini.generate_json(PROMPTS[role], image=png, mime="image/png")
    if resp is None:
        return "no_key_no_cache"
    L = {**base_loc, "reader": ctx.gemini.model}
    if resp.get("title"):
        builder.add("vision_text", resp["title"], L, METHOD_VISION, VISION_CONF, {"role": "title"})
    for f in resp.get("fields") or []:
        builder.add("vision_field", f"{f.get('label')}: {f.get('value')}", L, METHOD_VISION, VISION_CONF,
                    {"label": f.get("label"), "value": f.get("value")})
    for t in resp.get("tables") or []:
        cols = t.get("columns") or []
        for ri, row in enumerate(t.get("rows") or [], start=1):
            cells = {cols[i] if i < len(cols) else f"col{i}": v for i, v in enumerate(row)}
            builder.add("vision_table_row", " | ".join(f"{k}: {v}" for k, v in cells.items()),
                        {**L, "row": ri}, METHOD_VISION, VISION_CONF, {"header": cols, "cells": cells})
    for n in resp.get("nodes") or []:
        builder.add("vision_text", str(n), L, METHOD_VISION, VISION_CONF, {"role": "node"})
    for e in resp.get("edges") or []:
        builder.add("vision_edge", f"{e.get('from')} — {e.get('to')}", L, METHOD_VISION, VISION_CONF,
                    {"a": e.get("from"), "b": e.get("to")})
    for t in resp.get("text_blocks") or []:
        builder.add("vision_text", str(t), L, METHOD_VISION, VISION_CONF, {"role": "text_block"})
    for u in resp.get("uncertain") or []:
        builder.add("vision_text", str(u), L, METHOD_VISION, 0.4, {"role": "uncertain", "flag": "uncertain"})
    return "ok"


def parse(info: SourceInfo, path: Path, ctx: Ctx) -> list[Segment]:
    role = (info.options or {}).get("role", "screenshot")
    b = SegmentBuilder(info.doc_id)
    raw = path.read_bytes()
    im = Image.open(io.BytesIO(raw))
    loc = {"image": path.name}
    _ocr(b, im, loc, psm=11, scale=2)
    status = _vision(b, ctx, raw, role, loc)
    return b.segments


def parse_scan(info: SourceInfo, path: Path, ctx: Ctx) -> list[Segment]:
    role = (info.options or {}).get("role", "scan")
    b = SegmentBuilder(info.doc_id)
    pdf = pdfium.PdfDocument(str(path))
    for pno in range(len(pdf)):
        im = pdf[pno].render(scale=2).to_pil()
        buf = io.BytesIO(); im.save(buf, format="PNG")
        loc = {"page": pno + 1}
        _ocr(b, im, loc, psm=6, scale=1)
        _vision(b, ctx, buf.getvalue(), role, loc)
    return b.segments
