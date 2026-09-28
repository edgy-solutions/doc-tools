"""Tests for the pure geometry decision behind the Table-crop bottom-edge fix
(doc_tools/utils/crop_geometry.py).

Loaded by DIRECT FILE PATH, not `import doc_tools...` — `doc_tools/__init__.py` ends
with `from .definitions import defs`, which pulls in `unstructured` -> `python-magic`,
which blocks at module level on this Windows box (see the project memory note
"doc-tools-local-suite-hangs-on-libmagic"). `corrected_bottom` itself has no such
import (plain tuples in, a float out), so loading the module by path — the same
technique `tests/test_pcn_score.py` uses for `scripts/pcn_score.py` — is enough to
test it standalone, with no PDF, no pdfplumber, and no doc_tools import chain.
"""
import importlib.util
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "doc_tools" / "utils" / "crop_geometry.py"


def _load():
    spec = importlib.util.spec_from_file_location("crop_geometry", _MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


crop_geometry = _load()
corrected_bottom = crop_geometry.corrected_bottom
corrected_box = crop_geometry.corrected_box

PAGE_HEIGHT = 1000.0  # generous headroom; the clamp test sets its own smaller page
PAGE_WIDTH = 600.0    # ditto, horizontally; the clamp test sets its own smaller page


def test_extends_to_a_row_that_straddles_the_bottom_edge():
    """The PCN23-002 shape: the last row's top is inside the crop box but its own
    bottom runs past it — the fix should extend to that row's real bottom."""
    el_box = (0.0, 100.0, 200.0, 300.0)
    row_boxes = [(0.0, 280.0, 200.0, 320.0)]  # starts at 280 (< 300 - 0.5), ends at 320
    assert corrected_bottom(el_box, row_boxes, PAGE_HEIGHT) == 320.0


def test_no_matched_table_applies_percent_padding():
    """Rule 4 fallback: step 1 found no overlapping pdfplumber table at all."""
    el_box = (0.0, 100.0, 200.0, 300.0)
    assert corrected_bottom(el_box, [], PAGE_HEIGHT) == pytest.approx(300.0 + 0.03 * 200.0)


def test_swallowed_prose_row_is_dropped_but_the_real_row_still_completes():
    """The pdfplumber-bbox-blowup pathology: the matched "table" includes a row that
    is really a swallowed body-prose block, towering over its siblings. It must not
    be extended to — but the genuine row beside it must STILL be completed. The guard
    is a filter on implausible rows, not an abort on the whole correction, precisely
    so one bad row does not cost the crop a real one."""
    el_box = (0.0, 100.0, 200.0, 300.0)
    row_boxes = [
        (0.0, 280.0, 200.0, 320.0),   # a genuine row (height 40), straddles the edge
        (0.0, 150.0, 200.0, 900.0),   # the swallow: height 750, also starts inside
    ]
    assert corrected_bottom(el_box, row_boxes, PAGE_HEIGHT) == 320.0


def test_a_lone_swallowed_row_falls_back_to_padding():
    """The case a sibling-comparison guard cannot see: the matched table has exactly
    ONE candidate row and it is the swallow, so there is nothing to compare it
    against. The absolute ceiling is what catches this — without it the crop would
    extend 600pt and take half the page with it."""
    el_box = (0.0, 100.0, 200.0, 300.0)
    row_boxes = [(0.0, 290.0, 200.0, 900.0)]  # height 610, no siblings
    assert corrected_bottom(el_box, row_boxes, PAGE_HEIGHT) == pytest.approx(
        300.0 + 0.03 * 200.0)


def test_correction_is_clamped_to_the_page_height():
    el_box = (0.0, 100.0, 200.0, 790.0)
    row_boxes = [(0.0, 785.0, 200.0, 850.0)]  # a plausible row running past the page
    assert corrected_bottom(el_box, row_boxes, page_height=800.0) == 800.0


def test_box_that_already_contains_its_rows_is_returned_unchanged():
    el_box = (0.0, 100.0, 200.0, 300.0)
    row_boxes = [(0.0, 150.0, 200.0, 170.0)]  # fully inside [100, 300] already
    assert corrected_bottom(el_box, row_boxes, PAGE_HEIGHT) == 300.0


def test_dense_parts_list_rows_are_not_rejected_as_implausible():
    """The PCN23-002 shape is 18 rows of ~8pt. The relative test alone would compare
    a normal 2-line row against an 8pt median and reject it at 3x; the floor in the
    ceiling is what keeps a dense table's own rows admissible."""
    el_box = (0.0, 100.0, 200.0, 297.0)
    row_boxes = [(0.0, 100.0 + 8 * i, 200.0, 108.0 + 8 * i) for i in range(25)]
    # the last row spans 292..300 — it starts inside the box and runs past it, so it
    # must be extended to rather than filtered for being 8pt against an 8pt median
    assert corrected_bottom(el_box, row_boxes, PAGE_HEIGHT) == 300.0


# --------------------------------------------------------------------------- #
# corrected_box — all four edges. `corrected_bottom`'s own tests above are left
# untouched; these exercise the new function only.
# --------------------------------------------------------------------------- #

# A row/cell that sits fully inside the box on the axis it doesn't test is a
# CANDIDATE (its near-edge condition is met) but never moves the opposite edge
# of that axis, because `far` never beats `fixed` in the max()/min() the guard
# performs. Used below to keep the two edges NOT under test pinned to their
# original value without falling back to padding (which an empty list would
# trigger instead).
_NEUTRAL_ROW = (100.0, 150.0, 300.0, 200.0)   # fully inside top=100..bottom=300
_NEUTRAL_CELL = (150.0, 100.0, 250.0, 300.0)  # fully inside x0=100..x1=300


def test_box_bottom_extends_independently():
    el_box = (100.0, 100.0, 300.0, 300.0)
    row_boxes = [(100.0, 280.0, 300.0, 330.0)]  # starts at 280 (< 300-0.5), ends at 330
    result = corrected_box(el_box, row_boxes, [_NEUTRAL_CELL], PAGE_WIDTH, PAGE_HEIGHT)
    assert result == (100.0, 100.0, 300.0, 330.0)


def test_box_top_extends_independently():
    el_box = (100.0, 100.0, 300.0, 300.0)
    row_boxes = [(100.0, 70.0, 300.0, 120.0)]  # ends at 120 (> 100+0.5), starts at 70
    result = corrected_box(el_box, row_boxes, [_NEUTRAL_CELL], PAGE_WIDTH, PAGE_HEIGHT)
    assert result == (100.0, 70.0, 300.0, 300.0)


def test_box_right_extends_independently():
    el_box = (100.0, 100.0, 300.0, 300.0)
    cell_boxes = [(280.0, 100.0, 320.0, 300.0)]  # starts at 280 (< 300-0.5), ends at 320
    result = corrected_box(el_box, [_NEUTRAL_ROW], cell_boxes, PAGE_WIDTH, PAGE_HEIGHT)
    assert result == (100.0, 100.0, 320.0, 300.0)


def test_box_left_extends_independently():
    el_box = (100.0, 100.0, 300.0, 300.0)
    cell_boxes = [(70.0, 100.0, 120.0, 300.0)]  # ends at 120 (> 100+0.5), starts at 70
    result = corrected_box(el_box, [_NEUTRAL_ROW], cell_boxes, PAGE_WIDTH, PAGE_HEIGHT)
    assert result == (70.0, 100.0, 300.0, 300.0)


def test_box_unchanged_when_nothing_half_captured_on_any_edge():
    """Both the row and the cell are candidates on their respective axes (their
    near-edge condition is met) but neither is half-captured on either side, so
    every edge stays exactly at the element's own value -- no edge silently
    drifts by the percent-padding fallback just because a table/cell matched."""
    el_box = (100.0, 100.0, 300.0, 300.0)
    result = corrected_box(el_box, [_NEUTRAL_ROW], [_NEUTRAL_CELL], PAGE_WIDTH, PAGE_HEIGHT)
    assert result == el_box


def test_box_clamps_at_all_four_page_boundaries():
    """One row overshoots the bottom, one overshoots above the top, one cell
    overshoots past the right, one cell overshoots past the left -- all four
    corrections land outside a small page and must all clamp to its edges."""
    el_box = (10.0, 10.0, 40.0, 40.0)
    row_boxes = [
        (10.0, 35.0, 40.0, 80.0),     # bottom candidate, real bottom 80 > page
        (10.0, -30.0, 40.0, 15.0),    # top candidate, real top -30 < 0
    ]
    cell_boxes = [
        (30.0, 10.0, 200.0, 40.0),    # right candidate, real x1 200 > page
        (-200.0, 10.0, 20.0, 40.0),   # left candidate, real x0 -200 < 0
    ]
    result = corrected_box(el_box, row_boxes, cell_boxes, page_width=50.0, page_height=50.0)
    assert result == (0.0, 0.0, 50.0, 50.0)


def test_box_swallowed_prose_row_is_filtered_but_the_real_row_still_completes():
    """Horizontal analogue of `test_swallowed_prose_row_is_dropped...` above,
    driven through `corrected_box`: a matched table row that is really a
    swallowed prose block (height 750, dwarfing its 40pt sibling) must not pull
    the bottom edge down to it, but the genuine row beside it still completes."""
    el_box = (100.0, 100.0, 300.0, 300.0)
    row_boxes = [
        (100.0, 280.0, 300.0, 320.0),  # genuine row (height 40), straddles the edge
        (100.0, 150.0, 300.0, 900.0),  # the swallow: height 750, also a candidate
    ]
    result = corrected_box(el_box, row_boxes, [_NEUTRAL_CELL], PAGE_WIDTH, PAGE_HEIGHT)
    assert result == (100.0, 100.0, 300.0, 320.0)


def test_box_swallowed_prose_cell_is_filtered_but_the_real_cell_still_completes():
    """The horizontal guard's own scenario, chosen to prove the RELATIVE test is
    the one doing the work (the module's own comment on `_MAX_CELL_WIDTH_RATIO`
    concedes the absolute ceiling is weak horizontally): two genuine 40pt-wide
    cells set the median at 40, so the ratio ceiling is 40*12=480 -- comfortably
    below `_MAX_PLAUSIBLE_CELL_PTS` (576). A 500pt "cell" clears the (weak)
    576pt absolute ceiling but is rejected by the 480pt relative one, so this
    would NOT be caught if the absolute test were the only guard."""
    el_box = (100.0, 100.0, 300.0, 300.0)
    cell_boxes = [
        (280.0, 100.0, 320.0, 300.0),  # genuine, width 40, straddles the right edge
        (180.0, 100.0, 220.0, 300.0),  # genuine, width 40, sets the median with the above
        (150.0, 100.0, 650.0, 300.0),  # the swallow: width 500, also a candidate
    ]
    result = corrected_box(el_box, [_NEUTRAL_ROW], cell_boxes, PAGE_WIDTH, PAGE_HEIGHT)
    assert result == (100.0, 100.0, 320.0, 300.0)


def test_box_horizontal_cap_clamps_rather_than_abandons():
    """A single plausible cell (no siblings, so only the weak 576pt absolute
    ceiling applies, and 220 clears it easily) would extend the right edge by
    200pt -- the correction is not abandoned for being large, but the MOVE is
    capped at `_MAX_HORIZ_EXTENSION_PTS` (36pt) rather than jumping the full
    200, on a page far too wide for the page clamp to be what catches this."""
    el_box = (100.0, 100.0, 300.0, 300.0)
    cell_boxes = [(280.0, 100.0, 500.0, 300.0)]  # width 220, real x1 500 (+200 over fixed)
    result = corrected_box(el_box, [_NEUTRAL_ROW], cell_boxes, page_width=1000.0,
                           page_height=1000.0)
    assert result == (100.0, 100.0, 336.0, 300.0)  # 300 + min(200, 36)


def test_box_reproduces_the_adi_left_edge_shape():
    """The ADI_PDN_23_0120.pdf shape: the element's left edge sits ~11pt inside
    a cell that starts further left (the header read `del` for "Model", the
    data cell read `7873ACPZ` for "AD7873ACPZ") -- the fix should extend left
    by that ~11pt and move nothing else, including the right edge the cell
    shares with the element's own (already-correct) x1."""
    el_box = (50.0, 100.0, 300.0, 300.0)
    cell_boxes = [(39.0, 100.0, 300.0, 300.0)]  # starts 11pt further left; x1 matches
    result = corrected_box(el_box, [_NEUTRAL_ROW], cell_boxes, PAGE_WIDTH, PAGE_HEIGHT)
    assert result == (39.0, 100.0, 300.0, 300.0)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
