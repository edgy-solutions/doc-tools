"""The row-conversion seal: one fixture row, both shapes, the same cell.

ARCHITECT, 2026-10-21, item 3: *"Seal: one fixture row through the converter,
drawn by cortex's reader in both shapes, lands on the same cell."*

Items 1 and 2 of that packet landed at `d9e6118` (row bboxes as fractions AND
`page_dims` dropped in the same write, never one without the other). This file
is item 3.

WHAT THIS SEALS, AND WHAT IT CANNOT
-----------------------------------
The seal spans a language boundary: the converter is Python here, the reader is
TypeScript in `cortex-ui`. So it has two legs, and only one of them can live in
this suite:

* **Leg A, this file.** Cortex's read-and-draw rule, transcribed from their
  source (`src/lib/promotionReview.ts` `readEvidence`, `src/lib/evidenceRef.ts`
  `isFractionBox`/`FRACTION_PAGE`, and the sealed `src/lib/bboxScale.ts`
  `scaleBox`) at cortex `2fb587c`. This is the leg that runs on every commit
  and catches a drift in MY converter.
* **Leg B, theirs.** The same fixture through the REAL reader, run by their
  vitest. A transcription is a restatement, and a restatement of somebody
  else's contract is exactly the thing that silently stops matching it — so
  the numbers both legs agree on are committed as a fixture
  (`tests/fixtures/sustainment/row_fraction_seal.json`), not re-derived on
  each side. Leg B is placed with them and its result is reported in the
  packet; if the two legs ever disagree, THEIRS is the authority and this file
  is the thing that is wrong.

The rule being sealed, in one line: a fraction box is read on a 1x1 page and a
pixel box on its `page_dims`, and both then go through the same `scaleBox`. So
the conversion is correct exactly when it is the inverse of their scaling —
which is an arithmetic claim, and testable here.

THE MIDDLE OF THE SPAN, which this file deliberately does NOT cover. When the
seal was first written the row carried `page_number`/`bboxes` and the BFF
turned them into cortex's `page`/`bbox`, so a reshaping step sat between the
two legs and neither could see it. The architect closed that on 2026-10-21:
the producer emits `wire_evidence_ref` and *"the BFF serves 7f's
wire_evidence_ref as is"*, with Lane 1 adding a third leg proving a fixture row
leaves their route byte-equal and with no `page_dims`. So the span is
converter -> BFF -> reader and the three legs cover it; this file is the first.
"""
import json
import pathlib

import pytest

from doc_tools.utils import provenance
from doc_tools.utils import sustainment_merge as merge

# --------------------------------------------------------------------------- #
# The fixture row, as the extractor produces it before conversion
# --------------------------------------------------------------------------- #
# A parts-table cell on a US-letter page rasterized at 200 DPI (1700x2200), the
# space `bboxScale.ts` names as what doc-tools ships. The numbers are chosen so
# that NO edge divides exactly -- see
# `test_the_fixture_exercises_rounding_on_all_four_edges`. A fixture that
# divided cleanly would seal the easy half of the converter and leave the
# rounding untested, which is where a units conversion actually goes wrong.
PAGE_DIMS = {"width": 1700.0, "height": 2200.0}
PIXEL_BBOX = [223.0, 917.0, 661.0, 953.0]

FIXTURE_PROV = {
    "page_number": 3,
    "page_dims": dict(PAGE_DIMS),
    "bboxes": [list(PIXEL_BBOX)],
    "match_method": "text_layer_cell",
    "match_confidence": 1.0,
}

# Three render sizes, because the drift this rule exists to prevent is a box
# that slides off the text as you zoom -- their own red test renders at two.
# 850x1100 is an exact half (the pixel leg is then exact, so it is the
# reference); the other two are deliberately not integer ratios.
RENDER_SIZES = [
    {"width": 850.0, "height": 1100.0},
    {"width": 1024.0, "height": 1325.0},
    {"width": 1700.0, "height": 2200.0},
]

FIXTURE_PATH = (pathlib.Path(__file__).parent
                / "fixtures" / "sustainment" / "row_fraction_seal.json")

# A fraction rounded to `FRACTION_DIGITS` carries at most half a unit in the
# last place; a width or height is a difference of two, so twice that. Scaled
# to the rendered page that is the worst drift the conversion can introduce.
MAX_FRACTION_ERROR = 0.5 * 10 ** -provenance.FRACTION_DIGITS


# --------------------------------------------------------------------------- #
# Cortex's reader, transcribed. Leg B is the authority; see the module docstring
# --------------------------------------------------------------------------- #
FRACTION_PAGE = {"width": 1.0, "height": 1.0}


def is_fraction_box(b):
    """`evidenceRef.ts` `isFractionBox` at cortex `2fb587c`.

    Exactly 4 finite numbers with `0 <= x0 < x1 <= 1` and `0 <= y0 < y1 <= 1`.
    Note `x0 < x1` STRICTLY: a zero-area box fails, and a failure here is not
    local -- it drops the whole list on their side and 422s the call on Lane
    1's. That asymmetry is why the converter returns no box instead of a
    degenerate one.
    """
    if not isinstance(b, list) or len(b) != 4:
        return False
    if not all(isinstance(v, (int, float)) and v == v and abs(v) != float("inf")
               for v in b):
        return False
    x0, y0, x1, y1 = b
    return 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1


def read_evidence(ref):
    """`promotionReview.ts` `readEvidence`, the both-shapes discrimination.

    Returns `(state, bbox, page_dims)`. The switch is the PRESENCE of
    `page_dims`, not its value: absent (or `undefined`) means the ruled
    fraction form, read on a 1x1 page. A `page_dims` present but null takes the
    PIXEL branch and is malformed -- which is why this lane omits the key
    rather than nulling it.
    """
    if not isinstance(ref, dict):
        return "malformed", None, None
    page = ref.get("page")
    page_ok = isinstance(page, int) and not isinstance(page, bool) and page >= 1
    if "bbox" not in ref or ref["bbox"] is None:
        # Stated on this page, no box to draw. Either form.
        return ("ok" if page_ok else "malformed"), None, FRACTION_PAGE
    b = ref["bbox"]
    if "page_dims" not in ref:
        if not page_ok or not is_fraction_box(b):
            return "malformed", None, None
        return "ok", b, FRACTION_PAGE
    d = ref["page_dims"]
    if not page_ok or not isinstance(b, list) or len(b) != 4:
        return "malformed", None, None
    if not isinstance(d, dict):
        return "malformed", None, None
    w, h = d.get("width"), d.get("height")
    if not isinstance(w, (int, float)) or not isinstance(h, (int, float)):
        return "malformed", None, None
    if w <= 0 or h <= 0:
        return "malformed", None, None
    x0, y0, x1, y1 = b
    if x1 <= x0 or y1 <= y0:
        return "malformed", None, None
    return "ok", [x0, y0, x1, y1], {"width": w, "height": h}


def scale_box(bbox, page_dims, rendered):
    """`bboxScale.ts` `scaleBox` -- the module they call a sealed constant.

    Normalize against `page_dims`, then scale to the rendered page. The whole
    point of the ruled form is that it needs no second rule: the fraction form
    is this same function with a 1x1 page.
    """
    x0, y0, x1, y1 = bbox
    sx = rendered["width"] / page_dims["width"]
    sy = rendered["height"] / page_dims["height"]
    return {"left": x0 * sx, "top": y0 * sy,
            "width": (x1 - x0) * sx, "height": (y1 - y0) * sy}


def draw(ref, rendered):
    """Read a served `evidence_ref` and place its box, as the card does."""
    state, bbox, dims = read_evidence(ref)
    assert state == "ok", f"cortex would refuse this ref: {ref}"
    assert bbox is not None, "this ref carries no box to draw"
    return scale_box(bbox, dims, rendered)


# --------------------------------------------------------------------------- #
# The two shapes of the one fixture row
# --------------------------------------------------------------------------- #
def old_shape():
    """What the DEPLOYED producer writes: pixel box plus the dims it is in."""
    return {"page": FIXTURE_PROV["page_number"],
            "bbox": list(PIXEL_BBOX),
            "page_dims": dict(PAGE_DIMS),
            "units": "px"}


def new_shape():
    """The row's `wire_evidence_ref`, taken FROM the producer, not hand-written.

    A hand-written expectation here would seal the fixture against itself and
    pass if the converter were deleted.

    STRENGTHENED by the architect's producer-owns-the-wire-shape ruling
    (2026-10-21): *"The BFF serves 7f's wire_evidence_ref as is. No renaming,
    no synthesizing, no page_dims of its own."* Before that ruling this leg had
    to MODEL a rename — the row carried `page_number`/`bboxes` and something
    downstream turned them into `page`/`bbox`. Now the producer emits the wire
    shape itself, so what this test draws is the bytes cortex receives, and the
    modelled step is gone rather than merely assumed correct.
    """
    return merge._row_wire_evidence_ref(FIXTURE_PROV, "text_layer_cell")


# --------------------------------------------------------------------------- #
# The several-box row, added at cortex's request
# --------------------------------------------------------------------------- #
#: *"7f: please make one fixture in leg B's family a several-box row, so
#: cortex's leg covers the union and its note."* (cortex packet, 2026-10-21 §5.)
#:
#: A two-line cell, and each edge of the union comes from a DIFFERENT box: x0
#: and y1 from the second, y0 and x1 from the first. A transposed min/max would
#: therefore change the result, which a fixture whose second box sits wholly
#: inside the first could not detect. All eight edges divide inexactly.
PIXEL_BBOXES_MULTI = [[223.0, 917.0, 661.0, 953.0],
                      [189.0, 959.0, 587.0, 995.0]]

MULTI_PROV = dict(FIXTURE_PROV, bboxes=[list(b) for b in PIXEL_BBOXES_MULTI])


def multi_shape():
    """The several-box row's wire ref, from the producer."""
    return merge._row_wire_evidence_ref(MULTI_PROV, "text_layer_cell")


def test_the_union_OUTLINE_covers_every_box_it_replaces_when_DRAWN():
    """The union's point is what a steward sees, so assert it where they see
    it: through the reader, in rendered pixels, not as four fractions.

    cortex outlines the union for a multi-box row and captions the note. If the
    outline failed to cover one of the lines, a steward reading a two-line cell
    would see one line boxed and no sign the other existed -- and because the
    outlined box is a REAL box, nothing about that looks like a bug.
    """
    for rendered in RENDER_SIZES:
        drawn = draw(multi_shape(), rendered)
        sx = rendered["width"] / PAGE_DIMS["width"]
        sy = rendered["height"] / PAGE_DIMS["height"]
        # Slack: the union is taken over rounded fractions, so against the raw
        # pixel geometry it can fall one rounding quantum short.
        slack_x = MAX_FRACTION_ERROR * rendered["width"]
        slack_y = MAX_FRACTION_ERROR * rendered["height"]
        for x0, y0, x1, y1 in PIXEL_BBOXES_MULTI:
            assert drawn["left"] <= x0 * sx + slack_x
            assert drawn["top"] <= y0 * sy + slack_y
            assert drawn["left"] + drawn["width"] >= x1 * sx - slack_x
            assert drawn["top"] + drawn["height"] >= y1 * sy - slack_y


def test_the_multi_box_fixture_would_CATCH_a_transposed_union():
    """Guards the fixture's design, not the code -- the same role as the
    all-four-edges test above.

    Every edge of this union comes from a different box, so each of the four
    `min`/`max` choices is exercised. A later "tidying" of the fixture into two
    neatly nested boxes would leave this file green while the union could take
    its maximum from the wrong corner.
    """
    first, second = PIXEL_BBOXES_MULTI
    assert second[0] < first[0], "x0 must come from the SECOND box"
    assert first[1] < second[1], "y0 must come from the FIRST box"
    assert first[2] > second[2], "x1 must come from the FIRST box"
    assert second[3] > first[3], "y1 must come from the SECOND box"


def test_the_several_box_row_carries_the_NOTE_cortex_captions():
    """cortex's review-row reader has no `note` today (their packet §5): it
    would outline the union as if it were one cell and the note would be lost
    without a trace. They ship the `note` reader in the same release as this
    conversion, so the two are paired -- which is worth pinning at this end,
    because the producer cannot see a dropped caption.
    """
    ref = multi_shape()
    assert ref["note"] == "2 boxes"
    assert set(ref) == {"page", "bbox", "note"}


# --------------------------------------------------------------------------- #
# The seal
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rendered", RENDER_SIZES,
                         ids=["half", "non-integer-zoom", "full"])
def test_one_fixture_row_lands_on_the_SAME_CELL_in_both_shapes(rendered):
    """THE SEAL the architect ordered, at three render sizes.

    The old shape is the reference: it is what the live image writes today and
    what every stored row still renders as. If the converted row lands
    anywhere else, a steward approving against the outline is approving
    against the wrong cell -- and nothing would raise, because both forms are
    individually well-formed.
    """
    before = draw(old_shape(), rendered)
    after = draw(new_shape(), rendered)

    # The only slack is the converter's rounding, scaled to this render size.
    tol_pos = MAX_FRACTION_ERROR * max(rendered["width"], rendered["height"])
    for key in ("left", "top", "width", "height"):
        # A width is a difference of two rounded fractions, so twice the slack.
        tol = tol_pos * (2 if key in ("width", "height") else 1)
        assert abs(before[key] - after[key]) <= tol, (
            f"{key}: {before[key]} -> {after[key]} at {rendered}")


def test_the_drift_the_seal_allows_is_SUB_PIXEL_and_not_merely_small():
    """A tolerance is only honest if its size is stated, not just satisfied.

    Six fraction digits on a 2200 px page is ~1e-3 px of drift: three orders
    below the one-pixel line where an outline could visibly leave the text. So
    the seal is not trading accuracy for a passing assertion.
    """
    rendered = {"width": 1700.0, "height": 2200.0}
    before = draw(old_shape(), rendered)
    after = draw(new_shape(), rendered)
    worst = max(abs(before[k] - after[k])
                for k in ("left", "top", "width", "height"))
    assert worst < 0.01, f"drift is {worst} px, which is no longer sub-pixel"


def test_the_fixture_exercises_rounding_on_all_four_edges():
    """Guard on the seal itself: a cleanly-dividing fixture would prove little.

    If someone later "tidies" these numbers to round ones, the seal above goes
    on passing while testing only exact arithmetic -- the half of the converter
    that was never in doubt.
    """
    exact = [PIXEL_BBOX[0] / PAGE_DIMS["width"], PIXEL_BBOX[1] / PAGE_DIMS["height"],
             PIXEL_BBOX[2] / PAGE_DIMS["width"], PIXEL_BBOX[3] / PAGE_DIMS["height"]]
    rounded = new_shape()["bbox"]
    for i, (e, r) in enumerate(zip(exact, rounded)):
        assert e != r, (
            f"edge {i} divides exactly, so the fixture does not test rounding")


def test_the_converted_box_satisfies_cortexs_fraction_predicate():
    """Their reader refuses the whole ref otherwise, and a refused ref is a
    card with no outline -- not an error anyone sees on this side."""
    assert is_fraction_box(new_shape()["bbox"])


def test_the_new_shape_OMITS_page_dims_rather_than_nulling_it():
    """The discrimination is on the key's PRESENCE (`Object.hasOwn`), so a
    `page_dims: null` is read as the PIXEL form and then refused as malformed.
    Omitting is the signal; nulling is a silent no-outline."""
    assert "page_dims" not in new_shape()
    nulled = dict(new_shape(), page_dims=None)
    state, _, _ = read_evidence(nulled)
    assert state == "malformed", (
        "a nulled page_dims must not read as the fraction form")


def test_converting_the_box_while_KEEPING_the_dims_draws_a_speck():
    """Cortex's hazard, pinned: this is why items 1 and 2 are ONE commit.

    It is the opposite of what intuition says -- converting the box but leaving
    `page_dims` behind is WORSE than converting neither, because the fraction
    is divided by 1700 again and lands as a speck in the page corner with no
    error and nothing to distinguish it from a real tiny box there.
    """
    rendered = {"width": 1700.0, "height": 2200.0}
    half_converted = dict(new_shape(), page_dims=dict(PAGE_DIMS))
    state, bbox, dims = read_evidence(half_converted)
    assert state == "ok", "it is well-formed, which is the whole problem"
    speck = scale_box(bbox, dims, rendered)
    assert speck["width"] < 1.0 and speck["height"] < 1.0
    assert speck["left"] < 1.0 and speck["top"] < 1.0


# --------------------------------------------------------------------------- #
# The committed fixture, which is what leg B reads
# --------------------------------------------------------------------------- #
def test_the_committed_fixture_matches_what_the_converter_produces_today():
    """The fixture is the shared artifact across the language boundary, so it
    must not be allowed to go stale. If the converter changes, this fails here
    before cortex's leg starts disagreeing with a file nobody re-generated.
    """
    assert FIXTURE_PATH.exists(), f"missing seal fixture: {FIXTURE_PATH}"
    stored = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert stored["old_shape"] == old_shape()
    assert stored["new_shape"] == new_shape()
    assert stored["render_sizes"] == RENDER_SIZES
    for case in stored["expected_cells"]:
        rendered = case["rendered"]
        assert draw(old_shape(), rendered) == pytest.approx(case["cell"],
                                                            abs=1e-9)

    # The several-box half, which cortex's leg reads for the union and note.
    multi = stored["multi_box"]
    assert multi["pixel_bboxes"] == PIXEL_BBOXES_MULTI
    assert multi["new_shape"] == multi_shape()
    assert multi["fractions"] == merge._row_fractions(MULTI_PROV)
    for case in multi["expected_union_cells"]:
        assert draw(multi_shape(), case["rendered"]) == pytest.approx(
            case["cell"], abs=MAX_FRACTION_ERROR * max(
                case["rendered"]["width"], case["rendered"]["height"]) * 2)
