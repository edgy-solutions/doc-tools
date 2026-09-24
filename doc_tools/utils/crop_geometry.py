"""Fix the Table-crop bottom edge unstructured's hi_res path cuts through.

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
  - `corrected_bottom` is PURE (plain tuples in, a float out) and holds ALL of the
    decision logic (rules 2-6 of the spec this implements) — testable with no PDF,
    no pdfplumber, no doc_tools import chain.
  - `repair_table_crops` is the IO half: opens the PDF with pdfplumber (rule 1: find
    the best-overlapping table) and pypdfium2 (re-render + re-crop), and is the only
    part that touches a file.

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
    share its bottom y). This module never assumes which INDEX holds which corner;
    it only replaces whichever points carry the OLD bottom y with the NEW one, which
    is robust to that ordering by construction.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

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


# --------------------------------------------------------------------------- #
# PURE — no PDF, no pdfplumber, no pypdfium2. Rules 2-6.
# --------------------------------------------------------------------------- #
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

    def _padded() -> float:
        return min(bottom + pad_frac * (bottom - top), page_height)

    if not row_boxes:
        return _padded()

    candidates = [rb for rb in row_boxes if rb[1] < bottom - 0.5]
    if not candidates:
        # A matched table, but nothing in it starts inside the element's own box —
        # there is no row here to complete. Leave the bottom alone.
        return min(bottom, page_height)

    # GUARD — a FILTER, not an abort.
    #
    # The extension is bounded by the tallest candidate row's height by construction
    # (the row R that sets `row_bottom` has R.top < bottom - 0.5, so R's own height
    # already exceeds the extension). That makes any guard phrased as "extension vs.
    # the tallest row used" dead code — it is an identity of rules 2+3, not a
    # data-dependent test. The real pathology is different in kind: pdfplumber's
    # `find_tables()` on a form-like page returns a "table" that has swallowed body
    # prose, and one of its "rows" is a prose block 300pt tall. That row is not a row.
    #
    # So reject implausible ROWS rather than abandoning the correction, and use two
    # independent tests because each covers the other's blind spot:
    #   - relative: a real table's rows are close in height, so a row towering over
    #     the median of its siblings is a swallow. Blind when EVERY row is a swallow.
    #   - absolute: a table row taller than `_MAX_PLAUSIBLE_ROW_PTS` is not a row at
    #     any scale. Covers the all-swallowed case, and the single-candidate case
    #     where there are no siblings to compare against at all.
    # Filtering (rather than returning `_padded()` outright) means a genuine row that
    # merely shares a table with a swallowed block still gets completed correctly.
    heights = sorted(rb[3] - rb[1] for rb in candidates)
    median_h = heights[len(heights) // 2]
    ceiling = min(_MAX_PLAUSIBLE_ROW_PTS,
                  max(median_h * _MAX_ROW_HEIGHT_RATIO, _MIN_ROW_HEIGHT_ALLOWANCE))
    plausible = [rb for rb in candidates if (rb[3] - rb[1]) <= ceiling]
    if not plausible:
        return _padded()

    corrected = max(bottom, max(rb[3] for rb in plausible))
    if corrected <= bottom:
        return min(bottom, page_height)  # already contains every plausible row
    return min(corrected, page_height)


# --------------------------------------------------------------------------- #
# IO — pdfplumber (rule 1) + pypdfium2 (re-render/re-crop). Everything below here
# touches a file or a PDF and is deliberately kept out of `corrected_bottom`.
# --------------------------------------------------------------------------- #
def _rows_for_best_table(tables: Sequence[Any], el_box_pts: Box) -> List[Box]:
    """Rule 1: the `pdfplumber` table (from `page.find_tables()`) with the largest
    overlap AREA against `el_box_pts`, and its rows' bboxes — or `[]` if none of
    `tables` overlaps the element's box at all."""
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
    if best is None:
        return []
    return [tuple(r.bbox) for r in best.rows]


def repair_table_crops(pdf_path: str, elements: List[Dict[str, Any]],
                       image_output_dir: str) -> int:
    """Re-render and overwrite the crop file for each Table element whose corrected
    bottom (see `corrected_bottom`) differs from unstructured's own by more than
    0.5pt, and update that element's `metadata.coordinates.points` IN PLACE to match
    (mutates `elements`; nothing is returned besides the count).

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
            for el in table_elements:
                meta = el.get("metadata") or {}
                page_number = meta.get("page_number")
                coords = meta.get("coordinates")
                if not page_number or not isinstance(coords, dict):
                    continue
                points = coords.get("points")
                layout_height = coords.get("layout_height")
                image_path = meta.get("image_path")
                if not points or not layout_height or not image_path:
                    continue
                if not (1 <= page_number <= len(pdf.pages)):
                    continue

                pp_page = pdf.pages[page_number - 1]
                page_height_pts = pp_page.height
                if not page_height_pts:
                    continue
                scale = float(layout_height) / float(page_height_pts)  # == dpi/72
                if scale <= 0:
                    continue

                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                x0_px, top_px, x1_px, bottom_px = min(xs), min(ys), max(xs), max(ys)
                el_box_pts: Box = (x0_px / scale, top_px / scale,
                                   x1_px / scale, bottom_px / scale)

                tables = tables_cache.get(page_number)
                if tables is None:
                    tables = pp_page.find_tables()
                    tables_cache[page_number] = tables
                row_boxes = _rows_for_best_table(tables, el_box_pts)
                new_bottom_pts = corrected_bottom(el_box_pts, row_boxes, page_height_pts)

                if (new_bottom_pts - el_box_pts[3]) <= 0.5:
                    continue  # not enough of a change to bother re-rendering

                crop_path = os.path.join(
                    image_output_dir,
                    os.path.basename(str(image_path).replace("\\", "/")),
                )
                if not os.path.exists(crop_path):
                    continue

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
                left = max(0, min(int(round(x0_px)), img_w))
                right = max(left, min(int(round(x1_px)), img_w))
                upper = max(0, min(int(round(top_px)), img_h))
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
                # point(s) carrying the OLD bottom y move, whichever index they're
                # at (see the coordinate-space note in the module docstring).
                new_points = [
                    [p[0], new_bottom_px if abs(p[1] - bottom_px) < 1e-6 else p[1]]
                    for p in points
                ]
                coords["points"] = new_points
                n_fixed += 1
    finally:
        pdf_doc.close()
    return n_fixed
