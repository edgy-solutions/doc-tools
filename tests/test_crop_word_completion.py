"""Tests for rule 7 (word completion) in doc_tools/utils/crop_geometry.py.

WHY THIS FILE EXISTS. Rules 2-6 complete a row or cell that the element box
already began to include. MEASURED 2026-10-16 on IDT_PDN_OV-19-05.pdf p1, that
is not the only way an edge lands mid-glyph: find_tables() returned one table
spanning most of the page whose "rows" are prose blocks, so rules 2-6 were
CORRECT to leave the top and bottom edges alone -- and both edges still cut
words. Rule 7 extends an edge that passes through a word to that word's far
side. These tests pin the rule and, above all, pin that its straddle criterion
agrees with the seal's `_cut_words_by_edge`: a rule that "fixes" an edge by a
different yardstick than the gate uses would pass here and fail the gate.

SCOPE. Pure: plain tuples in, tuples out. No PDF, pdfplumber, S3 or network.
The seal is loaded by file path exactly as in tests/test_crop_seal_edges.py
(see its LOADING note for why, and why pytest must run from PowerShell).
"""
import importlib.util
import inspect
from pathlib import Path

import pytest

from doc_tools.utils import crop_geometry as cg

_SEAL_PATH = Path(__file__).resolve().parents[1] / "scripts" / "pcn_crop_seal.py"


def _load():
    spec = importlib.util.spec_from_file_location("pcn_crop_seal", _SEAL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


seal = _load()

PAGE_W, PAGE_H = 612.0, 792.0
BOX = (100.0, 200.0, 300.0, 400.0)
CAP = cg._WORD_COMPLETION_MAX_PTS


def rule7(box, words, siblings=()):
    """Rule 7 alone. corrected_box cannot isolate it: with no rows/cells rules
    2-6 fall back to percentage padding (3% per edge), so the box moves anyway.
    corrected_box wires this function in as its last step (tests 1, 2, 9)."""
    return cg._word_completed_box(box, words, siblings, PAGE_W, PAGE_H)


def cuts(box, words, siblings=()):
    """The seal's verdict on `box`, with word tuples adapted to its dicts."""
    dicts = [{"text": f"w{i}", "x0": a, "top": b, "x1": c, "bottom": d}
             for i, (a, b, c, d) in enumerate(words)]
    return seal._cut_words_by_edge(dicts, box, list(siblings))


def approx_box(got, want):
    assert got == pytest.approx(want, abs=1e-6)


# --- 1. back-compat / inertness ------------------------------------------

def test_without_words_the_result_is_the_pre_rule7_result():
    # Rows and cells drive real corrections on all four edges. Rule 7 must be
    # invisible to every existing caller: omitted, empty-tuple and empty-list
    # word/sibling arguments all give the identical tuple, and that tuple is
    # a genuine correction (not just the input handed back).
    rows = [(100.0, 190.0, 300.0, 240.0), (100.0, 360.0, 300.0, 430.0)]
    cells = [(90.0, 190.0, 200.0, 240.0), (200.0, 360.0, 320.0, 430.0)]
    base = cg.corrected_box(BOX, rows, cells, PAGE_W, PAGE_H)
    assert base != BOX
    assert base[0] < BOX[0] and base[1] < BOX[1]
    assert base[2] > BOX[2] and base[3] > BOX[3]
    assert cg.corrected_box(BOX, rows, cells, PAGE_W, PAGE_H,
                            word_boxes=(), sibling_boxes=()) == base
    assert cg.corrected_box(BOX, rows, cells, PAGE_W, PAGE_H,
                            word_boxes=[], sibling_boxes=[]) == base
    # Sibling boxes alone, with no words, are also inert.
    assert cg.corrected_box(BOX, rows, cells, PAGE_W, PAGE_H,
                            sibling_boxes=[(0.0, 0.0, 612.0, 792.0)]) == base


def test_corrected_bottom_takes_no_word_parameters():
    # corrected_bottom is the older single-edge entry point; its signature is
    # part of the "bit-for-bit identical for existing callers" promise.
    params = inspect.signature(cg.corrected_bottom).parameters
    assert not [p for p in params if "word" in p or "sibling" in p]


# --- 2. the measured IDT case --------------------------------------------

IDT_EL = (50.8, 117.3, 553.0, 505.7)
IDT_ROWS = [(60.6, a, 553.1, b) for a, b in [
    (45.1, 125.6), (125.6, 187.3), (187.3, 213.3), (213.3, 367.9),
    (367.9, 465.6), (455.7, 465.6), (465.6, 567.1), (567.1, 679.6),
    (679.6, 723.1)]]
IDT_TITLE = [(a, 109.8, b, 124.8) for a, b in [
    (144.5, 218.5), (222.2, 360.3), (364.0, 423.0), (426.8, 467.5)]]
IDT_PROSE = [(a, 498.5, b, 507.8) for a, b in [
    (64.5, 93.5), (95.9, 109.5), (111.8, 140.9), (143.4, 201.7),
    (204.1, 229.1), (231.5, 258.8), (263.6, 285.4), (287.9, 302.5),
    (304.9, 313.8), (316.2, 325.5), (327.8, 373.8), (376.2, 393.2)]]


def test_idt_rules_2_to_6_leave_both_edges_mid_glyph_and_rule7_fixes_them():
    words = IDT_TITLE + IDT_PROSE
    # (a) The finding: rows alone are right to leave top/bottom alone, and the
    # seal confirms both edges still cut words. Without this half the test
    # would pass even if rules 2-6 had started fixing it and rule 7 were dead.
    before = cg.corrected_box(IDT_EL, IDT_ROWS, [], PAGE_W, PAGE_H)
    assert before[1] == IDT_EL[1] and before[3] == IDT_EL[3]
    seen = cuts(before, words)
    assert seen["top"] and seen["bottom"]
    # (b) Rule 7 moves exactly top and bottom, to the words' far sides.
    after = cg.corrected_box(IDT_EL, IDT_ROWS, [], PAGE_W, PAGE_H,
                             word_boxes=words)
    approx_box(after, (before[0], 109.8, before[2], 507.8))
    assert after[0] == before[0] and after[2] == before[2]
    assert after[1] - IDT_EL[1] == pytest.approx(-7.5, abs=0.1)
    assert after[3] - IDT_EL[3] == pytest.approx(2.1, abs=0.05)
    # The gate agrees: nothing is cut on any edge.
    assert cuts(after, words) == {"left": [], "top": [], "right": [],
                                  "bottom": []}


# --- 3. outward only -----------------------------------------------------

def test_a_word_wholly_inside_the_box_moves_nothing():
    assert rule7(BOX, [(150.0, 250.0, 200.0, 262.0)]) == BOX


def test_an_edge_never_snaps_inward_to_exclude_a_straddling_word():
    # The word's near side (210) is INSIDE the box. Snapping the top edge down
    # to 210 would "exclude" it, which would also shrink the table and could
    # drop content; rule 7 must go to the far side (190) instead.
    approx_box(rule7(BOX, [(150.0, 190.0, 200.0, 210.0)]),
               (100.0, 190.0, 300.0, 400.0))
    # Same on the bottom: near side 390 is inside, far side 410 is outward.
    approx_box(rule7(BOX, [(150.0, 390.0, 200.0, 410.0)]),
               (100.0, 200.0, 300.0, 410.0))
    # And left/right.
    approx_box(rule7(BOX, [(90.0, 250.0, 110.0, 262.0)]),
               (90.0, 200.0, 300.0, 400.0))
    approx_box(rule7(BOX, [(290.0, 250.0, 310.0, 262.0)]),
               (100.0, 200.0, 310.0, 400.0))


# --- 4. sibling exclusion ------------------------------------------------

def test_a_word_inside_a_sibling_box_does_not_move_the_edge():
    word = (150.0, 390.0, 200.0, 410.0)
    contained = (140.0, 385.0, 210.0, 415.0)
    assert rule7(BOX, [word], [contained]) == BOX
    assert rule7(BOX, [word])[3] == 410.0
    # A sibling that holds only part of the word excludes nothing.
    partial = (100.0, 405.0, 300.0, 500.0)
    assert rule7(BOX, [word], [partial])[3] == 410.0


def test_sibling_tolerance_is_one_point_and_no_more():
    word = (150.0, 390.0, 200.0, 410.0)
    # Word exceeds the sibling by exactly 1pt on every side: still excluded.
    edge = (151.0, 391.0, 199.0, 409.0)
    assert rule7(BOX, [word], [edge]) == BOX
    # Exceeds it by more than 1pt (bottom by 1.5): NOT excluded.
    over = (151.0, 391.0, 199.0, 408.5)
    assert rule7(BOX, [word], [over])[3] == 410.0


# --- 5. cap --------------------------------------------------------------

def test_a_far_reaching_word_moves_the_edge_by_the_cap_and_still_reads_cut():
    word = (150.0, 100.0, 200.0, 210.0)  # reaches 100pt above the top edge
    out = rule7(BOX, [word])
    assert out[1] == pytest.approx(BOX[1] - CAP)
    assert (out[0], out[2], out[3]) == (BOX[0], BOX[2], BOX[3])
    # A capped move must never be able to look like a clean one: the gate
    # still reports the word cut on the top edge.
    assert cuts(out, [word])["top"]


# --- 6. page clamp -------------------------------------------------------

def test_words_beyond_the_page_cannot_push_an_edge_off_the_page():
    box = (5.0, 5.0, 605.0, 785.0)
    words = [(-8.0, 300.0, 20.0, 320.0),    # left
             (590.0, 300.0, 640.0, 320.0),  # right
             (300.0, -5.0, 320.0, 20.0),    # top
             (300.0, 780.0, 320.0, 820.0)]  # bottom
    assert rule7(box, words) == (0.0, 0.0, PAGE_W, PAGE_H)


# --- 7. other-axis gating ------------------------------------------------

def test_a_word_beside_the_box_does_not_move_the_top_or_bottom_edge():
    # Level with the top and bottom edges but far outside the box x span.
    words = [(10.0, 190.0, 50.0, 210.0), (500.0, 190.0, 560.0, 210.0),
             (10.0, 390.0, 50.0, 410.0), (500.0, 390.0, 560.0, 410.0)]
    assert rule7(BOX, words) == BOX


def test_a_word_above_or_below_the_box_does_not_move_the_left_or_right_edge():
    # Straddles x0=100 / x1=300 but sits far outside the box y span.
    words = [(90.0, 10.0, 110.0, 50.0), (290.0, 10.0, 310.0, 50.0),
             (90.0, 600.0, 110.0, 640.0), (290.0, 600.0, 310.0, 640.0)]
    assert rule7(BOX, words) == BOX


# --- 8. iteration --------------------------------------------------------

def test_a_second_line_is_completed_once_the_first_move_exposes_it():
    first = (150.0, 190.0, 200.0, 210.0)   # straddles top=200 now
    second = (150.0, 170.0, 200.0, 191.0)  # straddles only once top is 190
    # With `second` listed first, a single pass tests it before `first` has
    # moved the edge, so one pass provably stops at 190.
    words = [second, first]
    one_pass = cg._word_completed_box(BOX, words, [], PAGE_W, PAGE_H,
                                      passes=1)
    assert one_pass[1] == 190.0
    assert cuts(one_pass, words)["top"]
    out = rule7(BOX, words)
    assert out[1] == 170.0
    assert cuts(out, words)["top"] == []


# --- 9. idempotence ------------------------------------------------------

def test_applying_the_correction_to_its_own_output_changes_nothing():
    words = IDT_TITLE + IDT_PROSE
    # Cells span the box width so the x padding fallback (rules 2-6, not
    # rule 7) is not what is being compared.
    cells = [(IDT_EL[0], 60.0, IDT_EL[2], 700.0)]
    once = cg.corrected_box(IDT_EL, IDT_ROWS, cells, PAGE_W, PAGE_H,
                            word_boxes=words)
    twice = cg.corrected_box(once, IDT_ROWS, cells, PAGE_W, PAGE_H,
                             word_boxes=words)
    assert twice == once
    w = [(150.0, 190.0, 200.0, 210.0)]
    o = rule7(BOX, w)
    assert rule7(o, w) == o
