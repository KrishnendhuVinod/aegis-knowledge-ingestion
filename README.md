# Aegis Knowledge Ingestion

Turns the messy Aegis Series-7 HCS documentation package into a provenance-preserving knowledge
base that an agent can query with evidence, conflicts, and explicit gaps.

> **Status: Day 3 of 5 complete.** Ingestion, knowledge base, answering layer and the 23-question evaluation harness are
> built and tested. Remaining: run the evaluation on your machine (optionally with Gemini), then the PDF report.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .                                         # makes `aegis_kb` importable (no PYTHONPATH needed)
# OPTIONAL: install Tesseract OCR (without it Gemini reads images alone, no OCR cross-check): Ubuntu `sudo apt install tesseract-ocr` | macOS `brew install tesseract` | Windows: UB-Mannheim installer, add to PATH
cp .env.example .env                                     # Windows: copy .env.example .env  (then add your free key from https://aistudio.google.com/apikey)
python scripts/check_gemini.py                           # confirms which model your key can use
# put the dataset at data/raw/aegis-dataset/  (the folder that directly contains manuals/, reference/, ...)
python -m aegis_kb.ingest                                # Layer 0 -> data/processed/{segments.jsonl,manifest.json}
python -m aegis_kb.build_kb                              # Layers 1-2 -> data/processed/kb.json (+ printed summary)
python -m aegis_kb.evaluate                              # the 23 questions + reworded variants -> data/processed/eval_report_deterministic.md
python -m aegis_kb.evaluate --llm                        # also run the Gemini composer (cached, validated) -> eval_report_gemini.md
python -m aegis_kb.ask "Is PS-04 the same component as PS-04A?"     # one question, with evidence
python -m pytest -q
```
Use `--no-llm` to run fully offline (OCR + deterministic parsers only).

## Pipeline: what is deterministic and what is model-based, and why

| Source | Method | Why |
|---|---|---|
| Born-digital PDF (manuals, ECNs, alarm ref, SDS) | **deterministic** (pdfplumber + layout rules) | exact text, exact page/section; a model adds only risk |
| XLSX, DOCX, PPTX, HTML, JSON | **deterministic** | structured formats; values must be exact (IDs "as printed", nulls kept) |
| Vector diagrams (hydraulic, wiring) | **deterministic geometry** | topology is recoverable from lines/boxes exactly; models hallucinate edges, geometry can't |
| Scanned PDF, PNG screenshots, PNG diagram | **OCR (tesseract) + Gemini vision, both kept** | text only exists in pixels; two independent readings let us *measure* reading loss |

Every segment records its `method` and a reading `confidence`. Models are never used to decide
truth, trust, or entity identity in this layer.

**Gemini is called only for images**, with `temperature=0`, and every response is cached to
`data/cache/llm/` (keyed by model+prompt+image hash). **Commit the cache**: it makes the pipeline and
the evaluation reproducible by anyone without an API key, and protects against free-tier quota limits.
If there is no key and no cache entry, the pipeline falls back to OCR-only instead of failing.

## Source trust (hand-curated in `src/aegis_kb/sources.py`)

official manuals/references/register > change notices (authoritative on *what changed*) > system export >
drawings > HMI screenshots (one unit, one moment) > training slides (derived) > superseded legacy manual
(valid only for sw 3.0-3.1) > field notes (unreviewed, undated) > unrelated safety data sheet (noise).
Trust is a *tie-break hint only*; conflicts are stored explicitly, never resolved by rank alone.

## Findings from ingestion (seed of the loss/confidence analysis)

* **pdfminer mis-decodes a Symbol-font arrow** as the "fi" ligature (`PS-04 fi PS-04A` in ECN-1042's title;
  poppler decodes it correctly). Repaired by a narrow, logged rule; the segment records `repairs`.
* **OCR confuses `0/O` and `1/l/I` inside identifiers** (`PS-O4A`, `Al7`, `A117` for `A17`; seen when Tesseract was
  available). On the final run Tesseract was not installable (managed laptop), so images are read by Gemini alone and
  Gemini transcribed all identifiers verbatim (`P.S.04-A`, `PS-04A`, `3.2.1`). Identifiers are then matched by a
  punctuation-insensitive normal form (`norm_id`), never by prefix.
* Paragraphs split across a page break (the "180 bar" sentence) are re-joined; page span is kept in `location.pages`.
* **Emphasis is information**: "Do not reset ... above 50 bar." is bold in the source; captured as `bold_text`.
* JSON `null` is kept and flagged (`min_pressure_bar_required_for_reset: null` = "no minimum specified", not "unmentioned").
* Hydraulic schematic: a **grey (hydraulic fluid) line connects PLC-03 and the HPU**, which is physically odd for a
  controller. Recorded faithfully; to be surfaced as an ambiguity when answering "what connects to the controller".
* PDF page counts differ from the task brief (e.g. operator manual is 2 pages, not 12). Nothing hard-codes page assumptions.

## Known limits (Day 1)

* The Gemini path is covered by a stubbed-client test and the cache logic, but needs one real run with your key
  (`python scripts/check_gemini.py` then ingest) before the cache can be committed.
* Image reading confidence for vision output is a fixed prior (0.8); it is refined by OCR cross-check on Day 2.
* Diagram edges are undirected (the drawings have no arrowheads).

## Day 2: knowledge base (`python -m aegis_kb.build_kb`)

* **Entities & aliases** (`entities.py`): register rows are the authority. Every alias decision stores relation
  (`same_as`, `variant_of`, `superseded_by`, `distinct_from`, `corresponds_to`, `related_not_same`, `unregistered`),
  evidence and a reason, and **rejected merges are stored too** (PS-04 is not PS-04A, which is not PS-40; `PLC-03 I/O RACK`
  is not the PLC-03 controller; `IV-21 VALVE DRIVER` is not valve IV-21).
* **Claims** (`extractors.py`): subject / predicate / value / unit / `applies_when` (software-revision scope) / evidence
  segment ids / source docs / best trust rank / status (`asserted`, `planned`, `observation`, `low_trust_observation`,
  `inferred`, `explicitly_not_specified`). Identical claims from different documents are merged, so corroboration is visible.
* **Conflicts** (`conflicts.py`): 180 bar (software < 3.2) vs 200 bar (>= 3.2) is computed as *scoped coexistence*, not a
  conflict. Also recorded: the 175 bar field note (observation, not adjudicated), the reset boundary at exactly 50 bar, the
  grey fluid-line drawn to the controller, and ECN-1042's "manufactured after 2024" rationale vs software-based scope.
* **Gaps** (`gaps.py`): six absences, each after a real search, with **near-misses shown and rejected** (e.g. the fluid's
  flash point is not a PS-04A temperature rating; "Status: Released" is not an approver).
* The config key `sensor_ps04a_threshold_bar` is mapped to "normal operating pressure" with status **inferred**: no document
  states that mapping, and the claim says what it is based on.

**Limits (to state in the report):** extraction is rule-based. The structure-driven extractors (register, revision history,
ECN fields, alarm table, JSON, diagrams) are generic; the sentence-pattern rules for prose are specific to this corpus. An
LLM extractor could sit behind the same `Claim` interface for unseen documents, with a regex validator requiring every
claim's value to appear in its cited segment. Image-derived claims inherit Gemini's reading (confidence prior 0.8).

## Day 3: answering and evaluation

**Answer record** (`answer.py`): `answer`, `caveats`, the `claims` used, `evidence` (source doc, location, snippet, reading
confidence, role = `supports` / `context` / `searched_not_answering`), the relevant `conflicts` and the `gaps`.

* **Retrieval** (`retrieve.py`): entity linking inside the question (longest-match, punctuation-insensitive, so `PS-04` is not
  matched inside `PS-04A`, and config keys like `sensor_ps04a_threshold_bar` link to PS-04A) + lexical scoring + a predicate lexicon.
* **Deterministic composer (default):** question-pattern renderers that build every sentence from claim values, so each
  number and name is traceable. If a renderer's expected claims are missing it falls back to a generic list of findings
  rather than guessing. Questions that match a recorded gap get "cannot be determined" plus what was searched and rejected.
* **Gemini composer (`--llm`):** sees only retrieved, citable findings (never the raw documents) and must return claim ids.
  The answer is **rejected and replaced by the deterministic one** if it cites an unknown claim id, returns nothing, or
  contains a number that is in neither the findings nor the question. Responses are cached like all model calls.

**Evaluation** (`evaluate.py`, rubric in `gold.py`): per-question checks of required content, forbidden content, supporting
documents, surfaced ambiguities (e.g. the grey line at the controller, the reset boundary) and abstention for the five
unanswerable questions; plus numeric grounding (no number in an answer that is absent from its cited evidence) and citation
validity. A set of **reworded questions** measures whether answers depend on exact wording.

**Honest limits:**
* The rubric is the author's reading of the sources, not an official answer key. Verify it against the PDFs.
* The deterministic renderers and the rubric were written with sight of the 23 questions, so 100% on the originals is
  expected; the reworded set is the better indication of generalisation, and is still small and author-written.
* Question-intent classification is keyword/regex based; an unseen question type falls back to the generic renderer, or to
  the Gemini composer if enabled.
