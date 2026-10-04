"""Knowledge-base tests: entities/aliases, claims, scopes, conflicts, gaps. Image documents come from the Gemini-reading fixture."""
import json
from pathlib import Path

import pytest

from aegis_kb.build_kb import build
from aegis_kb.entities import norm_id
from aegis_kb.parsers import PARSERS
from aegis_kb.parsers._common import Ctx
from aegis_kb.schema import Segment
from aegis_kb.sources import REGISTRY
from aegis_kb.versions import SwScope

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "raw" / "aegis-dataset"
IMAGE_PARSERS = {"pdf_scan", "image_screenshot", "image_diagram"}
pytestmark = pytest.mark.skipif(not DATA.exists(), reason="dataset not in data/raw/")

_kb = {}


def segments():
    segs = []
    for info in REGISTRY:
        if info.parser not in IMAGE_PARSERS:
            segs += PARSERS[info.parser](info, DATA / info.path, Ctx(DATA, None))
    for line in (ROOT / "tests" / "fixtures" / "vision_segments.jsonl").read_text(encoding="utf-8").splitlines():
        segs.append(Segment(**json.loads(line)))
    return segs


@pytest.fixture(scope="module")
def kb():
    if "kb" not in _kb:
        segs = segments()
        _kb["segs"], _kb["kb"] = {s.segment_id: s for s in segs}, build(segs)
    return _kb["kb"]


def claims(kb, predicate=None, subject=None, status=None):
    return [c for c in kb.claims if (predicate is None or c.predicate == predicate)
            and (subject is None or c.subject == subject) and (status is None or c.status == status)]


def decision(kb, surface, relation, decision_="accepted", entity=None):
    return [d for d in kb.decisions if d.surface == surface and d.relation == relation and d.decision == decision_
            and (entity is None or d.entity_id == entity)]


# ---------------- scopes ----------------
def test_scope_algebra():
    ge, lt = SwScope.since("3.2"), SwScope.before("3.2")
    assert ge.relation(lt) == "disjoint" and ge.relation(SwScope.all()) == "overlap"
    assert ge.relation(SwScope.unknown()) == "unknown"
    assert ge.contains("3.2.1") and not lt.contains("3.2") and lt.contains("3.1")


# ---------------- entities / aliases ----------------
def test_normalisation_keeps_ps04_and_ps04a_apart():
    assert norm_id("P.S.04-A") == norm_id("PS-04A") == "PS04A"
    assert norm_id("PS-04") == "PS04" != norm_id("PS-04A")


def test_aliases_resolve(kb):
    assert decision(kb, "HP unit", "same_as", entity="HPU")
    assert decision(kb, "Hydraulic Power Pack", "same_as", entity="HPU")
    assert decision(kb, "hydraulic pack", "same_as", entity="HPU")
    h = {e.id: e for e in kb.entities}["HPU"]
    assert {"Hydraulic Unit", "HP unit", "Hydraulic Power Pack", "hydraulic pack"} <= set(h.aliases)


def test_diagnostics_tag_maps_to_ps04a_not_ps04(kb):
    (d,) = decision(kb, "P.S.04-A", "variant_of")
    assert d.entity_id == "PS-04A" and "punctuation" in d.reason and d.evidence


def test_ps04_ps04a_superseded_not_same(kb):
    assert decision(kb, "PS-04", "superseded_by", entity="PS-04A")
    (rej,) = decision(kb, "PS-04", "same_as", "rejected", entity="PS-04A")
    assert "form-fit-function" in rej.reason


def test_ps04_vs_ps40_distinct(kb):
    assert decision(kb, "PS-40", "distinct_from", entity="PS-04")
    assert decision(kb, "PS-40", "same_as", "rejected", entity="PS-04")


def test_look_alike_drawing_parts_not_merged(kb):
    for lab in ("PLC-03 I/O RACK", "PLC-03 24VDC POWER SUPPLY", "IV-21 VALVE DRIVER"):
        assert decision(kb, lab, "related_not_same", "rejected"), lab
    ents = {e.id: e for e in kb.entities}
    assert ents["PLC-03 I/O RACK"].registered is False and ents["PLC-03"].registered is True


def test_wiring_designation_corresponds_not_equal(kb):
    assert decision(kb, "PRESSURE XDCR (field device)", "corresponds_to", entity="PS-04A")
    assert {e.id: e for e in kb.entities}["TB-7"].type == "component"       # terminal block stays its own entity


def test_no_alias_collisions(kb):
    assert kb.meta["alias_collisions"] == []


# ---------------- claims ----------------
def test_every_claim_has_real_evidence(kb):
    ids = _kb["segs"]
    for c in kb.claims:
        assert c.evidence and all(e in ids for e in c.evidence), c.id


def test_pressure_claims_are_version_scoped_and_corroborated(kb):
    p200 = [c for c in claims(kb, "normal_pressure", status="asserted") if c.value == 200]
    p180 = [c for c in claims(kb, "normal_pressure", status="asserted") if c.value == 180]
    assert p200 and all(SwScope.from_dict(c.applies_when).min == (3, 2) for c in p200)
    assert {"operator_manual", "ecn_1042", "revision_history"} <= set(p200[0].docs)
    assert any(SwScope.from_dict(c.applies_when).max == (3, 2) for c in p180)
    assert any("legacy_manual_v1" in c.docs and SwScope.from_dict(c.applies_when).min == (3, 0) for c in p180)


def test_field_note_is_low_trust_and_separate(kb):
    (c,) = claims(kb, "observed_pressure", status="low_trust_observation")
    assert c.value == 175 and c.trust_rank == 5 and c.docs == ["site_survey_notes"]
    assert not any(c.value == 175 for c in claims(kb, "normal_pressure"))


def test_ecn_introduced_the_sensor_change(kb):
    (c,) = claims(kb, "introduced_by")
    assert c.value == "ECN-1042" and "ecn_1042" in c.docs
    sr = claims(kb, "sensor_replacement", subject="PS-04")[0]
    assert sr.value == {"replaced_by": "PS-04A"} and SwScope.from_dict(sr.applies_when).min == (3, 2)


def test_revision_3_2_facts(kb):
    assert any(c.value == "2025-09-30" for c in claims(kb, "release_date", "software:3.2"))
    planned = claims(kb, "release_date", "software:3.3")[0]
    assert planned.status == "planned"


def test_register_location_of_iv21(kb):
    assert claims(kb, "location", "IV-21")[0].value == "Hydraulic Module"


def test_alarm_a17_facts(kb):
    assert claims(kb, "alarm_threshold", "A17")[0].value == {"op": "<", "value": 150}
    causes = claims(kb, "alarm_causes", "A17")[0].value
    assert causes == ["IV-21 closed or partially closed", "Low hydraulic fluid", "Pressure sensor signal invalid"]
    pa = claims(kb, "persistence_action", "A17")[0]
    assert pa.value == {"persistence_s": 10, "action": "Shutdown Procedure 4.7"}
    assert {"maintenance_manual", "alarm_reference", "config_export"} <= set(pa.docs)
    steps = claims(kb, "procedure_steps", "Shutdown Procedure 4.7")[0].value
    assert steps[0] == "close IV-21" and "set POWER selector to OFF" in steps


def test_alarm_screen_shows_threshold_exceeded(kb):
    (c,) = claims(kb, "observed_persistence")
    assert c.value["active_s"] == 14 and c.value["threshold_s"] == 10 and c.value["exceeds_threshold"] is True


def test_startup_preconditions_merge_across_sources(kb):
    pre = {json.dumps(c.value, sort_keys=True): c for c in claims(kb, "startup_precondition")
           if SwScope.from_dict(c.applies_when).max is None}
    assert len(pre) == 4
    iv = pre[json.dumps({"key": "iv21_open", "state": "OPEN"}, sort_keys=True)]
    assert {"operator_manual", "config_export", "training_slides"} <= set(iv.docs)


def test_reset_rules(kb):
    r = claims(kb, "reset_prohibited_above_bar", "PLC-03.reset")[0]
    assert r.value == 50 and {"operator_manual", "maintenance_manual", "config_export"} <= set(r.docs)
    assert claims(kb, "reset_min_pressure")[0].status == "explicitly_not_specified"


def test_config_key_mapping_is_flagged_inferred(kb):
    (m,) = claims(kb, "config_maps_to")
    assert m.status == "inferred" and "no document states this mapping" in m.note
    assert m.subject == "config:sensors.sensor_ps04a_threshold_bar"


def test_hydraulic_schematic_connections(kb):
    edges = {(c.subject, c.value["to"], c.value["line_colour"]) for c in claims(kb, "connected_to")
             if "hydraulic_schematic" in c.docs}
    assert ("PLC-03", "PS-04A", "purple") in edges or ("PS-04A", "PLC-03", "purple") in edges
    assert ("PLC-03", "IV-21", "purple") in edges or ("IV-21", "PLC-03", "purple") in edges


def test_training_slides_introduce_auxiliary_reservoir_only(kb):
    intro = claims(kb, "introduces_term")
    assert [c.subject for c in intro] == ["Auxiliary Reservoir"]
    assert {"training_slides", "hydraulic_schematic"} <= set(intro[0].docs)


def test_calibration_record_and_unspecified_interval(kb):
    rec = claims(kb, "calibration_record", "PS-04A")[0]
    assert rec.value["date"] == "2026-01-09" and rec.value["points"][2]["Reference"] == "200 bar"
    ci = claims(kb, "calibration_interval", "PS-04A")[0]
    assert ci.status == "explicitly_not_specified" and ci.value is None


def test_diagnostics_screen_observations(kb):
    assert claims(kb, "displays_tag")[0].value == "P.S.04-A"
    assert claims(kb, "observed_firmware_rev", "PS-04A")[0].value == "3.2.1"


# ---------------- conflicts ----------------
def kinds(kb):
    return {(c.kind, c.predicate) for c in kb.conflicts}


def test_180_vs_200_is_coexistence_not_conflict(kb):
    assert ("scoped_coexistence", "normal_pressure") in kinds(kb)
    assert not any(c.kind == "conflict" for c in kb.conflicts)


def test_expected_ambiguities_flagged(kb):
    k = kinds(kb)
    assert ("observation_disagrees", "observed_pressure") in k
    assert ("ambiguity", "reset_boundary") in k
    assert ("ambiguity", "setpoint_applicability") in k
    grey = [c for c in kb.conflicts if c.predicate == "connected_to"]
    assert grey and "controller" in grey[0].description


# ---------------- gaps ----------------
def test_gaps_are_real_absences_with_rejected_near_misses(kb):
    g = {x.topic.split()[0] + x.id: x for x in kb.gaps}
    assert all(not x.hits for x in kb.gaps)
    temp = next(x for x in kb.gaps if "temperature" in x.topic)
    assert any(m.startswith("hydraulic_fluid_sds") for m in temp.near_misses)      # fluid temps seen, rejected
    approver = next(x for x in kb.gaps if "ECN-1058" in x.topic)
    assert any(m.startswith("ecn_1058") for m in approver.near_misses)
    volt = next(x for x in kb.gaps if "400V" in x.topic)
    assert len(volt.related_claims) == 2                                              # Q1 480V and T1 480:120V
