"""Pure merge / reconcile / validation / review-payload helpers for the
sustainment two-pass extractor.

Deliberately imports ONLY the light modules (provenance, sustainment_normalize,
table_text_layer — the last is re + typing and nothing else) so the whole
merge+review pipeline is unit-testable without importing the heavy Dagster/BAML
stack. The plugin (doc_tools/plugins/sustainment.py) wires these
together with the two BAML calls.
"""
from typing import Any, List, Optional, Tuple

from doc_tools.utils import provenance
from doc_tools.utils import sustainment_normalize as norm
from doc_tools.utils import table_text_layer as text_layer


def _g(obj: Any, name: str):
    return getattr(obj, name, None)


def header_to_dict(h: Any) -> dict:
    """BAML NoticeHeader (or None / any duck-typed object) -> plain dict, with
    doc_type normalized to 'PCN'/'PDN'."""
    cats = [getattr(c, "value", c) for c in (_g(h, "categories") or [])]
    return {
        "doc_id": _g(h, "doc_id"),
        "doc_type": norm.normalize_doc_type(_g(h, "doc_type")),
        "revision": _g(h, "revision"),
        "pub_date": _g(h, "pub_date"),
        "pub_date_source": _g(h, "pub_date_source"),
        "mfr": _g(h, "mfr"),
        "mfr_source": _g(h, "mfr_source"),
        "mfr_parent": _g(h, "mfr_parent"),
        "mfr_parent_source": _g(h, "mfr_parent_source"),
        "categories": cats,
        "summary": _g(h, "summary"),
        "doc_level_ltb_date": _g(h, "doc_level_ltb_date"),
        "doc_level_ltb_date_source": _g(h, "doc_level_ltb_date_source"),
    }


def part_to_dict(p: Any) -> dict:
    return {
        "affected_mpn": _g(p, "affected_mpn"),
        "affected_mpn_source": _g(p, "affected_mpn_source"),
        "replacement_mpn": _g(p, "replacement_mpn"),
        "replacement_mpn_source": _g(p, "replacement_mpn_source"),
        "ltb_date": _g(p, "ltb_date"),
        "ltb_date_source": _g(p, "ltb_date_source"),
    }


def empty_header(doc_id: str) -> dict:
    return {"doc_id": doc_id, "doc_type": "PCN", "revision": None, "pub_date": "",
            "pub_date_source": None, "mfr": "", "mfr_source": None,
            # None, not "": an absent parent company is the COMMON case, and "" would read
            # as a parent the extractor lost. Matches the blank sentinel
            # `HEADER_SOURCED_FIELDS` declares for the field.
            "mfr_parent": None, "mfr_parent_source": None, "categories": [],
            "summary": "", "doc_level_ltb_date": None, "doc_level_ltb_date_source": None}


def dequote_parts(parts: List[dict]) -> int:
    """Strip enclosing quotes from MPN VALUES in place; returns how many it changed.

    A notice that prints its part numbers in quotes yields '"090-44310-31"'. The quote
    is a delimiter around the MPN, never a character of it — but downstream it is treated
    as one, and every graph MERGE, join and lookup against the real MPN silently misses.

    Runs BEFORE dedup_parts, or a quoted and an unquoted copy of the same part survive as
    two rows instead of collapsing into one.

    The *_source snippets are deliberately NOT touched: they are provenance, and
    provenance has to keep matching the document character-for-character.
    """
    n = 0
    for p in parts:
        for field in ("affected_mpn", "replacement_mpn"):
            raw = p.get(field)
            if not raw:
                continue
            clean = text_layer.strip_enclosing_quotes(raw)
            if clean != raw:
                p[field] = clean
                n += 1
    return n


def dedup_parts(parts: List[dict], counts: Optional[dict] = None) -> List[dict]:
    """Dedup by affected_mpn across crops (first occurrence wins). Drops rows
    with no affected_mpn. This is the multi-crop reconciliation: a page-spanning
    table extracted per-crop re-emits repeated headers / continued rows.

    When `counts` is passed, it is filled in place with two SEPARATE tallies:
    `counts["duplicate"]` (a row whose affected_mpn repeats one already kept)
    and `counts["no_mpn"]` (a row with no affected_mpn at all). Both keys are
    always set, including to 0 — a row disappearing for one reason is a
    different finding from it disappearing for the other, and 0 is itself
    informative (it says this fire had nothing to collapse).

    Routine collapsing is EXPECTED, not a defect signal: a page-spanning table
    extracted per-crop re-emits its header row and any continued row on every
    crop, so `duplicate` > 0 on a normal fire is the mechanism working as
    designed, not evidence of a problem.

    This counter is meant to be read as a FIRE-TO-FIRE DELTA, never as an
    absolute. "Collapsed 1 means a misread" is wrong on its own: if a degraded
    fire collapses one MORE duplicate than its sibling fires on the same
    document, that extra duplicate is suspect — a misread row that happened to
    collide with (or get produced alongside) a correct one, which dedup then
    silently ate. But if two fires collapse the SAME number of duplicates and
    one simply emitted fewer parts going in, the model never produced the
    missing row in the first place; dedup had nothing to do with that loss.
    Only the comparison across fires can tell those two cases apart.
    """
    seen, out = set(), []
    n_dup = 0
    n_no_mpn = 0
    for p in parts:
        k = (p.get("affected_mpn") or "").strip()
        if not k:
            n_no_mpn += 1
            continue
        if k in seen:
            n_dup += 1
            continue
        seen.add(k)
        out.append(p)
    if counts is not None:
        counts["duplicate"] = n_dup
        counts["no_mpn"] = n_no_mpn
    return out


def reconcile_ltb(parts: List[dict], doc_level_ltb: Optional[str]) -> List[dict]:
    """Per-part LTB: prefer per-row, fall back to the doc-level date (in place).

    Also RECORDS WHICH ONE WON, in `ltb_date_inherited`. That flag is what lets
    the review item carry honest evidence. Without it the backfill is invisible
    downstream: this function writes an ISO date into `ltb_date` and leaves
    `ltb_date_source` None, so the review builder used to fall back to
    searching the positioned OCR index for the ISO string itself — which the
    document never prints in that form (it says "June 6, 2024", or prints the
    date once in a header sentence and never on the row at all). Every such
    row therefore resolved to `not_found` BY CONSTRUCTION, measured at 965 of
    965 on the 88 deployed review.json. An inherited date is not unlocatable;
    its evidence is the header sentence that states it once.
    """
    for p in parts:
        own = p.get("ltb_date")
        own = own.strip() if isinstance(own, str) else own
        p["ltb_date"] = norm.effective_ltb(own, doc_level_ltb)
        p["ltb_date_inherited"] = bool(p["ltb_date"]) and not own
    return parts


def clean_replacements(parts: List[dict]) -> List[dict]:
    """Null out replacement_mpn values that are comma-separated lists (a vision
    model copying a Qualification Vehicle column into replacement on a PCN with
    no replacements). Keeps a genuine single replacement. In place."""
    for p in parts:
        cleaned = norm.clean_replacement(p.get("replacement_mpn"))
        if cleaned is None and p.get("replacement_mpn"):
            p["replacement_mpn_source"] = None
        p["replacement_mpn"] = cleaned
    return parts


def _row_fractions(prov: dict) -> List[list]:
    """A review item's `bboxes` in PAGE FRACTIONS, dropping any that cannot convert.

    ARCHITECT RULING 2026-10-21: page fractions, *"the same everywhere evidence_ref
    appears"* — which includes these rows. Lane 1 lifted the hold on 10-21 once
    cortex `a3cf4d1` (which reads both forms) went live in 204.

    `page_dims` is DROPPED by the caller in the same breath, and that is not
    cosmetic: cortex reads the presence of `page_dims` as "this box is in pixels"
    and would divide a fraction by 1700, drawing a speck in the page corner with no
    error — a coincidence defect visible only on converted data (their a3cf4d1
    packet, section 2). Converting the box and keeping the dims is therefore worse
    than doing neither.

    A box with no dims yields NOTHING rather than a bare pixel box: with the dims
    gone there is no divisor on either side, so a pixel box would read as a
    wildly out-of-range fraction and flag the row unreadable. It was already
    unusable before this change — cortex's pixel form needs `page_dims` to scale —
    so nothing that worked is lost.
    """
    return _convert_row_boxes(prov)[0]


def _convert_row_boxes(prov: dict) -> Tuple[List[list], Optional[str]]:
    """The row's boxes in page fractions, plus the one note worth carrying.

    Split out of `_row_fractions` so `wire_evidence_ref` can say WHY a row has
    no box. Once the numbers are unit-free the note is the only place an absent
    or wrong-space box still shows, so dropping it on the floor would make the
    two indistinguishable: a row that never had geometry and a row whose
    geometry could not be converted look identical without it.

    Returns `(boxes, note)`. The note is the FIRST distinct reason among the
    boxes that failed to convert, and is reported only when nothing converted —
    a row that got a usable box does not need to explain the one it dropped.
    """
    dims = prov.get("page_dims") or {}
    out: List[list] = []
    notes: List[str] = []
    for box in prov.get("bboxes") or []:
        frac, note = provenance.to_page_fractions(
            list(box) if box else None, dims.get("width"), dims.get("height"))
        if frac:
            out.append(frac)
        elif note and note not in notes:
            notes.append(note)
    return out, (notes[0] if notes and not out else None)


def _union(boxes: List[list]) -> list:
    """The smallest box containing all of them, in the same space.

    ARCHITECT RULING 2026-10-21: *"Rows with several boxes get bbox = their
    union, with note 'n boxes'."* A union is the only single box that cannot
    point at the WRONG cell: picking one of several (say `bboxes[0]`) outlines
    a real box, so a steward reading a two-line cell would see one line
    outlined and no indication the other exists.

    Taken over the CONVERTED boxes, so it contains every box this row emits in
    `bboxes` exactly. Against the raw pixel geometry it can fall short by half
    a unit in the last fraction place (~0.001 px at a full render), because its
    inputs are already rounded. That is deliberate: widening it would make the
    union inconsistent with the `bboxes` beside it, which carry the same
    quantum, and the shortfall is below the sub-pixel bound the row seal
    states. Pinned by
    ``test_row_wire_evidence_ref.py::test_the_union_can_fall_one_ROUNDING_QUANTUM_short_of_the_raw_geometry``.
    """
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _row_wire_evidence_ref(prov: dict, region) -> Optional[dict]:
    """The row's `{page, bbox, note?}` — the ruled wire shape, written here.

    ARCHITECT RULING 2026-10-21: *"7f emits `wire_evidence_ref {page, bbox,
    note?}` on every row, in fractions, alongside its internal
    bboxes/page_number ... The BFF serves 7f's wire_evidence_ref as is. No
    renaming, no synthesizing, no page_dims of its own."*

    So this is no longer an internal shape that something downstream reshapes:
    it is the bytes cortex's reader receives, and its keys are exactly the
    three the ruling names. An extra key is a 422 at the BFF and makes cortex
    drop the whole list.

    Two cases yield NO ref at all rather than a partial one:

    * **a derived field.** *"Derived fields carry no evidence_ref at all, as
      ruled"* — a derived value is on no page, so there is nothing to navigate
      to and a `page` would be a fiction.
    * **no page.** The same ruling: *"bbox may be null; page may not."* The
      page is the locator and the box only refines it, so a ref without one
      has nothing left to offer.

    A row WITH a page and no box still gets a ref (`bbox: None`): the card
    jumps to the page and labels it "on page N, no box". That half works and
    is the normal no-coordinates outcome, since `page_number` comes from the
    metadata rather than from the geometry.
    """
    if region == "derived":
        return None
    page = prov.get("page_number")
    if page is None:
        return None
    boxes, note = _convert_row_boxes(prov)
    out: dict = {"page": page, "bbox": None}
    if len(boxes) == 1:
        out["bbox"] = boxes[0]
    elif boxes:
        out["bbox"] = _union(boxes)
        # Counts the boxes in the UNION, not the row's raw boxes: a box that
        # failed to convert is not inside the outline being drawn, so counting
        # it would overstate what the box covers.
        note = f"{len(boxes)} boxes"
    if note:
        out["note"] = note
    return out


def _review_item(field_path, value, source, region, prov=None, needs_review=False, reason=None):
    prov = prov or {}
    item = {
        "field_path": field_path, "value": value, "source_snippet": source,
        "region": region, "page_number": prov.get("page_number"),
        # Page fractions, and NO `page_dims` — see `_row_fractions`. The key is
        # omitted, not nulled: cortex discriminates the two forms on its PRESENCE.
        "bboxes": _row_fractions(prov),
        "match_method": prov.get("match_method", "derived" if region == "derived" else "not_found"),
        "match_confidence": prov.get("match_confidence", 0.0),
        "needs_review": needs_review, "review_reason": reason,
        "approval_state": "pending",
    }
    # The ruled wire shape, served VERBATIM by the BFF, alongside the internal
    # `bboxes`/`page_number` above. Omitted entirely when there is no page or
    # the field is derived — never written as null, because an absent
    # `evidence_ref` is how the reader is told there is no evidence, while a
    # null one is a malformed ref.
    wire = _row_wire_evidence_ref(prov, region)
    if wire is not None:
        item["wire_evidence_ref"] = wire
    return item


def build_review_items(header: dict, parts: List[dict], index: List[dict],
                       ocr_text_norm: str) -> Tuple[List[dict], List[str]]:
    """One review item per approvable value, each with provenance + needs_review.
    Returns (items, doc-level reasons)."""
    items: List[dict] = []
    reasons: List[str] = []

    doc_ltb_prov: Optional[dict] = None
    doc_ltb_src: Optional[str] = None
    for fp, val, src in (
        ("header.pub_date", header.get("pub_date"), header.get("pub_date_source")),
        ("header.mfr", header.get("mfr"), header.get("mfr_source")),
        ("header.mfr_parent", header.get("mfr_parent"), header.get("mfr_parent_source")),
        ("header.doc_level_ltb_date", header.get("doc_level_ltb_date"),
         header.get("doc_level_ltb_date_source")),
    ):
        if not val:
            continue
        prov = provenance.resolve_value(src or val, index, prefer_region="narrative")
        nr = not prov["found"]
        reason = "source not located in document" if nr else None
        if nr:
            reasons.append(f"{fp}: source not located")
        items.append(_review_item(fp, val, src or val, "header", prov, nr, reason))
        if fp == "header.doc_level_ltb_date" and prov["found"]:
            # KEPT for the rows that inherit this date. The doc-level LTB is stated
            # once, in prose, and resolves against its own verbatim source; a row
            # that inherited it points a reviewer AT THAT SENTENCE. Only kept when
            # it actually resolved: an unlocated header date has no evidence to lend.
            doc_ltb_prov, doc_ltb_src = prov, src or val

    if header.get("summary"):
        items.append(_review_item("header.summary", header.get("summary"), None, "derived"))
    if header.get("categories"):
        items.append(_review_item("header.categories", header.get("categories"), None, "derived"))

    for i, p in enumerate(parts):
        amp = p.get("affected_mpn")
        amp_src = p.get("affected_mpn_source") or amp
        # TEXT-LAYER parts carry AUTHORITATIVE provenance: the exact bbox of the CELL the
        # value was read out of. Prefer it over resolve_value's string-match, which is a
        # best-effort search of a positioned OCR index — it resolves to the enclosing
        # TABLE region (every part on a page sharing one huge box) and can miss entirely
        # ("source not located"). Overwriting a known cell with a guessed table was
        # discarding the whole point of reading the text layer.
        tl_bbox = p.get("text_layer_bbox")
        if tl_bbox:
            prov = {
                "found": True,
                "page_number": p.get("text_layer_page"),
                "bboxes": [tl_bbox],
                "page_dims": p.get("text_layer_page_dims"),
                "match_method": "text_layer_cell",
                "match_confidence": 1.0,
            }
        else:
            prov = provenance.resolve_value(amp_src, index, prefer_region="table")
        # A text-layer value came OUT of the document, so it cannot be a hallucination —
        # the OCR-verbatim check exists to catch vision transcription/invention and does
        # not apply. (It would also false-positive: the OCR text stream and the table cell
        # can tokenize differently.)
        in_ocr = True if tl_bbox else ((provenance._norm(amp) in ocr_text_norm) if amp else False)
        reason = None
        if not in_ocr:
            reason = "affected_mpn not found verbatim in OCR text (possible hallucination)"
        elif not prov["found"]:
            reason = "source not located"
        nr = reason is not None
        if nr:
            reasons.append(f"parts[{i}].affected_mpn: {reason}")
        items.append(_review_item(f"parts[{i}].affected_mpn", amp, amp_src, "table", prov, nr, reason))

        if p.get("replacement_mpn"):
            # Same authority rule as the affected MPN. The replacement sits in the paired
            # cell on the same row; the row's bbox locates it far better than a string
            # search that would land on the enclosing table (or nothing).
            rep_bbox = p.get("text_layer_replacement_bbox")
            if rep_bbox:
                rprov = {"found": True, "page_number": p.get("text_layer_page"),
                         "bboxes": [rep_bbox], "page_dims": p.get("text_layer_page_dims"),
                         "match_method": "text_layer_cell", "match_confidence": 1.0}
            else:
                rprov = provenance.resolve_value(
                    p.get("replacement_mpn_source") or p["replacement_mpn"], index, prefer_region="table")
            rnr = not rprov["found"]
            items.append(_review_item(f"parts[{i}].replacement_mpn", p["replacement_mpn"],
                                      p.get("replacement_mpn_source"), "table", rprov, rnr,
                                      "source not located" if rnr else None))
        if p.get("ltb_date"):
            lsrc = p.get("ltb_date_source")
            if p.get("ltb_date_inherited") and doc_ltb_prov:
                # INHERITED from the document-level date: the row prints no date, so
                # the only honest evidence is the header sentence that states it once.
                # Point the reviewer there, and SAY SO in match_method — an inherited
                # bbox must never be mistaken for a cell this row owns.
                lprov = dict(doc_ltb_prov, match_method="inherited_doc_level")
                lsrc = doc_ltb_src
            else:
                # Resolve on the VERBATIM SOURCE ONLY, never on the value. The value is
                # an ISO date the document is not obliged to print in that form, so the
                # old `or p["ltb_date"]` fallback searched for a string that mostly does
                # not exist. Dropping it also removes a hazard the MPN fields do not
                # have: an MPN's value IS its printed form, but a bare ISO date can
                # match an UNRELATED occurrence elsewhere on the page and outline the
                # wrong thing. For a steward vetting a row in a few looks, a confident
                # wrong crop is worse than an honest not_found. Where a document really
                # does print ISO dates, the model's source snippet is that same string,
                # so this path loses nothing real.
                lprov = provenance.resolve_value(lsrc, index, prefer_region="table")
            items.append(_review_item(f"parts[{i}].ltb_date", p["ltb_date"],
                                      lsrc, "table", lprov, False, None))
    return items, reasons


def validate_count(header: dict, n_parts: int) -> Optional[str]:
    """Cross-pass sanity check: summary-implied count vs extracted count."""
    stated = norm.summary_stated_count(header.get("summary"))
    if stated is not None and stated != n_parts:
        return f"cross-check: summary implies ~{stated} parts but {n_parts} were extracted"
    return None
