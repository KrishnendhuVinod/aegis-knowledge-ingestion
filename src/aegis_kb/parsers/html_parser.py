"""HTML (legacy CMS export) -> segments. Deterministic (BeautifulSoup)."""
from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

from ..schema import SegmentBuilder, Segment
from ..sources import SourceInfo
from ._common import Ctx, clean, admonition_of

HEAD = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.*)$")


def parse(info: SourceInfo, path: Path, ctx: Ctx) -> list[Segment]:
    b = SegmentBuilder(info.doc_id)
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
    if soup.title:
        b.add("metadata", soup.title.get_text(), {"element": "title"})
    section = None
    headers: list[str] = []
    counters: dict[str, int] = {}

    def loc(el, extra=None):
        counters[el] = counters.get(el, 0) + 1
        return {"section": section, "element": el, "index": counters[el], **(extra or {})}

    body = soup.body
    for tag in body.find_all(["h1", "h2", "h3", "p", "li", "tr", "div"]):
        classes = tag.get("class") or []
        if tag.name == "div":
            if "banner" in classes:
                # The banner states supersession: it is evidence ABOUT the document's validity.
                b.add("metadata", clean(tag.get_text(" ")), loc("div.banner"),
                      data={"role": "document_status_banner"})
            elif "warn" in classes:
                b.add("paragraph", clean(tag.get_text(" ")), loc("div.warn"), data={"admonition": "warning"})
            continue
        if tag.find_parent("div", class_=["banner", "warn"]):
            continue
        text = clean(tag.get_text(" "))
        if not text:
            continue
        if tag.name in ("h1", "h2", "h3"):
            m = HEAD.match(text)
            section = text if m else (section if tag.name == "h1" else text)
            b.add("heading", text, {"section": section, "element": tag.name, "index": len(b.segments)},
                  data={"level": int(tag.name[1])})
        elif tag.name == "p":
            role = "meta" if "meta" in classes else None
            kind = "metadata" if role else "paragraph"
            data = {"role": "document_footer_or_status"} if role else {}
            if (a := admonition_of(text)):
                data["admonition"] = a
            b.add(kind, text, loc("p"), data=data)
        elif tag.name == "li":
            parent = tag.parent.name
            idx = len(tag.parent.find_all("li", recursive=False))
            pos = [x for x in tag.parent.find_all("li", recursive=False)].index(tag) + 1
            b.add("bullet", text, loc("li", {"list": parent, "position": pos}),
                  data={"list_marker": f"{pos}" if parent == "ol" else "•"})
        elif tag.name == "tr":
            cells = tag.find_all(["th", "td"])
            vals = [clean(c.get_text(" ")) for c in cells]
            if all(c.name == "th" for c in cells):
                headers = vals
                continue
            row = {headers[i] if i < len(headers) else f"col{i}": v for i, v in enumerate(vals)}
            b.add("table_row", " | ".join(f"{k}: {v}" for k, v in row.items()),
                  loc("tr"), data={"header": headers, "cells": row, "lists": {}})
    return b.segments
