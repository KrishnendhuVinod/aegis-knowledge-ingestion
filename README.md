# Aegis Knowledge Ingestion

Turns a messy documentation package for a fictional machine (the *Aegis Series-7 Hydraulic Control System*: manuals,
engineering change notices, a spreadsheet register, a JSON configuration export, drawings, screenshots, a scanned record,
training slides and unrelated noise) into a **structured knowledge base with provenance**, and answers natural-language
questions from it with **evidence, flagged conflicts, and explicit "cannot be determined" answers**.

The chat layer is deliberately thin. The substance is the layer underneath: how each source is read, how facts are
represented, how aliases and look-alikes are resolved, how version-dependent facts coexist, and how absence is reported.

## Results

Evaluation on the 23 assessment questions plus 10 reworded variants (`python -m aegis_kb.evaluate`, deterministic composer):

| Metric | Result |
|---|---|
| Original questions passed | **23 / 23** (14 answerable, 4 answerable-with-caveat, 5 unanswerable) |
| Abstention on the 5 unanswerable questions | **5 / 5** (no invented value; what was searched and rejected is shown) |
| Reworded questions passed | **10 / 10** |
| Mean content recall | 1.00 |
| Numeric grounding (every number in an answer appears in its cited evidence or the question) | 100% |
| Citation validity (every cited segment exists in the segment store) | 100% |

**Read these numbers with care** (details in *Known limitations*): the rubric is the author's own reading of the sources, and
the answer renderers were written with sight of the 23 questions, so 100% on the originals is expected rather than a measure
of generalisation. The reworded set is the better signal, but it is small and also author-written.

Knowledge base built from the 20 source files: 325 segments, 23 entities (12 registered + 11 drawing-only), 70 alias
decisions (including rejected merges), 186 claims, 5 conflict/ambiguity records, 6 searched-and-absent gaps.

## How it works

```
 20 source files (8 formats)
        |  parsers (deterministic; OCR + Gemini vision for images only)
        v
 Layer 0  SEGMENTS    one record per paragraph / bullet / table row / JSON leaf / diagram edge / image field,
        |             each with doc, exact location, extraction method and reading confidence
        v
 Layer 1  ENTITIES    register rows are the authority; every alias decision stores relation, evidence and reason
        |             (rejected merges are stored too)
        v
 Layer 2  CLAIMS      subject / predicate / value / unit / applies_when (software-revision scope) / evidence segment
        |  CONFLICTS  ids / trust rank / status;   conflicts, ambiguities and searched-and-absent GAPS kept explicitly
        v
 ANSWERS              {answer, caveats, claims, evidence[doc, location, snippet, role], conflicts, gaps}
```

Each layer only points *down* at the one beneath it, so an answer can be traced to a page, cell or line in a source file.
See `docs/schema.md` for the record definitions.

### Deterministic vs model-based, and why

| Source | Method | Why |
|---|---|---|
| Born-digital PDFs (manuals, ECNs, alarm reference, safety data sheet) | **deterministic** (pdfplumber + layout rules) | exact text and page/section; a model would only add risk |
| XLSX, DOCX, PPTX, HTML, JSON | **deterministic** | structured formats; IDs kept "as printed", nulls kept |
| Vector drawings (hydraulic schematic, wiring diagram) | **deterministic geometry** | topology is recoverable exactly from boxes and stroked lines; a model can hallucinate an edge, geometry cannot |
| Scanned PDF, 3 screenshots, 1 raster diagram | **Gemini vision** (+ optional Tesseract OCR) | the text exists only as pixels |
| Claim extraction, entity resolution, conflict detection, gap search, answer composition | **rule-based** | traceable and testable without a model |
| Optional answer wording (`--llm`) | **Gemini**, validated | sees only retrieved, citable findings; rejected if it invents anything |

Gemini is called **only for the five image files**, at temperature 0, and every response is cached in `data/cache/llm/`.
The cache is committed, so the pipeline and evaluation reproduce **without an API key**.

## Knowledge representation

* **Segment** - smallest citable unit. `method` = deterministic / ocr / vision_llm; `confidence` = how faithfully it was
  *read* (not whether it is true).
* **Source trust** is separate from reading confidence and lives per document in `sources.py` (hand-curated, with a written
  rationale for each file): official manuals/register/revision history > change notices (authoritative on what changed) >
  system export > drawings > HMI screenshots (one unit, one moment) > training slides (derived) > superseded legacy manual
  (valid only for software 3.0-3.1) > field notes (unreviewed, undated) > unrelated safety data sheet. Trust is a tie-break
  hint only; it never silently resolves a conflict.
* **Entity / alias decision** - relations are kept distinct because mixing them is the main trap: `same_as`, `variant_of`,
  `corresponds_to` (a wiring designation of a thing), `superseded_by` (related by replacement, not identity),
  `distinct_from` (look-alike), `related_not_same`, `unregistered`.
* **Claim** - `applies_when` is a first-class software-revision scope, and `status` is one of `asserted`, `planned`,
  `observation`, `low_trust_observation`, `inferred`, `explicitly_not_specified`. Identical claims from different documents
  are merged so corroboration is visible.
* **Conflict record** - `scoped_coexistence`, `conflict`, `observation_disagrees`, `ambiguity`.
* **Gap** - a question the corpus does not answer, recorded only after a real search, with the near-misses that were
  examined and rejected.

### How each trap in the corpus is handled

| Trap | Handling |
|---|---|
| 180 bar vs 200 bar | two claims with **disjoint** scopes (software < 3.2 vs >= 3.2) -> `scoped_coexistence`, not a conflict; the legacy manual's 180 is scoped to 3.0-3.1 |
| Alias variants (HPU / HP unit / Hydraulic Power Pack / "hydraulic pack"; `P.S.04-A`; `PRESSURE XDCR`) | register aliases + text evidence + punctuation-insensitive normal form (`norm_id`), never prefix matching |
| PS-04 vs PS-04A vs PS-40 | PS-04 `superseded_by` PS-04A (not the same part); PS-40 `distinct_from` both (register: "NOT related"); the rejected merges are stored with reasons |
| `PLC-03 I/O RACK`, `IV-21 VALVE DRIVER` in drawings | contain a registered ID plus extra words that are not the register name -> kept as separate drawing-only parts |
| Field note says ~175 bar | low-trust observation in its own predicate; surfaced as a caveat, never used as the answer |
| Config key `sensor_ps04a_threshold_bar` | mapped to "normal operating pressure" with status **inferred** and the basis stated: no document states the mapping |
| Grey (hydraulic-fluid) line drawn to the controller | reported faithfully; flagged as unexplained; not counted as a control/signal connection |
| Reset "above 50" prohibited vs "below 50" permitted | boundary at exactly 50 recorded as an ambiguity |
| ECN-1042 cites "units manufactured after 2024" while manuals scope by software revision | recorded as an ambiguity; the answer follows software revision and says so |
| Null `min_pressure_bar_required_for_reset` | kept as `explicitly_not_specified` ("no minimum required"), not dropped |
| Revision 3.3 | kept with status `planned` |
| Safety data sheet (noise) | ingested, then never cited; its temperature/flash-point text appears only as a *rejected near-miss* for the PS-04A temperature question |
| Missing facts (temperature rating, voltage-sensor calibration interval, ECN-1058 approver, IV-21 MTBF, 400V/3-phase) | gaps with search evidence; the answer says "cannot be determined" and lists related facts that *are* stated |

## Answering

`python -m aegis_kb.ask "Is PS-04 the same component as PS-04A?"` returns the answer, caveats, the claims and evidence used
(document, location, snippet, reading confidence, role), and any relevant conflict or gap records. Example:

> No. PS-04 and PS-04A are not the same component. PS-04 was superseded by PS-04A (effective software revision 3.2,
> ECN-1042): the component register lists them as separate components with different status (PS-04: Superseded; PS-04A:
> Active), and ECN-1042 states that PS-04A is not a form-fit-function replacement for PS-04. They are related by
> replacement, not identity.

* **Retrieval** (`retrieve.py`): entity linking inside the question (longest match, so `PS-04` is not matched inside
  `PS-04A`; config keys like `sensor_ps04a_threshold_bar` link to PS-04A) + lexical scoring + a predicate lexicon.
* **Deterministic composer (default):** intent-specific renderers that build each sentence from claim values. If a
  renderer's expected claims are missing, it falls back to a generic list of findings instead of guessing. Questions that
  match a recorded gap get "cannot be determined" plus what was searched.
* **Gemini composer (`--llm`):** sees only retrieved findings with claim ids. Its answer is rejected and replaced by the
  deterministic one if it cites an unknown claim id, returns nothing, or contains a number found in neither the findings nor
  the question. This path is covered by unit tests with a stub model; **it was not exercised against the live API for the
  reported results** (`answers_with_llm_mode = 0`).

## Loss and confidence analysis

Where information can be lost or distorted, what was done about it, and what remains.

**Born-digital PDFs.** pdfminer decodes a Symbol-font arrow as the "fi" ligature (`PS-04 fi PS-04A` in the ECN-1042 title;
poppler decodes it correctly). A narrow rule repairs it and records `repairs: ["symbol_font_arrow"]` on the segment. Bullet
glyphs (`(cid:127)`) are normalised; paragraphs split across a page break (the "180 bar" sentence) are re-joined with their
page span kept; bold emphasis ("Do not reset ... above 50 bar.") is captured as `bold_text`. Page headers/footers are dropped
by position, which would misfire on a differently laid-out document.

**Images (5 files).** Their only text source in the reported run is Gemini: Tesseract could not be installed on the machine
used, so no automatic OCR cross-check exists. Vision readings carry a fixed prior confidence of 0.8 (uncalibrated). To
compensate, Gemini's transcription of all five images was compared line by line against the source images; no transcription
errors were found (a manual check, not an automated one). In an earlier run with Tesseract, OCR confused `0/O` and `1/l/I`
inside identifiers (`PS-O4A`, `Al7`, `A117`), which is why identifiers are matched through a normal form and why verbatim
transcription was demanded of the model. The electrical diagram's *edges* come from vision (not verified geometrically),
unlike the two vector drawings whose topology comes from line geometry.

**Coverage.** Segments cited by at least one claim, out of the content segments per document:

| Document | Cited | | Document | Cited |
|---|---|---|---|---|
| component_register | 12/12 | | operator_manual | 13/19 |
| config_export | 28/28 | | maintenance_manual | 6/11 |
| revision_history | 5/5 | | legacy_manual_v1 | 5/14 |
| ecn_1042 | 9/10 | | training_slides | 6/13 |
| ecn_1058 | 7/8 | | hydraulic_schematic | 10/21 |
| alarm_reference | 5/6 | | wiring_diagram | 5/14 |
| screen_alarms | 5/7 | | electrical_diagram | 7/18 |
| screen_diagnostics | 6/11 | | calibration_scan | 9/16 |
| screen_home | 5/12 | | site_survey_notes | 1/7 |
| terminology_glossary | 1/12 | | hydraulic_fluid_sds | 0/14 (noise, by design) |

Uncited does not mean lost: every segment stays in `segments.jsonl` and is searched when a gap is checked. But prose that
no rule matched (about a third of the operator manual's segments, e.g. introductory text) cannot contribute to an answer
beyond the generic fallback. Titles, node boxes and legends are segments but not claims.

**Scope assumptions.** The manual's "prior to 3.2" has an open lower bound. Screens showing "SW REV 3.2" are scoped to
[3.2, 3.3). Revision 3.3 is only "planned" in the source and is treated as such.

## What I chose not to do

* **No embedding / vector-search RAG over raw chunks.** It blurs software-version scope and provenance and cannot reliably
  abstain; the corpus is small enough for explicit structure.
* **No LLM claim extraction.** Rule-based extraction is traceable and testable offline. An LLM extractor could sit behind the
  same `Claim` interface for unseen documents, with a validator requiring each value to occur in its cited segment.
* **No automatic conflict resolution by recency or trust rank.** Conflicts and ambiguities are stored with both sides and
  the scope, and answers state them.
* **No fuzzy identifier matching** beyond punctuation/case/spacing: similarity would merge PS-04 with PS-04A.
* **No silent filling of unspecified values.** Nulls are kept, absent facts become gaps, and an inferred mapping says it is inferred.
* **No promotion of field notes or training slides above manuals.**
* **No OCR cross-check in the reported run** (optional, not installable on the machine used).
* **No web UI** (command line only), and the raw dataset is not committed.

## Known limitations

* **Corpus-specific extraction.** Register, revision-history, ECN-header, alarm-table, JSON and diagram extractors are
  generic and keyed on structure, but the sentence-pattern rules for prose are specific to this corpus.
* **Intent classification is keyword/regex based.** An unseen question type gets the generic fallback (nearest findings, not
  a verified absence), or the Gemini composer if enabled. Gap detection covers six defined absence topics.
* **Evaluation rubric** (`gold.py`) is the author's reading of the documents, not an official key; verify it against the PDFs.
* **Evaluation bias** as described under *Results*.
* **Vision readings** carry an uncalibrated confidence prior and were checked by hand, not by a second automatic reader.
* **Model availability** on Gemini's free tier changes; the model is set with `GEMINI_MODEL` (default `gemini-3.1-flash-lite`).
  The response cache is keyed on model + prompt + image, so it reproduces only if the same model name is used.

## Setup and usage

Python 3.10 or newer (developed on 3.12; also run on 3.14).

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell      (macOS/Linux: source .venv/bin/activate)
python -m pip install -r requirements.txt
python -m pip install -e .
```

Place the dataset so that `data/raw/aegis-dataset/manuals/operator_manual.pdf` exists, then:

```bash
python -m aegis_kb.ingest        # Layer 0: data/processed/segments.jsonl + manifest.json
python -m aegis_kb.build_kb      # Layers 1-2: data/processed/kb.json + printed summary
python -m aegis_kb.evaluate      # data/processed/eval_report_deterministic.md and eval_results_deterministic.json
python -m aegis_kb.ask "What must be true before starting the Hydraulic Power Unit?"
python -m pytest -q              # 61 tests (59 pass and 2 are skipped when Tesseract is not installed)
```

* **Without an API key:** run the commands as above; image readings come from the committed cache.
* **With a Gemini key** (free, https://aistudio.google.com/apikey): copy `.env.example` to `.env`, set `GEMINI_API_KEY`, run
  `python scripts/check_gemini.py` to see which models the key can use, and set `GEMINI_MODEL` if the default is unavailable.
  Add `--llm` to `evaluate` or `ask` to also use the Gemini composer.
* **Tesseract** is optional (`TESSERACT_CMD` in `.env` if it is installed but not on PATH).
* `ingest --no-llm` ignores the model and its cache entirely (OCR/deterministic only), so image documents then depend on Tesseract.

## Repository layout

```
src/aegis_kb/
  schema.py  sources.py  llm.py  ingest.py        Layer 0: segment record, source registry + trust, cached Gemini client, runner
  parsers/                                         pdf_text, pdf_diagram (geometry), image (OCR + vision), html, xlsx, docx, pptx, json
  versions.py  kb_schema.py  entities.py           software scopes; KB records; entities, aliases, merge reasoning
  extractors.py  conflicts.py  gaps.py  build_kb.py   claims; conflict/ambiguity detection; searched absence; KB build + summary
  retrieve.py  answer.py  ask.py                   question linking and retrieval; answer composers; command line
  gold.py  evaluate.py                             rubric for the 23 questions + reworded variants; scoring and reports
tests/                                             61 tests; tests/fixtures holds the five image documents as Gemini read them
docs/schema.md                                     record definitions and evidence roles
scripts/check_gemini.py                            checks the key and lists usable models
data/cache/llm/                                    committed Gemini responses (makes the run key-free)
data/processed/                                    generated outputs: segments, manifest, knowledge base, evaluation reports
```
