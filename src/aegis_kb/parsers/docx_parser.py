"""DOCX -> segments in document order (paragraphs and tables interleaved). Deterministic.

Also reads what extractors usually drop: footnotes and document properties. Property
dates matter for trust: e.g. a "no date recorded" field note whose file metadata
carries a date is evidence, and one with none is a gap.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml import etree

from ..schema import SegmentBuilder, Segment
from ..sources import SourceInfo
from ._common import Ctx, clean, admonition_of

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _footnotes(path: Path) -> list[tuple[str, str]]:
    out = []
    with zipfile.ZipFile(path) as z:
        for part in ("word/footnotes.xml", "word/endnotes.xml"):
            if part in z.namelist():
                root = etree.fromstring(z.read(part))
                for fn in root:
                    fid = fn.get(f"{W}id")
                    if fid is None or int(fid) <= 0 or fn.get(f"{W}type"):
                        continue          # skip separator/continuation notes
                    t = clean("".join(fn.itertext()))
                    if t:
                        out.append((part.split("/")[-1].split(".")[0] + ":" + fid, t))
    return out


def parse(info: SourceInfo, path: Path, ctx: Ctx) -> list[Segment]:
    b = SegmentBuilder(info.doc_id)
    doc = Document(path)
    cp = doc.core_properties
    props = {k: (str(v) if v else None) for k, v in {
        "author": cp.author, "last_modified_by": cp.last_modified_by,
        "created": cp.created, "modified": cp.modified, "title": cp.title}.items()}
    b.add("metadata", "document properties: " + ", ".join(f"{k}={v}" for k, v in props.items()),
          {"part": "docProps/core.xml"}, data={"role": "file_properties", **props})

    section, tcount, pcount = None, 0, 0
    for el in doc.element.body.iterchildren():
        if el.tag == f"{W}p":
            p = Paragraph(el, doc)
            text = clean(p.text)
            if not text:
                continue
            pcount += 1
            style = p.style.name if p.style is not None else ""
            italic = bool(p.runs) and all(r.italic for r in p.runs if r.text.strip())
            if style.startswith("Heading") or style == "Title":
                section = text
                b.add("heading", text, {"section": section, "paragraph": pcount}, data={"style": style})
                continue
            data = {"style": style}
            if italic:
                data["italic"] = True
            if (a := admonition_of(text)):
                data["admonition"] = a
            b.add("bullet" if style.startswith("List") else "paragraph", text,
                  {"section": section, "paragraph": pcount}, data=data)
        elif el.tag == f"{W}tbl":
            tcount += 1
            t = Table(el, doc)
            rows = [[clean(c.text) for c in r.cells] for r in t.rows]
            if not rows:
                continue
            header = rows[0]
            for ri, row in enumerate(rows[1:], start=1):
                cells = {header[i] if i < len(header) else f"col{i}": v for i, v in enumerate(row)}
                b.add("table_row", " | ".join(f"{k}: {v}" for k, v in cells.items()),
                      {"section": section, "table": tcount, "row": ri},
                      data={"header": header, "cells": cells, "lists": {}})
    for fid, text in _footnotes(path):
        b.add("footnote", text, {"part": fid}, data={"role": "docx_footnote"})
    return b.segments
