"""The TI PCN#20210316000.1 live miss, as measured on sandbox at pin c8dce84a.

A review task reached alice's queue with ONE affected part — `"Jun 22, 2021"` — at
`match_confidence: 1.0`, `match_method: "text_layer_cell"`, page 3, and
`needs_review: False`. The nine devices the notice actually names were not found,
and the notice type came back unclassified and was defaulted to PCN.

Everything in this module is transcribed from the real artifacts, not invented:

  * `_page3_form()` and `_PRODUCT_AFFECTED` are `page.find_tables()[0]` and `[2]` of
    `sustainment/inbound/TI_PCN_20210316000.pdf` (480,972 bytes, the size recorded in
    `scripts/pcn_ground_truth.json`), read with the pod's own pdfplumber.
  * `_ELEMENTS` is the `Title`/`NarrativeText` surface of that document's `text.json`
    under `doc-tools@f56df3a.../`, in document order.
  * The outcome being pinned is `review.json` from the same prefix: `review_items[4]`
    is `parts[0].affected_mpn` = `"Jun 22, 2021"`, and `doc_type_source` is
    `"no-title-evidence"`.

The four `test_*` functions below assert the CORRECT behaviour and therefore FAIL
until the fix lands; `test_the_embedded_tables_are_the_document_as_pdfplumber_reads_it`
is a fidelity guard that passes now and keeps the transcription honest.
"""
from typing import Dict, List, Optional, Tuple

import pytest

from doc_tools.utils import sustainment_header_trust as header_trust
from doc_tools.utils import table_text_layer as text_layer

# --------------------------------------------------------------------------- #
# page 3, table 0 — the notice's own form, bbox (48.6, 70.5, 557.1, 524.1).
#
# 27 rows x 30 columns, nearly all empty: the form's labels and values land in
# whichever cell the ruling lines put them in, and the two do NOT always share a row.
# Written sparsely because writing it out in full would be 810 cells of "".
#
# THE SHAPE THAT CAUSES THE MISS is rows 5 and 6: the value "Jun 22, 2021" is at
# r5c10 while its label "Proposed 1st Ship Date:" is at r6c1 — one row BELOW. The
# label is prose and would have vetoed the row it was on; it is not on that row.
# --------------------------------------------------------------------------- #
_FORM_ROWS = 27
_FORM_COLS = 30

_FORM_CELLS: Dict[Tuple[int, int], str] = {
    (0, 1): "PCN Number:", (0, 8): "20210316000.1",
    (0, 21): "PCN Date:", (0, 28): "Mar 25, 2021",
    (1, 6): "Die Coating addition for Select Devices",
    (2, 1): "Title:",
    (4, 1): "Customer Contact:", (4, 10): "PCN Manager",
    (4, 18): "Dept:", (4, 26): "Quality Services",
    (5, 10): "Jun 22, 2021", (5, 16): "Estimated Sample",
    (5, 26): "Date provided at\nsample request.",
    (6, 1): "Proposed 1st Ship Date:",
    (7, 16): "Availability:",
    (9, 1): "Change Type:",
    (10, 4): "Assembly Site", (10, 14): "Assembly Process", (10, 24): "Assembly Materials",
    (11, 4): "Design", (11, 14): "Electrical Specification",
    (11, 24): "Mechanical Specification",
    (12, 4): "Test Site", (12, 14): "Packing/Shipping/Labeling", (12, 24): "Test Process",
    (13, 4): "Wafer Bump Site", (13, 14): "Wafer Bump Material",
    (13, 24): "Wafer Bump Process",
    (14, 4): "Wafer Fab Site", (14, 14): "Wafer Fab Materials",
    (14, 24): "Wafer Fab Process",
    (15, 14): "Part number change",
    (16, 0): "PCN Details",
    (17, 1): "Description of Change:",
    (18, 0): ("This notification is to announce the qualification of Polyimide Die "
              "Coating material for the devices\nlisted in “Product Affected” "
              "section.\nDie Coat Current Change To\nNONE POLYIMIDE"),
    (19, 1): "Reason for Change:",
    (20, 0): "Continuity of Supply",
    (21, 1): ("Anticipated impact on Form, Fit, Function, Quality or Reliability "
              "(positive / negative):"),
    (22, 0): "None",
    (23, 1): "Changes to product identification resulting from this PCN:",
    (24, 0): "Not applicable",
    (25, 1): "Product Affected:",
    (26, 0): ("TPS54340DDA TPS54360DDA TPS54540DDA TPS54560DDA\n"
              "TPS54340DDAR TPS54360DDAR TPS54540DDAR TPS54560DDAR\n"
              "TPS54340DDAR-P"),
}


def _page3_form() -> List[List[str]]:
    return [[_FORM_CELLS.get((r, c), "") for c in range(_FORM_COLS)]
            for r in range(_FORM_ROWS)]


# page 3, table 2 — bbox (54.3, 477.3, 530.3, 524.1). THE PRODUCT AFFECTED LIST.
# All nine devices, and nothing else: no column header, and the caption that names
# it ("Product Affected:") is not in this table at all — it is at r25c1 of the form
# above, a DIFFERENT table. So this grid is declined for having nothing to label it.
_PRODUCT_AFFECTED: List[List[Optional[str]]] = [
    ["TPS54340DDA", "TPS54360DDA", "TPS54540DDA", "TPS54560DDA"],
    ["TPS54340DDAR", "TPS54360DDAR", "TPS54540DDAR", "TPS54560DDAR"],
    ["TPS54340DDAR-P", None, None, None],
]

# page 3, table 1 — the die-coat before/after pair. Declined, correctly: it names a
# material, not a part. Here so the page is the real page and not a convenient subset.
_DIE_COAT: List[List[Optional[str]]] = [
    ["", "Die Coat Current", "", "", "Change To", ""],
    ["NONE", None, None, "POLYIMIDE", None, None],
]

# The nine devices, from scripts/pcn_ground_truth.json (count: 9), verbatim-confirmed
# in the source PDF's text layer. DEVICES ONLY, ruled 2026-10-10: page 2's customer
# part numbers are the customers' own designations, not additional affected parts.
_NINE_DEVICES = [
    "TPS54340DDA", "TPS54360DDA", "TPS54540DDA", "TPS54560DDA",
    "TPS54340DDAR", "TPS54360DDAR", "TPS54540DDAR", "TPS54560DDAR",
    "TPS54340DDAR-P",
]

# text.json's element surface, in document order. Four elements are typed `Title` and
# every one is a section heading; the document's own headline — the only text that says
# what KIND of notice this is — is typed `NarrativeText`, element [2].
_ELEMENTS = [
    {"type": "Image", "text": "TEXAS INSTRUMENTS"},
    {"type": "UncategorizedText", "text": "12500 TI Boulevard, MS 8640, Dallas, Texas 75243"},
    {"type": "NarrativeText",
     "text": ("PCN#20210316000.1 Die Coat addition for select devices "
              "Change Notification / Sample Request")},
    {"type": "ListItem", "text": "Date: March 25, 2021"},
    {"type": "ListItem", "text": "To: Flextronics PCN"},
    {"type": "NarrativeText", "text": "Dear Customer:"},
    {"type": "NarrativeText",
     "text": ("This notice does not change the end-of-life status of any product. Should "
              "product affected be on a previously issued product withdrawal notice...")},
    {"type": "Title", "text": "Attachment: 1"},
    {"type": "Title", "text": "Products Affected:"},
    {"type": "Title", "text": "Reason for Change:"},
    {"type": "Title", "text": "IMPORTANT NOTICE AND DISCLAIMER"},
]


# --------------------------------------------------------------------------- #
# fidelity guard — passes today, and keeps the transcription above honest
# --------------------------------------------------------------------------- #

def test_the_embedded_tables_are_the_document_as_pdfplumber_reads_it():
    """Not a behaviour assertion: a check that the grids above still describe the real
    page. If someone 'tidies' the sparse form into something more readable and the
    label/value row split disappears, the miss stops reproducing and the tests below
    would pass for the wrong reason."""
    form = _page3_form()
    assert (len(form), len(form[0])) == (27, 30)

    # the shape that defeats the prose veto: value and label on DIFFERENT rows
    assert form[5][10] == "Jun 22, 2021"
    assert form[6][1] == "Proposed 1st Ship Date:"
    assert not any("Ship Date" in (c or "") for c in form[5])

    # the caption that names the parts list is in the FORM, not in the parts table
    assert form[25][1] == "Product Affected:"
    assert not any("Affected" in (c or "") for row in _PRODUCT_AFFECTED for c in row or [])

    # no column header anywhere in the parts table, which is why it is declined today
    assert text_layer.find_header_row(_PRODUCT_AFFECTED) is None
    assert text_layer.find_title_row(_PRODUCT_AFFECTED) is None

    # and the nine devices really are all of it
    flat = [c for row in _PRODUCT_AFFECTED for c in row if c]
    assert sorted(flat) == sorted(_NINE_DEVICES)


# --------------------------------------------------------------------------- #
# 1. the bait date must not be a part
# --------------------------------------------------------------------------- #

def test_the_page3_form_yields_no_parts_at_all():
    """THE LIVE MISS. The form carries no part numbers — the nine devices are in their
    own table — so tier 1 must take nothing from it. Today it returns
    ['Jun 22, 2021'] from r5c10."""
    parts = text_layer.parts_from_grid(_page3_form())
    assert [p["affected_mpn"] for p in parts] == []


@pytest.mark.parametrize("bait", [
    "Jun 22, 2021",      # the exact value that reached alice's queue
    "Mar 25, 2021",      # r0c28 of the same form, one veto away from being next
    "March 25, 2021",
    "2021-06-22",
    "06/22/2021",
])
def test_a_date_is_never_a_part_number(bait):
    """A candidate that parses as a date is rejected at the parts boundary, never
    emitted. `looks_like_mpn` admitted all of these: 12 characters, two spaces, a
    digit present — which is the whole of the plausibility floor it applied."""
    assert not text_layer.looks_like_mpn(bait), bait


@pytest.mark.parametrize("label", [
    "PCN Number:", "PCN Date:", "Title:", "Dept:", "Change Type:",
    "Product Affected:", "Proposed 1st Ship Date:", "Availability:",
])
def test_a_form_label_is_never_a_part_number(label):
    """Labels are the other half of a form. None of these is a part number, and
    `Product Affected:` becoming one would be especially bad: it is the caption of the
    list we are trying to find."""
    assert not text_layer.looks_like_mpn(label), label


def test_the_real_mpns_still_pass_the_tightened_floor():
    """The tightening must not cost recall. `090-44310-31` is the one most at risk from
    a date rule and it is a real part number in this corpus."""
    for mpn in _NINE_DEVICES + ["090-44310-31", "S1613E-20.0000 (T)", "2683",
                                "WL2511F0048.000000", "LTC6226HDC#TRMPBF"]:
        assert text_layer.looks_like_mpn(mpn), mpn


# --------------------------------------------------------------------------- #
# 2. the labelled parts table must win, and must be found at all
# --------------------------------------------------------------------------- #

def test_the_bare_grid_on_its_own_is_still_declined():
    """CORRECTED 2026-10-10, and the correction is the finding. This test first asked the
    bare grid to yield its nine devices with nothing naming it — and that rule cannot be
    had. A headerless, captionless grid of MPN-shaped tokens is byte-for-byte the shape
    of a continuation row (`_CONT_ROW` in test_table_text_layer.py), which is pinned to
    decline because reading it guesses at columns nobody labelled. Any rule strong
    enough to pass the old assertion broke four such pins.

    So the decline stays, and it is correct. What was missing was never a grid-intrinsic
    rule: it is the CONNECTION to the label the document actually prints."""
    out = text_layer.grid_outcome(_PRODUCT_AFFECTED)
    assert out.parts == []
    assert out.decline is not None
    assert "no caption naming the contents" in out.decline.reason


def test_the_grid_yields_all_nine_devices_once_a_label_names_it():
    """The other half of the same mechanism, at unit level: the caption DOES exist —
    'Product Affected:' — it is just in the enclosing form rather than inside this grid.
    Once that connection is made, every column is an affected part and all nine devices
    come out. That the connection is found on the real page is the next test's job; this
    one pins only what follows from it."""
    out = text_layer.grid_outcome(_PRODUCT_AFFECTED, labelled=True)
    assert out.decline is None, out.decline
    assert sorted(p["affected_mpn"] for p in out.parts) == sorted(_NINE_DEVICES)


def test_the_labelled_parts_table_wins_over_the_form_on_the_same_page():
    """Page 3 end to end, in the order pdfplumber returns the tables. A table labelled
    'Product Affected' is a parts source; cells in the notice's header/form region are
    not, whatever they look like. Today this page yields exactly the wrong one of the
    two: one date, no devices."""
    parts, _declines = text_layer.parts_and_declines_from_pages([(3, _real_page3())])
    got = [p["affected_mpn"] for p in parts]
    assert sorted(got) == sorted(_NINE_DEVICES)
    assert "Jun 22, 2021" not in got


def test_the_label_names_only_the_grid_below_it_not_every_later_table():
    """The locator's one real hazard, pinned on the page that exposed it. "Product
    Affected:" bottoms at y=464; the die-coat table's top is y=309, ABOVE the label, so
    the label does not name it. A page-order rule marks it anyway and it stays empty only
    because "NONE" and "POLYIMIDE" carry no digits — put digits in a table like that and
    the weaker rule emits them as parts."""
    tables = _real_page3().find_tables()
    assert text_layer._labelled_table_indices(tables) == {2}


def test_a_digit_bearing_table_after_the_label_is_not_swept_in():
    """The same hazard with the content that makes it bite: a revision or spec grid whose
    cells do carry digits. It sits BELOW the label here, and the nearest-table rule still
    excludes it, because the device grid is nearer."""
    spec = [["Storage temp", "125", "C"],
            ["Lead pitch", "0.5mm", "nominal"],
            ["Moisture level", "MSL3", "260C"]]
    page = _FakePage(
        _FakeTable(_page3_form(), _TABLE_BBOXES["form"], _LABEL_CELL_BBOX),
        _FakeTable(_PRODUCT_AFFECTED, _TABLE_BBOXES["devices"]),
        _FakeTable(spec, (54.32, 560.0, 530.28, 610.0)),
    )
    assert text_layer._labelled_table_indices(page.find_tables()) == {1}
    parts, _declines = text_layer.parts_and_declines_from_pages([(3, page)])
    got = [p["affected_mpn"] for p in parts]
    assert sorted(got) == sorted(_NINE_DEVICES)
    for fabricated in ("125", "0.5mm", "MSL3", "260C"):
        assert fabricated not in got


# --------------------------------------------------------------------------- #
# 3. the classifier
# --------------------------------------------------------------------------- #

def test_the_notice_classifies_as_a_pcn_from_its_own_printed_headline():
    """`doc_type_source` came back 'no-title-evidence' and the type was defaulted to
    PCN — the right answer reached by no evidence, which is a coin landing correctly.

    The document states its type plainly: 'PCN#20210316000.1 ... Change Notification /
    Sample Request'. `doc_type_from_titles` classifies that string ('PCN', 'title') the
    moment it is offered one. It is never offered it, because the partitioner typed
    that line `NarrativeText` and only `Title` elements are considered. TI is the first
    notice in the corpus whose headline is not a `Title`.

    The end-of-life sentence in element [6] is the hazard any widening has to survive:
    it is page-1 prose about a PREVIOUS notice, and a blob scan would read its
    'end-of-life' as a PDN keyword contradicting the explicit PCN code.

    The surface the classifier consumes is therefore NOT `titles_from_elements` — that
    function means what it says, every `Title`-typed element, and it keeps meaning it
    (pinned just below). The widening is its own named thing."""
    candidates = header_trust.headline_candidates(_ELEMENTS)
    doc_type, source = header_trust.doc_type_from_titles(candidates)
    assert doc_type == "PCN", (doc_type, source, candidates)
    assert source == "title", (doc_type, source, candidates)


def test_titles_from_elements_keeps_its_narrow_meaning():
    """The widening must not be done by quietly redefining `titles_from_elements` to
    return things that are not titles. It still returns exactly the `Title` elements,
    and on this document that is exactly the four section headings that caused the
    miss — which is the fact the fix routes around rather than erases."""
    assert header_trust.titles_from_elements(_ELEMENTS) == [
        "Attachment: 1", "Products Affected:", "Reason for Change:",
        "IMPORTANT NOTICE AND DISCLAIMER",
    ]


def test_the_headline_would_classify_if_it_were_offered():
    """Passes today. Pins the fact that the classifier's LOGIC is sound and the defect
    is in which elements it is handed — so the fix belongs in the title surface, not in
    the keyword rules."""
    headline = ("PCN#20210316000.1 Die Coat addition for select devices "
                "Change Notification / Sample Request")
    assert header_trust.doc_type_from_titles([headline]) == ("PCN", "title")
    # and the four real Titles genuinely say nothing about the type
    assert header_trust.doc_type_from_titles(
        ["Attachment: 1", "Products Affected:", "Reason for Change:",
         "IMPORTANT NOTICE AND DISCLAIMER"]) == (None, "no-title-evidence")


# --------------------------------------------------------------------------- #
# the same fake page the rest of the suite uses (tests/test_table_text_layer.py)
# --------------------------------------------------------------------------- #

class _FakeTable:
    """`bbox` and `cell_bboxes` are OPTIONAL and, where given, are MEASURED off the real
    page 3 (see `_TABLE_BBOXES`). Cells with no measured bbox keep the unit-square
    placeholders the other table tests use; those feed provenance highlighting only, and
    the label logic reads a measured cell or nothing."""

    def __init__(self, grid, bbox=None, cell_bboxes=None):
        self._grid = grid
        cb = cell_bboxes or {}
        self.rows = [type("R", (), {"cells": [cb.get((r, c), (c, r, c + 1, r + 1))
                                              for c in range(len(row))]})()
                     for r, row in enumerate(grid)]
        if bbox is not None:
            self.bbox = bbox

    def extract(self):
        return self._grid


# Measured in-pod off the real PDF, 2026-10-10 (pdfplumber find_tables on page 3;
# bbox = x0, top, x1, bottom, top-down). These are load-bearing, not decoration: the
# parts-label locator names the nearest table BELOW the label, and only the real y
# values put the die-coat table (top 309.08) ABOVE the "Product Affected:" label
# (bottom 464.32) and the device grid (top 477.33) below it. With placeholder geometry
# the test would fall back to page order and pass for the wrong reason.
_TABLE_BBOXES = {
    "form": (48.63, 70.49, 557.11, 524.13),
    "die_coat": (54.32, 309.08, 552.07, 337.81),
    "devices": (54.32, 477.33, 530.28, 524.13),
}
_LABEL_CELL_BBOX = {(25, 1): (54.32, 451.69, 552.07, 464.32)}   # 'Product Affected:'


class _FakePage:
    width, height = 595.4, 841.66   # the real page 3's dimensions

    def __init__(self, *grids):
        self._tables = [g if isinstance(g, _FakeTable) else _FakeTable(g) for g in grids]

    def find_tables(self):
        return self._tables


def _real_page3() -> _FakePage:
    """Page 3 with the real tables AND their real geometry, in pdfplumber's order."""
    return _FakePage(
        _FakeTable(_page3_form(), _TABLE_BBOXES["form"], _LABEL_CELL_BBOX),
        _FakeTable(_DIE_COAT, _TABLE_BBOXES["die_coat"]),
        _FakeTable(_PRODUCT_AFFECTED, _TABLE_BBOXES["devices"]),
    )


# =========================================================================== #
# PAGE 2 — excluded by ACCIDENT, and this section is what stops that accident
# from being load-bearing.
#
# Measured 2026-10-10 on the real PDF: `page.find_tables()` returns ZERO tables
# for page 2. The page carries a 15-row `DEVICE | CUSTOMER PART NUMBER` table in
# its text layer, and the text-layer pass never sees it as a table at all. The
# DEVICES-ONLY ruling (ground truth, `TI_PCN_20210316000.pdf.source`) says those
# customer part numbers are not affected parts — so the extractor agrees with the
# ruling for a reason that has nothing to do with the ruling.
#
# A GLOBAL RULE IS NOT AVAILABLE, and that is measured too: 10 of TYC's 26
# ground-truth parts come from a column headed `Customer Part Number`, so
# "a customer part number is never an affected part" would take TYC from 26/26 to
# 16/26. The two notices use that column to mean different things, and the general
# question stays open.
#
# What is available is an ENUMERATION. `_PAGE2` below is page 2 as the document
# prints it, and the tests assert that everything it could possibly contribute is
# already adjudicated — each string is either one of the nine real devices or one
# of the eleven parts ground truth rules out by name. A detector change, or a
# vision pass over this page, therefore cannot admit the eleven silently: the gate
# names them, and anything NOT on either list reddens CI at PR time.
# =========================================================================== #
_PAGE2_ROWS = [
    ("TPS54340DDAR", "AGIH-1827-5217"),
    ("TPS54560DDAR", "AGIH-1827-5253"),
    ("TPS54560DDAR", "CBI-C5ICS-F0023"),
    ("TPS54540DDAR", "DYGG-311220-01/02"),
    ("TPS54560DDAR", "GEC-5499697"),
    ("TPS54560DDAR", "GEC1H-5499697"),
    ("TPS54540DDAR", "INGH-192055445"),
    ("TPS54340DDAR", "PBEH-453564691091"),
    ("TPS54560DDAR", "SEA3H-HUA39159"),
    ("TPS54360DDAR", "TDN1G-300-611-00"),
    ("TPS54360DDA", "null"),               # literal "null" on the page, 3 of them
    ("TPS54540DDA", "null"),
    ("TPS54340DDA", "null"),
    ("TPS54560DDA", "CBI-C5ICS-F0023"),    # the one duplicate customer part number
    ("TPS54360DDAR", "KODH-112-00240"),
]

# The table AS IT WOULD BE IF DETECTED. Written out because the hazard cannot be
# tested against a page that yields no tables: the question is not what page 2
# does today, it is what happens the day it stops being invisible.
_PAGE2 = [["DEVICE", "CUSTOMER PART NUMBER"]] + [list(r) for r in _PAGE2_ROWS]


def _ti_ground_truth():
    """TI's entry from the SHIPPED ground-truth file, not a copy of it.

    A copy would let the file and this module drift, and the drift would be
    invisible in exactly the direction that matters: a customer part number
    quietly dropped from `expect_absent_mpns` while these tests keep passing
    against the stale copy. Returns the scorer module too, since the gate's
    verdict is part of what is being asserted.
    """
    import importlib.util
    from pathlib import Path

    scripts = Path(__file__).resolve().parents[1] / "scripts"
    spec = importlib.util.spec_from_file_location("pcn_score",
                                                  scripts / "pcn_score.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, mod.load_ground_truth()["TI_PCN_20210316000.pdf"]


def test_page_two_is_transcribed_as_the_document_prints_it():
    """Fidelity guard, independent of any extractor behaviour.

    Ground truth's `source` describes this page in words -- "15 DEVICE + CUSTOMER
    PART NUMBER rows (11 distinct customer part numbers, 3 literal 'null' cells,
    1 duplicate)". Those four numbers are asserted here against the transcription,
    so the prose and the fixture cannot disagree.
    """
    assert len(_PAGE2_ROWS) == 15
    cpns = [c for _d, c in _PAGE2_ROWS]
    assert cpns.count("null") == 3
    real = [c for c in cpns if c != "null"]
    assert len(real) == 12 and len(set(real)) == 11        # one duplicate
    assert real.count("CBI-C5ICS-F0023") == 2

    devices = {d for d, _c in _PAGE2_ROWS}
    assert len(devices) == 8
    assert devices < set(_NINE_DEVICES), \
        "page 2 devices must be a strict subset of page 3 nine"


def test_the_eleven_ruled_out_parts_are_exactly_page_twos_own_column():
    """The corpus list and the page must be the same eleven strings.

    This is the join that makes the guard below meaningful: `expect_absent_mpns`
    is only a real enumeration of the hazard if it enumerates THIS page.
    """
    _mod, gt = _ti_ground_truth()
    on_page = {c for _d, c in _PAGE2_ROWS if c != "null"}
    assert set(gt["expect_absent_mpns"]) == on_page
    assert len(gt["expect_absent_mpns"]) == 11


def test_page_two_can_emit_nothing_that_is_not_already_adjudicated():
    """THE GUARD. Every string page 2 can contribute is already decided.

    Deliberately written as a SUBSET assertion, not an equality, so that it never
    inverts: it holds today, when the grid yields 8 devices and all 11 customer
    part numbers, and it still holds if the DEVICES-ONLY ruling is ever
    implemented and the grid yields only devices. What it does not tolerate is a
    string belonging to neither list -- a new misread off this page, or a twelfth
    customer part number appearing after a detector change -- and that is the case
    no other test in the tree would catch before a fire.
    """
    _mod, gt = _ti_ground_truth()
    adjudicated = set(gt["mpns"]) | set(gt["expect_absent_mpns"])

    emitted = {p["affected_mpn"] for p in text_layer.grid_outcome(_PAGE2).parts}
    assert emitted, "the fixture must exercise the extractor, not pass vacuously"

    unadjudicated = emitted - adjudicated
    assert not unadjudicated, (
        "page 2 emitted a part that is neither a real device nor ruled out: "
        f"{sorted(unadjudicated)}. Decide what it is in "
        "scripts/pcn_ground_truth.json before this test is made to pass.")


def test_if_page_two_is_ever_detected_every_spurious_part_is_named():
    """The failure must be legible at the gate, not 11 anonymous strings.

    Scores page 2 emission against the real ground-truth entry. The assertion is
    that `spurious` and `ruled_out` are the SAME set -- page 2 can produce no
    unanticipated spurious part -- which is true today and stays true if the
    ruling is implemented (both go empty). `clean is False` is asserted alongside
    it so that naming a part is never mistaken for excusing it.
    """
    mod, gt = _ti_ground_truth()
    emitted = sorted({p["affected_mpn"]
                      for p in text_layer.grid_outcome(_PAGE2).parts})
    scored = mod.score_notice(emitted, gt)

    assert set(scored["spurious"]) == set(scored["ruled_out"])
    if scored["ruled_out"]:
        assert scored["clean"] is False
        text = mod.render(
            {"per_notice": {"TI_PCN_20210316000.pdf": scored},
             "totals": {"gt": 9, "exact": scored["exact"],
                        "spurious": len(scored["spurious"]), "missing": 0,
                        "malformed": 0, "ruled_out": len(scored["ruled_out"]),
                        "emitted": len(emitted)},
             "header_totals": None})
        assert "RULED OUT by ground truth" in text


def test_nothing_in_the_extractor_declines_page_twos_grid():
    """THE CANARY, and it is MEANT to fail the day the ruling is implemented.

    Page 2 grid has a real column header, so `grid_outcome` accepts it on its own
    merits and pairs BOTH columns as affected -- `device` and `part number` are
    both in `AFFECTED_HEADERS`. There is no decline, no rule, nothing: the eleven
    are excluded only because the page yields no tables.

    If this test goes red, read it as the good news it is -- something now
    declines this grid. Check that the decline names the ruling, update the
    ground-truth `source` and `_expect_absent_why` to say the ruling is
    implemented rather than anticipated, and delete this test. Do not make it pass
    by loosening the guard above.
    """
    out = text_layer.grid_outcome(_PAGE2)
    assert out.decline is None
    assert text_layer.pair_columns(_PAGE2[0]) == [(0, None), (1, None)]
