"""Fix the Table-crop edges unstructured's hi_res path cuts through.

WHY THIS EXISTS. unstructured's hi_res path writes each Table crop using its own
detected layout bbox with ZERO padding. Measured on the corpus (2026-09-24 survey,
`docs/pcn-crop-clipping-survey-2026-09-24.md`): 9 tables across 5 of 9 notices have a
bottom edge that slices horizontally through the last row's glyphs. Worst case: Diodes
page 5 keeps only 32% of `WC21400001`. The case that motivated this fix — `PCN23-002`
page 2 — keeps 53% of `SYTX9-122HP-1+`, which the vision model then read as
`SYTYD-122HP-1+`: a real part silently replaced by a wrong one.

MEASURED CONSTRAINT — do not union with pdfplumber's table bbox directly. On
form-like pages `page.find_tables()` returns bboxes that swallow body prose;
unioning a Table element's crop with one of those can extend the crop by up to
337.5pt (half a page). The rule here instead extends only to the BOTTOM OF THE
SPECIFIC ROWS that start inside the element's own box — measured to extend by at
most 8.3pt on the same corpus — with a guard (see `corrected_bottom`) against the
pathological case where the matched "table" itself is a swallow.

TWO LAYERS, DELIBERATELY SPLIT:
  - `corrected_bottom` (bottom edge only) and `corrected_box` (all four edges,
    sharing the same doctrine via the private `_corrected_edge` helper) are PURE
    (plain tuples in, a float/tuple out) and hold ALL of the decision logic (rules
    2-6 of the spec this implements) — testable with no PDF, no pdfplumber, no
    doc_tools import chain.
  - `repair_table_crops` is the IO half: opens the PDF with pdfplumber (rule 1: find
    the best-overlapping table, and its rows/cells) and pypdfium2 (re-render +
    re-crop), and is the only part that touches a file.

COORDINATE SPACES. Critical facts this module relies on (verified against the
installed unstructured / unstructured_inference source, not assumed):
  - unstructured's hi_res layout coordinates and the crop image's pixel space are the
    SAME space: layout is rendered at `pdf_image_dpi`, and
    `layout_height / page.height == dpi / 72` (pdfplumber's `page.height` is in PDF
    points, 72/inch). So `scale = layout_height / page.height` converts PDF points to
    that same pixel/layout space, and is exactly the `dpi/72.0` factor
    `rasterize_pdf_pages` (doc_tools/utils/extraction.py) passes to
    `page.render(scale=...)`.
  - A Table/Image element's `metadata.coordinates.points` is a 4-point polygon built
    by `unstructured_inference.inference.elements.Rectangle.coordinates`
    (`(x1,y1),(x1,y2),(x2,y2),(x2,y1)` — i.e. two points share the bbox's top y, two
    share its bottom y, and likewise in pairs for x0/x1). This module never assumes
    which INDEX holds which corner; it only replaces whichever points carry an OLD
    x0/x1/top/bottom with the corresponding NEW value, which is robust to that
    ordering by construction.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

Box = Tuple[float, float, float, float]  # (x0, top, x1, bottom)

# A candidate "row" taller than this is not a table row at any plausible font size —
# it is a prose block that `find_tables()` swallowed. One inch, in PDF points.
_MAX_PLAUSIBLE_ROW_PTS = 72.0
# ...and a row more than this multiple of its siblings' median height is a swallow
# even when it is under the absolute ceiling.
_MAX_ROW_HEIGHT_RATIO = 3.0
# Floor for the relative test, so a table of very short rows (a dense parts list,
# ~8pt rows) does not reject a normal header or wrapped cell for being 2 lines tall.
_MIN_ROW_HEIGHT_ALLOWANCE = 30.0

# --- Horizontal (left/right) analogues of the three constants above ---
#
# A candidate CELL wider than this is not a real cell. Unlike the vertical case,
# this is a WEAK test: a legitimately merged full-width header cell can run
# ~500pt wide on a plain US-Letter page (612pt wide, ~576pt inside typical
# margins), so the ceiling has to sit above that or it rejects real headers.
# Set to the standard 8in printable text width, comfortably above the ~500pt
# legitimate case; it only catches the no-siblings-to-compare-against case
# (mirroring `_MAX_PLAUSIBLE_ROW_PTS`'s role) and does little work otherwise —
# see the comment at the horizontal guard below.
_MAX_PLAUSIBLE_CELL_PTS = 576.0
# A cell more than this multiple of its siblings' median width is a swallow.
# Set well above `_MAX_ROW_HEIGHT_RATIO` (3.0) because a real full-width merged
# header cell over a many-narrow-column data table can legitimately be 6-10x
# the median column width; this is the WORKHORSE test horizontally (the
# absolute ceiling above rarely binds), but it is only as good as the gap
# between "legitimate wide header" and "swallowed prose block" ratios, and nothing
# here guarantees that gap always exists on a given page.
_MAX_CELL_WIDTH_RATIO = 12.0
# Floor for the relative test, so a table with very narrow columns (e.g. a
# ~15pt checkbox/status column) does not reject an ordinary ~100pt data column
# for being several times the median column width.
_MIN_CELL_WIDTH_ALLOWANCE = 100.0
# Hard cap on how far ANY horizontal edge is allowed to move, regardless of what
# a candidate cell (or the percent-padding fallback) would otherwise justify.
# The measured real need (ADI_PDN_23_0120.pdf, header "del"/"7873ACPZ" for
# "Model"/"AD7873ACPZ") is ~10-12pt — about two characters. The module's own
# vertical survey (docstring above) measured that correction extending by at
# most 8.3pt on the real corpus. The documented FAILURE MODE — `find_tables()`
# swallowing prose on a form-like page — can blow a box out by up to 337.5pt
# (half a page). 36pt sits well clear of the measured need on either axis while
# staying far short of the pathological blowup, so a bad match is clamped
# rather than allowed to consume the crop.
_MAX_HORIZ_EXTENSION_PTS = 36.0


# --------------------------------------------------------------------------- #
# PURE — no PDF, no pdfplumber, no pypdfium2. Rules 2-6.
# --------------------------------------------------------------------------- #
# --- Rule 7 (word completion) ---------------------------------------------
#
# WHY A SEVENTH RULE EXISTS. Rules 2-6 complete a row or a cell that
# unstructured's box already began to include. MEASURED 2026-10-16 on
# `IDT_PDN_OV-19-05.pdf` p1, that is not the only way an edge lands mid-glyph:
# `find_tables()` returned ONE table spanning (60.6, 45.1, 553.1, 723.1) -- 678pt
# of a 792pt page -- whose nine "rows" are prose blocks of 9.9 to 154.6pt. The
# element box (50.8, 117.3, 553.0, 505.7) sits inside it, so rule 1 matched, and
# then:
#   - top 117.3: every plausible row (<= the 72pt ceiling) starts at or BELOW
#     125.6, so `min(row.top) >= top` and rule 3 correctly leaves it alone;
#   - bottom 505.7: every plausible row already ends at or ABOVE 465.6, so
#     `max(row.bottom) <= bottom` and rule 3 correctly leaves it alone.
# Both edges are therefore "correct" by rules 2-6 and both still cut text: the
# top through the title (`PRODUCT DISCONTINUANCE NOTICE (PDN)`, 109.8-124.8) and
# the bottom through a prose line (498.5-507.8). The defect is not a half-caught
# ROW -- it is an edge inside a line of text the matched table does not represent
# as a row at all. Three fires on pin sha256:85ad4c9d failed the crop seal on
# exactly this, byte-identically, while fire 1 scored 522/522 parts; the seal, not
# the parts, is what held exit 0.
#
# THE RULE: after rules 2-6, extend any edge that still passes through a word to
# that word's far side. OUTWARD ONLY, never inward -- the module's standing
# doctrine is that a re-cut crop may cost a column LABEL but must never cost a
# ROW, and an inward snap can drop one. The criterion is byte-for-byte the one
# `scripts/pcn_crop_seal.py::_cut_words_by_edge` measures (edge through the
# word's own axis by >0.5pt on both sides, overlap on the other axis within 1pt,
# sibling-covered words excluded), so the repair answers the same question the
# gate asks instead of a near-miss of it.
#
# The measured moves on that page are 7.5pt (top) and 2.1pt (bottom). The cap is
# set well above a tall title line and well below anything that could restructure
# a crop; if it ever binds, the edge stays cut and the seal says so -- a capped
# move must not be allowed to look like a clean one.
_WORD_COMPLETION_MAX_PTS = 36.0
# A move can bisect a word on the NEXT line (a descender, a taller glyph), so the
# step is iterated. Each pass is monotone outward and the cap is cumulative, so
# this terminates on its own; the ceiling only bounds pathological pages.
_WORD_COMPLETION_PASSES = 4


def _corrected_edge(fixed: float, other: float, candidate_boxes: Sequence[Box],
                    near_idx: int, far_idx: int, *, increasing: bool, bound: float,
                    pad_frac: float, max_plausible_size: float, max_size_ratio: float,
                    min_size_allowance: float,
                    max_extension: Optional[float] = None) -> float:
    """Shared 1-D logic behind every edge of `corrected_box` (and, via
    `corrected_bottom`, the original bottom-only fix). Operates on plain Box
    tuples by INDEX so the same code serves both axes:
      - bottom: near_idx=1 (row.top), far_idx=3 (row.bottom), increasing=True
      - top:    near_idx=3 (row.bottom), far_idx=1 (row.top), increasing=False
      - right:  near_idx=0 (cell.x0), far_idx=2 (cell.x1), increasing=True
      - left:   near_idx=2 (cell.x1), far_idx=0 (cell.x0), increasing=False

    `fixed` is the edge being corrected (e.g. `bottom`); `other` is the box's
    opposite edge on the same axis (e.g. `top`), used only to size the
    percent-padding fallback. `increasing` says which way `fixed` is allowed to
    move: True pushes it toward `bound` via max() (bottom/right), False pushes
    it toward `bound` via min() (top/left) -- `bound` is `page_height`/
    `page_width` for the two increasing edges and `0.0` for the two decreasing
    ones. `max_extension`, when given, caps how far `fixed` may move from its
    original value in one call, applied to BOTH the candidate-driven correction
    and the padding fallback, so no single edge move ever exceeds it regardless
    of source.
    """
    box_size = (fixed - other) if increasing else (other - fixed)

    def _clamp(v: float) -> float:
        return min(v, bound) if increasing else max(v, bound)

    def _cap(extension: float) -> float:
        return extension if max_extension is None else min(extension, max_extension)

    def _padded() -> float:
        extension = _cap(pad_frac * box_size)
        return _clamp(fixed + extension if increasing else fixed - extension)

    if not candidate_boxes:
        return _padded()

    if increasing:
        candidates = [cb for cb in candidate_boxes if cb[near_idx] < fixed - 0.5]
    else:
        candidates = [cb for cb in candidate_boxes if cb[near_idx] > fixed + 0.5]
    if not candidates:
        # A matched table, but nothing in it starts inside the element's own box
        # on this edge -- there is nothing here to complete. Leave it alone.
        return _clamp(fixed)

    # GUARD — a FILTER, not an abort. See the module-level comment on
    # `_MAX_PLAUSIBLE_ROW_PTS` / `_MAX_CELL_WIDTH_RATIO` etc. for why two
    # independent tests (relative-to-median and an absolute ceiling) are used,
    # and why the horizontal absolute ceiling is intentionally weak.
    sizes = sorted(abs(cb[far_idx] - cb[near_idx]) for cb in candidates)
    median_size = sizes[len(sizes) // 2]
    ceiling = min(max_plausible_size, max(median_size * max_size_ratio, min_size_allowance))
    plausible = [cb for cb in candidates if abs(cb[far_idx] - cb[near_idx]) <= ceiling]
    if not plausible:
        return _padded()

    if increasing:
        far_extreme = max(cb[far_idx] for cb in plausible)
        corrected = max(fixed, far_extreme)
        if corrected <= fixed:
            return _clamp(fixed)  # already contains every plausible candidate
        return _clamp(fixed + _cap(corrected - fixed))
    else:
        far_extreme = min(cb[far_idx] for cb in plausible)
        corrected = min(fixed, far_extreme)
        if corrected >= fixed:
            return _clamp(fixed)  # already contains every plausible candidate
        return _clamp(fixed - _cap(fixed - corrected))


def corrected_bottom(el_box: Box, row_boxes: Sequence[Box], page_height: float,
                     *, pad_frac: float = 0.03) -> float:
    """The corrected bottom edge (PDF points) for one Table element's box.

    `el_box` is `(x0, top, x1, bottom)` in PDF points. `row_boxes` is the MATCHED
    table's rows (rule 1's output — the caller already picked the one pdfplumber
    table with the largest overlap and handed over ALL of its `.rows` bboxes; pass
    `[]` when rule 1 found no overlapping table at all). `page_height` clamps the
    result to the page.

    Rule 2: among `row_boxes`, keep every row whose top starts inside the element
    box (`row.bbox[1] < bottom - 0.5`) — i.e. the row unstructured's box already
    began to include, so extending to its full bottom is completing a row already
    half-captured, not inventing a new one.
    Rule 3: corrected = max(bottom, tallest of those rows' bottoms).
    Rule 4: no matched table (or no row starts inside the box) -> percent padding.
    Rule 5: clamp to the page.
    Rule 6: guard against a matched-table mismatch (the pdfplumber-bbox-blowup
    case) — see the comment at the guard below for why this deliberately does NOT
    read "the tallest of ALL rows used in step 2" as literally as the spec prose
    states it; that literal reading is unreachable (proof in the same comment).
    """
    x0, top, x1, bottom = el_box
    return _corrected_edge(
        bottom, top, row_boxes, 1, 3, increasing=True, bound=page_height,
        pad_frac=pad_frac, max_plausible_size=_MAX_PLAUSIBLE_ROW_PTS,
        max_size_ratio=_MAX_ROW_HEIGHT_RATIO,
        min_size_allowance=_MIN_ROW_HEIGHT_ALLOWANCE)


def _word_completed_box(box: Box, word_boxes: Sequence[Box],
                        sibling_boxes: Sequence[Box],
                        page_width: float, page_height: float,
                        *, max_extension: float = _WORD_COMPLETION_MAX_PTS,
                        passes: int = _WORD_COMPLETION_PASSES) -> Box:
    """Rule 7: `box` with every edge that passes THROUGH a word extended outward
    to that word's far side. Pure -- plain tuples in, a tuple out.

    `word_boxes` are the page's words as `(x0, top, x1, bottom)`;
    `sibling_boxes` are the OTHER Table elements' boxes on the same page, whose
    wholly-contained words are that sibling's content and are not this box's cut
    (the same exclusion, and the same 1pt tolerance, as the seal's
    `_covered_by_sibling`; without it a first survey pass reported 924 false
    cuts).

    Edges only ever move away from the box's centre, each is capped at
    `max_extension` from its incoming value, and all four are clamped to the
    page. With no words, or with no word straddling any edge, the box is
    returned unchanged -- which is what keeps rule 7 inert for every caller that
    does not pass words.

    WHICH SIBLING WORLD. The caller passes the STORED sibling boxes, because at
    repair time the repaired ones are not all known yet (elements are repaired in
    sequence). That is the conservative direction and deliberately so: repaired
    boxes are supersets of stored ones (this rule and rules 2-6 both only grow a
    box), so stored siblings exclude FEWER words, so rule 7 extends at least as
    far as it would with repaired siblings. The seal then tests the result
    against repaired siblings, which excludes more -- so this can over-satisfy
    the gate but never under-satisfy it.
    """
    if not word_boxes:
        return box

    def _covered(w: Box) -> bool:
        for sx0, stop, sx1, sbot in sibling_boxes:
            if (sx0 - 1 <= w[0] and w[2] <= sx1 + 1
                    and stop - 1 <= w[1] and w[3] <= sbot + 1):
                return True
        return False

    live = [w for w in word_boxes if not _covered(w)]
    if not live:
        return box

    x0, top, x1, bottom = box
    # Budget per edge, measured from the box handed in, not from each pass.
    limits = (x0 - max_extension, top - max_extension,
              x1 + max_extension, bottom + max_extension)

    for _ in range(max(0, passes)):
        moved = False
        for w in live:
            wx0, wtop, wx1, wbot = w
            # Other-axis overlap, paired to the edge's own axis, exactly as the
            # seal pairs them.
            in_x = wx1 > x0 - 1 and wx0 < x1 + 1
            in_y = wbot > top - 1 and wtop < bottom + 1
            if in_y:
                if wx1 > x0 + 0.5 and wx0 < x0 - 0.5:
                    x0 = max(min(wx0, x0), limits[0], 0.0)
                    moved = True
                if wx0 < x1 - 0.5 and wx1 > x1 + 0.5:
                    x1 = min(max(wx1, x1), limits[2], page_width)
                    moved = True
            if in_x:
                if wbot > top + 0.5 and wtop < top - 0.5:
                    top = max(min(wtop, top), limits[1], 0.0)
                    moved = True
                if wtop < bottom - 0.5 and wbot > bottom + 0.5:
                    bottom = min(max(wbot, bottom), limits[3], page_height)
                    moved = True
        if not moved:
            break

    return (x0, top, x1, bottom)


def corrected_box(el_box: Box, row_boxes: Sequence[Box], cell_boxes: Sequence[Box],
                  page_width: float, page_height: float,
                  *, pad_frac: float = 0.03,
                  word_boxes: Sequence[Box] = (),
                  sibling_boxes: Sequence[Box] = ()) -> Box:
    """The corrected `(x0, top, x1, bottom)` for one Table element's box, all
    four edges, applying the SAME doctrine `corrected_bottom` applies to the
    bottom edge alone (see its docstring for rules 2-6 in full):

      - bottom: candidate ROWS have `row.top < bottom - 0.5`; new bottom =
        `max(row.bottom)` over the plausible ones; clamp to `page_height`.
      - top: candidate ROWS have `row.bottom > top + 0.5`; new top =
        `min(row.top)`; clamp to `0`.
      - right: candidate CELLS have `cell.x0 < x1 - 0.5`; new x1 =
        `max(cell.x1)`; clamp to `page_width`.
      - left: candidate CELLS have `cell.x1 > x0 + 0.5`; new x0 =
        `min(cell.x0)`; clamp to `0`.

    Rows carry no horizontal information (a row spans the full matched table
    width), which is why the horizontal edges are corrected against `cell_boxes`
    instead. `row_boxes` / `cell_boxes` are rule 1's output for the SAME matched
    table (pass `[]` for either when rule 1 found no overlapping table, or when
    that table reports no rows/cells).

    Each edge is corrected independently against the ORIGINAL `el_box` (an
    edge's own correction never sees another edge's already-corrected value),
    matching the fact that unstructured's original box can be cut on more than
    one side at once and each cut is an independent measurement.

    The horizontal edges additionally never move by more than
    `_MAX_HORIZ_EXTENSION_PTS` in one call (see that constant's comment) —
    there is no vertical analogue because the measured vertical extension never
    approached a scale where one was needed.

    Rule 7 (word completion) then runs on that result when `word_boxes` is
    supplied: any edge still passing through a word is extended outward to the
    word's far side, capped and clamped. `sibling_boxes` are the other Table
    elements' boxes on the page, used only for the exclusion rule 7 shares with
    the seal. Both default to empty, which makes rule 7 a no-op and keeps every
    existing caller's result bit-for-bit identical — `corrected_bottom` does not
    take them at all. See `_word_completed_box` and the constants above it for
    the measurement that forced the rule.
    """
    x0, top, x1, bottom = el_box
    new_bottom = _corrected_edge(
        bottom, top, row_boxes, 1, 3, increasing=True, bound=page_height,
        pad_frac=pad_frac, max_plausible_size=_MAX_PLAUSIBLE_ROW_PTS,
        max_size_ratio=_MAX_ROW_HEIGHT_RATIO,
        min_size_allowance=_MIN_ROW_HEIGHT_ALLOWANCE)
    new_top = _corrected_edge(
        top, bottom, row_boxes, 3, 1, increasing=False, bound=0.0,
        pad_frac=pad_frac, max_plausible_size=_MAX_PLAUSIBLE_ROW_PTS,
        max_size_ratio=_MAX_ROW_HEIGHT_RATIO,
        min_size_allowance=_MIN_ROW_HEIGHT_ALLOWANCE)
    new_x1 = _corrected_edge(
        x1, x0, cell_boxes, 0, 2, increasing=True, bound=page_width,
        pad_frac=pad_frac, max_plausible_size=_MAX_PLAUSIBLE_CELL_PTS,
        max_size_ratio=_MAX_CELL_WIDTH_RATIO,
        min_size_allowance=_MIN_CELL_WIDTH_ALLOWANCE,
        max_extension=_MAX_HORIZ_EXTENSION_PTS)
    new_x0 = _corrected_edge(
        x0, x1, cell_boxes, 2, 0, increasing=False, bound=0.0,
        pad_frac=pad_frac, max_plausible_size=_MAX_PLAUSIBLE_CELL_PTS,
        max_size_ratio=_MAX_CELL_WIDTH_RATIO,
        min_size_allowance=_MIN_CELL_WIDTH_ALLOWANCE,
        max_extension=_MAX_HORIZ_EXTENSION_PTS)
    # Rule 7 LAST, on the rule-2-6 result: it finishes edges that are correct by
    # rows and cells and still land inside a word. Inert without `word_boxes`.
    return _word_completed_box(
        (new_x0, new_top, new_x1, new_bottom), word_boxes, sibling_boxes,
        page_width, page_height)


# --------------------------------------------------------------------------- #
# IO — pdfplumber (rule 1) + pypdfium2 (re-render/re-crop). Everything below here
# touches a file or a PDF and is deliberately kept out of `corrected_bottom`.
# --------------------------------------------------------------------------- #
def _best_overlapping_table(tables: Sequence[Any], el_box_pts: Box) -> Optional[Any]:
    """Rule 1: the `pdfplumber` table (from `page.find_tables()`) with the largest
    overlap AREA against `el_box_pts`, or `None` if none of `tables` overlaps the
    element's box at all. The area-overlap selection itself is unchanged from
    before this module grew horizontal edges; only the row-bbox extraction that
    used to live inline here was pulled out so both axes can share the pick."""
    x0, top, x1, bottom = el_box_pts
    best, best_area = None, 0.0
    for t in tables:
        tx0, ttop, tx1, tbottom = t.bbox
        ox0, oy0 = max(x0, tx0), max(top, ttop)
        ox1, oy1 = min(x1, tx1), min(bottom, tbottom)
        if ox1 <= ox0 or oy1 <= oy0:
            continue
        area = (ox1 - ox0) * (oy1 - oy0)
        if area > best_area:
            best, best_area = t, area
    return best


def _rows_for_best_table(tables: Sequence[Any], el_box_pts: Box) -> List[Box]:
    """Rule 1, vertical-only: the best-overlapping table's rows' bboxes — or `[]`
    if none of `tables` overlaps the element's box at all. Kept for backward
    compatibility (`scripts/pcn_crop_seal.py` calls this by name); prefer
    `_rows_and_cells_for_best_table` for new code that also needs the cells."""
    best = _best_overlapping_table(tables, el_box_pts)
    if best is None:
        return []
    return [tuple(r.bbox) for r in best.rows]


def _rows_and_cells_for_best_table(tables: Sequence[Any], el_box_pts: Box
                                   ) -> Tuple[List[Box], List[Box]]:
    """Rule 1, both axes: the best-overlapping table's row bboxes (vertical
    candidates) AND its cell bboxes (horizontal candidates) — or `([], [])` if
    none of `tables` overlaps the element's box at all.

    `Table.cells` (installed pdfplumber 0.11.10, `pdfplumber/table.py`) is
    already the flat list of every real cell bbox `find_tables()` located for
    this table — a plain `List[T_bbox]` built directly from
    `intersections_to_cells`, never sparse. It is `Table.rows[i].cells` (built
    by re-gridding onto the union of all row/column edges via `.get(x)`) that
    can hold `None` for a missing cell in a sparse row — not `Table.cells`
    itself. We use `.cells` here, so the defensive skip below should never
    actually trigger against this pdfplumber version; it is kept anyway in case
    that internal shape changes upstream.
    """
    best = _best_overlapping_table(tables, el_box_pts)
    if best is None:
        return [], []
    row_boxes = [tuple(r.bbox) for r in best.rows]
    cell_boxes = [tuple(c) for c in best.cells
                 if isinstance(c, (tuple, list)) and len(c) == 4]
    return row_boxes, cell_boxes


class _ElementBox(NamedTuple):
    """One Table element's geometry, decoded once. `px` is the element's
    ORIGINAL pixel-space `(x0, top, x1, bottom)`, kept because the in-place
    `metadata.coordinates.points` rewrite matches each old coordinate against it
    (see COORDINATE SPACES in the module docstring); recomputing it at the tail
    from `box * scale` would reintroduce a rounding difference between the value
    matched and the value stored."""
    page: int
    box: Box
    scale: float
    image_path: str
    coords: Dict[str, Any]
    points: list
    px: Box


def _decode_element_box(el: Dict[str, Any], pdf: Any) -> Optional[_ElementBox]:
    """One Table element decoded to `(page_number, box_pts, scale, image_path)`,
    or `None` when this element carries nothing to repair.

    Lifted out of `repair_table_crops`'s loop so the pre-pass that collects the
    page's STORED element boxes and the repair loop itself cannot disagree about
    which elements count or where their edges are. Returning `None` rather than
    raising keeps the PDF-only-by-construction contract: an element from a
    non-PDF source has no coordinates and is skipped, not errored on.
    """
    meta = el.get("metadata") or {}
    page_number = meta.get("page_number")
    coords = meta.get("coordinates")
    if not page_number or not isinstance(coords, dict):
        return None
    points = coords.get("points")
    layout_height = coords.get("layout_height")
    image_path = meta.get("image_path")
    if not points or not layout_height or not image_path:
        return None
    if not (1 <= page_number <= len(pdf.pages)):
        return None

    pp_page = pdf.pages[page_number - 1]
    if not pp_page.height or not pp_page.width:
        return None
    scale = float(layout_height) / float(pp_page.height)  # == dpi/72
    if scale <= 0:
        return None

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    px: Box = (min(xs), min(ys), max(xs), max(ys))
    box: Box = (px[0] / scale, px[1] / scale, px[2] / scale, px[3] / scale)
    return _ElementBox(page_number, box, scale, str(image_path),
                       coords, points, px)


def repair_table_crops(pdf_path: str, elements: List[Dict[str, Any]],
                       image_output_dir: str) -> int:
    """Re-render and overwrite the crop file for each Table element with at least
    one corrected edge (see `corrected_box`) that differs from unstructured's own
    by more than 0.5pt, and update that element's `metadata.coordinates.points` IN
    PLACE to match (mutates `elements`; nothing is returned besides the count).

    PDF-only by construction: `elements` with no `metadata.image_path` / no
    `metadata.coordinates` (e.g. anything from a non-PDF source) are skipped, not
    errored on. Never raises for an individual element's own data being off-shape;
    a genuinely fatal problem (the PDF won't open, pdfplumber/pypdfium2 missing)
    propagates to the caller, which is expected to wrap this call in a broad
    try/except — a geometry repair must never fail a document parse.
    """
    table_elements = [e for e in elements
                      if isinstance(e, dict) and e.get("type") == "Table"]
    if not table_elements:
        return 0

    import pdfplumber
    import pypdfium2 as pdfium

    n_fixed = 0
    pdf_doc = pdfium.PdfDocument(pdf_path)
    try:
        with pdfplumber.open(pdf_path) as pdf:
            tables_cache: Dict[int, list] = {}
            page_img_cache: Dict[Tuple[int, float], Any] = {}
            words_cache: Dict[int, List[Box]] = {}

            # PRE-PASS: every Table element's STORED box, keyed by page, before
            # any element is repaired. Rule 7 needs the other elements' boxes on
            # the page (its sibling exclusion), and a repair that asked for them
            # mid-loop would see a mix of repaired and unrepaired siblings whose
            # content depends on element ORDER. Stored boxes are order-free and
            # are the conservative world -- see `_word_completed_box`.
            decoded = [(i, _decode_element_box(el, pdf))
                       for i, el in enumerate(table_elements)]
            stored_by_page: Dict[int, List[Tuple[int, Box]]] = {}
            for i, d in decoded:
                if d is not None:
                    stored_by_page.setdefault(d.page, []).append((i, d.box))

            for i, el in enumerate(table_elements):
                d = decoded[i][1]
                if d is None:
                    continue
                page_number, el_box_pts, scale = d.page, d.box, d.scale
                image_path, coords, points = d.image_path, d.coords, d.points
                x0_px, top_px, x1_px, bottom_px = d.px
                pp_page = pdf.pages[page_number - 1]
                page_height_pts = pp_page.height
                page_width_pts = pp_page.width

                tables = tables_cache.get(page_number)
                if tables is None:
                    tables = pp_page.find_tables()
                    tables_cache[page_number] = tables
                row_boxes, cell_boxes = _rows_and_cells_for_best_table(tables, el_box_pts)
                if page_number not in words_cache:
                    words_cache[page_number] = [
                        (w["x0"], w["top"], w["x1"], w["bottom"])
                        for w in pp_page.extract_words()]
                sibling_boxes = [b for (j, b) in stored_by_page[page_number]
                                 if j != i]
                new_x0_pts, new_top_pts, new_x1_pts, new_bottom_pts = corrected_box(
                    el_box_pts, row_boxes, cell_boxes, page_width_pts, page_height_pts,
                    word_boxes=words_cache[page_number],
                    sibling_boxes=sibling_boxes)

                moved = (
                    abs(new_x0_pts - el_box_pts[0]) > 0.5
                    or abs(new_top_pts - el_box_pts[1]) > 0.5
                    or abs(new_x1_pts - el_box_pts[2]) > 0.5
                    or abs(new_bottom_pts - el_box_pts[3]) > 0.5
                )
                if not moved:
                    continue  # not enough of a change on any edge to bother re-rendering

                crop_path = os.path.join(
                    image_output_dir,
                    os.path.basename(str(image_path).replace("\\", "/")),
                )
                if not os.path.exists(crop_path):
                    continue

                new_x0_px = new_x0_pts * scale
                new_top_px = new_top_pts * scale
                new_x1_px = new_x1_pts * scale
                new_bottom_px = new_bottom_pts * scale
                cache_key = (page_number, scale)
                page_img = page_img_cache.get(cache_key)
                if page_img is None:
                    pdfium_page = pdf_doc[page_number - 1]
                    try:
                        # Exactly rasterize_pdf_pages's own render call
                        # (doc_tools/utils/extraction.py) so the crop pixel space
                        # matches the layout/coordinates space bit for bit.
                        page_img = pdfium_page.render(scale=scale).to_pil().convert("RGB")
                    finally:
                        pdfium_page.close()
                    page_img_cache[cache_key] = page_img

                img_w, img_h = page_img.size
                left = max(0, min(int(round(new_x0_px)), img_w))
                right = max(left, min(int(round(new_x1_px)), img_w))
                upper = max(0, min(int(round(new_top_px)), img_h))
                lower = max(upper, min(int(round(new_bottom_px)), img_h))
                if right <= left or lower <= upper:
                    continue
                crop_img = page_img.crop((left, upper, right, lower))

                ext = os.path.splitext(crop_path)[1].lower()
                if ext == ".png":
                    crop_img.save(crop_path, format="PNG")
                else:
                    crop_img.convert("RGB").save(crop_path, format="JPEG", quality=85)

                # Same 4-point polygon SHAPE the element already used — only the
                # point(s) carrying an OLD x0/x1/top/bottom move, whichever index
                # they're at (see the coordinate-space note in the module
                # docstring). A point's x can carry the old x0 XOR the old x1
                # (never both, short of a degenerate zero-width box), and
                # likewise for y and top/bottom, so elif is safe here.
                new_points = []
                for p in points:
                    px, py = p[0], p[1]
                    if abs(px - x0_px) < 1e-6:
                        px = new_x0_px
                    elif abs(px - x1_px) < 1e-6:
                        px = new_x1_px
                    if abs(py - top_px) < 1e-6:
                        py = new_top_px
                    elif abs(py - bottom_px) < 1e-6:
                        py = new_bottom_px
                    new_points.append([px, py])
                coords["points"] = new_points
                n_fixed += 1
    finally:
        pdf_doc.close()
    return n_fixed
