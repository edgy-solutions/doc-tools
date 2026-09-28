"""Tests for the crop seal's cut-detection rule (scripts/pcn_crop_seal.py).

WHY THIS FILE EXISTS. The seal used to measure the BOTTOM edge alone, and that is
why it reported `stored_cut_words 0` on a corpus that contains `ADI_PDN_23_0120`,
whose table crop is cut on its LEFT edge hard enough that the ingest read
`7873ACPZ` for `AD7873ACPZ` and `del` for the `Model` header. A zero from a
one-edge instrument is not a clean corpus, it is an unmeasured one — so the
regression this module guards is not "does the geometry maths work" (that is
tests/test_crop_geometry.py) but "can a non-bottom cut still hide inside a
bottom-edge zero". `test_the_adi_left_cut_is_reported_as_a_left_cut` is that
guard, and it asserts on the real strings.

SCOPE. `_cut_words_by_edge` is pure: word dicts and a box in, a per-edge dict of
strings out. Nothing here touches S3, a PDF, pdfplumber or the network — the
`_measure_notice` / `seal_corpus` layers around it need real corpus PDFs and are
exercised by an actual corpus run, not here.

LOADING. The module is loaded by file path (`scripts/` is not an importable
package, and giving it an `__init__.py` would make a measurement harness look
like library code — same technique as tests/test_pcn_score.py). Its own
`from doc_tools.utils import ...` then executes `doc_tools/__init__.py`, which
pulls in `unstructured` -> `python-magic`: that costs ~12s on this Windows box
and hangs outright under the Bash tool (project memory
"doc-tools-local-suite-hangs-on-libmagic" — run pytest from PowerShell). Cost
only, not correctness: other modules in this suite import `doc_tools` too, so it
is paid once per session. Stubbing the package out of sys.modules instead was
tried and rejected: `doc_tools/__init__.py` has side effects (OPENAI_* -> LLM_*
aliasing, the baml_client sys.path insert) that later tests in the same session
depend on, and a stub silently skips them.
"""
import importlib.util
from pathlib import Path

import pytest

_SEAL_PATH = Path(__file__).resolve().parents[1] / "scripts" / "pcn_crop_seal.py"


def _load():
    spec = importlib.util.spec_from_file_location("pcn_crop_seal", _SEAL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


seal = _load()
cut_by_edge = seal._cut_words_by_edge

# One box for every test: x0=100, top=200, x1=300, bottom=400 (PDF points, y
# growing downward, exactly as pdfplumber reports `extract_words()`).
BOX = (100.0, 200.0, 300.0, 400.0)


def w(text, x0, top, x1, bottom):
    return {"text": text, "x0": x0, "top": top, "x1": x1, "bottom": bottom}


def _only(cut, edge):
    """The cut dict reports `edge` non-empty and every other edge empty."""
    assert cut[edge], f"expected a {edge} cut, got {cut}"
    others = {e: v for e, v in cut.items() if e != edge and v}
    assert not others, f"expected {edge} only, also got {others}"
    return cut[edge]


def _legacy_cut_words(words, el_box_pts, bottom, sibling_boxes):
    """The PRE-four-edge `_cut_words`, verbatim, kept as the reference the bottom
    edge must still agree with. Its whole visible behaviour was the bottom edge,
    so any disagreement means the signature change (one box in, instead of a box
    plus a separate bottom) altered a measured verdict — which it must not."""
    x0, _top, x1, _bottom = el_box_pts
    cut = []
    for word in words:
        if not (word["top"] < bottom - 0.5 and word["bottom"] > bottom + 0.5):
            continue
        if not (word["x1"] > x0 - 1 and word["x0"] < x1 + 1):
            continue
        covered_by_sibling = False
        for sx0, stop, sx1, sbot in sibling_boxes:
            if (sx0 - 1 <= word["x0"] and word["x1"] <= sx1 + 1
                    and stop - 1 <= word["top"] and word["bottom"] <= sbot + 1):
                covered_by_sibling = True
                break
        if covered_by_sibling:
            continue
        cut.append(word["text"])
    return cut


# --------------------------------------------------------------------------- #
# One test per edge: the edge that cuts is the edge that is reported.
# --------------------------------------------------------------------------- #
def test_a_word_straddling_the_bottom_edge_is_reported_as_bottom_only():
    word = w("SYTX9-122HP-1+", 150.0, 390.0, 220.0, 410.0)
    assert _only(cut_by_edge([word], BOX, []), "bottom") == ["SYTX9-122HP-1+"]


def test_a_word_straddling_the_top_edge_is_reported_as_top_only():
    word = w("Affected", 150.0, 190.0, 220.0, 210.0)
    assert _only(cut_by_edge([word], BOX, []), "top") == ["Affected"]


def test_a_word_straddling_the_right_edge_is_reported_as_right_only():
    word = w("Replacement", 290.0, 300.0, 340.0, 312.0)
    assert _only(cut_by_edge([word], BOX, []), "right") == ["Replacement"]


def test_a_word_straddling_the_left_edge_is_reported_as_left_only():
    word = w("AD7873ACPZ", 88.0, 300.0, 140.0, 312.0)
    assert _only(cut_by_edge([word], BOX, []), "left") == ["AD7873ACPZ"]


# --------------------------------------------------------------------------- #
# The two ways a word is NOT cut.
# --------------------------------------------------------------------------- #
def test_a_word_fully_inside_the_box_is_cut_by_nothing():
    word = w("SYDC-19-52HP+", 150.0, 300.0, 220.0, 312.0)
    assert cut_by_edge([word], BOX, []) == {"left": [], "top": [],
                                            "right": [], "bottom": []}


def test_a_word_outside_the_box_on_the_other_axis_is_cut_by_nothing():
    # Level with the bottom edge and straddling it vertically, but 200pt to the
    # right of the box: the horizontal in-range check must reject it.
    far_right = w("PageFooter", 500.0, 390.0, 560.0, 410.0)
    # Mirror: straddling the left edge horizontally, but 100pt below the box —
    # the vertical in-range check must reject it.
    far_below = w("Signature", 88.0, 500.0, 140.0, 512.0)
    empty = {"left": [], "top": [], "right": [], "bottom": []}
    assert cut_by_edge([far_right], BOX, []) == empty
    assert cut_by_edge([far_below], BOX, []) == empty


def test_a_word_whole_inside_a_sibling_box_is_excluded_though_it_straddles():
    # Straddles our bottom edge, so it is a cut in isolation...
    word = w("Rev", 150.0, 390.0, 220.0, 410.0)
    assert _only(cut_by_edge([word], BOX, []), "bottom") == ["Rev"]
    # ...but it sits WHOLE inside the next Table element's own box on this page,
    # so that crop shows it complete and it is not lost. Not a cut.
    sibling = (120.0, 380.0, 280.0, 460.0)
    assert cut_by_edge([word], BOX, [sibling]) == {"left": [], "top": [],
                                                   "right": [], "bottom": []}


# --------------------------------------------------------------------------- #
# The regression the whole four-edge change exists for.
# --------------------------------------------------------------------------- #
def test_the_adi_left_cut_is_reported_as_a_left_cut():
    """ADI_PDN_23_0120's shape, by its real strings: the crop's LEFT edge falls
    through `AD7873ACPZ` so that only `7873ACPZ` is inside it, and through
    `Model` so that only `del` is. Both were read back from the crop in exactly
    that truncated form; the bottom-only instrument scored the page zero."""
    # x0=100 is the box's left edge. `AD` ends at 99.2, `7873ACPZ` starts at
    # 100.8 — the edge lands in the gap between glyph runs, inside the word.
    mpn = w("AD7873ACPZ", 88.0, 300.0, 152.0, 311.0)
    header = w("Model", 92.0, 280.0, 124.0, 291.0)
    cut = cut_by_edge([mpn, header], BOX, [])
    assert cut["left"] == ["AD7873ACPZ", "Model"]
    assert not cut["top"] and not cut["right"] and not cut["bottom"]
    # And the proof that this is a REGRESSION test and not a restatement of
    # existing behaviour: the pre-change instrument saw nothing here.
    assert _legacy_cut_words([mpn, header], BOX, BOX[3], []) == []


# --------------------------------------------------------------------------- #
# The bottom edge must be unchanged by the signature change.
# --------------------------------------------------------------------------- #
_BOTTOM_CASES = [
    ("straddles the bottom edge", [w("cut", 150.0, 390.0, 220.0, 410.0)], []),
    ("sits whole above the edge", [w("safe", 150.0, 300.0, 220.0, 312.0)], []),
    ("sits whole below the edge", [w("below", 150.0, 405.0, 220.0, 417.0)], []),
    ("grazes the edge within tolerance",
     [w("graze", 150.0, 399.6, 220.0, 400.4)], []),
    ("straddles but is out of the column span",
     [w("footer", 500.0, 390.0, 560.0, 410.0)], []),
    ("straddles, just inside the 1pt column tolerance",
     [w("edgecase", 299.5, 390.0, 340.0, 410.0)], []),
    ("straddles but a sibling shows it whole",
     [w("covered", 150.0, 390.0, 220.0, 410.0)],
     [(120.0, 380.0, 280.0, 460.0)]),
    ("straddles and the sibling does NOT contain it",
     [w("uncovered", 150.0, 390.0, 220.0, 410.0)],
     [(120.0, 380.0, 280.0, 405.0)]),
    ("several words at once",
     [w("a", 150.0, 390.0, 180.0, 410.0), w("b", 200.0, 300.0, 230.0, 312.0),
      w("c", 240.0, 392.0, 270.0, 408.0)], []),
]


@pytest.mark.parametrize("label,words,sibs",
                         _BOTTOM_CASES, ids=[c[0] for c in _BOTTOM_CASES])
def test_the_bottom_edge_verdict_is_unchanged_by_the_signature_change(
        label, words, sibs):
    """Old-vs-new, directly: the four-edge function's `bottom` list must equal
    what the verbatim pre-change `_cut_words` returns for the same page. The
    seal cannot be re-run against the real PDFs from here (no S3, no network),
    so this side-by-side IS the proof that the refactor moved no number."""
    assert cut_by_edge(words, BOX, sibs)["bottom"] == _legacy_cut_words(
        words, BOX, BOX[3], sibs)
