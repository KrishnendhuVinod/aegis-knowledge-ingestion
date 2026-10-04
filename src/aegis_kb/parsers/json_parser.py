"""JSON -> one segment per leaf, with its full path. Deterministic.

Nulls are KEPT and flagged: `min_pressure_bar_required_for_reset: null` is information
("no minimum is specified"), not an absence of information. Dropping nulls would turn
"explicitly unspecified" into "never mentioned".
"""
from __future__ import annotations

import json
from pathlib import Path

from ..schema import SegmentBuilder, Segment
from ..sources import SourceInfo
from ._common import Ctx


def parse(info: SourceInfo, path: Path, ctx: Ctx) -> list[Segment]:
    b = SegmentBuilder(info.doc_id)
    doc = json.loads(path.read_text(encoding="utf-8"))

    def walk(node, trail):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, trail + [k])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, trail + [i])
        else:
            jpath = "$." + ".".join(str(t) for t in trail)
            b.add("json_leaf", f"{'.'.join(str(t) for t in trail)} = {json.dumps(node)}",
                  {"json_path": jpath},
                  data={"path": [str(t) for t in trail], "key": str(trail[-1]), "value": node,
                        "type": type(node).__name__, "is_null": node is None})

    walk(doc, [])
    return b.segments
