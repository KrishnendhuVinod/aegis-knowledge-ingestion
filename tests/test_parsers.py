"""Parser tests: each one pins a property that a later answer depends on."""
import json
from pathlib import Path

import pytest

from aegis_kb.llm import Gemini
from aegis_kb.parsers import PARSERS
from aegis_kb.parsers._common import Ctx
from aegis_kb.parsers.image_parser import ocr_available
from aegis_kb.sources import BY_ID, REGISTRY

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "raw" / "aegis-dataset"
pytestmark = pytest.mark.skipif(not DATA.exists(), reason="dataset not in data/raw/")

_cache: dict = {}
needs_ocr = pytest.mark.skipif(not ocr_available(), reason="tesseract not installed (OCR is optional)")
IMAGE_PARSERS = {"pdf_scan", "image_screenshot", "image_diagram"}


def segs(doc_id, gemini=None):
    key = (doc_id, id(gemini))
    if key not in _cache:
        info = BY_ID[doc_id]
        _cache[key] = PARSERS[info.parser](info, DATA / info.path, Ctx(DATA, gemini))
    return _cache[key]


def find(doc_id, needle, **kw):
    return [s for s in segs(doc_id, kw.get("gemini")) if needle in s.text]


# ---------- registry ----------
def test_registry_covers_every_file_exactly():
    on_disk = {p.relative_to(DATA).as_posix() for p in DATA.rglob("*") if p.is_file()}
    assert on_disk == {s.path for s in REGISTRY}
    assert len(REGISTRY) == 20


def test_every_file_parses_to_something():
    for info in REGISTRY:
        if info.parser in IMAGE_PARSERS and not ocr_available():
            continue            # image files need OCR or a model reading; covered by the vision test
        assert len(segs(info.doc_id)) > 0, info.doc_id


# ---------- born-digital PDF ----------
def test_startup_preconditions_are_bullets_in_section_4_3():
    got = [s for s in segs("operator_manual") if s.kind == "bullet" and s.location["section"].startswith("4.3")]
    texts = " ".join(s.text for s in got)
    assert "IV-21 is OPEN" in texts and "emergency stop circuit is RESET" in texts and "fluid level" in texts


def test_paragraph_continues_across_page_break():
    (s,) = find("operator_manual", "Normal HPU discharge pressure is 200 bar")
    assert "180 bar figure on a unit running revision 3.2" in s.text
    assert s.location["pages"] == [1, 2]


def test_warning_and_bold_emphasis_captured():
    assert any(s.data.get("admonition") == "warning" for s in find("operator_manual", "maintenance access panel"))
    (s,) = find("operator_manual", "Do not reset the PLC-03")
    assert "above 50 bar" in s.data["bold_text"]


def test_alarm_table_rows_and_cause_list():
    (row,) = [s for s in segs("alarm_reference") if s.kind == "table_row" and s.data["cells"]["Alarm"] == "A17"]
    assert "below 150 bar" in row.data["cells"]["Condition"]
    assert len(row.data["lists"]["Possible Cause(s)"]) == 3
    assert any(s.kind == "footnote" and "Procedure 4.7" in s.text for s in segs("alarm_reference"))


def test_symbol_font_arrow_repaired_and_logged():
    (s,) = [s for s in segs("ecn_1042") if s.kind == "kv" and s.data["key"] == "Title"]
    assert "PS-04 → PS-04A" in s.text and "symbol_font_arrow" in s.data["repairs"]


def test_ecn_header_fields_are_kv():
    kv = {s.data["key"]: s.data["value"] for s in segs("ecn_1042") if s.kind == "kv"}
    assert kv["Effective"] == "Software Revision 3.2"


# ---------- tabular / structured ----------
def test_register_ids_kept_as_printed():
    ids = {s.data["cells"]["Component ID (as printed)"] for s in segs("component_register")}
    assert {"PS-04", "PS-04A", "PS-40", "IV-21", "HPU"} <= ids
    (ps40,) = [s for s in segs("component_register") if s.data["cells"]["Component ID (as printed)"] == "PS-40"]
    assert "NOT related" in ps40.data["cells"]["Notes"]


def test_revision_history_keeps_planned_row_marked():
    r33 = [s for s in segs("revision_history") if s.data["cells"]["Software Revision"] == "3.3"][0]
    assert "planned" in r33.data["cells"]["Release Date"]


def test_json_nulls_preserved_and_flagged():
    (s,) = [s for s in segs("config_export") if s.data["key"] == "min_pressure_bar_required_for_reset"]
    assert s.data["is_null"] is True and s.data["value"] is None
    assert s.location["json_path"] == "$.controller_reset.min_pressure_bar_required_for_reset"


# ---------- other document formats ----------
def test_html_banner_marks_document_superseded():
    banner = [s for s in segs("legacy_manual_v1") if s.data.get("role") == "document_status_banner"]
    assert banner and "supersedes" in banner[0].text
    assert any("180 bar" in s.text for s in segs("legacy_manual_v1"))


def test_pptx_slides_and_table():
    assert any("Auxiliary Reservoir" in s.text for s in segs("training_slides"))
    assert len([s for s in segs("training_slides") if s.kind == "table_row"]) == 4


def test_docx_field_notes_content_and_properties():
    assert find("site_survey_notes", "175 bar")
    assert any(s.kind == "metadata" and s.data.get("role") == "file_properties" for s in segs("site_survey_notes"))


# ---------- diagrams (deterministic topology) ----------
def _edges(doc):
    return {(frozenset({s.data["a"], s.data["b"]}), s.data["colour"]) for s in segs(doc) if s.kind == "diagram_edge"}


def test_hydraulic_schematic_topology():
    e = _edges("hydraulic_schematic")
    plc = "PLC-03 (HCS Controller)"
    assert (frozenset({plc, "PS-04A"}), "purple") in e
    assert (frozenset({plc, "IV-21"}), "purple") in e
    # recorded faithfully even though odd: a grey (fluid-path) line touching the controller
    assert (frozenset({plc, "Hydraulic Power Unit (HPU)"}), "grey") in e
    assert all(s.data["resolved"] for s in segs("hydraulic_schematic") if s.kind == "diagram_edge")


def test_legend_attached_to_edges():
    purple = [s for s in segs("hydraulic_schematic") if s.kind == "diagram_edge" and s.data["colour"] == "purple"]
    assert purple and all("control/signal" in s.data["legend_meaning"] for s in purple)


def test_wiring_diagram_uses_wiring_designations_only():
    nodes = {s.data["label"] for s in segs("wiring_diagram") if s.kind == "diagram_node"}
    assert not any("PS-04A" == n for n in nodes)
    assert any("PRESSURE XDCR" in n for n in nodes)
    assert any("PS-04A" in s.text for s in segs("wiring_diagram") if s.kind == "paragraph")


# ---------- images: OCR baseline + vision layer ----------
class FakeGemini:
    model = "fake-model"
    can_call_api = True
    stats = {}

    def generate_json(self, prompt, image=None, mime="image/png"):
        return {"title": "DIAG", "fields": [{"label": "Tag", "value": "P.S.04-A"}], "tables": [],
                "nodes": [], "edges": [], "text_blocks": [], "uncertain": ["firmware"]}


@needs_ocr
def test_images_without_model_are_ocr_only():
    info = BY_ID["screen_diagnostics"]
    out = PARSERS[info.parser](info, DATA / info.path, Ctx(DATA, None))
    assert out and {s.method for s in out} == {"ocr"}


def test_vision_layer_keeps_identifier_verbatim_and_flags_uncertainty():
    info = BY_ID["screen_diagnostics"]
    out = PARSERS[info.parser](info, DATA / info.path, Ctx(DATA, FakeGemini()))
    v = [s for s in out if s.method == "vision_llm"]
    assert any(s.kind == "vision_field" and s.data["value"] == "P.S.04-A" for s in v)
    assert any(s.data.get("flag") == "uncertain" and s.confidence < 0.5 for s in v)
    if ocr_available():
        assert any(s.method == "ocr" for s in out)       # both readings are retained, never merged


@needs_ocr
def test_scan_ocr_reads_the_calibration_target():
    text = " ".join(s.text for s in segs("calibration_scan"))
    assert "CALIBRATION" in text.upper()


# ---------- LLM wrapper ----------
def test_cache_hit_needs_no_key(tmp_path):
    g = Gemini(tmp_path, model="m", api_key=None)
    k = g._key("p", b"img")
    (tmp_path / f"{k}.json").write_text(json.dumps({"response": {"x": 1}}))
    assert g.generate_json("p", image=b"img") == {"x": 1}
    assert g.stats["cache_hits"] == 1


def test_no_key_no_cache_returns_none_instead_of_crashing(tmp_path):
    g = Gemini(tmp_path, model="m", api_key=None)
    g.api_key = None
    assert g.generate_json("p", image=b"img") is None
    assert g.stats["skipped_no_key"] == 1
