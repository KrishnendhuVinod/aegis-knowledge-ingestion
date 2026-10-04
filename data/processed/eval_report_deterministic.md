# Evaluation report - deterministic

| Metric | Result |
|---|---|
| original_all | 23/23 (100%) |
| original_answerable | 14/14 (100%) |
| original_caveated | 4/4 (100%) |
| original_unanswerable_abstention | 5/5 (100%) |
| reworded_all | 10/10 (100%) |
| mean_content_recall | 1.0 |
| numeric_grounding_rate | 1.0 |
| citation_validity_rate | 1.0 |
| answers_with_llm_mode | 0 |
| llm_rejected | 0 |

| ID | Set | Intent | Result | Issues |
|---|---|---|---|---|
| Q1 | original | startup | PASS |  |
| Q2 | original | pressure_current | PASS |  |
| Q3 | original | alarm_profile | PASS |  |
| Q4 | original | identity | PASS |  |
| Q5 | original | provenance | PASS |  |
| Q6 | original | topology | PASS |  |
| Q7 | original | persistence | PASS |  |
| Q8 | original | reset | PASS |  |
| Q9 | original | pressure_before | PASS |  |
| Q10 | original | alarm_for_threshold | PASS |  |
| Q11 | original | location | PASS |  |
| Q12 | original | novelty | PASS |  |
| Q13 | original | tag_match | PASS |  |
| Q14 | original | revision | PASS |  |
| Q15 | original | config_mapping | PASS |  |
| Q16 | original | applicability | PASS |  |
| Q17 | original | identity | PASS |  |
| Q18 | original | pressure_before | PASS |  |
| Q19 | original | gap | PASS |  |
| Q20 | original | gap | PASS |  |
| Q21 | original | gap | PASS |  |
| Q22 | original | gap | PASS |  |
| Q23 | original | gap | PASS |  |
| Q1 | reworded | startup | PASS |  |
| Q2 | reworded | pressure_current | PASS |  |
| Q4 | reworded | identity | PASS |  |
| Q8 | reworded | reset | PASS |  |
| Q10 | reworded | alarm_for_threshold | PASS |  |
| Q11 | reworded | location | PASS |  |
| Q18 | reworded | pressure_before | PASS |  |
| Q22 | reworded | gap | PASS |  |
| Q21 | reworded | gap | PASS |  |
| Q17 | reworded | identity | PASS |  |

## Answers

### Q1 (original): What must be true before starting the Hydraulic Power Unit?

Before starting the Hydraulic Power Unit (HPU), all of these must be true:
- Isolation valve IV-21 is OPEN
- The emergency stop circuit is RESET
- The hydraulic fluid level is within the normal band (sight glass)
- The maintenance access panel is installed and closed (the manual warns not to start the HPU with it removed)
These come from the operator manual (the panel condition is given as a WARNING) and are corroborated by config_export, maintenance_manual, training_slides.

- *Supporting documents:* config_export, maintenance_manual, operator_manual, training_slides  |  *claims:* C079, C080, C078, C081  |  *conflict records:* none

### Q2 (original): What is the current normal operating pressure for the HPU, and under what conditions does that apply?

The normal HPU discharge pressure is 200 bar. That applies to units running software revision 3.2 or later, where the pressure is measured by sensor PS-04A. On earlier revisions (below 3.2) the normal pressure was 180 bar, measured by PS-04, so the value depends on the unit's software revision.

- *Caveat:* A field note reports about 175 bar, but it is low-trust (uncalibrated gauge, unreviewed, undated, software revision not recorded) and cannot override the manual.
- *Supporting documents:* ecn_1042, operator_manual, revision_history, site_survey_notes  |  *claims:* C048, C047, C186  |  *conflict records:* X01, X02, X05

### Q3 (original): What does alarm A17 indicate, and what are its possible causes?

Alarm A17 indicates Hydraulic Pressure Low: the condition is "hydraulic pressure below 150 bar" (panel indication RED). Possible causes:
- IV-21 closed or partially closed
- Low hydraulic fluid
- Pressure sensor signal invalid
Required action: See Section 4 of the Maintenance Manual. If persistent > 10 s, run Shutdown Proc. 4.7*

- *Caveat:* ECN-1058 corrected the documentation: the A17 condition is evaluated against whichever pressure sensor is active for the installed software revision (PS-04 before 3.2, PS-04A from 3.2); the threshold is unchanged.
- *Supporting documents:* alarm_reference, config_export, maintenance_manual, operator_manual, revision_history  |  *claims:* C084, C094, C096, C098, C097, C090, C052  |  *conflict records:* none

### Q4 (original): Is PS-04 the same component as PS-04A?

No. PS-04 and PS-04A are not the same component. PS-04 was superseded by PS-04A (effective software revision 3.2, ECN-1042): the component register lists them as separate components with different status (PS-04: Superseded; PS-04A: Active), and ECN-1042 states that PS-04A is not a form-fit-function replacement for PS-04. They are related by replacement, not identity.

- *Supporting documents:* component_register, ecn_1042, operator_manual, revision_history  |  *claims:* C049, C065, C069  |  *conflict records:* none

### Q5 (original): Which document introduced the change from PS-04 to PS-04A?

ECN-1042 (Engineering Change Notice, 'Pressure Sensor Replacement (PS-04 → PS-04A) and Operating Pressure Update', effective Software Revision 3.2, status Released) introduced the change from PS-04 to PS-04A. The component register, operator manual and revision history all point to it.

- *Supporting documents:* component_register, ecn_1042, operator_manual, revision_history  |  *claims:* C065, C056, C057, C059, C049  |  *conflict records:* none

### Q6 (original): Which components connect directly to the HCS controller, according to the hydraulic schematic?

According to the hydraulic schematic, PLC-03 (HCS Controller) connects directly to PS-04A (Pressure Sensor 04A) and IV-21 (Isolation Valve 21) through purple lines, which the legend defines as control/signal connections to PLC-03.

- *Caveat:* A further line joins PLC-03 and HPU (Hydraulic Power Unit), but it is drawn grey, which the legend assigns to 'hydraulic fluid path'; the drawing does not explain a fluid-path line at the controller, so it is flagged as unexplained and not counted as a control/signal connection.
- *Supporting documents:* hydraulic_schematic  |  *claims:* C113, C114, C112  |  *conflict records:* X04

### Q7 (original): What action is required if alarm A17 persists for more than 10 seconds?

If alarm A17 persists for more than 10 seconds, execute Shutdown Procedure 4.7 before investigating further (do not just silence the alarm). The procedure: close IV-21; confirm pressure decay; set POWER selector to OFF; tag out per site lockout/tagout procedure; then proceed to Section 6 (Troubleshooting). A transient A17 that clears on its own within a few seconds during valve transition does not require it.

- *Caveat:* The HMI alarm screenshot shows A17 active for 14 s against the 10 s threshold, i.e. that unit is past the point where the shutdown procedure is required.
- *Supporting documents:* alarm_reference, config_export, maintenance_manual, screen_alarms  |  *claims:* C090, C092, C091, C181  |  *conflict records:* none

### Q8 (original): Under what circumstances must the controller not be reset?

Do not reset the PLC-03 controller while hydraulic pressure is above 50 bar: resetting under pressure can cause an uncommanded valve transition (the maintenance manual adds: a momentary uncommanded actuation of IV-21). Reset is only permitted when pressure, as reported by the active sensor (PS-04 before software 3.2, PS-04A from 3.2), reads below 50 bar; bleed pressure first using the manual bleed procedure (Section 8). The firmware also blocks reset above 50 bar and specifies no minimum pressure.

- *Caveat:* Manuals prohibit reset 'above 50 bar' and permit it only 'below 50 bar'; behaviour at exactly 50 bar is not stated. The firmware config blocks reset 'above' 50, which suggests exactly that value is allowed, but no document says so.
- *Supporting documents:* config_export, maintenance_manual, operator_manual  |  *claims:* C082, C089, C083, C161  |  *conflict records:* X03

### Q9 (original): What was the operating pressure threshold before software revision 3.2, and what changed it?

Before software revision 3.2 the normal HPU discharge pressure was 180 bar, measured by sensor PS-04. ECN-1042 changed it: effective with software 3.2 (released 2025-09-30) the setpoint was revised from 180 bar to 200 bar, alongside replacing PS-04 with PS-04A. The ECN describes it as a deliberate process change, not a sensor calibration artifact.

- *Supporting documents:* component_register, ecn_1042, legacy_manual_v1, operator_manual, revision_history  |  *claims:* C047, C085, C048, C046, C067, C049, C065, C044  |  *conflict records:* X01, X02, X05

### Q10 (original): Which alarm is associated with a pressure sensor reading below 150 bar?

Alarm A17 (Hydraulic Pressure Low) is the one raised when discharge pressure is below 150 bar. (The related high-pressure alarm is A18, above 220 bar.)

- *Supporting documents:* alarm_reference, component_register, config_export  |  *claims:* C095, C020, C100  |  *conflict records:* none

### Q11 (original): According to the component register, what is the location of the isolation valve IV-21?

According to the component register, IV-21 (Isolation Valve 21) is located in: Hydraulic Module.

- *Supporting documents:* component_register  |  *claims:* C005, C004  |  *conflict records:* none

### Q12 (original): Does the training slide deck introduce any component or alarm not found in the manuals?

Yes, one component: the Auxiliary Reservoir. It appears in the training slides (described there as a Line 4/5-specific configuration detail) and in the hydraulic schematic, but not in the operator manual, maintenance manual, alarm reference, component register or glossary. No alarm is introduced: the slides contain no alarm codes. The slides' informal name 'hydraulic pack' is just another name for the HPU, not a new component.

- *Supporting documents:* hydraulic_schematic, training_slides  |  *claims:* C111, C110  |  *conflict records:* none

### Q13 (original): What sensor ID appears on the diagnostics screenshot, and does it match a known component?

The diagnostics screenshot shows the sensor tag 'P.S.04-A' (the screen notes this is the tag as printed on the physical unit label). It matches the known component PS-04A (Pressure Sensor 04A): the two differ only in punctuation, and it does not match PS-04 (that would read PS04 with no trailing A). PS-04A is the active HPU discharge pressure sensor on software 3.2 and later; the same screen reports a scaled value of 200.3 bar and calibration status WITHIN TOLERANCE.

- *Supporting documents:* screen_diagnostics  |  *claims:* C166, C167, C168, C169, C170, C171  |  *conflict records:* none

### Q14 (original): Per the revision history, when did software revision 3.2 take effect, and what changed alongside it?

Per the revision history, software revision 3.2 took effect on 2025-09-30. Alongside it: pressure sensor PS-04 was replaced by PS-04A, and the normal HPU discharge pressure setpoint changed from 180 bar to 200 bar (see ECN-1042).

- *Supporting documents:* component_register, ecn_1042, operator_manual, revision_history  |  *claims:* C044, C045, C046, C049  |  *conflict records:* none

### Q15 (original): What does sensor_ps04a_threshold_bar in the configuration export correspond to in the operator manual's terminology?

sensor_ps04a_threshold_bar corresponds to the operator manual's normal operating pressure for the HPU, i.e. the HPU discharge pressure setpoint (200 bar), as measured by PS-04A. This is an INFERRED mapping: no document states it. It rests on the key naming ps04a, the value matching the manual's 200 bar for software 3.2 and later, and the export's applies_from_firmware 3.2.

- *Caveat:* The export's own note says not to map sensor_ps40_* keys: PS-40 is the unrelated coolant-loop sensor.
- *Supporting documents:* config_export, operator_manual  |  *claims:* C162, C163, C164  |  *conflict records:* none

### Q16 (original): Does the 200 bar threshold apply to all Aegis HCS units, or only some?

No, not all units: only some. The 200 bar setpoint applies to units running software revision 3.2 or later, which use sensor PS-04A (PS-04A needs controller firmware 3.2 or later). Units on software below 3.2 keep PS-04 and the older 180 bar setpoint: ECN-1042 says PS-04 remains installed and supported there and that PS-04A must not be installed on firmware older than 3.2.

- *Caveat:* ECN-1042 justifies the 200 bar setpoint by benefit on 'Series-7 units manufactured after 2024', while the manuals scope 200 bar by software revision (3.2 and later) and PS-04A requires firmware >= 3.2. No source says whether older-built units that run revision >= 3.2 firmware use 200 bar, or whether newer-built units on older firmware may.
- *Supporting documents:* component_register, ecn_1042, operator_manual, revision_history  |  *claims:* C048, C068, C069, C013, C066, C067  |  *conflict records:* X01, X02, X05

### Q17 (original): Is PS-04 the same as PS-40?

No. PS-04 and PS-40 are different, unrelated components. PS-40 is 'Pressure Sensor 40' located at Coolant Loop, Skid B, while the other sits on the HPU discharge line. The component register says PS-40 is NOT related to the HPU discharge circuit and warns not to confuse it with PS-04 / PS-04A.

- *Supporting documents:* component_register  |  *claims:* C008, C015  |  *conflict records:* none

### Q18 (original): What was the pressure limit before revision 3.2?

Before software revision 3.2 the normal HPU discharge pressure was 180 bar, measured by sensor PS-04. ECN-1042 changed it: effective with software 3.2 (released 2025-09-30) the setpoint was revised from 180 bar to 200 bar, alongside replacing PS-04 with PS-04A. The ECN describes it as a deliberate process change, not a sensor calibration artifact.

- *Supporting documents:* component_register, ecn_1042, legacy_manual_v1, operator_manual, revision_history  |  *claims:* C047, C085, C048, C046, C067, C049, C065, C044  |  *conflict records:* X01, X02, X05

### Q19 (original): What is the maximum continuous operating temperature of PS-04A?

This cannot be determined from the provided sources. No document gives a temperature rating for PS-04A. Temperature mentions elsewhere are about other things. (Searched 325 text segments; none gives the answer.)

- *Supporting documents:* none  |  *claims:* none  |  *conflict records:* none

### Q20 (original): What is the calibration interval for the electrical system diagram's voltage sensor?

This cannot be determined from the provided sources. The electrical schematic shows no voltage sensor (only a 24VDC sensor-loop POWER SUPPLY and a pressure transducer loop reference), so the question's premise is not supported; and no source gives a calibration interval for any sensor (the PS-04A calibration record says none is specified). (Searched 325 text segments; none gives the answer.) Related facts that are stated: PS-04A calibration interval: not specified.

- *Supporting documents:* calibration_scan  |  *claims:* C185  |  *conflict records:* none

### Q21 (original): Who approved engineering bulletin ECN-1058?

This cannot be determined from the provided sources. ECN-1058's header lists number, title, effective date, references and status ('Released') but no approver or signature. 'Released' does not say who approved it. (Searched 325 text segments; none gives the answer.) Related facts that are stated: doc:ECN-1058 header.status: Released.

- *Supporting documents:* ecn_1058  |  *claims:* C064  |  *conflict records:* none

### Q22 (original): What is the mean time between failures for the isolation valve IV-21?

This cannot be determined from the provided sources. No reliability data for IV-21 (or any component) appears in the package. (Searched 325 text segments; none gives the answer.)

- *Supporting documents:* none  |  *claims:* none  |  *conflict records:* none

### Q23 (original): Is the Aegis Series-7 HCS compatible with a 3-phase 400V supply?

This cannot be determined from the provided sources. Only 480V is mentioned (Q1 main disconnect 480V incoming; T1 480:120V control power). Nothing states the phase count or compatibility with 400V. (Searched 325 text segments; none gives the answer.) Related facts that are stated: Q1 rated voltage: {'volts': 480, 'role': 'incoming supply'}; T1 rated voltage: {'primary_v': 480, 'secondary_v': 120}.

- *Supporting documents:* component_register  |  *claims:* C035, C039  |  *conflict records:* none

### Q1 (reworded): What conditions need to be satisfied prior to powering up the HPU?

Before starting the Hydraulic Power Unit (HPU), all of these must be true:
- Isolation valve IV-21 is OPEN
- The emergency stop circuit is RESET
- The hydraulic fluid level is within the normal band (sight glass)
- The maintenance access panel is installed and closed (the manual warns not to start the HPU with it removed)
These come from the operator manual (the panel condition is given as a WARNING) and are corroborated by config_export, maintenance_manual, training_slides.

- *Supporting documents:* config_export, maintenance_manual, operator_manual, training_slides  |  *claims:* C079, C080, C078, C081  |  *conflict records:* none

### Q2 (reworded): What pressure should the hydraulic unit normally run at now, and when does that value apply?

The normal HPU discharge pressure is 200 bar. That applies to units running software revision 3.2 or later, where the pressure is measured by sensor PS-04A. On earlier revisions (below 3.2) the normal pressure was 180 bar, measured by PS-04, so the value depends on the unit's software revision.

- *Caveat:* A field note reports about 175 bar, but it is low-trust (uncalibrated gauge, unreviewed, undated, software revision not recorded) and cannot override the manual.
- *Supporting documents:* ecn_1042, operator_manual, revision_history, site_survey_notes  |  *claims:* C048, C047, C186  |  *conflict records:* X01, X02, X05

### Q4 (reworded): Is sensor PS04A identical to PS-04?

No. PS-04 and PS-04A are not the same component. PS-04 was superseded by PS-04A (effective software revision 3.2, ECN-1042): the component register lists them as separate components with different status (PS-04: Superseded; PS-04A: Active), and ECN-1042 states that PS-04A is not a form-fit-function replacement for PS-04. They are related by replacement, not identity.

- *Supporting documents:* component_register, ecn_1042, operator_manual, revision_history  |  *claims:* C049, C065, C069  |  *conflict records:* none

### Q8 (reworded): When should the PLC-03 controller never be reset?

Do not reset the PLC-03 controller while hydraulic pressure is above 50 bar: resetting under pressure can cause an uncommanded valve transition (the maintenance manual adds: a momentary uncommanded actuation of IV-21). Reset is only permitted when pressure, as reported by the active sensor (PS-04 before software 3.2, PS-04A from 3.2), reads below 50 bar; bleed pressure first using the manual bleed procedure (Section 8). The firmware also blocks reset above 50 bar and specifies no minimum pressure.

- *Caveat:* Manuals prohibit reset 'above 50 bar' and permit it only 'below 50 bar'; behaviour at exactly 50 bar is not stated. The firmware config blocks reset 'above' 50, which suggests exactly that value is allowed, but no document says so.
- *Supporting documents:* config_export, maintenance_manual, operator_manual  |  *claims:* C082, C089, C083, C161  |  *conflict records:* X03

### Q10 (reworded): Which alarm fires when discharge pressure drops under 150 bar?

Alarm A17 (Hydraulic Pressure Low) is the one raised when discharge pressure is below 150 bar. (The related high-pressure alarm is A18, above 220 bar.)

- *Supporting documents:* alarm_reference, component_register, config_export  |  *claims:* C095, C020, C100  |  *conflict records:* none

### Q11 (reworded): Where is the isolation valve located, per the register?

According to the component register, IV-21 (Isolation Valve 21) is located in: Hydraulic Module.

- *Supporting documents:* component_register  |  *claims:* C005, C004  |  *conflict records:* none

### Q18 (reworded): What was the normal pressure setpoint prior to software revision 3.2?

Before software revision 3.2 the normal HPU discharge pressure was 180 bar, measured by sensor PS-04. ECN-1042 changed it: effective with software 3.2 (released 2025-09-30) the setpoint was revised from 180 bar to 200 bar, alongside replacing PS-04 with PS-04A. The ECN describes it as a deliberate process change, not a sensor calibration artifact.

- *Supporting documents:* component_register, ecn_1042, legacy_manual_v1, operator_manual, revision_history  |  *claims:* C047, C085, C048, C046, C067, C049, C065, C044  |  *conflict records:* X01, X02, X05

### Q22 (reworded): What is the MTBF of valve IV-21?

This cannot be determined from the provided sources. No reliability data for IV-21 (or any component) appears in the package. (Searched 325 text segments; none gives the answer.)

- *Supporting documents:* none  |  *claims:* none  |  *conflict records:* none

### Q21 (reworded): Which person signed off ECN-1058?

This cannot be determined from the provided sources. ECN-1058's header lists number, title, effective date, references and status ('Released') but no approver or signature. 'Released' does not say who approved it. (Searched 325 text segments; none gives the answer.) Related facts that are stated: doc:ECN-1058 header.status: Released.

- *Supporting documents:* ecn_1058  |  *claims:* C064  |  *conflict records:* none

### Q17 (reworded): Are PS-04 and PS-40 identical?

No. PS-04 and PS-40 are different, unrelated components. PS-40 is 'Pressure Sensor 40' located at Coolant Loop, Skid B, while the other sits on the HPU discharge line. The component register says PS-40 is NOT related to the HPU discharge circuit and warns not to confuse it with PS-04 / PS-04A.

- *Supporting documents:* component_register  |  *claims:* C008, C015  |  *conflict records:* none
