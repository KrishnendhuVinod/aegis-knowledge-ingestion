"""Gold rubric for the 23 evaluation questions + reworded variants.

IMPORTANT (state in the report): these expectations are the author's reading of the source documents, written to
check content, provenance, caveats and abstention. They are NOT an official answer key - verify each against the PDFs.

Fields: must = regexes that ALL must match the answer+caveats text; must_not = regexes that must NOT match;
docs = source documents that must appear among the supporting evidence; flags = conflict predicates that must be surfaced.
kind: answerable | caveated (answer must also carry a flagged ambiguity/inference) | unanswerable (must abstain).
"""
GOLD = {
    "Q1": dict(q="What must be true before starting the Hydraulic Power Unit?", kind="answerable",
               must=[r"IV-21 is OPEN", r"emergency stop circuit is RESET", r"fluid level is within the normal band",
                     r"maintenance access panel"], docs=["operator_manual"]),
    "Q2": dict(q="What is the current normal operating pressure for the HPU, and under what conditions does that apply?",
               kind="answerable", must=[r"200 bar", r"software revision 3\.2 or later", r"PS-04A"], docs=["operator_manual"]),
    "Q3": dict(q="What does alarm A17 indicate, and what are its possible causes?", kind="answerable",
               must=[r"Hydraulic Pressure Low", r"below 150 bar", r"IV-21 closed or partially closed",
                     r"Low hydraulic fluid", r"signal invalid"], docs=["alarm_reference"]),
    "Q4": dict(q="Is PS-04 the same component as PS-04A?", kind="answerable",
               must=[r"^No\b", r"not the same", r"supersed", r"ECN-1042"], must_not=[r"^Yes"],
               docs=["component_register", "ecn_1042"]),
    "Q5": dict(q="Which document introduced the change from PS-04 to PS-04A?", kind="answerable",
               must=[r"ECN-1042"], docs=["ecn_1042"]),
    "Q6": dict(q="Which components connect directly to the HCS controller, according to the hydraulic schematic?",
               kind="caveated", must=[r"PS-04A", r"IV-21", r"control/signal", r"grey"], must_not=[r"directly to[^.]*HPU"],
               docs=["hydraulic_schematic"], flags=["connected_to"]),
    "Q7": dict(q="What action is required if alarm A17 persists for more than 10 seconds?", kind="answerable",
               must=[r"more than 10 seconds", r"Shutdown Procedure 4\.7", r"close IV-21"], docs=["maintenance_manual"]),
    "Q8": dict(q="Under what circumstances must the controller not be reset?", kind="caveated",
               must=[r"above 50 bar", r"uncommanded", r"below 50 bar", r"exactly"], docs=["operator_manual", "maintenance_manual"],
               flags=["reset_boundary"]),
    "Q9": dict(q="What was the operating pressure threshold before software revision 3.2, and what changed it?",
               kind="answerable", must=[r"180 bar", r"ECN-1042", r"200 bar", r"PS-04A"], docs=["ecn_1042"]),
    "Q10": dict(q="Which alarm is associated with a pressure sensor reading below 150 bar?", kind="answerable",
                must=[r"A17", r"150 bar"], docs=["alarm_reference"]),
    "Q11": dict(q="According to the component register, what is the location of the isolation valve IV-21?",
                kind="answerable", must=[r"Hydraulic Module"], docs=["component_register"]),
    "Q12": dict(q="Does the training slide deck introduce any component or alarm not found in the manuals?",
                kind="answerable", must=[r"Auxiliary Reservoir", r"No alarm"], docs=["training_slides"]),
    "Q13": dict(q="What sensor ID appears on the diagnostics screenshot, and does it match a known component?",
                kind="answerable", must=[r"P\.S\.04-A", r"PS-04A", r"punctuation"], must_not=[r"matches PS-04(?!A)"],
                docs=["screen_diagnostics"]),
    "Q14": dict(q="Per the revision history, when did software revision 3.2 take effect, and what changed alongside it?",
                kind="answerable", must=[r"2025-09-30", r"PS-04A", r"180 bar to 200 bar"], docs=["revision_history"]),
    "Q15": dict(q="What does sensor_ps04a_threshold_bar in the configuration export correspond to in the operator manual's "
                  "terminology?", kind="caveated", must=[r"normal operating pressure", r"INFERRED", r"PS-04A"],
                docs=["config_export"]),
    "Q16": dict(q="Does the 200 bar threshold apply to all Aegis HCS units, or only some?", kind="caveated",
                must=[r"not all|only some", r"3\.2 or later", r"PS-04A", r"manufactured after 2024"], docs=["ecn_1042"],
                flags=["setpoint_applicability"]),
    "Q17": dict(q="Is PS-04 the same as PS-40?", kind="answerable",
                must=[r"^No\b", r"PS-40", r"Coolant Loop", r"NOT related"], must_not=[r"^Yes"], docs=["component_register"]),
    "Q18": dict(q="What was the pressure limit before revision 3.2?", kind="answerable", must=[r"180 bar", r"3\.2"],
                docs=["operator_manual"]),
    "Q19": dict(q="What is the maximum continuous operating temperature of PS-04A?", kind="unanswerable",
                must=[r"cannot be determined", r"temperature rating"], must_not=[r"\d+\s?°\s?C"], docs=[]),
    "Q20": dict(q="What is the calibration interval for the electrical system diagram's voltage sensor?", kind="unanswerable",
                must=[r"cannot be determined", r"no voltage sensor"], must_not=[r"\d+ (months|years|days)"], docs=[]),
    "Q21": dict(q="Who approved engineering bulletin ECN-1058?", kind="unanswerable",
                must=[r"cannot be determined", r"no approver"], must_not=[r"approved by [A-Z]"], docs=[]),
    "Q22": dict(q="What is the mean time between failures for the isolation valve IV-21?", kind="unanswerable",
                must=[r"cannot be determined", r"No reliability data"], must_not=[r"\d+ (hours|cycles)"], docs=[]),
    "Q23": dict(q="Is the Aegis Series-7 HCS compatible with a 3-phase 400V supply?", kind="unanswerable",
                must=[r"cannot be determined", r"480V"], must_not=[r"\byes\b"], docs=[]),
}

# Reworded questions: same expectations, different wording. Measures generalisation of intent + entity handling.
PARAPHRASES = [
    ("Q1", "What conditions need to be satisfied prior to powering up the HPU?"),
    ("Q2", "What pressure should the hydraulic unit normally run at now, and when does that value apply?"),
    ("Q4", "Is sensor PS04A identical to PS-04?"),
    ("Q8", "When should the PLC-03 controller never be reset?"),
    ("Q10", "Which alarm fires when discharge pressure drops under 150 bar?"),
    ("Q11", "Where is the isolation valve located, per the register?"),
    ("Q18", "What was the normal pressure setpoint prior to software revision 3.2?"),
    ("Q22", "What is the MTBF of valve IV-21?"),
    ("Q21", "Which person signed off ECN-1058?"),
    ("Q17", "Are PS-04 and PS-40 identical?"),
]
