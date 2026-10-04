"""XLSX -> one segment per data row, keyed by header. Deterministic (openpyxl).

Kept deliberately raw: IDs are stored exactly 'as printed' (the component register has
inconsistent formatting on purpose). Normalisation is a separate, logged step (Day 2),
never a silent change at parse time.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from ..schema import SegmentBuilder, Segment
from ..sources import SourceInfo
from ._common import Ctx, clean


def parse(info: SourceInfo, path: Path, ctx: Ctx) -> list[Segment]:
    b = SegmentBuilder(info.doc_id)
    wb = load_workbook(path, data_only=True)
    for ws in wb.worksheets:
        merged = {}
        for rng in ws.merged_cells.ranges:                      # fill merged cells so no row loses its value
            v = ws.cell(rng.min_row, rng.min_col).value
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    merged[(r, c)] = v
        rows = []
        for r in range(1, ws.max_row + 1):
            vals = [merged.get((r, c), ws.cell(r, c).value) for c in range(1, ws.max_column + 1)]
            if any(v not in (None, "") for v in vals):
                rows.append((r, vals))
        if not rows:
            continue
        hdr_row, hdr = rows[0]
        header = [clean(str(h)) if h is not None else f"col{i+1}" for i, h in enumerate(hdr)]
        for r, vals in rows[1:]:
            cells = {header[i]: ("" if v is None else clean(str(v))) for i, v in enumerate(vals)}
            last = get_column_letter(len(header))
            hidden = bool(ws.row_dimensions[r].hidden) or ws.sheet_state != "visible"
            b.add("table_row", " | ".join(f"{k}: {v}" for k, v in cells.items()),
                  {"sheet": ws.title, "row": r, "range": f"A{r}:{last}{r}"},
                  data={"header": header, "cells": cells, "lists": {}, **({"hidden": True} if hidden else {})})
        for row in ws.iter_rows():
            for cell in row:
                if cell.comment:
                    b.add("footnote", clean(cell.comment.text),
                          {"sheet": ws.title, "cell": cell.coordinate}, data={"role": "cell_comment"})
    return b.segments
