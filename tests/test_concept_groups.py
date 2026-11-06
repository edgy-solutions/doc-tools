"""concept_groups: the plan for the per-section concept calls (contract v4 section 4.6)."""
from types import SimpleNamespace as NS

import pytest

from doc_tools.utils.concept_groups import (
    ConceptCall, SectionRow, flatten_outline, plan_calls, render_call, section_of,
)


def sec(title, start, end=None, subs=()):
    return NS(title=title, level=1, start_page=start, end_page=end, subsections=list(subs))


def row(sid, start, end, depth=0, title=None):
    return SectionRow(id=sid, title=title or sid, level=1, start_page=start, end_page=end,
                      parent_id="c", depth=depth)


def test_flatten_outline_ids_are_preorder_and_positional():
    tree = [sec("A", 1, 4, [sec("A1", 1, 2), sec("A2", 3, 4)]), sec("B", 5, None)]
    rows = flatten_outline(tree, "c")
    assert [r.id for r in rows] == ["c_s0", "c_s0_s0", "c_s0_s1", "c_s1"]
    assert [r.depth for r in rows] == [0, 1, 1, 0]
    assert rows[1].parent_id == "c_s0"
    assert rows[0].parent_id == "c"


def test_flatten_outline_end_page_is_never_below_start():
    rows = flatten_outline([sec("A", 5, None), sec("B", 7, 3), sec("C", 2, 9)], "c")
    assert [r.end_page for r in rows] == [5, 7, 9]


def test_section_of_deepest_wins_then_later_start():
    rows = [row("p", 1, 10), row("child", 3, 4, depth=1),
            row("x", 6, 9), row("y", 8, 9)]
    assert section_of(3, rows).id == "child"
    assert section_of(2, rows).id == "p"
    assert section_of(8, rows).id == "y"  # same depth, later start
    assert section_of(11, rows) is None


def test_160_one_slide_sections_make_20_calls_of_8():
    rows = [row(f"s{i}", i, i) for i in range(1, 161)]
    calls = plan_calls(range(1, 161), rows)
    assert len(calls) == 20
    assert all(len(c.pages) == 8 for c in calls)


def test_a_long_section_splits_near_equal_never_over_the_cap():
    rows = [row("s", 1, 20)]
    calls = plan_calls(range(1, 21), rows)
    assert [len(c.pages) for c in calls] == [7, 7, 6]


def test_short_runs_are_packed_and_never_split():
    rows = [row("a", 1, 3), row("b", 4, 6), row("c", 7, 9)]
    calls = plan_calls(range(1, 10), rows)
    assert [c.pages for c in calls] == [(1, 2, 3, 4, 5, 6), (7, 8, 9)]


def test_unsectioned_pages_form_none_runs_packed_the_same():
    calls = plan_calls(range(1, 11), [])
    assert [len(c.pages) for c in calls] == [5, 5]
    assert all(s is None for c in calls for s in c.page_sections)


def test_max_slides_below_one_raises():
    with pytest.raises(ValueError):
        plan_calls([1], [], max_slides=0)


def test_a_nested_child_splits_its_parents_run():
    rows = [row("p", 1, 6), row("child", 3, 4, depth=1)]
    (call,) = plan_calls(range(1, 7), rows)
    assert call.page_sections == ("p", "p", "child", "child", "p", "p")
    assert call.section_ids() == ["p", "child", "p"]


def test_render_call_markers():
    rows = {"a": row("a", 1, 2, title="Pumps")}
    call = ConceptCall(pages=(1, 2, 3), page_sections=("a", "a", None))
    out = render_call(call, {1: "one", 2: "two", 3: "three"}, rows)
    assert out == ("=== Section: Pumps ===\n\n=== Slide 1 ===\none\n\n=== Slide 2 ===\ntwo\n\n"
                   "=== Section: (no section) ===\n\n=== Slide 3 ===\nthree")
