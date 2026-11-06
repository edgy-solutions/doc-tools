"""structural.outline: Section pages come from element metadata (contract v3, 4.5).

Pure tests on synthetic element lists, shaped like the measured fixture decks:
a section slide is exactly one ``Title`` at depth 0 holding a numbered heading;
the title slide has two Titles; the agenda is ``Title "Agenda"`` plus depth-1
Titles; a content slide is a Title plus a body.
"""
import re
from types import SimpleNamespace

import pytest

from doc_tools.passes.structural import (
    OutlineBuildError, build_outline, norm_title, outline_from_deck, outline_from_llm,
)
from doc_tools.plugins.models import BaseSection, DocumentNode
from doc_tools.plugins.training import OutlineAugmentation, TrainingPlugin


def el(page, text, typ="Title", depth=0):
    md = {"page_number": page}
    if typ == "Title":
        md["category_depth"] = depth
    return {"type": typ, "text": text, "metadata": md}


def header(page, text):
    return [el(page, text)]


def content(page, title, body="Some body text."):
    return [el(page, title), el(page, body, "NarrativeText")]


def title_slide(page=1):
    return [el(page, "Fluid Power"), el(page, "Course overview", depth=0)]


def agenda(page, heads):
    return [el(page, "Agenda")] + [el(page, h, depth=1) for h in heads]


def flat(sections, parent="C"):
    out = []
    for i, s in enumerate(sections):
        sid = f"{parent}_s{i}"
        out.append((sid, s.title, s.level, s.start_page, s.end_page, parent))
        out += flat(s.subsections, sid)
    return out


def boom():
    raise AssertionError("extract must not be called on the deck path")


# --- deck path --------------------------------------------------------------

def test_nested_four_levels():
    elements = (title_slide(1) + agenda(2, ["1 Hydraulics", "1.1 Pumps"])
                + header(3, "1 Hydraulics") + content(4, "Overview (1)")
                + header(5, "1.1 Pumps") + content(6, "Pump basics (1)")
                + header(7, "1.1.1 Gear Pumps") + content(8, "Gears (1)")
                + header(9, "1.1.1.1 Gear Mesh") + content(10, "Mesh (2)")
                + header(11, "2 Electrical") + content(12, "Circuits"))
    sections, source = build_outline(elements, boom)
    assert source == "deck"
    assert flat(sections) == [
        ("C_s0", "Hydraulics", 1, 3, 10, "C"),
        ("C_s0_s0", "Pumps", 2, 5, 10, "C_s0"),
        ("C_s0_s0_s0", "Gear Pumps", 3, 7, 10, "C_s0_s0"),
        ("C_s0_s0_s0_s0", "Gear Mesh", 4, 9, 10, "C_s0_s0_s0"),
        ("C_s1", "Electrical", 1, 11, 12, "C"),
    ]


def test_nested_empty_section_and_last_page_header():
    elements = (header(1, "1 Safety") + content(2, "Intro")
                + header(3, "1.1 PPE") + content(4, "Gloves")
                + header(5, "1.2 Arc Flash")
                + header(6, "2 Tools") + content(7, "Torque")
                + header(8, "3 Wrap up") + content(9, "Recap")
                + header(10, "4 References"))
    sections, source = build_outline(elements, boom)
    got = {t: (lvl, s, e) for _i, t, lvl, s, e, _p in flat(sections)}
    assert source == "deck"
    assert got["Arc Flash"] == (2, 5, 5)          # empty: ends on its own page
    assert got["PPE"] == (2, 3, 4)
    assert got["Safety"] == (1, 1, 5)
    assert got["References"] == (1, 10, 10)       # last header on the last page
    assert all(e >= s >= 1 for _t, (_l, s, e) in got.items())


def test_numbering_gap_nests_under_nearest_shallower_and_keeps_its_level():
    elements = header(1, "1 Top") + content(2, "x") + header(3, "1.1.1 Deep") + content(4, "y")
    sections, _ = build_outline(elements, boom)
    assert flat(sections) == [("C_s0", "Top", 1, 1, 4, "C"),
                              ("C_s0_s0", "Deep", 3, 3, 4, "C_s0")]


def test_same_title_in_two_sections_gets_distinct_ids_and_pages():
    elements = (header(1, "1 Alpha") + header(2, "1.1 Summary") + content(3, "a")
                + header(4, "2 Beta") + header(5, "2.1 Summary") + content(6, "b"))
    sections, _ = build_outline(elements, boom)
    summaries = [(i, s, e) for i, t, _l, s, e, _p in flat(sections) if t == "Summary"]
    assert summaries == [("C_s0_s0", 2, 3), ("C_s1_s0", 5, 6)]


@pytest.mark.parametrize("slides", [
    content(1, "1 Numbered Title With Body"),                       # Title plus a body
    header(1, "Pumps"),                                              # unnumbered single Title
    [el(1, "1.1 Pumps"), el(1, "Speaker notes.", "NarrativeText")],  # header with a notes element
    [el(1, "1.1 Pumps", depth=1)],                                   # numbered, but depth 1
    title_slide(1),                                                  # two Titles
    agenda(1, ["1 A", "2 B"]),                                       # several elements
    [el(1, "1 Pumps", "NarrativeText")],                             # not a Title
])
def test_not_headers(slides):
    assert outline_from_deck(slides) is None


def test_page_breaks_and_blank_text_are_ignored_when_detecting_a_header():
    page = header(1, "1 Pumps") + [el(1, "", "PageBreak"), el(1, "   ", "NarrativeText")]
    assert [s.title for s in outline_from_deck(page)] == ["Pumps"]


def test_deck_path_is_deterministic():
    elements = header(1, "1 A") + content(2, "x") + header(3, "2 B") + content(4, "y")
    a, _ = build_outline(elements, boom)
    b, _ = build_outline([dict(e) for e in elements], boom)
    assert a == b and flat(a) == flat(b)


# --- LLM path -----------------------------------------------------------------

def sec(title, *subs, level=1, start=99, end=0):
    return {"title": title, "level": level, "start_page": start, "end_page": end,
            "subsections": list(subs)}


def outline_of(*sections):
    return SimpleNamespace(sections=list(sections))


def test_llm_titles_are_anchored_to_element_pages_not_llm_pages():
    elements = (content(1, "Intro") + content(2, "Basics") + content(3, "Advanced")
                + content(4, "Wrap up"))
    out = outline_from_llm(elements, [outline_of(
        sec("Intro", start=3), sec("Basics", start=9), sec("Advanced", start=1),
        sec("Wrap up", start=2))])
    assert [(s.title, s.start_page, s.end_page) for s in out] == [
        ("Intro", 1, 1), ("Basics", 2, 2), ("Advanced", 3, 3), ("Wrap up", 4, 4)]


def test_counter_suffix_and_section_number_match():
    elements = content(1, "Pumps (2)") + content(2, "3.1 Valves")
    out = outline_from_llm(elements, [outline_of(sec("Pumps"), sec("Valves"))])
    assert [(s.title, s.start_page) for s in out] == [("Pumps", 1), ("Valves", 2)]
    assert norm_title("3.1.2  Pumps  (12)") == "pumps"


def test_unanchored_parent_is_dropped_and_its_child_lifted():
    elements = content(1, "Intro") + content(2, "Pumps") + content(3, "Valves")
    out = outline_from_llm(elements, [outline_of(
        sec("Intro"), sec("Not A Slide Title", sec("Pumps", level=2), sec("Valves", level=2)))])
    assert flat(out) == [("C_s0", "Intro", 1, 1, 1, "C"),
                         ("C_s1", "Pumps", 1, 2, 2, "C"),
                         ("C_s2", "Valves", 1, 3, 3, "C")]


def test_a_duplicate_across_chunk_outlines_is_dropped():
    elements = content(1, "Intro") + content(2, "Pumps") + content(3, "Valves")
    out = outline_from_llm(elements, [outline_of(sec("Intro"), sec("Pumps")),
                                      outline_of(sec("Pumps"), sec("Valves"))])
    assert [(s.title, s.start_page) for s in out] == [("Intro", 1), ("Pumps", 2), ("Valves", 3)]


def test_a_title_only_before_the_cursor_is_dropped():
    elements = content(1, "Early") + content(2, "Middle") + content(3, "Late")
    out = outline_from_llm(elements, [outline_of(sec("Middle"), sec("Early"), sec("Late"))])
    assert [(s.title, s.start_page) for s in out] == [("Middle", 2), ("Late", 3)]


def test_llm_titles_are_stripped_and_levels_follow_the_final_tree():
    elements = content(1, "Part") + content(2, "Chapter")
    out = outline_from_llm(elements, [outline_of(sec(" Part ", sec("Chapter", level=2)))])
    assert flat(out) == [("C_s0", "Part", 1, 1, 2, "C"), ("C_s0_s0", "Chapter", 2, 2, 2, "C_s0")]


def test_llm_path_is_deterministic():
    elements = content(1, "A") + content(2, "B")
    ol = [outline_of(sec("A"), sec("B"))]
    assert outline_from_llm(elements, ol) == outline_from_llm(elements, ol)


# --- build failure ----------------------------------------------------------------

def test_extract_raising_is_an_outline_build_error():
    def extract():
        raise RuntimeError("gateway down")
    with pytest.raises(OutlineBuildError, match="gateway down"):
        build_outline(content(1, "Intro"), extract)


def test_one_failed_chunk_of_two_fails_the_build():
    with pytest.raises(OutlineBuildError, match="chunk 2"):
        build_outline(content(1, "Intro"),
                      lambda: ([outline_of(sec("Intro"))], ["chunk 2/2: TimeoutError: slow"]))


def test_a_successful_extract_that_anchors_nothing_is_an_empty_llm_outline():
    assert build_outline(content(1, "Intro"), lambda: ([outline_of(sec("Nowhere"))], [])) == ([], "llm")
    assert build_outline([], lambda: ([outline_of(sec("Nowhere"))], [])) == ([], "llm")


def test_the_import_failure_path_has_no_mock_outline(monkeypatch):
    def fail(self, els, max_chars):
        raise ImportError("no baml")
    monkeypatch.setattr(TrainingPlugin, "execute_global_pass", fail)
    with pytest.raises(OutlineBuildError):
        TrainingPlugin(domain_type="training").process_fulltext(
            "t", "C", {}, elements=content(1, "Intro"))


def test_the_deck_path_never_calls_the_llm(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("LLM path taken")
    monkeypatch.setattr(TrainingPlugin, "execute_global_pass", fail)
    monkeypatch.setattr(TrainingPlugin, "_extract_raw_text_outlines", fail)
    nodes = TrainingPlugin(domain_type="training").process_fulltext(
        "t", "C", {}, elements=header(1, "1 A") + content(2, "x"))
    aug = nodes[0].domain_augmentation
    assert aug.outline_source == "deck" and [s.title for s in aug.sections] == ["A"]


# --- to_graph_queries: the one replace statement -----------------------------------

def _queries(sections, source="deck"):
    node = DocumentNode(
        base_extraction=BaseSection(title="Course", level=0, page_start=0, content="", node_id="course-1"),
        domain_augmentation=OutlineAugmentation(sections=sections, metadata={}, outline_source=source))
    config = SimpleNamespace(graph_node_label="Course", graph_child_label="Slide")
    cypher, _ = TrainingPlugin(domain_type="training").to_graph_queries([node], config)
    return cypher


def _replace(cypher):
    stmts = [q for q in cypher if "Section:" in q["query"]]
    assert len(stmts) == 1, "exactly one Section statement"
    return stmts[0]


def test_replace_statement_shape():
    sections, _ = build_outline(
        header(1, "1 A") + content(2, "x") + header(3, "1.1 B") + header(4, "2 C"), boom)
    q = _replace(_queries(sections))
    text = q["query"]
    assert "DETACH DELETE" in text and "FOREACH" in text
    assert "MATCH (c:Course:TRAINING {id: $course_id})" in text
    assert re.findall(r"DETACH DELETE (\w+)", text) == ["o"]
    assert re.search(r"o1:Section:TRAINING", text) and re.search(r"o2:Section:TRAINING", text)
    for name in ("Slide", "Chunk", "Concept", "CanonicalConcept", "Project", "TargetNode", "User"):
        assert name not in text, name
    assert text.count("Course") == 1                                   # the anchoring MATCH only
    assert "SET c.outline_source = $outline_source" in text
    p = q["params"]
    assert p["course_id"] == "course-1" and p["id_prefix"] == "course-1_s"
    assert p["outline_source"] == "deck"
    rows = p["sections"]
    assert [r["id"] for r in rows] == ["course-1_s0", "course-1_s0_s0", "course-1_s1"]
    assert [r["parent_id"] for r in rows] == ["course-1", "course-1_s0", "course-1"]
    assert all(r["end_page"] >= r["start_page"] >= 1 for r in rows)
    assert all(r["end_page"] != 0 for r in rows)


def test_an_open_ended_section_never_writes_end_page_zero():
    from doc_tools.passes.structural import CourseSection
    q = _replace(_queries([CourseSection(title="T", level=1, start_page=4, end_page=0)], "llm"))
    assert q["params"]["sections"][0]["end_page"] == 4


def test_an_empty_outline_still_emits_the_statement():
    q = _replace(_queries([], "llm"))
    assert q["params"]["sections"] == [] and q["params"]["outline_source"] == "llm"
    assert "DETACH DELETE" in q["query"]


# --- asset level --------------------------------------------------------------------

def test_a_failed_outline_build_fails_the_run_and_replaces_nothing(monkeypatch):
    from doc_tools.assets import semantic_assets as sa
    from tests.test_document_parser_versioning import _FakeS3Client
    from tests.test_index_chunk_require_vector import _manifest
    from tests.test_training_workbench_golden import FakeWeaviate, _graph_run, empty_section_reply

    monkeypatch.setattr("doc_tools.utils.embed.embed_document", lambda t: [0.5] * 768)


    def failing(*a, **k):
        raise OutlineBuildError("1 outline chunk(s) failed: chunk 2/2: boom")

    # The concept calls succeed (with no concepts), so the run reaches the outline
    # check: a failed concept call raises failed:concept_parse first (#180).
    def no_concepts(self, section_text, instructions):
        return empty_section_reply(section_text)

    cid = "sha256:" + "e" * 64
    client, weaviate, holder = _FakeS3Client(), FakeWeaviate(), []
    with pytest.raises(OutlineBuildError, match="left in place"):
        _graph_run(_manifest(client, "training", cid), client, monkeypatch,
                   weaviate=weaviate, reraise=True, fulltext=failing, neo4j_out=holder,
                   extract=no_concepts)
    assert [o["properties"]["chunk_id"] for o in weaviate.objects] == \
        [f"{cid}_p1", f"{cid}_p2", f"{cid}_p3"]
    executed = [c.args[0] for c in holder[0].get_client.return_value.execute_query.call_args_list]
    assert any("MERGE (child:" in q for q in executed), "slide writes are still attempted"
    assert not any("Section" in q and "DETACH DELETE" in q for q in executed)
    assert sa.OutlineBuildError is OutlineBuildError


def test_a_non_training_domain_still_swallows_a_plugin_failure(monkeypatch):
    from tests.test_document_parser_versioning import _FakeS3Client
    from tests.test_index_chunk_require_vector import _manifest
    from tests.test_training_workbench_golden import FakeWeaviate, _graph_run
    from doc_tools.plugins.manufacturing import ManufacturingPlugin

    monkeypatch.setattr("doc_tools.utils.embed.embed_document", lambda t: [0.5] * 768)

    def failing(*a, **k):
        raise OutlineBuildError("not for this domain")

    monkeypatch.setattr(ManufacturingPlugin, "process_fulltext", failing)
    cid = "sha256:" + "f" * 64
    client = _FakeS3Client()
    _graph_run(_manifest(client, "manufacturing", cid), client, monkeypatch,
               weaviate=FakeWeaviate(), reraise=True)
