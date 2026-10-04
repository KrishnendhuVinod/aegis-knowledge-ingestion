# Knowledge representation

Three layers. Each layer only ever points *down* at the one beneath it, so any answer can be
traced to a page/cell/line in a source file.

```
Layer 2  CLAIMS + CONFLICTS      (implemented)  what we believe, under which conditions, with how much support
Layer 1  ENTITIES + ALIASES      (implemented)    what the things are, and why two labels are (or are not) the same thing
Layer 0  SEGMENTS                (implemented)  what each source literally says, and exactly where
```

## Layer 0 - Segment (implemented: `src/aegis_kb/schema.py`)

| field | meaning |
|---|---|
| `segment_id` | stable id `<doc_id>::<nnn>`; deterministic parsing => same ids every run |
| `doc_id` | key into the source registry (`sources.py`): trust tier, role, software-revision scope |
| `kind` | heading, paragraph, bullet, table_row, kv, json_leaf, slide_text, footnote, metadata, diagram_node/edge/legend, ocr_text, vision_* |
| `text` | readable rendering |
| `location` | page+section / sheet+row / slide+shape / json_path / pixel xy ... whatever pinpoints it |
| `method` | `deterministic` \| `ocr` \| `vision_llm` |
| `confidence` | how faithfully we **read** the source (0-1). Not how true the content is |
| `data` | structured payload: table cells, list items, edge endpoints, emphasis spans, repairs applied |

Two numbers are kept apart on purpose: **reading confidence** (per segment) and **source trust**
(per document, in the registry). A clean read of a field note is still low trust; a noisy read of an
official record is still high trust.

## Layer 1 - Entities and aliases (implemented: `entities.py`)

`Entity(id, canonical_name, type, status)` plus `Alias(entity_id, surface_form, evidence_segment_ids,
decision, reason)`. Three relation types, kept distinct because conflating them is the main trap:

* `same_as`       HPU = Hydraulic Unit = HP unit = Hydraulic Power Pack (register aliases column + manual statement)
* `superseded_by` PS-04 -> PS-04A (related by replacement, **not** the same component; ECN-1042)
* `distinct_from` PS-04 vs PS-40 (register says "NOT related"; different location)

Every alias decision stores its evidence and a one-line reason. Rejected merges are stored too.

## Layer 2 - Claims and conflicts (implemented: `extractors.py`, `conflicts.py`, `gaps.py`)

`Claim(subject_entity, predicate, value, unit, applies_when, source_segments[], trust, status)`

`applies_when` is a first-class condition, e.g. `sw_revision >= 3.2`. That is how
"180 bar" and "200 bar" coexist **without** being a conflict: they are different claims under
disjoint conditions. A `Conflict` record is created only when two claims have overlapping
conditions and different values, and it stores both sides plus the evidence (nothing is silently
picked). Absence is represented too: `Gap(question_pattern, searched_in, finding)` records that
we looked and the corpus does not say (e.g. no MTBF for IV-21 anywhere).

## Answer layer (implemented: `retrieve.py`, `answer.py`, `evaluate.py`)

Question -> entity linking -> intent -> renderer over claims -> `{answer, caveats, claims, evidence[], conflicts[], gaps[]}`.
Evidence roles: `supports` (cited by a used claim), `context` (what an "I don't know" was checked against, e.g. the register
row of the asked-about component), `searched_not_answering` (segments that matched loosely and were rejected).
