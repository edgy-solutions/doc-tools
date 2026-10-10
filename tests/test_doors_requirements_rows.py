"""``doors.requirements_rows`` -- requirements are outline OBJECTS.

Measured against the repo's real fixture ``SRS-MRAD-001_baseline-2.1.csv``: four
objects of type "Requirement" (SRS-5, SRS-6, SRS-7, SRS-9); its two tables are a
latency budget and a verification cross reference, neither holding requirement
text. The refusal fixture is synthetic: ``no-requirements_baseline-1.0.csv``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from doc_tools.parsers.doors_export import (
    DoorsParseError,
    RequirementsRows,
    parse_doors_export,
    requirements_rows,
)
from doc_tools.passes.dispatch import (
    PassContext,
    resolve_python_pass,
    run_passes_for_kind,
)

FIXDIR = Path(__file__).parent / "fixtures" / "doors"
REAL = FIXDIR / "SRS-MRAD-001_baseline-2.1.csv"
NOREQ = FIXDIR / "no-requirements_baseline-1.0.csv"


def _real() -> str:
    return REAL.read_text(encoding="utf-8")


def test_real_fixture_yields_the_four_requirement_objects():
    out = requirements_rows(_real())
    assert isinstance(out, RequirementsRows)
    assert [r.identifier for r in out.rows] == ["SRS-5", "SRS-6", "SRS-7", "SRS-9"]


def test_rows_carry_text_section_path_and_identity():
    out = requirements_rows(_real())
    by_id = {r.identifier: r for r in out.rows}
    assert by_id["SRS-5"].text.startswith(
        "The CSCI shall command the retarding force se")
    assert by_id["SRS-6"].text.startswith(
        "The CSCI shall limit commanded retarding forc")
    assert by_id["SRS-7"].text.startswith(
        "The CSCI shall record each arrestment event t")
    assert by_id["SRS-9"].text.startswith("Table 1 defines the allocated latency budget")
    # multi-line text is verbatim, newlines intact
    assert "\n\n" in by_id["SRS-7"].text
    assert by_id["SRS-5"].section_path == ("Functional Requirements",
                                           "Arrestment Sequencing")
    for r in out.rows:
        assert r.text and r.section_path
        assert r.object_type == "Requirement"
        assert r.identity.baseline == "2.1"
        assert r.identity == out.identity
    assert by_id["SRS-5"].attributes["Verification Method"] == "Test"


def test_supporting_table_anchors_are_the_two_tier1_tables():
    out = requirements_rows(_real())
    export = parse_doors_export(_real())
    assert out.supporting_table_anchor_ids == tuple(
        t.anchor_id for t in export.tier1_tables)
    assert out.supporting_table_anchor_ids == ("SRS-10", "SRS-29")


def test_no_requirement_objects_refuses_with_type_counts():
    with pytest.raises(DoorsParseError) as e:
        requirements_rows(NOREQ.read_text(encoding="utf-8"))
    msg = str(e.value)
    assert "Heading" in msg and "Information" in msg and "Table Cell" in msg
    assert "'Information': 2" in msg
    assert "outline objects" in msg


def test_requirement_with_empty_text_is_refused_by_name():
    text = _real()
    old = "SRS-6,3,,\"The CSCI shall limit commanded retarding force to 1,250 kN under all operating conditions, including degraded sensor modes.\",Requirement"
    assert text.count(old) == 1
    with pytest.raises(DoorsParseError) as e:
        requirements_rows(text.replace(old, "SRS-6,3,,,Requirement"))
    assert "SRS-6" in str(e.value)


def test_duplicate_identifier_is_refused_by_name():
    text = _real()
    assert text.count("\nSRS-6,3,") == 1
    with pytest.raises(DoorsParseError) as e:
        requirements_rows(text.replace("\nSRS-6,3,", "\nSRS-5,3,"))
    assert "SRS-5" in str(e.value)


def test_type_match_is_case_insensitive_and_preserved():
    text = _real()
    assert text.count(",Requirement,Test,") == 1
    out = requirements_rows(text.replace(",Requirement,Test,", ",requirement,Test,"))
    assert out.rows[0].object_type == "requirement"


def test_dispatch_end_to_end_both_passes_ok():
    results = run_passes_for_kind("doors-export", PassContext(text=_real()))
    assert [r.name for r in results] == [
        "identity.identity_from_doors_text", "doors.requirements_rows"]
    assert [r.status for r in results] == ["ok", "ok"]


def test_dispatch_records_a_refusal_as_refused_not_raised():
    results = run_passes_for_kind(
        "doors-export", PassContext(text=NOREQ.read_text(encoding="utf-8")))
    assert results[1].name == "doors.requirements_rows"
    assert results[1].status == "refused"


def test_pass_name_resolves_to_exactly_one_hit():
    hits = resolve_python_pass("doors.requirements_rows")
    assert len(hits) == 1, hits


def test_as_dict_is_plain_json():
    d = requirements_rows(_real()).as_dict()
    json.dumps(d)
    assert [r["identifier"] for r in d["rows"]] == ["SRS-5", "SRS-6", "SRS-7", "SRS-9"]
    assert isinstance(d["rows"][0]["section_path"], list)
    assert isinstance(d["rows"][0]["identity"], dict)
    assert d["rows"][0]["identity"]["baseline"] == "2.1"
