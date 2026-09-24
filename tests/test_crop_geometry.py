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

PAGE_HEIGHT = 1000.0  # generous headroom; the clamp test sets its own smaller page


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


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
