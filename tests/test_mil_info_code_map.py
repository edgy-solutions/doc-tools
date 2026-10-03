"""Tests for the S1000D info-code classifier.

Before this file, NOTHING in tests/ imported `classify_data_module`. The only
two S1000D fixtures (`test_parsers_rdf.py`, `test_xml_ingestion.py`) both use
`infoCode="520"` — a mapped code — so no test could ever reach the
fallthrough. The 3xx case below is the one the OpenDDIL mock surfaced.

The contract under test is the architect's standing rule, quoted in
`mil_40051_classifier.py`: "Fallthrough to mil:DataModule must log/count when
it fires (no silent absorption)."
"""
from __future__ import annotations

import logging

import pytest

from doc_tools.parsers.mil_info_code_map import (
    DATA_MODULE_ROOT,
    DESCRIPTIVE_DATA_MODULE,
    FAULT_ISOLATION_DATA_MODULE,
    FALLTHROUGH_COUNT,
    ILLUSTRATED_PARTS_DATA_MODULE,
    INFO_CODE_RANGES,
    MISSING_INFO_CODE_KEY,
    PROCEDURE_DATA_MODULE,
    UNMAPPED_FAMILIES,
    classify_data_module,
    kind_for_label,
    label_for_kind,
    reset_fallthrough_count,
)


@pytest.fixture(autouse=True)
def _clean_tally():
    """FALLTHROUGH_COUNT is module-global; isolate every test from the rest."""
    reset_fallthrough_count()
    yield
    reset_fallthrough_count()


# --- the mapped families ---------------------------------------------------

@pytest.mark.parametrize(
    "info_code,expected",
    [
        ("040", DESCRIPTIVE_DATA_MODULE),
        ("000", DESCRIPTIVE_DATA_MODULE),
        ("200", PROCEDURE_DATA_MODULE),
        ("421", FAULT_ISOLATION_DATA_MODULE),
        ("520", PROCEDURE_DATA_MODULE),
        ("720", PROCEDURE_DATA_MODULE),
        ("941", ILLUSTRATED_PARTS_DATA_MODULE),
    ],
)
def test_mapped_families_classify(info_code, expected):
    assert classify_data_module(info_code) == expected


def test_mapped_families_do_not_tally():
    """A successful classification must not touch the fallthrough counter."""
    for code in ("040", "200", "421", "520", "720", "941"):
        classify_data_module(code)
    assert FALLTHROUGH_COUNT == {}


# --- the fallthrough that had no coverage ----------------------------------

@pytest.mark.parametrize("first_digit", sorted(UNMAPPED_FAMILIES))
def test_unmapped_family_returns_root_and_tallies(first_digit, caplog):
    code = f"{first_digit}20"
    with caplog.at_level(logging.WARNING):
        assert classify_data_module(code) == DATA_MODULE_ROOT
    assert FALLTHROUGH_COUNT == {first_digit: 1}
    assert any(r.levelno == logging.WARNING for r in caplog.records), (
        "an unmapped family must LOG, not just count — the silent version of "
        "this is the defect the mock surfaced"
    )
    assert code in caplog.text


def test_the_openddil_320_case(caplog):
    """The concrete input that exposed this: maintenance-planning, 3xx."""
    with caplog.at_level(logging.WARNING):
        kind = classify_data_module("320")
    assert kind == DATA_MODULE_ROOT
    assert FALLTHROUGH_COUNT == {"3": 1}
    assert "maintenance-planning" in caplog.text


def test_tally_accumulates_per_family():
    for code in ("320", "321", "350", "100"):
        classify_data_module(code)
    assert FALLTHROUGH_COUNT == {"3": 3, "1": 1}


def test_a_digit_outside_every_known_family_still_counts(caplog):
    """6 is enumerated; a non-digit is not. Neither may be absorbed silently."""
    with caplog.at_level(logging.WARNING):
        assert classify_data_module("XYZ") == DATA_MODULE_ROOT
    assert FALLTHROUGH_COUNT == {"X": 1}
    assert "not recognised at all" in caplog.text


# --- the missing-info-code path -------------------------------------------

@pytest.mark.parametrize("empty", [None, "", "   "])
def test_missing_info_code_returns_root_and_tallies(empty, caplog):
    with caplog.at_level(logging.WARNING):
        assert classify_data_module(empty) == DATA_MODULE_ROOT
    assert FALLTHROUGH_COUNT == {MISSING_INFO_CODE_KEY: 1}
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_missing_and_unmapped_are_distinct_keys():
    """Two different defects; one tally must not mask the other."""
    classify_data_module(None)
    classify_data_module("320")
    assert FALLTHROUGH_COUNT == {MISSING_INFO_CODE_KEY: 1, "3": 1}


# --- whitespace / shape handling ------------------------------------------

def test_surrounding_whitespace_is_stripped_before_the_lookup():
    assert classify_data_module("  520  ") == PROCEDURE_DATA_MODULE
    assert FALLTHROUGH_COUNT == {}


def test_reset_clears_the_tally():
    classify_data_module("320")
    assert FALLTHROUGH_COUNT
    reset_fallthrough_count()
    assert FALLTHROUGH_COUNT == {}


# --- the enumeration itself ------------------------------------------------

def test_mapped_and_unmapped_families_are_disjoint():
    assert not set(INFO_CODE_RANGES) & set(UNMAPPED_FAMILIES)


def test_every_decimal_digit_is_accounted_for():
    """The point of UNMAPPED_FAMILIES: no digit is merely forgotten."""
    covered = set(INFO_CODE_RANGES) | set(UNMAPPED_FAMILIES)
    assert covered == set("0123456789"), (
        f"digits with no decision recorded either way: "
        f"{sorted(set('0123456789') - covered)}"
    )


def test_label_kind_roundtrip_holds_for_unambiguous_labels():
    for label in ("FaultIsolation", "IPD", "DataModule", "Figure"):
        assert label_for_kind(kind_for_label(label)) == label


def test_the_reverse_map_is_lossy_for_procedure():
    """Two labels share PROCEDURE_DATA_MODULE, so KIND_TO_LABEL cannot invert.

    `{v: k for k, v in LABEL_TO_KIND.items()}` keeps the LAST key for a
    repeated value, so the kind resolves to "ManufacturingStep" and the
    "Procedure" label is unreachable through label_for_kind. Pinned as
    current behaviour, not endorsed: any caller round-tripping a Procedure
    label through the kind silently relabels it.
    """
    assert kind_for_label("Procedure") == kind_for_label("ManufacturingStep")
    assert label_for_kind(PROCEDURE_DATA_MODULE) == "ManufacturingStep"
    assert label_for_kind(kind_for_label("Procedure")) != "Procedure"
