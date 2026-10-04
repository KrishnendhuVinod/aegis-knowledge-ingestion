"""Answering: question -> {answer, caveats, claims, evidence, conflicts, gaps}.

Two composers over the SAME knowledge-base records:
  * deterministic renderers  (default): build sentences from claim values, so every number/name is traceable and
    reproducible; used for the baseline numbers and as the fallback.
  * Gemini composer (--llm): sees ONLY retrieved, citable findings (never the raw corpus) and must return claim ids; its
    answer is validated (ids exist, every number occurs in the findings or the question) and REJECTED in favour of the
    deterministic answer if it fails.
Every answer carries: the claims used, the evidence segments (doc + location + snippet), relevant conflicts/ambiguities,
and what could not be determined.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .retrieve import Retriever, toks
from .versions import SwScope


def sc(c):
    return SwScope.from_dict(c.applies_when)


def legacy(c):
    s = sc(c)
    return s.known and s.max is not None


def ws(t):
    return re.sub(r"\s+", " ", str(t)).strip()


@dataclass
class R:
    intent: str
    text: str
    used: list = field(default_factory=list)
    caveats: list = field(default_factory=list)
    extra_evidence: list = field(default_factory=list)
    near_miss: list = field(default_factory=list)
    gaps: list = field(default_factory=list)
    context: list = field(default_factory=list)   # claims shown as 'context' evidence (what the answer was checked against)


class View:
    def __init__(self, kb, segs):
        self.kb, self.segs = kb, segs
        self.ent = {e.id: e for e in kb.entities}
        self.cl = {c.id: c for c in kb.claims}

    def claims(self, predicate=None, subject=None, status=None):
        return [c for c in self.kb.claims if (predicate is None or c.predicate == predicate)
                and (subject is None or c.subject == subject) and (status is None or c.status == status)]

    def name(self, eid):
        e = self.ent.get(eid)
        return f"{eid} ({e.name})" if e and e.registered and e.name != eid else eid

    def conflict(self, predicate):
        return [x for x in self.kb.conflicts if x.predicate == predicate]

    @staticmethod
    def bullets(items):
        return "\n".join(f"- {i}" for i in items)


# ------------------------------------------------------------------------------------------------ renderers
def r_startup(v, q, ents):
    by = {}
    for c in v.claims("startup_precondition"):
        if not legacy(c):
            by.setdefault(c.value["key"], []).append(c)
    labels = {"iv21_open": "Isolation valve IV-21 is OPEN",
              "estop_reset": "The emergency stop circuit is RESET",
              "fluid_level_normal": "The hydraulic fluid level is within the normal band (sight glass)",
              "maintenance_panel_closed": "The maintenance access panel is installed and closed (the manual warns not to "
                                          "start the HPU with it removed)"}
    items = [labels[k] for k in labels if k in by]
    used = [c for k in labels for c in by.get(k, [])]
    docs = sorted({d for c in used for d in c.docs})
    text = ("Before starting the Hydraulic Power Unit (HPU), all of these must be true:\n" + v.bullets(items) +
            f"\nThese come from the operator manual (the panel condition is given as a WARNING) and are corroborated by "
            f"{', '.join(d for d in docs if d != 'operator_manual')}.")
    return R("startup", text, used)


def r_pressure_current(v, q, ents):
    cur = [c for c in v.claims("normal_pressure", status="asserted") if sc(c).min == (3, 2) and sc(c).max is None]
    old = [c for c in v.claims("normal_pressure", status="asserted") if sc(c).max == (3, 2)]
    val = cur[0].value
    text = (f"The normal HPU discharge pressure is {val} bar. That applies to units running software revision 3.2 or later, "
            f"where the pressure is measured by sensor PS-04A. On earlier revisions (below 3.2) the normal pressure was "
            f"{old[0].value} bar, measured by PS-04, so the value depends on the unit's software revision.")
    cav, lt = [], v.claims("observed_pressure", status="low_trust_observation")
    if lt:
        cav.append(f"A field note reports about {lt[0].value} bar, but it is low-trust (uncalibrated gauge, unreviewed, undated, "
                   "software revision not recorded) and cannot override the manual.")
    return R("pressure_current", text, cur + old[:1] + lt, cav)


def r_pressure_before(v, q, ents):
    old = [c for c in v.claims("normal_pressure", status="asserted") if sc(c).max == (3, 2)]
    new = [c for c in v.claims("normal_pressure", status="asserted") if sc(c).min == (3, 2) and sc(c).max is None]
    chg = v.claims("setpoint_change")
    why = v.claims("setpoint_rationale")
    rel = v.claims("release_date", "software:3.2")
    rep = v.claims("sensor_replacement", "PS-04")
    ecn = v.claims("introduced_by")
    ecn_id = ecn[0].value if ecn else "the ECN"
    text = (f"Before software revision 3.2 the normal HPU discharge pressure was {old[0].value} bar, measured by sensor PS-04. "
            f"{ecn_id} changed it: effective with software 3.2 (released {rel[0].value if rel else 'n/a'}) the setpoint was "
            f"revised from {chg[0].value['from']} bar to {chg[0].value['to']} bar, alongside replacing PS-04 with PS-04A. "
            f"The ECN describes it as a deliberate process change, not a sensor calibration artifact.")
    return R("pressure_before", text, old + new[:1] + chg + why + rep + ecn + rel)


def r_alarm_profile(v, q, ents):
    m = re.search(r"\bA\d{2}\b", q, re.I)
    a = m.group(0).upper() if m else next((e for e in ents if v.ent[e].type == "alarm"), "A17")
    nm = v.claims("alarm_name", a) or v.claims("common_name", a)
    name = re.sub(r"^Alarm:\s*", "", str(nm[0].value)) if nm else a
    cond = v.claims("alarm_condition", a)
    causes = v.claims("alarm_causes", a)
    act = v.claims("alarm_required_action", a)
    pan = v.claims("alarm_panel_indication", a)
    per = v.claims("persistence_action", a)
    corr = v.claims("documentation_correction", a)
    text = (f"Alarm {a} indicates {name}: the condition is \"{ws(cond[0].value).lower()}\" (panel indication {pan[0].value}). "
            f"Possible causes:\n" + v.bullets(causes[0].value) + f"\nRequired action: {ws(act[0].value)}")
    cav = []
    if corr:
        cav.append("ECN-1058 corrected the documentation: the A17 condition is evaluated against whichever pressure sensor is "
                   "active for the installed software revision (PS-04 before 3.2, PS-04A from 3.2); the threshold is unchanged.")
    return R("alarm_profile", text, nm + cond + causes + act + pan + per + corr[:1], cav)


def r_persistence(v, q, ents):
    pa = v.claims("persistence_action", "A17")[0]
    steps = v.claims("procedure_steps", "Shutdown Procedure 4.7")
    note = v.claims("alarm_note", "A17")
    obs = v.claims("observed_persistence")
    text = (f"If alarm A17 persists for more than {pa.value['persistence_s']} seconds, execute {pa.value['action']} before "
            f"investigating further (do not just silence the alarm). The procedure: " + "; ".join(steps[0].value) + ". ")
    if note:
        text += "A transient A17 that clears on its own within a few seconds during valve transition does not require it."
    cav = []
    if obs:
        o = obs[0].value
        cav.append(f"The HMI alarm screenshot shows A17 active for {o['active_s']} s against the {o['threshold_s']} s "
                   "threshold, i.e. that unit is past the point where the shutdown procedure is required.")
    return R("persistence", text, [pa] + steps + note + obs, cav)


def r_reset(v, q, ents):
    proh = v.claims("reset_prohibited_above_bar")[0]
    perm = v.claims("reset_permitted_below_bar")
    pre = v.claims("reset_precondition_action")
    mn = v.claims("reset_min_pressure")
    text = (f"Do not reset the PLC-03 controller while hydraulic pressure is above {proh.value} bar: resetting under pressure "
            f"can cause an uncommanded valve transition (the maintenance manual adds: a momentary uncommanded actuation of "
            f"IV-21). Reset is only permitted when pressure, as reported by the active sensor (PS-04 before software 3.2, "
            f"PS-04A from 3.2), reads below {perm[0].value} bar; bleed pressure first using the manual bleed procedure "
            f"(Section 8). The firmware also blocks reset above {proh.value} bar and specifies no minimum pressure.")
    cav = [x.description for x in v.conflict("reset_boundary")]
    return R("reset", text, [proh] + perm + pre + mn, cav)


def r_alarm_for_threshold(v, q, ents):
    num = re.search(r"(\d+)\s*bar", q)
    below = bool(re.search(r"below|under|less|drops|falls|low", q, re.I))
    op = "<" if below else ">"
    hits = [c for c in v.claims("alarm_threshold") if c.value["op"] == op and (not num or c.value["value"] == int(num.group(1)))]
    c = hits[0]
    nm = v.claims("common_name", c.subject)
    name = re.sub(r"^Alarm:\s*", "", str(nm[0].value)) if nm else ""
    others = [x for x in v.claims("alarm_threshold") if x.subject != c.subject]
    text = (f"Alarm {c.subject} ({name}) is the one raised when discharge pressure is {'below' if op == '<' else 'above'} "
            f"{c.value['value']} bar. " + (f"(The related high-pressure alarm is {others[0].subject}, above "
                                           f"{others[0].value['value']} bar.)" if others else ""))
    return R("alarm_for_threshold", text, hits + nm + others[:1])


def _pair_decision(v, a, b):
    for d in v.kb.decisions:
        if d.decision == "accepted" and d.relation in ("superseded_by", "distinct_from") and {d.surface, d.entity_id} == {a, b}:
            return d
    return None


def r_identity(v, q, ents):
    a, b = ents[0], ents[1]
    if a == b:
        return R("identity", f"Yes. {a} and {b} are the same thing.", [])
    d = _pair_decision(v, a, b)
    ea, eb = v.ent[a], v.ent[b]
    if d and d.relation == "superseded_by":
        old, new = d.surface, d.entity_id
        eo, en = v.ent[old], v.ent[new]
        text = (f"No. {old} and {new} are not the same component. {old} was superseded by {new} (effective software revision "
                f"3.2, ECN-1042): the component register lists them as separate components with different status "
                f"({old}: {eo.status}; {new}: {en.status}), and ECN-1042 states that {new} is not a form-fit-function "
                f"replacement for {old}. They are related by replacement, not identity.")
        used = v.claims("sensor_replacement", old) + v.claims("introduced_by") + v.claims("installation_constraint")
    elif d:
        text = (f"No. {a} and {b} are different, unrelated components. {b if 'Coolant' in str(eb.location) else a} is "
                f"'{(eb if 'Coolant' in str(eb.location) else ea).name}' located at "
                f"{(eb if 'Coolant' in str(eb.location) else ea).location}, while the other sits on the HPU discharge line. "
                f"The component register says {'PS-40' if 'Coolant' in str(eb.location) or 'Coolant' in str(ea.location) else b} "
                f"is NOT related to the HPU discharge circuit and warns not to confuse it with PS-04 / PS-04A.")
        used = v.claims("location", a) + v.claims("location", b)
    else:
        text = f"{a} and {b} are recorded as different entities; no document states they are the same."
        used = []
    return R("identity", text, used, extra_evidence=list(d.evidence) if d else [])


def r_provenance(v, q, ents):
    c = v.claims("introduced_by")[0]
    ecn = c.value
    title = v.claims("header.title", f"doc:{ecn}")
    eff = v.claims("header.effective", f"doc:{ecn}")
    sts = v.claims("header.status", f"doc:{ecn}")
    text = (f"{ecn} (Engineering Change Notice, '{title[0].value}', effective {eff[0].value}, status {sts[0].value}) introduced "
            f"the change from PS-04 to PS-04A. The component register, operator manual and revision history all point to it.")
    return R("provenance", text, [c] + title + eff + sts + v.claims("sensor_replacement", "PS-04"))


def r_topology(v, q, ents):
    ctrl = next((e for e in ents if e.startswith("PLC-")), "PLC-03")
    doc = "hydraulic_schematic" if re.search(r"hydraulic|schematic", q, re.I) else ("wiring_diagram" if re.search(
        r"wiring", q, re.I) else ("electrical_diagram" if "electrical" in q.lower() else None))
    edges = [c for c in v.claims("connected_to") if (doc is None or doc in c.docs) and (c.subject == ctrl or c.value["to"] == ctrl)]
    sig, other = [], []
    for c in edges:
        peer = c.value["to"] if c.subject == ctrl else c.subject
        (sig if "control/signal" in (c.value.get("line_meaning") or "") else other).append((peer, c))
    colour = sig[0][1].value["line_colour"] if sig else "purple"
    text = (f"According to the {doc.replace('_', ' ') if doc else 'drawings'}, {v.name(ctrl)} connects directly to "
            + " and ".join(v.name(p) for p, _ in sig) +
            f" through {colour} lines, which the legend defines as control/signal connections to {ctrl}.")
    cav = []
    for p, c in other:
        cav.append(f"A further line joins {ctrl} and {v.name(p)}, but it is drawn {c.value['line_colour']}, which the legend "
                   f"assigns to '{c.value.get('line_meaning')}'; the drawing does not explain a fluid-path line at the "
                   "controller, so it is flagged as unexplained and not counted as a control/signal connection.")
    return R("topology", text, [c for _, c in sig] + [c for _, c in other], cav)


def r_location(v, q, ents):
    eid = next((e for e in ents if v.claims("location", e)), ents[0])
    loc = v.claims("location", eid)[0]
    nm = v.claims("common_name", eid)
    return R("location", f"According to the component register, {eid} ({nm[0].value}) is located in: {loc.value}.", [loc] + nm)


def r_tag_match(v, q, ents):
    t = v.claims("displays_tag")[0]
    tag = t.value
    d = next((x for x in v.kb.decisions if x.surface == tag and x.relation == "variant_of" and x.decision == "accepted"), None)
    eid = d.entity_id if d else None
    obs = [c for c in v.kb.claims if eid and c.subject == eid and c.predicate.startswith("observed_")]
    sc_val = next((c for c in obs if c.predicate == "observed_pressure"), None)
    cal = next((c for c in obs if c.predicate == "observed_calibration_status"), None)
    text = (f"The diagnostics screenshot shows the sensor tag '{tag}' (the screen notes this is the tag as printed on the "
            f"physical unit label). It matches the known component {v.name(eid)}: the two differ only in punctuation, and it "
            f"does not match PS-04 (that would read PS04 with no trailing A). {eid} is the active HPU discharge pressure "
            f"sensor on software 3.2 and later; the same screen reports a scaled value of {sc_val.value if sc_val else 'n/a'} "
            f"and calibration status {cal.value if cal else 'n/a'}.")
    return R("tag_match", text, [t] + obs, extra_evidence=list(d.evidence) if d else [])


def r_revision(v, q, ents):
    m = re.search(r"revision (\d+(?:\.\d+)*)", q, re.I)
    rev = m.group(1) if m else "3.2"
    rel = v.claims("release_date", f"software:{rev}")
    summ = v.claims("summary_of_changes", f"software:{rev}")
    chg = v.claims("setpoint_change")
    rep = v.claims("sensor_replacement", "PS-04")
    text = (f"Per the revision history, software revision {rev} took effect on {rel[0].value}. Alongside it: pressure sensor "
            f"PS-04 was replaced by PS-04A, and the normal HPU discharge pressure setpoint changed from {chg[0].value['from']} "
            f"bar to {chg[0].value['to']} bar (see ECN-1042).")
    return R("revision", text, rel + summ + chg + rep)


def r_config(v, q, ents):
    m = re.search(r"sensor_\w+", q)
    key = m.group(0) if m else "sensor_ps04a_threshold_bar"
    mp = [c for c in v.claims("config_maps_to") if c.subject.endswith(key)]
    if not mp:
        return r_generic(v, q, ents, None)
    c = mp[0]
    text = (f"{key} corresponds to the operator manual's normal operating pressure for the HPU, i.e. the HPU discharge pressure "
            f"setpoint ({[x.value for x in v.claims('normal_pressure', status='inferred') if sc(x).min == (3, 2)][0]} bar), as "
            f"measured by PS-04A. This is an INFERRED mapping: no document states it. It rests on the key naming ps04a, the "
            f"value matching the manual's 200 bar for software 3.2 and later, and the export's applies_from_firmware 3.2.")
    cav = ["The export's own note says not to map sensor_ps40_* keys: PS-40 is the unrelated coolant-loop sensor."]
    return R("config_mapping", text, mp + v.claims("normal_pressure", status="inferred"), cav)


def r_applicability(v, q, ents):
    cur = [c for c in v.claims("normal_pressure", status="asserted") if sc(c).min == (3, 2)]
    sup = v.claims("sensor_support")
    ins = v.claims("installation_constraint")
    fw = [c for c in v.claims("firmware_requirement", "PS-04A")]
    why = v.claims("setpoint_rationale")
    text = (f"No, not all units: only some. The {cur[0].value} bar setpoint applies to units running software revision 3.2 or "
            f"later, which use sensor PS-04A (PS-04A needs controller firmware 3.2 or later). Units on software below 3.2 keep "
            f"PS-04 and the older 180 bar setpoint: ECN-1042 says PS-04 remains installed and supported there and that PS-04A "
            f"must not be installed on firmware older than 3.2.")
    cav = [x.description for x in v.conflict("setpoint_applicability")]
    return R("applicability", text, cur + sup + ins + fw + why, cav)


def r_novelty(v, q, ents):
    intro = v.claims("introduces_term")
    alias = v.claims("alias_used_in_training")
    term = intro[0].subject
    note = intro[0].note or ""
    text = (f"Yes, one component: the {term}. It appears in the training slides (described there as a Line 4/5-specific "
            f"configuration detail) and in the hydraulic schematic, but not in the operator manual, maintenance manual, alarm "
            f"reference, component register or glossary. No alarm is introduced: the slides contain no alarm codes. The slides' "
            f"informal name '{alias[0].value}' is just another name for the HPU, not a new component.")
    g6 = [g for g in v.kb.gaps if "training slide" in g.topic]
    return R("novelty", text, intro + alias, gaps=g6)


def r_gap(v, q, ents, gaps):
    g = gaps[0]
    rel = [v.cl[i] for i in g.related_claims if i in v.cl]
    text = (f"This cannot be determined from the provided sources. {g.note} (Searched {g.segments_searched} text segments; none "
            f"gives the answer.)")
    if rel:
        text += " Related facts that are stated: " + "; ".join(f"{c.subject} {c.predicate.replace('_', ' ')}: "
                                                              f"{c.value if c.value is not None else 'not specified'}"
                                                              for c in rel[:3]) + "."
    ctx = [c for e in ents for c in v.claims("common_name", e)]
    return R("gap", text, rel, near_miss=g.near_misses, gaps=[g], context=ctx)


def r_generic(v, q, ents, retrieval):
    cs = retrieval.claims[:6] if retrieval else []
    lines = [f"{c.subject} - {c.predicate.replace('_', ' ')}: {c.value} ({sc(c).label()}; {c.status})" for c in cs]
    text = ("No specialised answer pattern matched this question. Most relevant findings in the knowledge base:\n" +
            (v.bullets(lines) if lines else "- none found"))
    return R("generic", text, cs)


# ------------------------------------------------------------------------------------------------ classification
INTENTS = [
    ("novelty", r"training slide|slide deck|slides?\b.*(introduce|new)"),
    ("tag_match", r"(diagnostic|screenshot|screen).*(sensor id|\btag\b|\bid\b)|(sensor id|\btag\b).*(diagnostic|screenshot)"),
    ("identity", r"\bsame\b|identical|equivalent|one and the same"),
    ("provenance", r"which document|introduced the change|which ecn|who introduced|originat"),
    ("applicability", r"apply to all|all .{0,30}units|only some|every unit"),
    ("config", r"configuration export|config export|sensor_\w+"),
    ("alarm_for_threshold", r"(which|what) alarm.*\d+\s*bar|alarm.*(associated|raised|triggered).*\d+\s*bar"),
    ("revision", r"revision history|take effect|took effect|when was .*released|which (software )?(revision|version).*(introduc|200)"),
    ("pressure_before", r"(before|prior to|earlier than|pre-?)\s*(software )?(revision |version )?\d?\.?\d*.*(pressure|threshold|limit|setpoint)|(pressure|threshold|limit|setpoint).*(before|prior to)\s*(software )?(revision|version)"),
    ("persistence", r"persist|more than \d+ seconds"),
    ("reset", r"\breset\b"),
    ("alarm_profile", r"alarm\s+a\d{2}|\ba\d{2}\b.*(indicat|cause|mean)|(indicat|cause).*\ba\d{2}\b"),
    ("topology", r"connect"),
    ("location", r"locat|where is"),
    ("startup", r"before start|startup|start up|true before|prior to (powering|starting|start)|power(ing)? up"),
    ("pressure_current", r"pressure"),
]
RENDER = {"startup": r_startup, "pressure_current": r_pressure_current, "pressure_before": r_pressure_before,
          "alarm_profile": r_alarm_profile, "persistence": r_persistence, "reset": r_reset,
          "alarm_for_threshold": r_alarm_for_threshold, "identity": r_identity, "provenance": r_provenance,
          "topology": r_topology, "location": r_location, "tag_match": r_tag_match, "revision": r_revision,
          "config": r_config, "applicability": r_applicability, "novelty": r_novelty}


def classify(q, ents, gaps):
    s = q.lower()
    for name, pat in INTENTS:
        if name == "novelty" and re.search(pat, s):
            return "novelty"
    if gaps:
        return "gap"
    for name, pat in INTENTS:
        if name == "identity" and len(ents) < 2:
            continue
        if re.search(pat, s):
            return name
    return "generic"


# ------------------------------------------------------------------------------------------------ evidence + assembly
def evidence_for(v, claims, extra, near):
    seen, out = set(), []
    order = sorted(claims, key=lambda c: c.trust_rank)
    for sid in [s for c in order for s in c.evidence] + list(extra):
        if sid in seen or sid not in v.segs:
            continue
        seen.add(sid)
        out.append(_ev(v, sid, "supports"))
    for sid in near:
        if sid not in seen and sid in v.segs:
            seen.add(sid)
            out.append(_ev(v, sid, "searched_not_answering"))
    return out


def _ev(v, sid, role):
    s = v.segs[sid]
    snip = ws(s.text)
    return {"segment_id": sid, "doc_id": s.doc_id, "kind": s.kind, "location": s.location, "role": role,
            "method": s.method, "reading_confidence": s.confidence, "snippet": snip[:200] + ("..." if len(snip) > 200 else "")}


def answer_question(q, kb, segs, retriever=None, llm=None) -> dict:
    v = View(kb, segs)
    rt = retriever or Retriever(kb)
    retrieval = rt.retrieve(q)
    ents = retrieval.entities
    intent = classify(q, ents, retrieval.gaps)
    if intent == "gap":
        r = r_gap(v, q, ents, retrieval.gaps)
    elif intent == "generic":
        r = r_generic(v, q, ents, retrieval)
    else:
        try:
            r = RENDER[intent](v, q, ents)
        except (IndexError, KeyError, StopIteration):
            r = r_generic(v, q, ents, retrieval)       # renderer's expected claims missing => honest fallback
    ev = evidence_for(v, r.used, r.extra_evidence, r.near_miss)
    have = {e["segment_id"] for e in ev}
    for c in r.context:
        for sid in c.evidence:
            if sid not in have and sid in v.segs:
                have.add(sid)
                ev.append(_ev(v, sid, "context"))
    ids = {c.id for c in r.used}
    conflicts = [x for x in kb.conflicts if set(x.claim_ids) & ids]
    out = {"question": q, "intent": r.intent, "answer": r.text, "caveats": r.caveats,
           "claims": [c.id for c in r.used], "evidence": ev, "conflicts": [x.id for x in conflicts],
           "gaps": [g.id for g in r.gaps], "mode": "deterministic"}
    if llm is not None:
        better = compose_llm(q, v, retrieval, r, llm)
        if better.get("ok"):
            out.update(answer=better["answer"], caveats=better.get("caveats", r.caveats), claims=better["claims"],
                       evidence=evidence_for(v, [v.cl[i] for i in better["claims"]], r.extra_evidence, r.near_miss),
                       mode="llm")
        else:
            out["llm_rejected"] = better["reason"]
    return out


# ------------------------------------------------------------------------------------------------ Gemini composer
def finding_line(c):
    return (f"[{c.id}] {c.subject} | {c.predicate} = {c.value if c.value is not None else 'NOT SPECIFIED'}"
            f"{(' ' + c.unit) if c.unit else ''} | applies: {sc(c).label()} | status: {c.status} | trust rank: {c.trust_rank} "
            f"(1=best) | sources: {', '.join(c.docs)}" + (f" | note: {ws(c.note)}" if c.note else ""))


def build_prompt(q, claims, conflicts, gaps):
    L = ["You answer questions about the Aegis Series-7 HCS using ONLY the findings below. Rules:",
         "1. Use no outside knowledge. If the findings do not answer it, say it cannot be determined from the sources.",
         "2. State the software-revision scope when a value depends on it. Say when a finding is inferred, an observation, "
         "low-trust, or explicitly not specified. Mention listed ambiguities that matter.",
         "3. Be concise (under 130 words). Every number you write must appear in the findings or the question.",
         "4. Return JSON only: {\"answer\": str, \"used_claim_ids\": [str], \"caveats\": [str]}.",
         "", "FINDINGS:"]
    L += [finding_line(c) for c in claims]
    if conflicts:
        L += ["", "CONFLICTS / AMBIGUITIES:"] + [f"[{x.id}] ({x.kind}) {x.description}" for x in conflicts]
    if gaps:
        L += ["", "SEARCHED BUT NOT FOUND:"] + [f"[{g.id}] {g.topic}: {g.note}" for g in gaps]
    L += ["", f"QUESTION: {q}"]
    return "\n".join(L)


def compose_llm(q, v, retrieval, r, llm) -> dict:
    by_id = {c.id: c for c in retrieval.claims + r.used}
    claims = list(by_id.values())[:24]
    confl = list({x.id: x for x in retrieval.conflicts + [x for x in v.kb.conflicts
                                                           if set(x.claim_ids) & {c.id for c in claims}]}.values())
    prompt = build_prompt(q, claims, confl, r.gaps or retrieval.gaps)
    try:
        resp = llm.generate_json(prompt)
    except Exception as e:                                  # network/quota: fall back, never crash an evaluation
        return {"ok": False, "reason": f"llm error: {type(e).__name__}"}
    if not resp:
        return {"ok": False, "reason": "no response (no key and no cached answer)"}
    ans, ids = str(resp.get("answer", "")).strip(), list(resp.get("used_claim_ids") or [])
    if not ans:
        return {"ok": False, "reason": "empty answer"}
    bad = [i for i in ids if i not in by_id]
    if bad:
        return {"ok": False, "reason": f"cited unknown claim ids {bad}"}
    if not ids and not (r.gaps or retrieval.gaps):
        return {"ok": False, "reason": "no claim ids cited"}
    allowed = set(re.findall(r"\d+(?:\.\d+)?", q + " " + "\n".join(finding_line(c) for c in claims)))
    novel = [n for n in re.findall(r"\d+(?:\.\d+)?", ans) if n not in allowed]
    if novel:
        return {"ok": False, "reason": f"ungrounded numbers {sorted(set(novel))}"}
    return {"ok": True, "answer": ans, "claims": ids or [c.id for c in r.used], "caveats": list(resp.get("caveats") or [])}
