"""Layer 1: entities, aliases and the reasoning behind every merge / non-merge.

Three relations are kept DISTINCT because mixing them up is the main trap in this corpus:
  same_as / variant_of   one physical thing, two labels      (HPU = HP unit; 'P.S.04-A' ~ PS-04A)
  superseded_by          related by replacement, NOT the same (PS-04 -> PS-04A)
  distinct_from          look-alike, unrelated                (PS-04 vs PS-40)
  corresponds_to         wiring/drawing designation of a thing (PRESSURE XDCR at J-14/TB-7 -> PS-04A)
  related_not_same       shares a name fragment, different part (PLC-03 I/O RACK vs PLC-03 controller)
  unregistered           appears in a drawing/slide but not in the register (e.g. Auxiliary Reservoir)

Rejected merges are stored too (decision='rejected'), so 'why are these NOT the same?' is answerable.
Authority: the component register. Text evidence can ADD aliases but never override the register.
"""
from __future__ import annotations

import re

from .kb_schema import Entity, AliasDecision

ABBREV = {"XFMR": "TRANSFORMER"}


def norm_id(s: str) -> str:
    """Punctuation/space/case-insensitive identifier form. 'P.S.04-A' -> 'PS04A'. NEVER a prefix match:
    'PS04' != 'PS04A', which is exactly what keeps PS-04 and PS-04A apart."""
    return re.sub(r"[^A-Za-z0-9]", "", s).upper()


def norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s.lower())).strip()


def _words(s: str) -> set:
    out = set()
    for w in re.findall(r"[A-Za-z]+", s):
        out.add(ABBREV.get(w.upper(), w.upper()))
    return out


class EntityIndex:
    def __init__(self):
        self.entities: dict[str, Entity] = {}
        self.decisions: list[AliasDecision] = []
        self.collisions: list[str] = []
        self._by_name: dict[str, tuple[str, str]] = {}   # norm_name -> (entity id, surface)
        self._by_nid: dict[str, tuple[str, str]] = {}    # norm_id   -> (entity id, surface)

    # ---- building
    def add_entity(self, e: Entity) -> None:
        self.entities[e.id] = e
        for surface in [e.id, e.name, *e.aliases]:
            self._register(e.id, surface)

    def _register(self, eid: str, surface: str) -> None:
        for table, key in ((self._by_name, norm_name(surface)), (self._by_nid, norm_id(surface))):
            if not key:
                continue
            if key in table and table[key][0] != eid:
                self.collisions.append(f"'{surface}' collides: {table[key][0]} vs {eid}")
            else:
                table[key] = (eid, surface)

    def add_alias(self, eid: str, surface: str) -> None:
        if surface not in self.entities[eid].aliases:
            self.entities[eid].aliases.append(surface)
        self._register(eid, surface)

    def decide(self, surface, entity_id, relation, decision, reason, evidence=(), confidence=1.0) -> AliasDecision:
        d = AliasDecision(surface, entity_id, relation, decision, reason, list(evidence), confidence)
        self.decisions.append(d)
        return d

    # ---- lookup
    def resolve(self, surface: str) -> AliasDecision | None:
        """Resolve a label to a registered entity, or None. Does not record anything."""
        s = surface.strip()
        hit = self._by_name.get(norm_name(s))
        if hit:
            return AliasDecision(s, hit[0], "same_as", "accepted",
                                 f"exact match (case/spacing-insensitive) to '{hit[1]}' in the register", [], 1.0)
        hit = self._by_nid.get(norm_id(s))
        if hit:
            return AliasDecision(s, hit[0], "variant_of", "accepted",
                                 f"identifier differs from '{hit[1]}' only in punctuation/spacing/case "
                                 f"(normalised both = {norm_id(s)}); not a prefix match", [], 0.9)
        return None

    def resolve_node(self, label: str) -> tuple[str, AliasDecision]:
        """Resolve a DRAWING label to an entity id, creating an unregistered diagram entity if needed.
        Labels that merely CONTAIN a registered ID plus extra words are NOT merged unless the extra
        words equal that entity's name ('IV-21 VALVE DRIVER' is not valve IV-21)."""
        label = re.sub(r"\s+", " ", label).strip()
        base = re.sub(r"\s*\([^)]*\)", "", label).strip()
        paren = re.findall(r"\(([^)]*)\)", label)
        for d in self.decisions:                      # drawing designation explicitly tied to a register entity
            if d.surface == label and d.relation == "corresponds_to" and d.decision == "accepted":
                return d.entity_id, d
        for cand in [label, base, *paren]:
            d = self.resolve(cand)
            if d:
                return d.entity_id, self.decide(label, d.entity_id, d.relation, "accepted", d.reason, [], d.confidence)
        # contains a registered ID?
        tokens = sorted(self.entities, key=len, reverse=True)
        for eid in tokens:
            pat = r"(?<![A-Za-z0-9])" + re.escape(eid) + r"(?![A-Za-z0-9])"
            if re.search(pat, label, re.I):
                leftover = _words(re.sub(r"\S*\d\S*", " ", re.sub(pat, " ", label, flags=re.I)))
                name_words = _words(re.sub(r"\S*\d\S*", " ", self.entities[eid].name))
                if leftover and leftover == name_words:
                    return eid, self.decide(label, eid, "variant_of", "accepted",
                                            f"label = ID {eid} + the register name words {sorted(name_words)} "
                                            "(abbreviations expanded)", [], 0.8)
                nid = self._new_diagram_entity(label)
                self.decide(label, eid, "related_not_same", "rejected",
                            f"label contains '{eid}' but adds '{' '.join(sorted(leftover))}', which is not the register "
                            f"name of {eid} ('{self.entities[eid].name}'): a different part, not merged", [], 0.8)
                return nid, self.decisions[-1]
        nid = self._new_diagram_entity(label)
        return nid, self.decide(label, nid, "unregistered", "accepted",
                                "no register entity matches; kept as an unregistered, drawing-only part", [], 1.0)

    def _new_diagram_entity(self, label: str) -> str:
        eid = label.strip()
        if eid not in self.entities:
            self.entities[eid] = Entity(eid, eid, "diagram_part", registered=False)
            self._register(eid, eid)
        return eid


# ---------------------------------------------------------------------------------------------
# text evidence that ADDS aliases (never overrides the register)
# (doc, regex, entity, surface, relation, confidence, reason)
TEXT_ALIAS_RULES = [
    ("operator_manual", r"Hydraulic Unit or the HP unit.*same physical assembly", "HPU", "HP unit", "same_as", 1.0,
     "operator manual states 'All three terms refer to the same physical assembly'"),
    ("operator_manual", r"Hydraulic Unit or the HP unit.*same physical assembly", "HPU", "Hydraulic Unit", "same_as", 1.0,
     "operator manual states 'All three terms refer to the same physical assembly'"),
    ("maintenance_manual", r"Hydraulic Power Pack \(HPU\)", "HPU", "Hydraulic Power Pack", "same_as", 1.0,
     "maintenance manual writes 'Hydraulic Power Pack (HPU)'"),
    ("legacy_manual_v1", r"Hydraulic Power Pack \(HPU\)", "HPU", "Hydraulic Power Pack", "same_as", 1.0,
     "legacy manual writes 'Hydraulic Power Pack (HPU)'"),
    ("training_slides", r"\"hydraulic pack\".*same thing", "HPU", "hydraulic pack", "same_as", 0.8,
     "training slide says techs call the HPU the 'hydraulic pack' - 'same thing' (secondary source, informal)"),
    ("wiring_diagram", r"HPU discharge pressure transducer described elsewhere as PS-04A", "PS-04A",
     "PRESSURE XDCR (field device)", "corresponds_to", 0.95,
     "wiring drawing note: the device at J-14 / TB-7 is 'the HPU discharge pressure transducer described elsewhere "
     "as PS-04A'; the drawing uses the wiring designation only"),
    ("electrical_diagram", r"TB-7 REF: PRESSURE XDCR LOOP", "PS-04A", "TB-7 REF: PRESSURE XDCR LOOP",
     "corresponds_to", 0.85, "electrical drawing references TB-7 for the pressure transducer loop; register says "
     "TB-7 'corresponds to the PS-04A signal loop' (TB-7 itself is a terminal block, a separate entity)"),
]


def build_index(segs) -> EntityIndex:
    idx = EntityIndex()
    reg = [s for s in segs if s.doc_id == "component_register" and s.kind == "table_row"]
    for s in reg:
        c = {re.sub(r"\s+", " ", k): v for k, v in s.data["cells"].items()}
        cid = next(v for k, v in c.items() if k.startswith("Component ID")).strip()
        name = c.get("Common Name", cid)
        aliases = [a.strip() for a in re.split(r"[;,]", c.get("Known Aliases", "")) if a.strip() not in ("", "—", "-")]
        etype = "alarm" if name.lower().startswith("alarm:") else "component"
        idx.add_entity(Entity(cid, name, etype, aliases=list(aliases), location=c.get("Location"),
                              status=c.get("Status"), notes=c.get("Notes"), evidence=[s.segment_id]))
        for a in aliases:
            idx.decide(a, cid, "same_as", "accepted", "listed under 'Known Aliases' in the component register",
                       [s.segment_id], 1.0)

    # relations stated in register notes
    for s in reg:
        c = {re.sub(r"\s+", " ", k): v for k, v in s.data["cells"].items()}
        cid = next(v for k, v in c.items() if k.startswith("Component ID")).strip()
        note = re.sub(r"\s+", " ", c.get("Notes", ""))
        if m := re.search(r"Superseded by (\S+?) effective software rev ([\d.]+)", note):
            new = m.group(1)
            idx.decide(cid, new, "superseded_by", "accepted",
                       f"register: {cid} superseded by {new} effective software revision {m.group(2)} (ECN-1042)",
                       [s.segment_id], 1.0)
            idx.decide(cid, new, "same_as", "rejected",
                       f"{cid} and {new} are separate register rows with different status; ECN-1042 calls {new} "
                       "'not a form-fit-function replacement': related by replacement, not the same component",
                       [s.segment_id], 1.0)
        if "NOT related" in note and (m := re.search(r"confuse with ([^.]+)", note)):
            for other in [x.strip() for x in m.group(1).split("/")]:
                if other in idx.entities:
                    idx.decide(cid, other, "distinct_from", "accepted",
                               f"register note on {cid}: 'NOT related to the HPU discharge circuit'; located "
                               f"'{idx.entities[cid].location}' vs '{idx.entities[other].location}'", [s.segment_id], 1.0)
                    idx.decide(cid, other, "same_as", "rejected",
                               f"{cid} ({idx.entities[cid].location}) and {other} are explicitly unrelated look-alikes",
                               [s.segment_id], 1.0)

    # aliases from other documents
    for doc, pat, eid, surface, rel, conf, why in TEXT_ALIAS_RULES:
        hits = [s for s in segs if s.doc_id == doc and re.search(pat, re.sub(r"\s+", " ", s.text), re.I)]
        if not hits or eid not in idx.entities:
            continue
        if rel == "same_as":
            idx.add_alias(eid, surface)
        idx.decide(surface, eid, rel, "accepted", why, [h.segment_id for h in hits[:2]], conf)

    # tags read off screens / scans
    for s in segs:
        if s.kind in ("vision_field", "ocr_text") and re.search(r"\btag\b", (s.data.get("label") or s.text), re.I):
            val = (s.data.get("value") or s.text.split(":")[-1]).strip()
            d = idx.resolve(val)
            if d:
                idx.decide(val, d.entity_id, d.relation, "accepted",
                           f"tag read from {s.doc_id}: {d.reason}", [s.segment_id], d.confidence * s.confidence)
    return idx
