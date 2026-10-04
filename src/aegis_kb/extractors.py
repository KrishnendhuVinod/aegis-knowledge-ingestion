"""Layer 2: claim extraction. RULE-BASED and fully traceable: every claim cites the segment(s) it came from.

Three families of extractor:
  * structure-driven (generic): register rows, revision-history rows, ECN header fields, alarm-table rows,
    JSON leaves, diagram edges. These key off table headers / JSON paths, not wording.
  * sentence-pattern rules: prose in manuals/ECNs/scan notes. Each rule is a regex anchored on the sentence,
    so it re-finds its evidence wherever the text lives. These are the corpus-specific part; the report says so.
  * derived: terms present in slides but absent from the manuals (Q12 type questions).

Claims carry `applies_when` (software-revision scope) and a `status`, so 'asserted' / 'observation' /
'low_trust_observation' / 'inferred' / 'explicitly_not_specified' / 'planned' are never blended together.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

from .kb_schema import Claim
from .sources import BY_ID
from .versions import SwScope

PS = r"(PS-\d+[A-Z]?)"


def ws(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()


def snake(k: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", ws(k).lower()).strip("_")


class Extractor:
    def __init__(self, segs, idx):
        self.segs, self.idx = segs, idx
        self.by_doc = defaultdict(list)
        for s in segs:
            self.by_doc[s.doc_id].append(s)
        self._raw: list[dict] = []

    # ------------------------------------------------------------------ helpers
    def find(self, doc, pat, kinds=None, flags=re.I):
        out = []
        for s in self.by_doc.get(doc, []):
            if kinds and s.kind not in kinds:
                continue
            m = re.search(pat, ws(s.text), flags)
            if m:
                out.append((s, m))
        return out

    def add(self, subject, predicate, value, evidence, *, unit=None, scope=None, status="asserted",
            note=None, extraction="rule"):
        evidence = [e for e in evidence if e is not None]
        if not evidence:
            return
        docs = sorted({e.doc_id for e in evidence})
        self._raw.append(dict(
            subject=subject, predicate=predicate, value=value, unit=unit,
            applies_when=(scope or SwScope.unknown()).to_dict(),
            evidence=sorted({e.segment_id for e in evidence}), docs=docs,
            trust_rank=min(BY_ID[d].trust_rank for d in docs), status=status, note=note,
            reading_confidence=min(e.confidence for e in evidence), extraction=extraction))

    def _setpoint_pair(self, seg, frm, to, rev, via):
        """A stated change 'from X to Y effective rev' also evidences normal pressure X (before) and Y (since)."""
        self.add("HPU.discharge_pressure", "normal_pressure", int(frm), [seg], unit="bar",
                 scope=SwScope.before(rev), note=f"implied by the stated setpoint change ({via})")
        self.add("HPU.discharge_pressure", "normal_pressure", int(to), [seg], unit="bar",
                 scope=SwScope.since(rev), note=f"implied by the stated setpoint change ({via})")

    def cells(self, s):
        return {ws(k): ws(v) for k, v in s.data.get("cells", {}).items()}

    # ------------------------------------------------------------------ run
    def run(self) -> list[Claim]:
        for fn in (self.register, self.revision_history, self.ecns, self.operator_manual, self.legacy_manual,
                   self.maintenance_manual, self.alarm_reference, self.glossary, self.slides, self.diagrams,
                   self.config, self.screens_and_scan):
            fn()
        return self._merge()

    def _merge(self) -> list[Claim]:
        merged: dict[str, dict] = {}
        for c in self._raw:
            key = json.dumps([c["subject"], c["predicate"], c["value"], c["applies_when"], c["status"]],
                             sort_keys=True, default=str)
            if key in merged:
                m = merged[key]
                m["evidence"] = sorted(set(m["evidence"]) | set(c["evidence"]))
                m["docs"] = sorted(set(m["docs"]) | set(c["docs"]))
                m["trust_rank"] = min(m["trust_rank"], c["trust_rank"])
                m["reading_confidence"] = min(m["reading_confidence"], c["reading_confidence"])
                if c["note"] and (not m["note"] or c["note"] not in m["note"]):
                    m["note"] = (m["note"] + " | " if m["note"] else "") + c["note"]
            else:
                merged[key] = dict(c)
        return [Claim(id=f"C{i:03d}", **c) for i, c in enumerate(merged.values(), start=1)]

    # ------------------------------------------------------------------ register
    def register(self):
        for s in self.by_doc["component_register"]:
            if s.kind != "table_row":
                continue
            c = self.cells(s)
            cid = next(v for k, v in c.items() if k.startswith("Component ID"))
            self.add(cid, "common_name", c.get("Common Name"), [s], extraction="table")
            self.add(cid, "location", c.get("Location"), [s], scope=SwScope.all(), extraction="table")
            self.add(cid, "register_status", c.get("Status"), [s], note=c.get("Notes"), extraction="table")
            note = c.get("Notes", "")
            if m := re.search(r"(\d{3})V incoming", note):
                self.add(cid, "rated_voltage", {"volts": int(m.group(1)), "role": "incoming supply"}, [s],
                         unit="V", extraction="table")
            if m := re.search(r"(\d+):(\d+)V", note):
                self.add(cid, "rated_voltage", {"primary_v": int(m.group(1)), "secondary_v": int(m.group(2))},
                         [s], unit="V", extraction="table")
            if m := re.search(r"Requires controller firmware >= ([\d.]+)", note):
                self.add(cid, "firmware_requirement", f">= {m.group(1)}", [s], scope=SwScope.all())

    # ------------------------------------------------------------------ revision history
    def revision_history(self):
        for s in self.by_doc["revision_history"]:
            if s.kind != "table_row":
                continue
            c = self.cells(s)
            rev = c["Software Revision"]
            subj = f"software:{rev}"
            date = c["Release Date"]
            planned = "planned" in date.lower()
            iso = re.search(r"\d{4}-\d{2}-\d{2}", date).group(0)
            self.add(subj, "release_date", iso, [s], status="planned" if planned else "asserted",
                     note="source labels this release 'planned' (not confirmed released)" if planned else None,
                     extraction="table")
            self.add(subj, "summary_of_changes", c["Summary of Changes"], [s], extraction="table")
            summ = c["Summary of Changes"]
            if m := re.search(r"setpoint changed from (\d+) bar to (\d+) bar", summ):
                self.add("HPU.discharge_pressure", "setpoint_change",
                         {"from": int(m.group(1)), "to": int(m.group(2))}, [s], unit="bar", scope=SwScope.since(rev),
                         note=f"effective software revision {rev}, released {iso}")
                self._setpoint_pair(s, m.group(1), m.group(2), rev, "revision history")
            if m := re.search(rf"{PS} replaced by {PS}", summ):
                self.add(m.group(1), "sensor_replacement", {"replaced_by": m.group(2)}, [s], scope=SwScope.since(rev))
            if "Documentation correction" in summ:
                self.add("A17", "documentation_correction", ws(summ), [s], scope=SwScope.since(rev),
                         note="documentation only; thresholds unchanged")

    # ------------------------------------------------------------------ ECNs
    def ecns(self):
        for doc in ("ecn_1042", "ecn_1058"):
            segs = self.by_doc[doc]
            ecn_id = next((s.data["value"] for s in segs if s.kind == "kv" and s.data["key"] == "ECN Number"), doc)
            for s in segs:
                if s.kind == "kv":
                    self.add(f"doc:{ecn_id}", f"header.{snake(s.data['key'])}", s.data["value"], [s],
                             extraction="kv")
        # ECN-1042
        for s, m in self.find("ecn_1042", rf"\(({PS[1:-1]}) → ({PS[1:-1]})\)", kinds=["kv"]):
            self.add(f"change:{m.group(1)}->{m.group(2)}", "introduced_by", "ECN-1042",
                     [s] + [x for x, _ in self.find("component_register", r"See ECN-1042")][:1],
                     note="ECN-1042 title names the change; register note on PS-04 also cites ECN-1042")
        for s, m in self.find("ecn_1042", rf"{PS} is replaced by (?:pressure sensor )?{PS}"):
            self.add(m.group(1), "sensor_replacement", {"replaced_by": m.group(2)},
                     [s] + [x for x, _ in self.find("operator_manual", rf"{m.group(1)} is superseded by {m.group(2)}")]
                     + [x for x, _ in self.find("component_register", rf"Superseded by {m.group(2)}")],
                     scope=SwScope.since("3.2"))
            self.add(m.group(2), "firmware_requirement", ">= 3.2", [s], scope=SwScope.all(),
                     note="'controller firmware must be at revision 3.2 or later to read PS-04A correctly'")
        for s, m in self.find("ecn_1042", r"revised from (\d+) bar to (\d+) bar"):
            self.add("HPU.discharge_pressure", "setpoint_change", {"from": int(m.group(1)), "to": int(m.group(2))},
                     [s], unit="bar", scope=SwScope.since("3.2"),
                     note="ECN: 'a deliberate process change, not a sensor calibration artifact'")
            self._setpoint_pair(s, m.group(1), m.group(2), "3.2", "ECN-1042")
        for s, m in self.find("ecn_1042", r"improves press cycle time on (Series-7 units manufactured after \d{4})"):
            self.add("HPU.discharge_pressure", "setpoint_rationale",
                     {"benefit": "press cycle time", "units": m.group(1)}, [s],
                     note="stated as the reason for the setpoint, not as an applicability condition")
        for s, m in self.find("ecn_1042", rf"{PS} remains installed and supported on units running software revisions "
                                          r"prior to ([\d.]+)"):
            self.add(m.group(1), "sensor_support", "remains installed and supported", [s],
                     scope=SwScope.before(m.group(2)))
        for s, m in self.find("ecn_1042", rf"Do not install {PS} on a controller running firmware older than ([\d.]+)"):
            self.add(m.group(1), "installation_constraint", f"do not install on firmware older than {m.group(2)}",
                     [s], scope=SwScope.before(m.group(2)))
        for s, m in self.find("ecn_1042", rf"{PS}'s signal drift exceeded tolerance after approximately (\d+) months"):
            self.add(m.group(1), "change_reason", {"issue": "signal drift exceeded tolerance",
                                                     "after_months": int(m.group(2)), "symptom": "nuisance Alarm A19"},
                     [s])
        # ECN-1058
        for s, m in self.find("ecn_1058", r"evaluated against whichever pressure sensor is active"):
            self.add("A17", "documentation_correction",
                     "A17 low-pressure condition is evaluated against the pressure sensor active for the installed "
                     "software revision (PS-04 before 3.2, PS-04A from 3.2); threshold logic unchanged", [s],
                     note="documentation correction only; no firmware or hardware change")
        for s, m in self.find("ecn_1058", r"does not change the operating pressure setpoint"):
            self.add("HPU.discharge_pressure", "setpoint_unchanged_by", "ECN-1058", [s])

    # ------------------------------------------------------------------ operator manual
    def operator_manual(self):
        doc = "operator_manual"
        # normal pressure
        for s, m in self.find(doc, r"Normal HPU discharge pressure is (\d+) bar on software revision ([\d.]+) and later"):
            self.add("HPU.discharge_pressure", "normal_pressure", int(m.group(1)), [s], unit="bar",
                     scope=SwScope.since(m.group(2)))
        for s, m in self.find(doc, r"On revisions prior to ([\d.]+), normal discharge pressure was (\d+) bar, "
                                    rf"measured by the original {PS} sensor"):
            self.add("HPU.discharge_pressure", "normal_pressure", int(m.group(2)), [s], unit="bar",
                     scope=SwScope.before(m.group(1)), note=f"measured by {m.group(3)}")
        for s, m in self.find(doc, rf"as reported by {PS}, reaches (\d+) bar\. This is the normal operating pressure "
                                    r"for software revision ([\d.]+) and later"):
            self.add("HPU.discharge_pressure", "normal_pressure", int(m.group(2)), [s], unit="bar",
                     scope=SwScope.since(m.group(3)), note=f"measured by {m.group(1)}")
        for s, m in self.find(doc, r"Do not compare live readings against the (\d+) bar figure on a unit running "
                                    r"revision ([\d.]+) or later"):
            self.add("HPU.discharge_pressure", "usage_warning",
                     f"do not compare live readings against {m.group(1)} bar on revision {m.group(2)}+", [s],
                     scope=SwScope.since(m.group(2)))
        # components
        for s in self.by_doc[doc]:
            if s.kind == "table_row":
                c = self.cells(s)
                ref = c.get("Reference")
                eid = self.idx.resolve(ref).entity_id if ref and self.idx.resolve(ref) else ref
                self.add(eid, "function", c.get("Function"), [s], extraction="table")
        # startup preconditions
        self._startup_from_sequence(doc, "4.3")
        for s, m in self.find(doc, r"WARNING: Do not start the Hydraulic Power Unit with the maintenance access panel removed"):
            self.add("HPU", "startup_precondition", {"key": "maintenance_panel_closed", "state": "CLOSED"},
                     [s], note="stated as a WARNING (rotating components exposed)")
        # controller reset
        for s, m in self.find(doc, r"Do not reset the PLC-03 controller while hydraulic pressure is above (\d+) bar"):
            self.add("PLC-03.reset", "reset_prohibited_above_bar", int(m.group(1)), [s], unit="bar",
                     note="consequence: uncommanded valve transition")
        for s, m in self.find(doc, r"Bleed pressure below (\d+) bar first, using the manual bleed procedure in Section (\d+)"):
            self.add("PLC-03.reset", "reset_precondition_action",
                     f"bleed pressure below {m.group(1)} bar first (manual bleed procedure, Section {m.group(2)})", [s])
        # alarm pointer
        for s, m in self.find(doc, r"alarm A17 \(Hydraulic Pressure Low\)"):
            self.add("A17", "alarm_name", "Hydraulic Pressure Low", [s])

    def _startup_from_sequence(self, doc, section_prefix):
        """Bullets between 'Before starting, verify:' and 'Startup sequence:' are preconditions."""
        on = False
        for s in self.by_doc[doc]:
            sec = (s.location.get("section") or "")
            if not sec.startswith(section_prefix):
                continue
            t = ws(s.text)
            if re.match(r"Before starting, verify", t):
                on = True
            elif re.match(r"Startup sequence", t):
                on = False
            elif on and s.kind == "bullet":
                key = self._precondition_key(t)
                if key:
                    self.add("HPU", "startup_precondition", key, [s])

    @staticmethod
    def _precondition_key(text: str):
        t = text.lower()
        if "iv-21" in t or "isolation valve" in t:
            return {"key": "iv21_open", "state": "OPEN"}
        if "emergency stop" in t or "e-stop" in t:
            return {"key": "estop_reset", "state": "RESET"}
        if "fluid level" in t:
            return {"key": "fluid_level_normal", "state": "NORMAL"}
        if "panel" in t:
            return {"key": "maintenance_panel_closed", "state": "CLOSED"}
        return None

    # ------------------------------------------------------------------ legacy manual (software 3.0-3.1 only)
    def legacy_manual(self):
        doc = "legacy_manual_v1"
        scope = SwScope.before("3.2", floor="3.0")
        for s, m in self.find(doc, rf"Normal HPU discharge pressure is (\d+) bar, as measured by pressure sensor {PS}"):
            self.add("HPU.discharge_pressure", "normal_pressure", int(m.group(1)), [s], unit="bar", scope=scope,
                     note=f"measured by {m.group(2)}; source is the superseded Revision 1 manual (software 3.0-3.1)")
        for s, m in self.find(doc, r"Verify pressure reaches (\d+) bar"):
            self.add("HPU.discharge_pressure", "normal_pressure", int(m.group(1)), [s], unit="bar", scope=scope,
                     note="startup step in the superseded Revision 1 manual")
        on = False
        for s in self.by_doc[doc]:
            t = ws(s.text)
            if re.match(r"Before starting, verify", t):
                on = True
            elif s.kind == "bullet" and on:
                key = self._precondition_key(t)
                if key:
                    self.add("HPU", "startup_precondition", key, [s], scope=scope,
                             note="superseded Revision 1 manual")
            elif re.match(r"WARNING", t):
                on = False

    # ------------------------------------------------------------------ maintenance manual
    def maintenance_manual(self):
        doc = "maintenance_manual"
        for s, m in self.find(doc, r"Do NOT reset the PLC-03 controller while hydraulic pressure is above (\d+) bar"):
            self.add("PLC-03.reset", "reset_prohibited_above_bar", int(m.group(1)), [s], unit="bar",
                     note="consequence: momentary uncommanded actuation of IV-21")
        for s, m in self.find(doc, r"Controller reset is only permitted when pressure, as reported by the active "
                                    r"pressure sensor .*?reads below (\d+) bar"):
            self.add("PLC-03.reset", "reset_permitted_below_bar", int(m.group(1)), [s], unit="bar",
                     note="active sensor: PS-04 before software 3.2, PS-04A from 3.2")
        for s, m in self.find(doc, r"persists for more than (\d+) seconds, execute Shutdown Procedure ([\d.]+)"):
            self.add("A17", "persistence_action",
                     {"persistence_s": int(m.group(1)), "action": f"Shutdown Procedure {m.group(2)}"}, [s],
                     note="'Do not attempt to clear a persistent A17 by silencing the alarm alone'")
        for s, m in self.find(doc, r"may clear on its own within a few seconds if it was triggered by a transient"):
            self.add("A17", "alarm_note", "may clear on its own within a few seconds if caused by a transient "
                     "pressure dip during valve transition", [s])
        for s, m in self.find(doc, r"Shutdown Procedure ([\d.]+): (.+)"):
            steps = [x.strip().rstrip(".") for x in re.split(r",\s*", m.group(2))]
            self.add(f"Shutdown Procedure {m.group(1)}", "procedure_steps", steps, [s])
        for s, m in self.find(doc, r"Do not operate the unit with the panel removed"):
            self.add("HPU", "startup_precondition", {"key": "maintenance_panel_closed", "state": "CLOSED"},
                     [s])
        for s, m in self.find(doc, r"Hydraulic fluid level is low"):
            self.add("A17", "possible_cause_checklist", "hydraulic fluid level low", [s])

    # ------------------------------------------------------------------ alarm reference
    def alarm_reference(self):
        doc = "alarm_reference"
        for s in self.by_doc[doc]:
            if s.kind == "table_row":
                c = self.cells(s)
                a = c["Alarm"]
                cond = c["Condition"]
                self.add(a, "alarm_condition", cond, [s], extraction="table")
                if m := re.search(r"(below|above) (\d+) bar", cond):
                    self.add(a, "alarm_threshold", {"op": "<" if m.group(1) == "below" else ">", "value": int(m.group(2))},
                             [s], unit="bar", extraction="table")
                causes = [ws(x) for x in s.data.get("lists", {}).get("Possible Cause(s)", [])]
                if causes:
                    self.add(a, "alarm_causes", causes, [s], extraction="table")
                pk = next((k for k in c if k.startswith("Panel")), None)
                if pk:
                    self.add(a, "alarm_panel_indication", c[pk], [s], extraction="table")
                self.add(a, "alarm_required_action", c["Required Action"], [s], extraction="table")
        for s, m in self.find(doc, r"Shutdown Procedure ([\d.]+) applies only when A17 persists beyond (\d+) seconds"):
            self.add("A17", "persistence_action", {"persistence_s": int(m.group(2)),
                                                   "action": f"Shutdown Procedure {m.group(1)}"}, [s])
        for s, m in self.find(doc, r"Alarms A01–A16 and A20–A34 .*? documented in the companion .*?, (AEG-AL-\d+)"):
            self.add("alarm_reference", "coverage_note",
                     f"only A17-A19 are in this package; A01-A16 and A20-A34 are in {m.group(1)}, not supplied", [s])

    def glossary(self):
        for s, m in self.find("terminology_glossary", r"does not yet include an entry for"):
            self.add("glossary", "coverage_note", "glossary lacks entries for 'HP unit' and 'PS-04'; "
                     "absence from the glossary does not mean they are different things", [s])

    # ------------------------------------------------------------------ training slides
    def slides(self):
        doc = "training_slides"
        for s in self.by_doc[doc]:
            if s.kind == "table_row":
                c = self.cells(s)
                key = self._precondition_key(c.get("Check", "") + " " + c.get("What good looks like", ""))
                if key:
                    self.add("HPU", "startup_precondition", key, [s], note="training slide (secondary source)")
        manual_text = " ".join(ws(x.text).lower() for d in ("operator_manual", "maintenance_manual", "alarm_reference",
                                                           "component_register", "terminology_glossary")
                               for x in self.by_doc[d])
        for s in self.by_doc[doc]:
            for term in re.findall(r"[“\"]([^”\"]{3,40})[”\"]", s.text):
                t = term.strip()
                if self.idx.resolve(t):
                    self.add(self.idx.resolve(t).entity_id, "alias_used_in_training", t, [s],
                             note="informal name used in slides; resolves to a register entity")
                elif t.lower() not in manual_text:
                    nodes = [n for n in self.segs if n.kind == "diagram_node" and ws(n.text).lower() == t.lower()]
                    self.add(t, "introduces_term", "present in training slides, absent from the manuals and register",
                             [s] + nodes, note="slides call it a Line 4/5-specific configuration detail"
                             if "Line 4/5" in s.text or any("Line 4/5" in x.text for x in self.by_doc[doc]) else None)

    # ------------------------------------------------------------------ diagrams
    def diagrams(self):
        for doc, kind in (("hydraulic_schematic", "diagram_edge"), ("wiring_diagram", "diagram_edge"),
                          ("electrical_diagram", "vision_edge")):
            for s in self.by_doc[doc]:
                if s.kind != kind:
                    continue
                if kind == "diagram_edge" and not s.data.get("resolved"):
                    continue
                a, _ = self.idx.resolve_node(s.data["a"])
                b, _ = self.idx.resolve_node(s.data["b"])
                if a == b:
                    continue
                attrs = {"to": b}
                if s.data.get("colour"):
                    attrs.update(line_colour=s.data["colour"], line_meaning=s.data.get("legend_meaning"))
                self.add(a, "connected_to", attrs, [s], extraction="geometry" if kind == "diagram_edge" else "vision",
                         note=f"{doc}; drawings are undirected")

    # ------------------------------------------------------------------ configuration export
    def config(self):
        doc = "config_export"
        leaves = {tuple(s.data["path"]): s for s in self.by_doc[doc] if s.kind == "json_leaf"}
        for path, s in leaves.items():
            self.add(f"config:{'.'.join(path)}", "config_value", s.data["value"], [s], extraction="json")

        def L(*p):
            return leaves.get(p)
        for key, state in (("valve_iv21_required_state", "iv21_open"), ("estop_required_state", "estop_reset"),
                           ("maintenance_panel_required_state", "maintenance_panel_closed"),
                           ("fluid_level_required_band", "fluid_level_normal")):
            if s := L("startup_interlocks", key):
                self.add("HPU", "startup_precondition", {"key": state, "state": s.data["value"]}, [s], extraction="json")
        if s := L("sensors", "sensor_ps04a_alarm_low_bar"):
            self.add("A17", "alarm_threshold", {"op": "<", "value": s.data["value"]}, [s], unit="bar", extraction="json")
        if s := L("sensors", "sensor_ps04a_alarm_high_bar"):
            self.add("A18", "alarm_threshold", {"op": ">", "value": s.data["value"]}, [s], unit="bar", extraction="json")
        p, r = L("alarms", "A17", "persistence_before_shutdown_seconds"), L("alarms", "A17", "shutdown_procedure_ref")
        if p and r:
            self.add("A17", "persistence_action", {"persistence_s": p.data["value"],
                                                   "action": f"Shutdown Procedure {r.data['value']}"}, [p, r], extraction="json")
        if s := L("controller_reset", "max_pressure_bar_allowed_for_reset"):
            self.add("PLC-03.reset", "reset_prohibited_above_bar", s.data["value"], [s], unit="bar",
                     note="firmware blocks reset above this value", extraction="json")
        if s := L("controller_reset", "min_pressure_bar_required_for_reset"):
            self.add("PLC-03.reset", "reset_min_pressure", None, [s], status="explicitly_not_specified",
                     note="null in the export: no minimum pressure is required for reset", extraction="json")
        # inferred vocabulary mapping: config key -> manual concept
        t, ap = L("sensors", "sensor_ps04a_threshold_bar"), L("revision_applicability", "sensor_ps04a_threshold_bar",
                                                                  "applies_from_firmware")
        if t:
            ev = [t] + ([ap] if ap else []) + [x for x, _ in self.find("operator_manual", r"Normal HPU discharge pressure is 200 bar")]
            self.add("config:sensors.sensor_ps04a_threshold_bar", "config_maps_to",
                     {"concept": "normal HPU discharge pressure (operating pressure setpoint)", "entity": "PS-04A"},
                     ev, status="inferred",
                     note="no document states this mapping. Basis: key names ps04a; value 200 equals the manual's normal "
                          "pressure for 3.2+; applies_from_firmware 3.2 equals the manual's 'software revision 3.2 and later'. "
                          "Do not map sensor_ps40_* keys (config note).")
            self.add("HPU.discharge_pressure", "normal_pressure", t.data["value"], [t], unit="bar",
                     scope=SwScope.since(ap.data["value"]) if ap else SwScope.unknown(), status="inferred",
                     note="via config_maps_to (inferred)", extraction="json")
        lv, lb = L("revision_applicability", "sensor_ps04_legacy_threshold_bar", "value"), \
            L("revision_applicability", "sensor_ps04_legacy_threshold_bar", "applies_before_firmware")
        if lv and lb:
            self.add("HPU.discharge_pressure", "normal_pressure", lv.data["value"], [lv, lb], unit="bar",
                     scope=SwScope.before(lb.data["value"]), status="inferred",
                     note="config's own 'legacy threshold' entry; concept link inferred", extraction="json")
        z = L("sensors", "sensor_ps40_zone")
        if z:
            self.add("PS-40", "config_value", {"zone": z.data["value"]}, [z] + ([L("sensors", "sensor_ps40_note")] if L("sensors", "sensor_ps40_note") else []),
                     note="config note: unrelated to HPU discharge circuit; do not map to sensor_ps04a_* keys",
                     extraction="json")

    # ------------------------------------------------------------------ screenshots + scanned record (vision readings)
    def screens_and_scan(self):
        obs = SwScope(True, (3, 2), (3, 3))     # screens show 'SW REV 3.2'
        # diagnostics
        diag = {ws(s.data["label"]).rstrip(":"): s for s in self.by_doc["screen_diagnostics"]
                if s.kind == "vision_field" and s.data.get("label")}
        tag = diag.get("Tag")
        ent = None
        if tag:
            d = self.idx.resolve(tag.data["value"])
            ent = d.entity_id if d else None
            self.add("screen:diagnostics", "displays_tag", tag.data["value"], [tag], status="observation", scope=obs,
                     note=(f"resolves to {ent} ({d.relation}: {d.reason})" if d else "does not resolve to a register entity")
                     + "; screen note: shows the tag as printed on the physical unit label")
        for label, pred, unit in (("Raw Reading", "observed_raw_signal", None), ("Scaled Value", "observed_pressure", "bar"),
                                  ("Calibration Status", "observed_calibration_status", None),
                                  ("Last Calibrated", "observed_last_calibrated", None),
                                  ("Firmware Rev.", "observed_firmware_rev", None)):
            if label in diag and ent:
                self.add(ent, pred, diag[label].data["value"], [diag[label], tag], unit=unit, status="observation", scope=obs)
        # home
        for s in self.by_doc["screen_home"]:
            if s.kind == "vision_field" and re.search(r"HPU DISCHARGE PRESSURE", s.text, re.I):
                self.add("HPU.discharge_pressure", "observed_pressure", s.data["value"], [s], status="observation", scope=obs,
                         note="home screen, one unit at one moment")
            elif s.kind == "vision_field" and (k := self._precondition_key(s.text)):
                self.add("HPU", "observed_interlock_state", {"key": k["key"], "state": s.data["value"]}, [s],
                         status="observation", scope=obs)
        # alarms screen
        for s in self.by_doc["screen_alarms"]:
            if s.kind == "vision_table_row":
                c = {ws(k).strip("# ").upper() or "N": ws(str(v)) for k, v in s.data.get("cells", {}).items()}
                if "TAG" in c:
                    self.add(c["TAG"], "observed_alarm_state", {"state": c.get("STATE"), "time": c.get("TIME"),
                                                                "description": c.get("DESCRIPTION")}, [s],
                             status="observation", scope=obs)
        for s, m in self.find("screen_alarms", r"Alarm (A\d+) active for (\d+):(\d+):(\d+) .*? Shutdown Procedure ([\d.]+) "
                                                  r"threshold: (\d+):(\d+):(\d+)"):
            act = int(m.group(2)) * 3600 + int(m.group(3)) * 60 + int(m.group(4))
            thr = int(m.group(6)) * 3600 + int(m.group(7)) * 60 + int(m.group(8))
            self.add(m.group(1), "observed_persistence", {"active_s": act, "threshold_s": thr, "exceeds_threshold": act > thr,
                                                          "procedure": m.group(5)}, [s], status="observation", scope=obs)
        # scanned calibration record
        scan = self.by_doc["calibration_scan"]
        if scan:
            fields = {ws(s.data["label"]).rstrip(":"): ws(s.data["value"]) for s in scan
                      if s.kind == "vision_field" and s.data.get("label") and s.data.get("value")}
            pts = [s for s in scan if s.kind == "vision_table_row"]
            sensor = self.idx.resolve(fields.get("Sensor Tag", ""))
            if sensor and pts:
                rows = [{k: ws(str(v)) for k, v in p.data["cells"].items()} for p in pts]
                ev = pts + [s for s in scan if s.kind == "vision_field" and s.data.get("label", "").startswith(
                    ("Sensor Tag", "Calibration Date", "Technician"))]
                self.add(sensor.entity_id, "calibration_record",
                         {"date": fields.get("Calibration Date"), "technician": fields.get("Technician"), "points": rows},
                         ev, status="observation",
                         note="scanned copy from a field service binder, 'uncontrolled copy'; signature and date lines blank")
            for s, m in self.find("calibration_scan", r"Span reference target is (\d+) bar, consistent with the software "
                                                       r"revision ([\d.]+) operating pressure setpoint"):
                self.add("PS-04A", "calibration_span_reference", int(m.group(1)), [s], unit="bar", scope=SwScope.since(m.group(2)))
            for s, m in self.find("calibration_scan", rf"Prior sensor \({PS}\) span reference target was (\d+) bar .*?for historical "
                                                       r"comparison only"):
                self.add(m.group(1), "calibration_span_reference", int(m.group(2)), [s], unit="bar",
                         scope=SwScope.before("3.2"), note="'for historical comparison only. Do not use the 180 bar figure "
                         "to evaluate PS-04A'")
            for s, m in self.find("calibration_scan", rf"No calibration interval is specified for {PS}"):
                self.add(m.group(1), "calibration_interval", None, [s], status="explicitly_not_specified",
                         note="the record states recalibration frequency should be confirmed against the maintenance "
                              "schedule, which is not in the binder")
        # field notes (low trust)
        for s, m in self.find("site_survey_notes", r"read about (\d+) bar during a normal run, not (\d+) like the manual"):
            self.add("HPU.discharge_pressure", "observed_pressure", int(m.group(1)), [s], unit="bar",
                     status="low_trust_observation",
                     note="local panel gauge, admitted possibly off, no calibrated reference; unreviewed; undated; "
                          "software revision of the unit not recorded")
