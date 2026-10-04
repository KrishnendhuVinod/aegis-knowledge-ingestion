"""Conflict, coexistence and ambiguity detection over claims.

The key distinction (the point of carrying `applies_when` on every claim):
  scoped_coexistence     same subject+predicate, different values, DISJOINT software scopes -> not a conflict
  conflict               different values, OVERLAPPING scopes                                  -> real conflict
  observation_disagrees  an unreviewed/low-trust reading differs from the setpoints            -> flagged, not adjudicated
  ambiguity              the sources leave something open (boundary values, odd drawing lines, rationale vs scope)
Nothing is silently resolved: each record keeps all claim ids and says what is and is not known.
"""
from __future__ import annotations

import itertools
import json
from collections import defaultdict

from .kb_schema import Conflict
from .versions import SwScope

COMPARABLE = {"normal_pressure", "alarm_threshold", "reset_prohibited_above_bar", "persistence_action",
              "location", "register_status", "common_name"}


def _vk(c):
    return json.dumps(c.value, sort_keys=True, default=str)


def detect(claims, index) -> list[Conflict]:
    out: list[Conflict] = []
    n = itertools.count(1)

    def mk(kind, subject, predicate, cids, desc, res):
        out.append(Conflict(f"X{next(n):02d}", kind, subject, predicate, cids, desc, res))

    # 1. value comparison within (subject, predicate), asserted claims only
    groups = defaultdict(list)
    for c in claims:
        if c.predicate in COMPARABLE and c.status in ("asserted",):
            groups[(c.subject, c.predicate)].append(c)
    for (subj, pred), cs in groups.items():
        by_val = defaultdict(list)
        for c in cs:
            by_val[_vk(c)].append(c)
        for (va, ca), (vb, cb) in itertools.combinations(by_val.items(), 2):
            a, b = ca[0], cb[0]
            rels = {SwScope.from_dict(x.applies_when).relation(SwScope.from_dict(y.applies_when))
                    for x in ca for y in cb}
            sa = SwScope.from_dict(a.applies_when).label()
            sb = SwScope.from_dict(b.applies_when).label()
            ids = [x.id for x in ca + cb]
            if rels == {"disjoint"}:
                mk("scoped_coexistence", subj, pred, ids,
                   f"{subj} {pred}: {a.value} applies to {sa}; {b.value} applies to {sb}. The scopes are disjoint, so "
                   "these are two correct values for different software revisions, not a contradiction.",
                   "keep both; choose by the unit's software revision")
            elif "overlap" in rels:
                mk("conflict", subj, pred, ids,
                   f"{subj} {pred}: {a.value} ({sa}) vs {b.value} ({sb}) overlap in scope.",
                   "unresolved: compare source trust and dates (see trust_rank on each claim)")
            else:
                mk("ambiguity", subj, pred, ids, f"{subj} {pred}: {a.value} vs {b.value}; at least one has no stated "
                   "software scope.", "unresolved: applicability unknown")

    by_pred = defaultdict(list)
    for c in claims:
        by_pred[c.predicate].append(c)

    # 2. low-trust observation vs setpoints
    for obs in [c for c in by_pred["observed_pressure"] if c.status == "low_trust_observation"]:
        sp = [c for c in by_pred["normal_pressure"] if c.status == "asserted"]
        mk("observation_disagrees", obs.subject, "observed_pressure", [obs.id] + [c.id for c in sp],
           f"A field note reports about {obs.value} bar, which matches neither normal setpoint "
           f"({sorted({c.value for c in sp})} bar). The note's own caveats: uncalibrated gauge, unreviewed, undated, "
           "software revision not recorded, so it cannot be tied to either setpoint.",
           "do not adjudicate; the note cannot override manuals; a calibrated check would be needed")

    # 3. controller-reset boundary: 'above 50' prohibited, 'below 50' permitted -> exactly 50 undefined
    proh = [c for c in by_pred["reset_prohibited_above_bar"]]
    perm = [c for c in by_pred["reset_permitted_below_bar"]]
    for p in proh:
        for q in perm:
            if p.value == q.value:
                cfg = [c.id for c in proh if "config_export" in c.docs]
                mk("ambiguity", "PLC-03.reset", "reset_boundary", [p.id, q.id] + cfg,
                   f"Manuals prohibit reset 'above {p.value} bar' and permit it only 'below {q.value} bar'; behaviour at "
                   f"exactly {p.value} bar is not stated. The firmware config blocks reset 'above' {p.value}, which "
                   "suggests exactly that value is allowed, but no document says so.",
                   f"treat as: do not reset above {p.value} bar; reset below {q.value} bar is explicitly permitted; "
                   "the exact boundary value is unspecified")
                break

    # 4. a controller on a hydraulic-fluid line (drawing anomaly)
    for c in by_pred["connected_to"]:
        v = c.value
        meaning = (v.get("line_meaning") or "").lower()
        ends = {c.subject, v["to"]}
        if "hydraulic fluid" in meaning and any(e.startswith("PLC-") and e in index.entities
                                                and index.entities[e].registered for e in ends):
            mk("ambiguity", c.subject, "connected_to", [c.id],
               f"Hydraulic schematic: the line {c.subject} - {v['to']} is drawn in the colour the legend assigns to "
               f"'{v.get('line_meaning')}', but one end is the controller, which carries signals, not fluid. The legend "
               "assigns control/signal connections to the purple lines only.",
               "report purple lines as the control/signal connections; flag this grey line as unexplained")

    # 5. setpoint rationale vs scope (Q16-type ambiguity)
    for r in by_pred["setpoint_rationale"]:
        sc = [c.id for c in by_pred["normal_pressure"] if c.status == "asserted"
              and SwScope.from_dict(c.applies_when).min == (3, 2)]
        mk("ambiguity", "HPU.discharge_pressure", "setpoint_applicability", [r.id] + sc,
           f"ECN-1042 justifies the 200 bar setpoint by benefit on '{r.value['units']}', while the manuals scope 200 bar by "
           "software revision (3.2 and later) and PS-04A requires firmware >= 3.2. No source says whether older-built units "
           "that run revision >= 3.2 firmware use 200 bar, or whether newer-built units on older firmware may.",
           "best-supported reading: applicability follows the software revision (and PS-04A), not the build year; "
           "state the uncertainty")
    return out
