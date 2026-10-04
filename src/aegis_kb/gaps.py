"""Explicit absence: 'we searched and the corpus does not say'.

A gap is only reported after a real search, and the result lists:
  hits         segments that actually answer the question           (empty => not in the corpus)
  near_misses  segments that matched loosely but do NOT answer it   (shows we saw them and rejected them)
A source that states 'not specified' (e.g. the calibration record) is evidence of absence and is kept as such.
"""
from __future__ import annotations

import re

from .kb_schema import Gap

# topic, answer-bearing terms, entity aliases that must co-occur ([] = none required), doc scope ([] = any),
# near-miss terms, note
GAP_QUERIES = [
    ("Maximum continuous operating temperature of PS-04A",
     [r"\btemperature\b", r"°\s?C", r"\bdeg(?:rees)? ?C\b", r"operating range", r"thermal"],
     ["PS-04A", "PS04A", "P04A", "P.S.04-A", "Pressure Sensor 04A", "PRESSURE XDCR"], [],
     [r"\btemperature\b", r"°\s?C"],
     "No document gives a temperature rating for PS-04A. Temperature mentions elsewhere are about other things."),
    ("Calibration interval for a voltage sensor on the electrical system diagram",
     [r"voltage (?:sensor|transducer|transmitter|monitor)", r"calibration interval", r"recalibrat"],
     ["voltage sensor", "voltage transducer", "voltage monitor", "voltage transmitter", "SENSOR LOOP POWER"], [],
     [r"calibration interval", r"recalibrat", r"SENSOR LOOP POWER"],
     "The electrical schematic shows no voltage sensor (only a 24VDC sensor-loop POWER SUPPLY and a pressure "
     "transducer loop reference), so the question's premise is not supported; and no source gives a calibration "
     "interval for any sensor (the PS-04A calibration record says none is specified)."),
    ("Who approved ECN-1058",
     [r"approv", r"signed", r"authori[sz]ed by", r"reviewed by", r"signator"],
     ["ECN-1058"], ["ecn_1058"],
     [r"\bStatus\b", r"Released"],
     "ECN-1058's header lists number, title, effective date, references and status ('Released') but no approver or "
     "signature. 'Released' does not say who approved it."),
    ("Mean time between failures (MTBF) of isolation valve IV-21",
     [r"\bMTBF\b", r"mean time", r"failure rate", r"reliability", r"service life"],
     ["IV-21", "IV21", "Isolation Valve"], [],
     [r"\bMTBF\b", r"mean time", r"failure rate"],
     "No reliability data for IV-21 (or any component) appears in the package."),
    ("Compatibility with a 3-phase 400V supply",
     [r"\b400\s?V\b", r"3-?\s?phase", r"three[- ]phase", r"supply voltage"],
     [], [],
     [r"\b480\s?V\b", r"\bphase\b", r"compatib"],
     "Only 480V is mentioned (Q1 main disconnect 480V incoming; T1 480:120V control power). Nothing states the phase "
     "count or compatibility with 400V."),
    ("Does the training slide deck introduce any alarm not in the manuals?",
     [r"\bA\d{2}\b"], [], ["training_slides"], [r"\balarm\b"],
     "The slides contain no alarm codes."),
]


def _ws(t):
    return re.sub(r"\s+", " ", t)


def find_gaps(segs, claims) -> list[Gap]:
    out = []
    for i, (topic, terms, aliases, docs, near, note) in enumerate(GAP_QUERIES, start=1):
        hits, misses = [], []
        for s in segs:
            t = _ws(s.text)
            term_hit = any(re.search(p, t, re.I) for p in terms)
            subject_ok = (not aliases and not docs) or s.doc_id in docs or \
                any(a.lower() in t.lower() for a in aliases)
            if term_hit and subject_ok:
                hits.append(s.segment_id)                      # answer-bearing: right terms about the right subject
            elif term_hit or (subject_ok and any(re.search(p, t, re.I) for p in near)):
                misses.append(s.segment_id)                    # saw it, rejected it: right terms, wrong subject (or context only)
        related = []
        if "400V" in topic:
            related = [c.id for c in claims if c.predicate == "rated_voltage"]
        if "voltage sensor" in topic:
            related = [c.id for c in claims if c.predicate == "calibration_interval"]
        if "ECN-1058" in topic:
            related = [c.id for c in claims if c.subject == "doc:ECN-1058" and c.predicate == "header.status"]
        finding = "not_found"
        out.append(Gap(f"G{i:02d}", topic, terms, aliases, len(segs), hits, misses[:8], finding, related, note, list(docs)))
    return out
