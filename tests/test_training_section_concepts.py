"""The per-section concept call (contract v4 section 4.6), what it writes, and what it skips.

The one LLM seam is ``TrainingPlugin._extract_section``; every test stubs it.
"""
import re
import threading
import time
from types import SimpleNamespace

import pytest

from doc_tools.baml_client.types import (
    Concept as BConcept, SectionAugmentation, SectionNotes, SlideConcepts,
)
from doc_tools.passes.structural import CourseSection
from doc_tools.plugins.models import BaseSection, DocumentNode
from doc_tools.plugins.training import (
    Concept, OutlineAugmentation, SectionNote, SlideAugmentation, TrainingPlugin,
)
from doc_tools.utils.concept_identity import concept_node_id

CID = "sha256:" + "c" * 64
CONFIG = SimpleNamespace(graph_node_label="Document", graph_child_label="Slide")


def _plugin():
    return TrainingPlugin(domain_type="training")


def _slide(n, concepts=(), figs=()):
    return SlideConcepts(
        slide=n, figure_references=list(figs),
        concepts=[BConcept(name=c[0], salience=c[1], related_terms=list(c[2]) if len(c) > 2 else [])
                  for c in concepts])


def _reply(slides, sections=()):
    return SectionAugmentation(
        slides=list(slides),
        sections=[SectionNotes(section=t, summary=s, objectives=list(o)) for t, s, o in sections])


def _course(texts, sections=(), plugin=None, monkeypatch=None, stub=None):
    plugin = plugin or _plugin()
    monkeypatch.setattr(plugin, "_extract_section", stub)
    chunk_ids = {p: f"{CID}_p{p}" for p in texts}
    return plugin.augment_course(texts, chunk_ids, list(sections), CID)


@pytest.fixture(autouse=True)
def _file_prompts(monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "file")
    monkeypatch.delenv("TRAINING_CONCEPT_CONCURRENCY", raising=False)


def _sec(title, start, end=None, subs=()):
    return CourseSection(title=title, level=1, start_page=start, end_page=end,
                         subsections=list(subs))


def _slides_in(text):
    return [int(n) for n in re.findall(r"=== Slide (\d+) ===", text)]


# ---- the mapping ---------------------------------------------------------------

def test_a_reply_is_mapped_per_slide(monkeypatch):
    def stub(text, instr):
        return _reply([_slide(1, [("Pump", 0.9, ["Pumps"])], figs=["Figure 1"]),
                       _slide(2, [("Valve", 0.4)])])

    res = _course({1: "one", 2: "two"}, monkeypatch=monkeypatch, stub=stub)
    assert not res.failures
    n1, n2 = res.nodes[1], res.nodes[2]
    assert n1.base_extraction.node_id == f"{CID}_p1" and n1.base_extraction.content == "one"
    assert n1.base_extraction.title == "Page 1" and n1.base_extraction.page_start == 1
    c = n1.domain_augmentation.concepts[0]
    assert (c.name, c.salience, c.related_terms) == ("Pump", 0.9, ["Pumps"])
    assert n1.domain_augmentation.figure_references == ["Figure 1"]
    assert n2.domain_augmentation.concepts[0].name == "Valve"
    assert res.calls[0]["pages"] == [1, 2] and res.calls[0]["ok"] and res.calls[0]["attempts"] == 1


def test_the_instructions_are_fetched_once_per_course(monkeypatch):
    plugin = _plugin()
    seen = []
    real = plugin._get_dynamic_prompt
    monkeypatch.setattr(plugin, "_get_dynamic_prompt",
                        lambda **kw: seen.append(kw["prompt_name"]) or real(**kw))
    _course({p: "x" for p in range(1, 20)}, plugin=plugin, monkeypatch=monkeypatch,
            stub=lambda t, i: _reply([_slide(n) for n in _slides_in(t)]))
    assert seen == ["training_section_instructions"]


def test_a_missing_slide_is_retried_once_then_fails_that_page_only(monkeypatch):
    calls = []

    def stub(text, instr):
        calls.append(_slides_in(text))
        return _reply([_slide(1, [("A", 0.5)]), _slide(3, [("C", 0.5)])])

    res = _course({1: "a", 2: "b", 3: "c"}, monkeypatch=monkeypatch, stub=stub)
    assert len(calls) == 2
    assert set(res.nodes) == {1, 3}
    assert res.failures == {2: "MissingSlideError: no entry for slide 2 in the section reply"}
    assert res.calls[0]["attempts"] == 2 and res.calls[0]["ok"] is False


def test_a_missing_slide_that_the_retry_supplies_is_no_failure(monkeypatch):
    calls = []

    def stub(text, instr):
        calls.append(1)
        slides = [_slide(1)] if len(calls) == 1 else [_slide(1), _slide(2)]
        return _reply(slides)

    res = _course({1: "a", 2: "b"}, monkeypatch=monkeypatch, stub=stub)
    assert set(res.nodes) == {1, 2} and not res.failures and res.calls[0]["attempts"] == 2


def test_an_exception_fails_every_page_of_the_call_after_one_retry(monkeypatch):
    calls = []

    def stub(text, instr):
        calls.append(1)
        raise ValueError("boom")

    res = _course({1: "a", 2: "b"}, monkeypatch=monkeypatch, stub=stub)
    assert len(calls) == 2
    assert not res.nodes
    assert res.failures == {1: "ValueError: boom", 2: "ValueError: boom"}


def test_a_failed_call_does_not_take_down_another_call(monkeypatch):
    def stub(text, instr):
        if 1 in _slides_in(text):
            raise ValueError("boom")
        return _reply([_slide(n) for n in _slides_in(text)])

    res = _course({p: "x" for p in range(1, 10)}, monkeypatch=monkeypatch, stub=stub)
    assert set(res.failures) == set(range(1, 6))  # 9 slides: calls of 5 and 4
    assert set(res.nodes) == set(range(6, 10))


def test_extra_and_duplicate_reply_entries(monkeypatch):
    def stub(text, instr):
        return _reply([_slide(1, [("First", 0.5)]), _slide(1, [("Second", 0.5)]), _slide(99)])

    res = _course({1: "a"}, monkeypatch=monkeypatch, stub=stub)
    assert [c.name for c in res.nodes[1].domain_augmentation.concepts] == ["First"]
    assert 99 not in res.nodes and not res.failures


def test_salience_outside_unit_range_is_clamped_not_fatal(monkeypatch):
    def stub(text, instr):
        return _reply([_slide(1, [("Hi", 1.7), ("Lo", -0.2)]), _slide(2, [("Fine", 0.5)])])

    res = _course({1: "a", 2: "b"}, monkeypatch=monkeypatch, stub=stub)
    assert not res.failures
    sal = {c.name: c.salience for c in res.nodes[1].domain_augmentation.concepts}
    assert sal == {"Hi": 1.0, "Lo": 0.0}


def test_concurrency_assembles_results_in_call_order(monkeypatch):
    monkeypatch.setenv("TRAINING_CONCEPT_CONCURRENCY", "3")
    active, peak, lock = 0, 0, threading.Lock()

    def stub(text, instr):
        nonlocal active, peak
        first = _slides_in(text)[0]
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.15 if first == 1 else 0.01)  # the first call finishes LAST
        with lock:
            active -= 1
        return _reply([_slide(n) for n in _slides_in(text)])

    texts = {p: "x" for p in range(1, 25)}
    res = _course(texts, monkeypatch=monkeypatch, stub=stub)
    assert peak > 1
    assert [c["pages"][0] for c in res.calls] == [1, 9, 17]
    assert set(res.nodes) == set(texts) and not res.failures


def test_no_texts_makes_no_call(monkeypatch):
    def stub(text, instr):
        raise AssertionError("no call expected")

    res = _course({}, monkeypatch=monkeypatch, stub=stub)
    assert not res.nodes and not res.failures and not res.calls


# ---- section notes -------------------------------------------------------------

def test_notes_pair_by_position(monkeypatch):
    sections = [_sec("A", 1, 2), _sec("B", 3, 3)]

    def stub(text, instr):
        return _reply([_slide(n) for n in _slides_in(text)],
                      [("whatever the model wrote", "About A.", ["Do a"]),
                       ("another title", "About B.", [])])

    res = _course({1: "a", 2: "b", 3: "c"}, sections, monkeypatch=monkeypatch, stub=stub)
    assert res.section_notes[f"{CID}_s0"] == SectionNote(summary="About A.", objectives=["Do a"])
    assert res.section_notes[f"{CID}_s1"] == SectionNote(summary="About B.", objectives=[])


def test_notes_fall_back_to_pairing_by_title_when_counts_differ(monkeypatch):
    sections = [_sec("Alpha  Pumps", 1, 1), _sec("Beta", 2, 2)]

    def stub(text, instr):
        # one note too many, out of order, with whitespace and case differences
        return _reply([_slide(n) for n in _slides_in(text)],
                      [("beta", "About beta.", ["Do b"]),
                       ("Stray", "dropped", ["dropped"]),
                       ("alpha pumps", "About alpha.", [])])

    res = _course({1: "a", 2: "b"}, sections, monkeypatch=monkeypatch, stub=stub)
    assert res.section_notes[f"{CID}_s0"].summary == "About alpha."
    assert res.section_notes[f"{CID}_s1"].objectives == ["Do b"]
    assert len(res.section_notes) == 2


def test_unsectioned_runs_get_no_note_and_a_bad_note_never_fails(monkeypatch):
    def stub(text, instr):
        return _reply([_slide(n) for n in _slides_in(text)], [("(no section)", "x", ["y"])])

    res = _course({1: "a", 2: "b"}, [], monkeypatch=monkeypatch, stub=stub)
    assert res.section_notes == {} and not res.failures and set(res.nodes) == {1, 2}


def test_a_split_section_merges_its_notes_in_page_order(monkeypatch):
    sections = [_sec("Long", 1, 20)]

    def stub(text, instr):
        first = _slides_in(text)[0]
        return _reply([_slide(n) for n in _slides_in(text)],
                      [("Long", f"Part {first}.", ["Do x", f"Do {first}"])])

    res = _course({p: "x" for p in range(1, 21)}, sections, monkeypatch=monkeypatch, stub=stub)
    note = res.section_notes[f"{CID}_s0"]
    assert note.summary == "Part 1. Part 8. Part 15."
    assert note.objectives == ["Do x", "Do 1", "Do 8", "Do 15"]


def test_a_section_interrupted_by_a_child_merges_both_halves(monkeypatch):
    sections = [_sec("Parent", 1, 6, [_sec("Child", 3, 4)])]

    def stub(text, instr):
        return _reply([_slide(n) for n in _slides_in(text)],
                      [("Parent", "P1", ["a"]), ("Child", "C", []), ("Parent", "P2", ["A"])])

    res = _course({p: "x" for p in range(1, 7)}, sections, monkeypatch=monkeypatch, stub=stub)
    parent = res.section_notes[f"{CID}_s0"]
    assert parent.summary == "P1 P2" and parent.objectives == ["a"]  # de-duplicated, casefolded
    assert res.section_notes[f"{CID}_s0_s0"].summary == "C"


def test_a_note_with_no_summary_adds_no_blank_to_the_join(monkeypatch):
    sections = [_sec("Long", 1, 10)]

    def stub(text, instr):
        first = _slides_in(text)[0]
        return _reply([_slide(n) for n in _slides_in(text)],
                      [("Long", None if first == 1 else "Only.", [])])

    res = _course({p: "x" for p in range(1, 11)}, sections, monkeypatch=monkeypatch, stub=stub)
    assert res.section_notes[f"{CID}_s0"].summary == "Only."


# ---- the single-slide path -----------------------------------------------------

def test_augment_is_a_one_slide_unsectioned_call(monkeypatch):
    plugin = _plugin()
    seen = []

    def stub(text, instr):
        seen.append(text)
        return _reply([_slide(4, [("Torque", 0.8, ["Twist"])])])

    monkeypatch.setattr(plugin, "_extract_section", stub)
    sec = BaseSection(title="Page 4", level=1, page_start=4, content="body", node_id="s4")
    node = plugin.augment(sec)
    assert seen == ["=== Section: (no section) ===\n\n=== Slide 4 ===\nbody"]
    assert node.domain_augmentation.concepts[0].related_terms == ["Twist"]

    monkeypatch.setattr(plugin, "_extract_section", lambda t, i: _reply([_slide(9)]))
    with pytest.raises(ValueError):
        plugin.augment(sec)


# ---- the graph -----------------------------------------------------------------

def _graph(nodes, doc_id=CID):
    cypher, _ = _plugin().to_graph_queries(nodes, CONFIG, doc_id=doc_id)
    return cypher


def _slide_node(n, concepts):
    return DocumentNode(
        base_extraction=BaseSection(title=f"Page {n}", level=1, page_start=n, content="x",
                                    node_id=f"{CID}_p{n}"),
        domain_augmentation=SlideAugmentation(concepts=concepts))


def test_teaches_carries_related_terms_stripped(monkeypatch):
    q = [q for q in _graph([_slide_node(1, [Concept(name="Pump", salience=0.5,
                                                    related_terms=[" Pumps ", "", "  "])])])
         if "TEACHES" in q["query"]][0]
    assert "t.related_terms = $c_related_terms" in q["query"]
    assert q["params"]["c_related_terms"] == ["Pumps"]


def test_alias_of_comes_after_every_teaches_and_follows_the_rule():
    nodes = [
        _slide_node(1, [Concept(name="Pump", salience=0.5,
                                related_terms=["Pumps", "PUMP", "Pump  ", "Centrifugal Pump"]),
                        Concept(name="Valve", salience=0.5, related_terms=["Pump"])]),
        _slide_node(2, [Concept(name="Pump", salience=0.5, related_terms=["Pumps"])]),
    ]
    cypher = _graph(nodes)
    kinds = ["alias" if "ALIAS_OF" in q["query"] else "teaches" if "TEACHES" in q["query"] else "other"
             for q in cypher]
    first_alias = kinds.index("alias")
    assert "teaches" not in kinds[first_alias:]
    assert kinds.count("teaches") == 3
    aliases = [q for q in cypher if "ALIAS_OF" in q["query"]]
    pairs = [(q["params"]["from_id"], q["params"]["to_id"]) for q in aliases]
    pump, valve = (concept_node_id("TRAINING", n) for n in ("Pump", "Valve"))
    assert pairs == [(pump, concept_node_id("TRAINING", "Pumps")),
                     (pump, concept_node_id("TRAINING", "Centrifugal Pump")),
                     (valve, pump)]  # "PUMP"/"Pump  " normalise to the concept itself; no repeat
    q = aliases[0]
    assert "MATCH (b:Concept:TRAINING {id: $to_id})" in q["query"]
    assert "MERGE (a)-[r:ALIAS_OF]->(b)" in q["query"]
    assert "ON CREATE SET r.status = 'candidate', r.source = 'related_terms', r.course_id = $course_id" in q["query"]
    assert q["params"]["course_id"] == CID


def test_section_rows_carry_summary_and_objectives():
    aug = OutlineAugmentation(
        sections=[_sec("A", 1, 2, [_sec("A1", 1, 1)]), _sec("B", 3, 3)], outline_source="llm",
        section_notes={f"{CID}_s0": SectionNote(summary="About A.", objectives=["Do a"]),
                       f"{CID}_s0_s0": SectionNote()})
    node = DocumentNode(
        base_extraction=BaseSection(title="Course Outline", level=0, page_start=0, content="",
                                    node_id=CID),
        domain_augmentation=aug)
    q = [q for q in _graph([node]) if "UNWIND $sections" in q["query"]][0]
    assert "s.summary = row.summary, s.objectives = row.objectives" in q["query"]
    rows = {r["id"]: r for r in q["params"]["sections"]}
    assert list(rows) == [f"{CID}_s0", f"{CID}_s0_s0", f"{CID}_s1"]
    assert (rows[f"{CID}_s0"]["summary"], rows[f"{CID}_s0"]["objectives"]) == ("About A.", ["Do a"])
    assert (rows[f"{CID}_s0_s0"]["summary"], rows[f"{CID}_s0_s0"]["objectives"]) == (None, [])
    assert (rows[f"{CID}_s1"]["summary"], rows[f"{CID}_s1"]["objectives"]) == (None, [])


# ---- the asset -----------------------------------------------------------------

def _outline_node(doc_id):
    aug = OutlineAugmentation(sections=[_sec("Intro", 1, 2), _sec("Wrap", 3, 3)],
                              outline_source="llm")
    return DocumentNode(
        base_extraction=BaseSection(title="Course Outline", level=0, page_start=0, content="",
                                    node_id=doc_id),
        domain_augmentation=aug)


def _asset_run(monkeypatch, outline_ok):
    from doc_tools.passes.structural import OutlineBuildError
    from tests.test_document_parser_versioning import _FakeS3Client
    from tests.test_index_chunk_require_vector import _manifest
    from tests.test_training_workbench_golden import FakeWeaviate, _graph_run

    monkeypatch.setattr("doc_tools.utils.embed.embed_document", lambda t: [0.5] * 768)
    cid = "sha256:" + "d" * 64

    def extract(self, text, instr):
        slides = _slides_in(text)
        return _reply([_slide(n, [(f"Concept {n}", 0.5)]) for n in slides],
                      [("Intro", "About intro.", ["Explain intro"]), ("Wrap", None, [])]
                      if 1 in slides else [])

    def fulltext(self, *a, **k):
        if not outline_ok:
            raise OutlineBuildError("1 outline chunk(s) failed: boom")
        return [_outline_node(cid)]

    client, weaviate, holder = _FakeS3Client(), FakeWeaviate(), []
    try:
        _graph_run(_manifest(client, "training", cid), client, monkeypatch, weaviate=weaviate,
                   reraise=True, fulltext=lambda *a, **k: fulltext(None, *a, **k),
                   neo4j_out=holder, extract=extract)
    except OutlineBuildError:
        assert not outline_ok
    return cid, weaviate, holder[0]


def test_slides_carry_chunk_kind_and_section_objects_follow_the_outline(monkeypatch):
    cid, weaviate, neo4j = _asset_run(monkeypatch, outline_ok=True)
    by_id = {o["properties"]["chunk_id"]: o["properties"] for o in weaviate.objects}
    slides = [p for p in by_id.values() if p["chunk_kind"] == "slide"]
    assert sorted(p["chunk_id"] for p in slides) == [f"{cid}_p{n}" for n in (1, 2, 3)]
    sec = by_id[f"{cid}_s0"]
    assert sec["chunk_kind"] == "section" and sec["section_id"] == f"{cid}_s0"
    assert sec["page"] == 1 and sec["heading"] == "Intro" and sec["domain"] == "TRAINING"
    assert sec["text"] == "Intro\n\nAbout intro.\n\nObjectives:\n- Explain intro"
    assert f"{cid}_s1" not in by_id, "a section with no notes gets no object"
    weaviate.data.delete_many.assert_called_once()
    # the notes reached the Section rows of the replace statement
    q = [c.args for c in neo4j.get_client.return_value.execute_query.call_args_list
         if "UNWIND $sections" in c.args[0]][0]
    assert q[1]["sections"][0]["summary"] == "About intro."


def test_no_section_objects_when_the_outline_was_not_built(monkeypatch):
    cid, weaviate, _neo4j = _asset_run(monkeypatch, outline_ok=False)
    kinds = {o["properties"]["chunk_id"]: o["properties"]["chunk_kind"] for o in weaviate.objects}
    assert set(kinds.values()) == {"slide"} and len(kinds) == 3
    weaviate.data.delete_many.assert_not_called()


def test_other_domains_write_no_chunk_kind(monkeypatch):
    from doc_tools.assets import semantic_assets as sa

    src = open(sa.__file__, encoding="utf-8").read()
    # the property is added only inside the TRAINING branch
    assert '**({"chunk_kind": "slide"} if domain_label == "TRAINING" else {})' in src
