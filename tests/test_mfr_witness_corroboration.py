"""A manufacturer is compared by READING, not by string, and needs the witness.

THE 2026-10-09 RULING. TYC-PCN-24-210412.pdf has a text layer that drops the `ti`
ligature, and its manufacturer is read three ways, ALL correct readings of the page:
`TE Connectivity` (the printed heading), `TE Connecvity` (what the damaged text layer
hands an extractor) and `TE` (the logo wordmark, rendered as TE over "connectivity"). A
three-fire corpus run wrote mfr=`TE` in fire 1 and `TE Connectivity` in fires 2 and 3,
with the region witness running successfully in all three (witness_regions=2,
witness_regions_lost=0). The instability was in the COMPARATOR: an exact string compare
let the crop's `TE` overwrite the text layer's `TE Connectivity`. The ruling: compare
canonical-after-alias, never the raw string; mfr requires corroboration from the
witness; an uncorroborated mfr is null + review, never the uncorroborated value.

FIRE 1'S `TE` IS THE REGRESSION THIS FILE PINS
(`test_fire1_crop_te_does_not_overwrite_text_layer_te_connectivity`).

What must still FAIL, pinned below: two different manufacturers must not agree, and a
2-character subsequence trap (`TE` inside `Texas Instruments`) must not agree.
"""
import itertools

import pytest

from doc_tools.utils import mfr_agreement as ma
from doc_tools.utils import sustainment_header_trust as header_trust

FULL = "TE Connectivity"
DAMAGED = "TE Connecvity"
LOGO = "TE"
TYC = [FULL, DAMAGED, LOGO]


def _witness(mfr):
    """Region records as `_read_regions_witness` emits them (see
    tests/test_region_witness_supplies_header.py), with only the manufacturer line."""
    if mfr is None:
        text = "Document Number: PCN-24-210412"
    else:
        text = f"Manufacturer: {mfr}\nDocument Number: PCN-24-210412"
    return [{"element_id": "page_region_1_header_block",
             "type": "RegionTranscription", "region": "region_image",
             "page_number": 1, "bbox": [70.0, 42.4, 1620.1, 484.6],
             "page_width": 1700, "page_height": 2200,
             "text": text, "text_as_html": ""}]


def _header(mfr):
    return {"doc_id": "PCN-24-210412", "doc_type": "PCN", "revision": None,
            "mfr": mfr, "mfr_source": mfr, "pub_date": None, "pub_date_source": None,
            "doc_level_ltb_date": None, "doc_level_ltb_date_source": None,
            "categories": [], "summary": None}


# --------------------------------------------------------------------------- #
# the comparator
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("a,b", list(itertools.permutations(TYC, 2)))
def test_the_three_tyc_spellings_agree_pairwise_in_both_orders(a, b):
    assert ma.readings_agree(a, b)


@pytest.mark.parametrize("a,b", list(itertools.permutations(TYC, 2)))
def test_canonical_reading_is_the_fullest_of_every_pairing(a, b):
    """Any pairing that includes the printed heading yields `TE Connectivity`. The pair
    (`TE Connecvity`, `TE`) holds NO reading that is the full name, so the fullest it
    can return is `TE Connecvity` -- it cannot invent the dropped letters."""
    expected = FULL if FULL in (a, b) else DAMAGED
    assert ma.canonical_reading(a, b) == expected


def test_canonical_reading_over_all_three_is_te_connectivity():
    for perm in itertools.permutations(TYC):
        assert ma.canonical_reading(*perm) == FULL


def test_canonical_reading_ties_go_to_the_first_and_none_is_dropped():
    assert ma.canonical_reading("Vishay", "VISHAY") == "Vishay"
    assert ma.canonical_reading(None, "", "  ", "TE") == "TE"
    assert ma.canonical_reading(None, "") is None
    assert ma.canonical_reading() is None


def test_te_does_not_agree_with_texas_instruments_the_subsequence_trap():
    """`TE` IS a subsequence of `Texas Instruments` (T and e, both from `Texas`), so a
    2-character subsequence rule would equate two unrelated manufacturers. Rule 3 needs
    a word boundary and rule 2 needs 4+ characters, so neither fires."""
    assert ma._is_subsequence("te", "texas instruments")
    assert not ma.readings_agree("TE", "Texas Instruments")
    assert not ma.readings_agree("Texas Instruments", "TE")


def test_plainly_different_manufacturers_do_not_agree():
    assert not ma.readings_agree("Vishay", "onsemi")
    assert not ma.readings_agree("onsemi", "Vishay")


@pytest.mark.parametrize("empty", [None, "", "   ", "\t\n", " . "])
def test_empty_readings_never_agree_with_anything(empty):
    for other in TYC + [None, "", "  "]:
        assert not ma.readings_agree(empty, other)
        assert not ma.readings_agree(other, empty)


def test_fold_normalizes_case_whitespace_and_edge_punctuation():
    assert ma.fold("  TE   Connectivity.\n") == "te connectivity"
    assert ma.fold(None) is None and ma.fold("  ") is None


def test_a_short_subsequence_is_not_enough():
    # 3 characters: under the rule-2 floor, and no word boundary for rule 3.
    assert not ma.readings_agree("abc", "a1b2c3")
    # A substitution (same length) is never a drop.
    assert not ma.readings_agree("Vishay", "Vishai")


# --------------------------------------------------------------------------- #
# the supplier
# --------------------------------------------------------------------------- #
def test_fire1_crop_te_does_not_overwrite_text_layer_te_connectivity():
    """THE REGRESSION: fire 1 wrote mfr='TE' because the crop read the logo wordmark."""
    h = _header(FULL)
    reasons = header_trust.supply_header_from_regions(
        h, _witness(LOGO), text_layer_degraded=True)
    assert h["mfr"] == FULL
    assert h["mfr_source"] == FULL  # the crop's fragment is not a citation for it
    assert any("'TE Connectivity'" in r and "'TE'" in r for r in reasons)


def test_crop_te_connectivity_upgrades_text_layer_te_connecvity():
    h = _header(DAMAGED)
    reasons = header_trust.supply_header_from_regions(
        h, _witness(FULL), text_layer_degraded=True)
    assert h["mfr"] == FULL
    assert h["mfr_source"] == FULL
    assert any("TE Connecvity" in r and "TE Connectivity" in r for r in reasons)


def test_a_disagreeing_crop_still_replaces_as_before():
    h = _header("Vishay")
    header_trust.supply_header_from_regions(
        h, _witness(FULL), text_layer_degraded=True)
    assert h["mfr"] == FULL


# --------------------------------------------------------------------------- #
# the requirement
# --------------------------------------------------------------------------- #
def test_agreement_keeps_the_canonical_value():
    h = _header(DAMAGED)
    reasons = header_trust.require_mfr_witness_agreement(
        h, _witness(LOGO), text_layer_degraded=True)
    # `TE Connecvity` vs `TE`: both shorten the same name; the fuller is kept.
    assert h["mfr"] == DAMAGED
    assert len(reasons) == 1 and "TE Connecvity" in reasons[0] and "'TE'" in reasons[0]

    h = _header(DAMAGED)
    header_trust.require_mfr_witness_agreement(
        h, _witness(FULL), text_layer_degraded=True)
    assert h["mfr"] == FULL


def test_disagreement_nulls_mfr_and_source_and_names_both_readings():
    h = _header("Vishay")
    reasons = header_trust.require_mfr_witness_agreement(
        h, _witness(FULL), text_layer_degraded=True)
    assert h["mfr"] is None and h["mfr_source"] is None
    assert len(reasons) == 1
    assert "'Vishay'" in reasons[0] and "'TE Connectivity'" in reasons[0]
    assert "withdrawn rather than written" in reasons[0]


def test_no_witness_reading_nulls_with_a_reason_that_is_not_a_disproof():
    h = _header(FULL)
    reasons = header_trust.require_mfr_witness_agreement(
        h, _witness(None), text_layer_degraded=True)
    assert h["mfr"] is None and h["mfr_source"] is None
    assert len(reasons) == 1
    assert "supplied no manufacturer reading" in reasons[0]
    assert "Not corroborated is not the same as disproved" in reasons[0]
    # distinguishable from the disagreement case
    assert "withdrawn rather than written" not in reasons[0]


def test_a_healthy_document_is_untouched():
    for witness in (_witness(None), _witness("Vishay"), None):
        h = _header(FULL)
        before = dict(h)
        assert header_trust.require_mfr_witness_agreement(
            h, witness, text_layer_degraded=False) == []
        assert h == before


def test_an_already_empty_mfr_returns_no_reasons():
    for empty in (None, ""):
        h = _header(empty)
        h["mfr_source"] = None
        before = dict(h)
        assert header_trust.require_mfr_witness_agreement(
            h, _witness(FULL), text_layer_degraded=True) == []
        assert h == before
