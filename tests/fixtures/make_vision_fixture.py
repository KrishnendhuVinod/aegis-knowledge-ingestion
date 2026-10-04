"""Rebuilds vision_segments.jsonl: the five image documents exactly as Gemini (gemini-3.1-flash-lite) read them,
transcribed from the student's real ingest run. Lets the KB tests run without an API key or image OCR.
Run once:  python tests/fixtures/make_vision_fixture.py
"""
import json
from pathlib import Path

OUT = Path(__file__).parent / "vision_segments.jsonl"
rows, counters = [], {}


def add(doc, kind, text, data=None, loc=None):
    counters[doc] = counters.get(doc, 0) + 1
    rows.append({"segment_id": f"{doc}::{counters[doc]:03d}", "doc_id": doc, "kind": kind, "text": text,
                 "location": loc or {"image": doc, "reader": "gemini-3.1-flash-lite"}, "method": "vision_llm",
                 "confidence": 0.8, "data": data or {}})


def title(doc, t): add(doc, "vision_text", t, {"role": "title"})
def field(doc, label, value): add(doc, "vision_field", f"{label}: {value}", {"label": label, "value": value})
def text(doc, t): add(doc, "vision_text", t, {"role": "text_block"})
def node(doc, t): add(doc, "vision_text", t, {"role": "node"})
def edge(doc, a, b): add(doc, "vision_edge", f"{a} — {b}", {"a": a, "b": b})
def row(doc, cols, vals):
    cells = dict(zip(cols, vals))
    add(doc, "vision_table_row", " | ".join(f"{k}: {v}" for k, v in cells.items()), {"header": cols, "cells": cells})


d = "electrical_diagram"
title(d, "Aegis Series-7 HCS — Electrical Schematic (AEG-DWG-E02)")
for n in ["MAIN DISCONNECT Q1", "CONTROL XFMR T1 480:120V", "PLC-03 24VDC POWER SUPPLY", "PLC-03 I/O RACK",
          "E-STOP SAFETY RELAY KA1", "SENSOR LOOP POWER 24VDC", "IV-21 VALVE DRIVER"]:
    node(d, n)
for a, b in [("MAIN DISCONNECT Q1", "CONTROL XFMR T1 480:120V"), ("CONTROL XFMR T1 480:120V", "PLC-03 24VDC POWER SUPPLY"),
             ("CONTROL XFMR T1 480:120V", "PLC-03 I/O RACK"), ("PLC-03 24VDC POWER SUPPLY", "PLC-03 I/O RACK"),
             ("PLC-03 24VDC POWER SUPPLY", "SENSOR LOOP POWER 24VDC"), ("PLC-03 I/O RACK", "E-STOP SAFETY RELAY KA1"),
             ("PLC-03 I/O RACK", "IV-21 VALVE DRIVER")]:
    edge(d, a, b)
text(d, "Power distribution and interlock wiring")
text(d, "feeds pressure transducer loop (see wiring diagram AEG-DWG-W03)")
text(d, "TB-7 REF: PRESSURE XDCR LOOP")

d = "screen_home"
title(d, "AEGIS SERIES-7 HCS — HOME")
for l, v in [("HPU DISCHARGE PRESSURE", "200 bar"), ("STATUS", "RUNNING — NORMAL"), ("IV-21 (Isolation Valve)", "OPEN"),
             ("Emergency Stop", "RESET"), ("Maintenance Panel", "CLOSED"), ("Hydraulic Fluid Level", "NORMAL")]:
    field(d, l, v)
cols = ["ACTIVE COMPONENT SUMMARY", "col1", "col2"]
row(d, cols, ["HP unit", "PLC-03 controlled", "RUNNING"])
row(d, cols, ["PS-04A", "discharge pressure sensor", "OK"])
row(d, cols, ["IV-21", "isolation valve", "OPEN"])
text(d, "SW REV 3.2")
text(d, "Touch ALARMS for active/historical alarm list. Touch DIAGNOSTICS for sensor-level detail.")

d = "screen_alarms"
title(d, "AEGIS SERIES-7 HCS — ALARM LIST")
cols = ["#", "TAG", "DESCRIPTION", "STATE", "TIME"]
row(d, cols, ["1", "A17", "Hydraulic Pressure Low", "CLEARED", "08:14:02"])
row(d, cols, ["2", "A19", "Pressure Sensor Signal Invalid", "CLEARED", "03-11 22:40"])
row(d, cols, ["3", "A17", "Hydraulic Pressure Low", "ACTIVE", "08:14:57"])
row(d, cols, ["4", "A18", "Hydraulic Pressure High", "INACTIVE", "--"])
text(d, "SW REV 3.2")
text(d, "Alarm A17 active for 00:00:14 — Shutdown Procedure 4.7 threshold: 00:00:10")

d = "screen_diagnostics"
title(d, "AEGIS SERIES-7 HCS — DIAGNOSTICS")
for l, v in [("Tag", "P.S.04-A"), ("Signal Type", "4-20 mA"), ("Raw Reading", "14.8 mA"), ("Scaled Value", "200.3 bar"),
             ("Calibration Status", "WITHIN TOLERANCE"), ("Last Calibrated", "2026-01-09"), ("Firmware Rev.", "3.2.1")]:
    field(d, l, v)
text(d, "SW REV 3.2")
text(d, "SENSOR DIAGNOSTICS")
text(d, "Note: this screen displays the sensor tag as printed on the physical unit label.")

d = "calibration_scan"
title(d, "APPENDIX C — SENSOR CALIBRATION RECORD")
for l, v in [("Aegis Series-7 HCS", "(scanned from field service binder, uncontrolled copy)"), ("Sensor Tag:", "PS-04A"),
             ("Location:", "HPU discharge line"), ("Calibration Date:", "2026-01-09"), ("Technician:", "R. Okafor"),
             ("Signature:", ""), ("Date:", "")]:
    field(d, l, v)
cols = ["Point", "Reference", "Reading", "Result"]
row(d, cols, ["Zero (0%)", "0 bar", "0.1 bar", "PASS"])
row(d, cols, ["Mid (50%)", "100 bar", "99.6 bar", "PASS"])
row(d, cols, ["Span (100%)", "200 bar", "199.4 bar", "PASS"])
text(d, "Calibration Points")
text(d, "Note: this calibration record supersedes the field data sheet used prior to the PS-04 to PS-04A sensor change "
        "(see ECN-1042). Span reference target is 200 bar, consistent with the software revision 3.2 operating pressure setpoint.")
text(d, "Prior sensor (PS-04) span reference target was 180 bar — for historical comparison only. Do not use the 180 bar "
        "figure to evaluate PS-04A.")
text(d, "No calibration interval is specified for PS-04A on this form; recalibration frequency should be confirmed against "
        "the applicable maintenance schedule, which is not included in this binder.")
text(d, "Page 1 of 1 — scanned copy, quality varies")

OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
print(f"wrote {len(rows)} segments to {OUT}")
