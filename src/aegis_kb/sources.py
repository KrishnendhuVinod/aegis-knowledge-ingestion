"""Source registry: what each file IS and how far to trust it.

This is hand-curated ON PURPOSE. Trust is a judgement about document *role*
(controlled manual vs. unreviewed notebook page), and the package itself tells us
the roles (banners, document headers, folder names). Inferring it with a model
would add noise to the one place we want an auditable, explainable decision.

trust_rank: 1 = most authoritative ... 5 = ignore for answers.
This rank is only a TIE-BREAKER hint. Conflicts are never resolved by rank alone;
they are stored explicitly (see conflicts.py) with both sides and the applicability scope.

sw_scope: software-revision range the document claims to describe. This is what
lets us keep "180 bar (<3.2)" and "200 bar (>=3.2)" side by side without conflict.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class SourceInfo:
    doc_id: str
    path: str                  # relative to the dataset root
    parser: str                # key into parsers.PARSERS
    trust_tier: str
    trust_rank: int
    role: str                  # what the doc is authoritative FOR
    sw_scope: str | None       # e.g. ">=3.2", "3.0-3.1", None = not version-scoped
    rationale: str             # why this tier (goes in the report)
    options: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _s(*a, **k) -> SourceInfo:
    return SourceInfo(*a, **k)


REGISTRY: list[SourceInfo] = [
    _s("operator_manual", "manuals/operator_manual.pdf", "pdf_text", "official_current", 1,
       "operating procedures, normal operating values, startup preconditions", ">=3.2",
       "Controlled manual AEG-OM-700 Rev 4; header states it applies to software revision 3.2 and later."),
    _s("maintenance_manual", "manuals/maintenance_manual.pdf", "pdf_text", "official_current", 1,
       "alarm response, controller reset conditions, troubleshooting", None,
       "Controlled manual AEG-MM-700 Rev 3; covers both sensor generations explicitly."),
    _s("legacy_manual_v1", "manuals/legacy_manual_v1.html", "html", "superseded", 4,
       "historical values for software 3.0-3.1 only", "3.0-3.1",
       "Own banner says Revision 1, superseded, applies to 3.0/3.1 only. Valid as history, never as current."),
    _s("ecn_1042", "engineering_bulletins/ECN-1042.pdf", "pdf_text", "change_notice", 1,
       "WHAT changed and WHEN (PS-04 -> PS-04A, 180 -> 200 bar, effective sw 3.2)", None,
       "Engineering change notices are the controlled record of change; they outrank manuals on change history."),
    _s("ecn_1058", "engineering_bulletins/ECN-1058.pdf", "pdf_text", "change_notice", 1,
       "alarm A17 documentation correction (references ECN-1042)", None,
       "Controlled change notice. Documentation-only correction; does NOT change thresholds or setpoints."),
    _s("alarm_reference", "reference/alarm_reference.pdf", "pdf_text", "official_current", 1,
       "alarm conditions, causes, required actions", None,
       "Controlled reference AEG-AL-700 Rev 5 (incorporates ECN-1058). Covers A17-A19 only; A01-A16, A20-A34 are in a document NOT supplied."),
    _s("component_register", "reference/component_register.xlsx", "xlsx", "official_current", 1,
       "component identity: IDs, aliases, locations, status", None,
       "Authority for entity resolution. Note: IDs 'as printed' are inconsistent; aliases column is the key evidence."),
    _s("terminology_glossary", "reference/terminology_glossary.docx", "docx", "official_current", 2,
       "official terms (explicitly INCOMPLETE)", None,
       "Official but states it lags ECNs and omits terms like 'HP unit' and 'PS-04'. Absence from it is NOT evidence of difference."),
    _s("revision_history", "reference/revision_history.xlsx", "xlsx", "official_current", 1,
       "software revision timeline, effective dates", None,
       "Controlled timeline. Contains a 'planned' row (3.3) that must not be treated as in effect."),
    _s("hydraulic_schematic", "diagrams/system_diagram_hydraulic.pdf", "pdf_diagram", "drawing", 2,
       "hydraulic/signal topology (who connects to whom)", None,
       "Vector drawing: topology is recoverable exactly from geometry, but line colour semantics come from its legend."),
    _s("wiring_diagram", "diagrams/wiring_diagram.pdf", "pdf_diagram", "drawing", 2,
       "wiring topology; uses wiring designations (J-14, TB-7), not component-register IDs", None,
       "Vector drawing. Identity of 'PRESSURE XDCR' = PS-04A is stated only in its own note and the register note on TB-7."),
    _s("electrical_diagram", "diagrams/system_diagram_electrical.png", "image_diagram", "drawing", 2,
       "power distribution / interlock wiring", None,
       "Raster only; labels partly low-contrast/rotated, so read twice (OCR + vision) and cross-check.",
       options={"role": "diagram"}),
    _s("screen_home", "screenshots/screen_01_home.png", "image_screenshot", "ui_capture", 3,
       "observed values on ONE unit running sw 3.2 (an instance, not a specification)", "3.2",
       "HMI screenshot: real observation, but of a single unit at a single moment.",
       options={"role": "screenshot"}),
    _s("screen_alarms", "screenshots/screen_02_alarms.png", "image_screenshot", "ui_capture", 3,
       "observed alarm list on ONE unit", "3.2",
       "HMI screenshot; also shows the 10 s Shutdown Procedure 4.7 threshold.",
       options={"role": "screenshot"}),
    _s("screen_diagnostics", "screenshots/screen_03_diagnostics.png", "image_screenshot", "ui_capture", 3,
       "observed sensor tag/label on ONE unit", "3.2",
       "HMI screenshot; tag is shown 'as printed on the physical unit label' (an alias, not a register ID).",
       options={"role": "screenshot"}),
    _s("calibration_scan", "scans/scanned_appendix_calibration.pdf", "pdf_scan", "controlled_record_scan", 2,
       "one calibration event for PS-04A; states what is NOT specified", None,
       "Scanned field-binder copy ('uncontrolled copy'); content official in nature, but read with reduced fidelity.",
       options={"role": "scan"}),
    _s("config_export", "configuration/configuration_export.json", "json", "system_export", 2,
       "actual configured values on one controller (PLC-03, fw 3.2.1)", ">=3.2",
       "Machine-generated, structured and exact, but keys use their own vocabulary and describe one controller."),
    _s("site_survey_notes", "low_trust/site_survey_notes.docx", "docx", "low_trust", 5,
       "anecdotal field observation only", None,
       "Typed from a notebook, unreviewed, undated, no software revision recorded, self-admittedly uncalibrated gauge."),
    _s("hydraulic_fluid_sds", "noise/safety_data_sheet_hydraulic_fluid.pdf", "pdf_text", "noise", 5,
       "fluid safety only; irrelevant to the question set", None,
       "Real-looking but unrelated. Ingested (so filtering is visible and testable), then excluded from retrieval by tier."),
    _s("training_slides", "extra/training_slide_excerpt.pptx", "pptx", "secondary", 3,
       "restates operator manual for new operators; adds Line 4/5 details", None,
       "Derived/training material. Useful for aliases and for facts the manuals omit, but never authoritative over them."),
]

BY_ID = {s.doc_id: s for s in REGISTRY}
