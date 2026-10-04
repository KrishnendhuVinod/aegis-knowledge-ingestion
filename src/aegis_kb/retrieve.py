"""Question -> relevant KB records. Deterministic: entity linking + lexical scoring + predicate lexicon.

Used (a) to give the LLM composer a small, relevant, citable set of findings (never the raw corpus), and
(b) as the generic fallback when no specialised answer renderer matches.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from .entities import norm_id

STOP = set("""the a an of for to in on is are was were be been what which who whom whose does do did and or not under
any all that this these those it its as at by with from per according into than then there their about can could should
would will shall have has had how when where why also both either if""".split())

LEXICON = [
    (r"before start|startup|start up|power(?:ing)? up|precondition|must be true", ["startup_precondition"]),
    (r"pressure|setpoint|threshold|limit", ["normal_pressure", "setpoint_change", "setpoint_rationale",
                                           "alarm_threshold", "observed_pressure"]),
    (r"alarm|indicate|cause|a\d\d\b", ["alarm_condition", "alarm_causes", "alarm_threshold", "alarm_name",
                                       "alarm_required_action", "alarm_panel_indication", "persistence_action"]),
    (r"persist|seconds|shutdown", ["persistence_action", "procedure_steps", "observed_persistence", "alarm_note"]),
    (r"reset", ["reset_prohibited_above_bar", "reset_permitted_below_bar", "reset_min_pressure",
                "reset_precondition_action"]),
    (r"same|replace|supersed|introduc|change from|identical", ["sensor_replacement", "introduced_by", "sensor_support"]),
    (r"connect|wired|wiring|schematic", ["connected_to"]),
    (r"locat|where", ["location"]),
    (r"revision|release|take effect|version", ["release_date", "summary_of_changes", "setpoint_change"]),
    (r"config", ["config_maps_to", "config_value"]),
    (r"diagnostic|screenshot|screen|tag|sensor id", ["displays_tag", "observed_firmware_rev",
                                                    "observed_calibration_status"]),
    (r"training|slide", ["introduces_term", "alias_used_in_training"]),
    (r"calibrat", ["calibration_record", "calibration_interval", "calibration_span_reference"]),
    (r"voltage|supply|480", ["rated_voltage"]),
]


def toks(s: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z]+\d*[a-z]*|\d+(?:\.\d+)?", s.replace("_", " ").lower()):
        if w in STOP or len(w) < 2:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


@dataclass
class Retrieval:
    entities: list = field(default_factory=list)
    claims: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    gaps: list = field(default_factory=list)


class Retriever:
    def __init__(self, kb):
        self.kb = kb
        self.ent = {e.id: e for e in kb.entities}
        self.surfaces: dict[str, str] = {}
        for e in kb.entities:
            for s in [e.id, e.name, *e.aliases]:
                if len(s) >= 2:
                    self.surfaces[s.lower()] = e.id
        for d in kb.decisions:
            if d.decision == "accepted" and d.entity_id in self.ent and \
                    d.relation in ("same_as", "variant_of", "corresponds_to") and len(d.surface) >= 2:
                self.surfaces.setdefault(d.surface.lower(), d.entity_id)
        self.nid = {}
        for s, eid in self.surfaces.items():
            self.nid.setdefault(norm_id(s), eid)

    # ---------------------------------------------------------------- entity linking
    def link_entities(self, q: str) -> list[str]:
        found: list[tuple[int, str]] = []
        work = q
        for s in sorted(self.surfaces, key=len, reverse=True):
            pat = r"(?<![A-Za-z0-9])" + re.escape(s) + r"(?![A-Za-z0-9])"
            for m in re.finditer(pat, work, re.I):
                found.append((m.start(), self.surfaces[s]))
                work = work[:m.start()] + " " * (m.end() - m.start()) + work[m.end():]
        for m in re.finditer(r"(?<![A-Za-z0-9])([A-Za-z]{1,4}[-.]?\d+[A-Za-z]?)(?![A-Za-z0-9])", work):
            eid = self.nid.get(norm_id(m.group(1)))
            if eid:
                found.append((m.start(), eid))
        out = []
        for _, eid in sorted(found):
            if eid not in out:
                out.append(eid)
        return out

    # ---------------------------------------------------------------- gaps
    def match_gaps(self, q: str) -> list:
        qt = set(toks(q))
        out = []
        for g in self.kb.gaps:
            gt = set(toks(g.topic))
            overlap = len(gt & qt) / max(len(gt), 1)
            alias_in_q = any(re.search(r"(?<![A-Za-z0-9])" + re.escape(a) + r"(?![A-Za-z0-9])", q, re.I)
                             for a in g.entity_aliases)
            term_hit = any(re.search(p, q, re.I) for p in g.terms)
            by_terms = term_hit and ((g.entity_aliases and alias_in_q) or (not g.entity_aliases and not g.doc_scope))
            if overlap >= 0.6 or by_terms:
                out.append((max(overlap, 0.6 if by_terms else 0), g))
        return [g for _, g in sorted(out, key=lambda x: -x[0])]

    # ---------------------------------------------------------------- claims
    def retrieve(self, q: str, k_groups: int = 7) -> Retrieval:
        ents = self.link_entities(q)
        qt = set(toks(q))
        boost = set()
        for pat, preds in LEXICON:
            if re.search(pat, q, re.I):
                boost.update(preds)
        groups = defaultdict(list)
        for c in self.kb.claims:
            groups[(c.subject, c.predicate)].append(c)
        scored = []
        for (subj, pred), cs in groups.items():
            if pred == "config_value" and not re.search(r"config", q, re.I):
                continue
            text = " ".join([subj, pred.replace("_", " "), *(f"{c.value} {c.note or ''}" for c in cs)])
            overlap = len(qt & set(toks(text)))
            score = overlap
            if subj in ents or any(isinstance(c.value, dict) and c.value.get("to") in ents for c in cs):
                score += 4
            if pred in boost:
                score += 3
            if any(c.status == "asserted" for c in cs):
                score += 0.5
            scored.append((score, subj, pred, cs))
        scored.sort(key=lambda x: -x[0])
        picked = [x for x in scored[:k_groups] if x[0] >= 4]
        claims = [c for _, _, _, cs in picked for c in cs[:8]]
        ids = {c.id for c in claims}
        keys = {(c.subject, c.predicate) for c in claims}
        conflicts = [x for x in self.kb.conflicts if set(x.claim_ids) & ids or (x.subject, x.predicate) in keys]
        return Retrieval(ents, claims, conflicts, self.match_gaps(q))
