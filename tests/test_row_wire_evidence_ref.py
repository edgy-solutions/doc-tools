"""The row's `wire_evidence_ref` — the bytes the BFF now serves verbatim.

ARCHITECT RULING 2026-10-21 (the producer-owns-the-wire-shape ruling):

    *"The producer writes the wire shape; the BFF passes it verbatim.
    1. 7f emits wire_evidence_ref {page, bbox, note?} on every row, in
       fractions, alongside its internal bboxes/page_number. Rows with several
       boxes get bbox = their union, with note "n boxes".
    2. The BFF serves 7f's wire_evidence_ref as is. No renaming, no
       synthesizing, no page_dims of its own. Its reshaping code for evidence
       goes away. Old rows without wire_evidence_ref keep today's path
       (page_dims present) until they age out.
    3. The seal now spans the middle. Lane 1 adds the third leg."*

WHAT CHANGED ABOUT THE STAKES. Until this ruling the row's geometry was an
internal shape that the BFF reshaped, so a key name was negotiable and a
mistake was absorbed downstream. Now these three keys ARE what cortex's reader
receives. An extra key is a 422 at the BFF; an out-of-range box drops the whole
list. So the shape is pinned here key by key, not described.
"""
import pytest

from doc_tools.utils import sustainment_merge as merge

# 200-DPI US-letter, the space doc-tools ships pixel boxes in.
DIMS = {"width": 1700.0, "height": 2200.0}


def prov(**kw):
    base = {"page_number": 2, "page_dims": dict(DIMS), "bboxes": [],
            "match_method": "text_layer_cell", "match_confidence": 1.0}
    base.update(kw)
    return base


def ref(**kw):
    """The wire ref for a non-derived row with this provenance."""
    return merge._row_wire_evidence_ref(prov(**kw), "text_layer_cell")


# --------------------------------------------------------------------------- #
# The ruled shape
# --------------------------------------------------------------------------- #
def test_the_wire_ref_carries_EXACTLY_the_three_ruled_keys():
    """An extra key is a 422 at the BFF, and the way one would arrive is
    somebody passing the internal provenance through whole."""
    out = ref(bboxes=[[223.0, 917.0, 661.0, 953.0]])
    assert set(out) == {"page", "bbox"}
    # And with a note, exactly one more.
    multi = ref(bboxes=[[223.0, 917.0, 661.0, 953.0], [223.0, 960.0, 661.0, 996.0]])
    assert set(multi) == {"page", "bbox", "note"}


def test_the_box_is_in_FRACTIONS_not_the_pixels_it_came_from():
    out = ref(bboxes=[[223.0, 917.0, 661.0, 953.0]])
    assert out["bbox"] == [0.131176, 0.416818, 0.388824, 0.433182]
    assert all(0.0 <= v <= 1.0 for v in out["bbox"])


def test_the_wire_ref_carries_NO_page_dims_and_no_internal_key():
    """`page_dims` present is how cortex decides a box is in pixels, and the
    BFF no longer strips anything — so a stray one here would reach their
    reader and draw a speck."""
    out = ref(bboxes=[[223.0, 917.0, 661.0, 953.0]])
    for forbidden in ("page_dims", "page_number", "bboxes", "units",
                      "match_method", "match_confidence", "region"):
        assert forbidden not in out


def test_it_sits_ALONGSIDE_the_internal_keys_rather_than_replacing_them():
    """The ruling says *"alongside its internal bboxes/page_number"*. Old
    readers keep working through the transition; nothing is taken away."""
    item = merge._review_item("parts[0].mpn", "MC33063", "snip", "text_layer_cell",
                              prov(bboxes=[[223.0, 917.0, 661.0, 953.0]]))
    assert item["page_number"] == 2
    assert item["bboxes"] == [[0.131176, 0.416818, 0.388824, 0.433182]]
    assert item["wire_evidence_ref"] == {
        "page": 2, "bbox": [0.131176, 0.416818, 0.388824, 0.433182]}


# --------------------------------------------------------------------------- #
# The union, which is the ruling's one piece of new arithmetic
# --------------------------------------------------------------------------- #
def test_several_boxes_become_their_UNION_with_the_count_as_the_note():
    pixels = [[223.0, 917.0, 661.0, 953.0], [120.0, 960.0, 700.0, 996.0]]
    out = ref(bboxes=pixels)
    # Min of the mins, max of the maxes — over the CONVERTED boxes, so the
    # values are the 6-digit fractions and not the raw quotients.
    assert out["bbox"] == [round(120.0 / 1700, 6), round(917.0 / 2200, 6),
                           round(700.0 / 1700, 6), round(996.0 / 2200, 6)]
    assert out["note"] == "2 boxes"


def test_the_union_CONTAINS_every_box_it_replaces_exactly():
    """The property, not just the arithmetic: a steward reading a multi-line
    cell must not see one line outlined and no sign the others exist.

    Containment is asserted against the boxes this row actually EMITS in
    `bboxes`, which is the set a consumer could otherwise draw, and there it is
    exact — the union is min/max over those same values.
    """
    pixels = [[223.0, 917.0, 661.0, 953.0],
              [120.0, 960.0, 700.0, 996.0],
              [300.0, 1000.0, 500.0, 1040.0]]
    emitted = merge._row_fractions(prov(bboxes=pixels))
    x0, y0, x1, y1 = ref(bboxes=pixels)["bbox"]
    for b in emitted:
        assert x0 <= b[0] and y0 <= b[1] and x1 >= b[2] and y1 >= b[3]
    assert ref(bboxes=pixels)["note"] == "3 boxes"


def test_the_union_can_fall_one_ROUNDING_QUANTUM_short_of_the_raw_geometry():
    """Measured and accepted, rather than discovered later as a mystery.

    The union is taken over boxes already rounded to 6 places, so against the
    RAW pixel geometry an edge can be short by up to half a unit in the last
    place — 5e-7 of a page, or ~0.001 px at a full 2200 px render. That is
    below the sub-pixel bound the row seal already states, and it is the same
    quantum every individual emitted box carries, so widening the union would
    make it inconsistent with the `bboxes` beside it rather than more correct.

    This test exists so that "the union contains every box" is read with the
    precision it actually has. If the shortfall ever exceeds a quantum, the
    union stopped being a union.
    """
    pixels = [[223.0, 917.0, 661.0, 953.0], [300.0, 1000.0, 500.0, 1040.0]]
    x0, y0, x1, y1 = ref(bboxes=pixels)["bbox"]
    quantum = 0.5e-6
    for b in pixels:
        assert x0 <= b[0] / 1700 + quantum
        assert y0 <= b[1] / 2200 + quantum
        assert x1 >= b[2] / 1700 - quantum
        assert y1 >= b[3] / 2200 - quantum


def test_a_single_box_gets_NO_note():
    """`note` is optional and means something. A "1 boxes" on every ordinary
    row would be noise on the card and would train a reader to ignore it."""
    assert "note" not in ref(bboxes=[[223.0, 917.0, 661.0, 953.0]])


def test_the_note_counts_the_boxes_in_the_UNION_not_the_rows_raw_boxes():
    """One box here is past the page edge and converts to nothing, so it is
    not inside the outline being drawn. Counting it would overstate what the
    box covers."""
    out = ref(bboxes=[[223.0, 917.0, 661.0, 953.0],
                      [120.0, 960.0, 700.0, 996.0],
                      [1800.0, 100.0, 1900.0, 200.0]])  # entirely off-page
    assert out["note"] == "2 boxes"


# --------------------------------------------------------------------------- #
# The cases that yield no box, or no ref at all
# --------------------------------------------------------------------------- #
def test_a_page_with_no_box_still_gets_a_ref_with_a_null_bbox():
    """*"bbox may be null; page may not."* The card jumps to the page and
    labels it "on page N, no box" — that half works, and it is the NORMAL
    no-coordinates outcome because `page_number` comes from the metadata
    rather than from the geometry."""
    out = ref(bboxes=[])
    assert out == {"page": 2, "bbox": None}


def test_a_box_that_cannot_be_converted_says_WHY_in_the_note():
    """Once the numbers are unit-free the note is the only place an absent box
    still shows, so a row that never had geometry and a row whose geometry had
    no divisor must not look identical."""
    out = ref(bboxes=[[10.0, 10.0, 300.0, 30.0]], page_dims=None)
    assert out["page"] == 2 and out["bbox"] is None
    assert "unit-free" in out["note"]


def test_a_row_with_NO_PAGE_yields_no_ref_at_all():
    """The page is the locator and the box only refines it, so a ref with
    neither has nothing to offer. Omitted, never a null `page`."""
    assert ref(page_number=None) is None


def test_a_DERIVED_field_carries_no_evidence_ref_at_all():
    """*"Derived fields carry no evidence_ref at all, as ruled."* A derived
    value is on no page, so a `page` would be a fiction — and the row would
    navigate a steward somewhere the value is not stated."""
    assert merge._row_wire_evidence_ref(
        prov(bboxes=[[223.0, 917.0, 661.0, 953.0]]), "derived") is None


def test_the_key_is_OMITTED_from_the_item_rather_than_written_as_null():
    """An absent `evidence_ref` is how the reader is told there is no evidence;
    a null one is a malformed ref. Cortex's `readEvidence` returns "absent" for
    the first and "malformed" for the second, and only one of those is a
    card that renders."""
    derived = merge._review_item("header.part_count", 42, None, "derived",
                                 prov(bboxes=[]))
    assert "wire_evidence_ref" not in derived

    pageless = merge._review_item("parts[0].mpn", "X", "s", "text_layer_cell",
                                  prov(page_number=None))
    assert "wire_evidence_ref" not in pageless


# --------------------------------------------------------------------------- #
# The bound cortex refuses on, checked against the real predicate
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("boxes", [
    [[223.0, 917.0, 661.0, 953.0]],
    [[223.0, 917.0, 661.0, 953.0], [120.0, 960.0, 700.0, 996.0]],
    [[0.0, 0.0, 1700.0, 2200.0]],
    [[1.0, 1.0, 1699.0, 2199.0]],
])
def test_every_emitted_box_satisfies_cortexs_fraction_predicate(boxes):
    """`0 <= x0 < x1 <= 1` and the same in y, STRICTLY — a zero-area box fails.
    The failure is not local: it drops cortex's whole list and 422s the BFF, so
    a union must not be able to produce one."""
    out = ref(bboxes=boxes)
    x0, y0, x1, y1 = out["bbox"]
    assert 0 <= x0 < x1 <= 1
    assert 0 <= y0 < y1 <= 1
