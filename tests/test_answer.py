"""Answer-layer tests: entity linking in questions, the answer layer, the Gemini-composer guardrails, and the full evaluation."""
import pytest
from pathlib import Path

from aegis_kb.answer import answer_question, build_prompt, View, compose_llm, R
from aegis_kb.build_kb import build
from aegis_kb.evaluate import metrics, run
from aegis_kb.retrieve import Retriever, Retrieval
from test_kb import DATA, segments

pytestmark = pytest.mark.skipif(not DATA.exists(), reason="dataset not in data/raw/")
_s = {}


@pytest.fixture(scope="module")
def env():
    if not _s:
        segs = segments()
        _s["segs"], _s["kb"] = {x.segment_id: x for x in segs}, build(segs)
        _s["rt"] = Retriever(_s["kb"])
    return _s["kb"], _s["segs"], _s["rt"]


def ask(env, q, llm=None):
    kb, segs, rt = env
    return answer_question(q, kb, segs, rt, llm)


# ---------------- entity linking inside questions ----------------
def test_linking_does_not_match_ps04_inside_ps04a(env):
    rt = env[2]
    assert rt.link_entities("Is PS-04 the same component as PS-04A?") == ["PS-04", "PS-04A"]
    assert rt.link_entities("What about PS04A?") == ["PS-04A"]
    assert rt.link_entities("P.S.04-A reading") == ["PS-04A"]


def test_linking_aliases_and_config_keys(env):
    rt = env[2]
    assert "HPU" in rt.link_entities("What is the hydraulic pack pressure?")
    assert "PLC-03" in rt.link_entities("connect to the HCS controller")
    assert rt.link_entities("what is sensor_ps04a_threshold_bar") == ["PS-04A"]


# ---------------- the evaluation ----------------
def test_full_evaluation_original_and_reworded(env):
    kb, segs, _ = env
    rows = run(kb, segs)
    m = metrics(rows)
    failed = [(r["id"], r["set"], r["score"]["missing"], r["score"]["forbidden_hit"]) for r in rows if not r["score"]["pass"]]
    assert not failed, failed
    assert m["original_unanswerable_abstention"]["passed"] == 5
    assert m["numeric_grounding_rate"] == 1.0, [(r["id"], r["score"]["ungrounded_numbers"]) for r in rows
                                                if r["score"]["ungrounded_numbers"]]
    assert m["citation_validity_rate"] == 1.0


def test_every_answer_cites_segments_that_exist(env):
    kb, segs, _ = env
    for q in ("Is PS-04 the same as PS-40?", "What is the MTBF of valve IV-21?", "Which alarm is associated with a pressure "
                                                                                 "sensor reading below 150 bar?"):
        a = ask(env, q)
        assert a["evidence"] and all(e["segment_id"] in segs for e in a["evidence"])


def test_unanswerable_questions_never_invent_values(env):
    a = ask(env, "What is the maximum continuous operating temperature of PS-04A?")
    assert a["intent"] == "gap" and "cannot be determined" in a["answer"]
    assert not any(e["role"] == "supports" and "°" in e["snippet"] for e in a["evidence"])
    assert any(e["role"] == "searched_not_answering" and e["doc_id"] == "hydraulic_fluid_sds" for e in a["evidence"])


def test_unknown_question_falls_back_honestly(env):
    a = ask(env, "How many fasteners secure the access panel on Line 9 units?")
    assert a["intent"] in ("generic", "gap") and "No specialised answer pattern" in a["answer"] or a["intent"] == "gap"


def test_low_trust_note_is_caveated_not_used_as_the_answer(env):
    a = ask(env, "What is the current normal operating pressure for the HPU, and under what conditions does that apply?")
    assert "200 bar" in a["answer"] and "175" not in a["answer"] and any("175" in c for c in a["caveats"])


# ---------------- Gemini composer guardrails (fake model) ----------------
class FakeLLM:
    def __init__(self, resp):
        self.resp, self.prompts = resp, []

    def generate_json(self, prompt, image=None, mime=None):
        self.prompts.append(prompt)
        return self.resp


def test_valid_llm_answer_is_accepted_and_prompt_contains_only_findings(env):
    kb, segs, rt = env
    base = ask(env, "What is the current normal operating pressure for the HPU, and under what conditions does that apply?")
    cid = base["claims"][0]
    llm = FakeLLM({"answer": "It is 200 bar on software 3.2 or later; earlier units used 180 bar.", "used_claim_ids": [cid],
                   "caveats": []})
    a = ask(env, "What is the current normal operating pressure for the HPU, and under what conditions does that apply?", llm)
    assert a["mode"] == "llm" and a["claims"] == [cid]
    p = llm.prompts[0]
    assert "FINDINGS:" in p and "QUESTION:" in p and "[C" in p
    assert "Hydraulic Power Unit (HPU), which supplies pressurized fluid" not in p        # raw corpus text never sent


@pytest.mark.parametrize("resp,why", [
    ({"answer": "It is 250 bar.", "used_claim_ids": ["C001"]}, "ungrounded numbers"),
    ({"answer": "It is 200 bar.", "used_claim_ids": ["C999"]}, "unknown claim ids"),
    ({"answer": "", "used_claim_ids": []}, "empty"),
    (None, "no response"),
])
def test_bad_llm_answers_fall_back_to_deterministic(env, resp, why):
    a = ask(env, "What is the current normal operating pressure for the HPU, and under what conditions does that apply?",
            FakeLLM(resp))
    assert a["mode"] == "deterministic" and why in a["llm_rejected"] and "200 bar" in a["answer"]
