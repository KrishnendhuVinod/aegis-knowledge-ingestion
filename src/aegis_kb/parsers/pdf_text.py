"""Born-digital PDF -> segments. Fully deterministic (pdfplumber).

Rules (all learned from inspecting the package, documented in docs/schema.md):
  * Page header (top<40) and footer (top>740) are dropped, except the page-1 header
    which becomes a `metadata` segment (it carries doc id + revision).
  * A heading = whole line bold AND font size >= 12. (10pt bold lines exist in body
    text for emphasis; they are paragraphs with emphasis="bold", NOT headings.)
  * Section context (e.g. "4.3 Starting the HPU") is carried across lines AND pages.
  * pdfplumber renders the bullet glyph as '(cid:127)'; normalised to '•'.
  * A paragraph that ends without terminal punctuation at a page end is continued on
    the next page (the "180 bar" sentence in the operator manual splits across pages).
  * Tables are extracted separately, one segment per row, keyed by header. Cells with
    numbered lists ("1. ... 2. ...") are additionally split into items.
  * Key/value header blocks (ECN pages: "Effective: Software Revision 3.2") -> `kv`.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pdfplumber

from ..schema import SegmentBuilder, Segment
from ..sources import SourceInfo
from ._common import Ctx, admonition_of, clean

HEADER_Y, FOOTER_Y = 40, 740
NUM_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.*)$")
BULLET = re.compile(r"^(?:\(cid:127\)|•)\s*")
NUMBERED_STEP = re.compile(r"^\d+\s+[A-Z]")
KV = re.compile(r"^([A-Z][A-Za-z ]{2,24}):\s+(\S.*)$")


def _line_style(line: dict) -> tuple[float, float]:
    chars = [c for c in line["chars"] if c["text"].strip()]
    if not chars:
        return 0.0, 10.0
    bold = sum("Bold" in c["fontname"] for c in chars) / len(chars)
    size = Counter(round(c["size"]) for c in chars).most_common(1)[0][0]
    return bold, size


LIGATURES = {"\ufb01": "fi", "\ufb02": "fl", "\ufb00": "ff", "\ufb03": "ffi", "\ufb04": "ffl"}
SYMBOL_REPAIR = {"\ufb01": "\u2192"}   # pdfminer decodes Symbol-font code 0xAE (arrow) as the 'fi' ligature


def _repair_line(line: dict) -> tuple[str, list[str]]:
    """Fix known pdfminer mis-decodes. Returns (text, repairs applied)."""
    text, repairs = line["text"], []
    # Walk the chars so only Symbol-font glyphs are repaired; genuine ligatures are expanded afterwards.
    if any("Symbol" in c["fontname"] and c["text"] in SYMBOL_REPAIR for c in line["chars"]):
        n_bad = sum("Symbol" in c["fontname"] and c["text"] in SYMBOL_REPAIR for c in line["chars"])
        for bad, good in SYMBOL_REPAIR.items():
            text = text.replace(bad, good, n_bad)
        repairs.append("symbol_font_arrow")
    for lig, expanded in LIGATURES.items():
        text = text.replace(lig, expanded)
    return text, repairs


def _bold_spans(line: dict) -> list[str]:
    """Contiguous bold runs (>=2 words) in a line. Bold flags are aligned to the line TEXT, because
    this PDF has no space glyphs (spaces are implied by gaps), so chars alone would glue words."""
    chars = [c for c in line["chars"] if not c["text"].isspace()]
    flags, i = [], 0
    for ch in line["text"]:
        if ch.isspace():
            flags.append(None)
        else:
            flags.append("Bold" in chars[i]["fontname"] if i < len(chars) else False)
            i += 1
    spans, cur = [], ""
    for ch, f in zip(line["text"], flags):
        if f is None:
            if cur:
                cur += ch
        elif f:
            cur += ch
        elif cur:
            spans.append(cur.strip()); cur = ""
    if cur.strip():
        spans.append(cur.strip())
    return [x for x in spans if len(x.split()) >= 2]


def _split_numbered(cell: str) -> list[str]:
    items, cur = [], None
    for ln in cell.split("\n"):
        if re.match(r"^\d+\.\s", ln):
            if cur is not None:
                items.append(cur)
            cur = re.sub(r"^\d+\.\s", "", ln)
        elif cur is not None:
            cur += " " + ln.strip()
    if cur is not None:
        items.append(cur)
    return items


def parse(info: SourceInfo, path: Path, ctx: Ctx) -> list[Segment]:
    b = SegmentBuilder(info.doc_id)
    section = {"title": None, "number": None}
    pending: dict | None = None     # open paragraph / bullet being accumulated
    seen_numbered_heading = False

    def flush():
        nonlocal pending
        if not pending:
            return
        text = clean(" ".join(pending["lines"]))
        if text:
            kind = pending["kind"]
            adm = admonition_of(text) if kind == "paragraph" else None
            data = {}
            if adm:
                data["admonition"] = adm
            if pending.get("emphasis"):
                data["emphasis"] = "bold"
            elif pending.get("bold"):
                data["bold_text"] = " ".join(pending["bold"])
            if kind == "paragraph" and pending.get("footnote"):
                kind = "footnote"
            if kind == "paragraph" and text.startswith("Document AEG-"):
                kind = "metadata"
            loc = {"page": pending["pages"][0], "section": section_snapshot(pending["section"])}
            if len(pending["pages"]) > 1:
                loc["pages"] = pending["pages"]
            if pending.get("list_marker"):
                data["list_marker"] = pending["list_marker"]
            if pending.get("repairs"):
                data["repairs"] = pending["repairs"]
            b.add(kind, text, loc, data=data)
        pending = None

    def section_snapshot(sec):
        return f'{sec["number"]} {sec["title"]}'.strip() if sec["title"] else None

    with pdfplumber.open(path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            tbboxes = [t.bbox for t in tables]
            body = page
            for bb in tbboxes:
                body = body.outside_bbox(bb)
            lines = body.extract_text_lines(return_chars=True, strip=True, expand_ligatures=False)
            items = [("line", l["top"], l) for l in lines] + \
                    [("table", t.bbox[1], t) for t in tables]
            items.sort(key=lambda x: x[1])

            prev_bottom = None
            first_content_on_page = True
            for typ, top, obj in items:
                if typ == "table":
                    flush()
                    rows = obj.extract()
                    header = [clean(c) for c in rows[0]]
                    for ri, row in enumerate(rows[1:], start=1):
                        cells = {header[i]: clean(c) for i, c in enumerate(row)}
                        lists = {header[i]: _split_numbered(c) for i, c in enumerate(row)
                                 if len(_split_numbered(c)) >= 2}
                        text = " | ".join(f"{k}: {v}" for k, v in cells.items())
                        b.add("table_row", text,
                              {"page": pno, "section": section_snapshot(section), "row": ri,
                               "table_bbox": [round(x) for x in obj.bbox]},
                              data={"header": header, "cells": cells, "lists": lists})
                    prev_bottom = obj.bbox[3]
                    first_content_on_page = False
                    continue

                line = obj
                raw_text, line_repairs = _repair_line(line)
                raw_text = raw_text.strip()
                txt = BULLET.sub("• ", raw_text) if BULLET.match(raw_text) else raw_text
                if top < HEADER_Y:
                    if pno == 1:
                        b.add("metadata", txt, {"page": 1, "zone": "page_header"})
                    continue
                if top > FOOTER_Y:
                    continue

                bold, size = _line_style(line)
                is_heading = bold >= 0.9 and size >= 12
                gap = (top - prev_bottom) if prev_bottom is not None else 99
                prev_bottom = line["bottom"]

                if is_heading:
                    flush()
                    m = NUM_HEADING.match(txt)
                    if m:
                        seen_numbered_heading = True
                        section.update(number=m.group(1), title=m.group(2))
                        level = m.group(1).count(".") + 1
                    else:
                        level = 0
                        is_cover_title = pno == 1 and top < 150      # document title block, not a section
                        if not is_cover_title:
                            section.update(number=None, title=txt)
                    b.add("heading", txt, {"page": pno, "section": section_snapshot(section)},
                          data={"level": level, **({"role": "title"} if level == 0 and pno == 1 and top < 150 else {}),
                                **({"repairs": line_repairs} if line_repairs else {})})
                    first_content_on_page = False
                    continue

                if not seen_numbered_heading and (m := KV.match(txt)) and not admonition_of(txt):
                    flush()
                    b.add("kv", txt, {"page": pno, "section": section_snapshot(section)},
                          data={"key": m.group(1), "value": m.group(2),
                                **({"repairs": line_repairs} if line_repairs else {})})
                    first_content_on_page = False
                    continue

                is_bullet = txt.startswith("• ")
                is_step = bool(NUMBERED_STEP.match(txt)) and size <= 10 and not is_bullet
                continuation_across_page = (
                    first_content_on_page and pending is not None
                    and pending["kind"] == "paragraph"
                    and not re.search(r"[.!?:]$", pending["lines"][-1].strip())
                )
                new_block = (is_bullet or is_step or gap > 5 or pending is None) and not continuation_across_page

                if new_block:
                    flush()
                    footnote = txt.startswith("*") and size <= 8
                    pending = {"kind": "bullet" if (is_bullet or is_step) else "paragraph",
                               "lines": [txt[2:] if is_bullet else txt], "pages": [pno],
                               "section": dict(section), "footnote": footnote,
                               "emphasis": bold >= 0.9, "bold": _bold_spans(line), "repairs": list(line_repairs),
                               "list_marker": "•" if is_bullet else (txt.split()[0] if is_step else None)}
                    if is_step:
                        pending["lines"] = [txt.split(" ", 1)[1]]
                else:
                    pending["lines"].append(txt)
                    pending["repairs"] = sorted(set(pending["repairs"]) | set(line_repairs))
                    pending["bold"] += _bold_spans(line)
                    if pno not in pending["pages"]:
                        pending["pages"].append(pno)
                first_content_on_page = False
        flush()
    return b.segments
