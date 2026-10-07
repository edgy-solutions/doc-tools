"""Contract tests for the DOORS spreadsheet-export parser.

``doc_tools/parsers/doors_export.py`` turns a flat CSV of DOORS objects into
(a) a module identity and (b) tier-1 table artifacts, deterministically and
with no LLM. These tests pin:

  A. Identity read off the real fixture, including the module-path-vs-project
     collision the ``key`` property exists to avoid.
  B. Object counts and type tally off the fixture, plus two CSV-quoting edge
     cases (an embedded newline, a literal double quote) that prove the
     parser is reading real CSV semantics and not splitting on commas.
  C. The two reconstructed tables' shape.
  D. The CSV/JSON artifact round-trip, including a comma-bearing cell.
  E. The exact artifact key set -- tier-2 tables must never appear in it.
  F. A ragged table routes to tier-2 and is held back from ``artifacts()``
     rather than padded, because a padded cell reads as a correct-looking
     wrong answer under the wrong header.
  G. Each of the module's six named refusals, raised as ``DoorsParseError``,
     with the diagnostic-message checks the docstring promises for 2 and 3.

No mocks: the parser is pure text in, dataclasses out.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from doc_tools.parsers.doors_export import DoorsParseError, parse_doors_export

FIXTURE = (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "doors"
           / "SRS-MRAD-001_baseline-2.1.csv")


@pytest.fixture(scope="module")
def export():
    return parse_doors_export(FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# A. Identity
# ---------------------------------------------------------------------------

def test_identity_key_from_module_path(export):
    """The module path wins the key, exactly as the property's docstring
    says -- if this breaks, either the fixture or the precedence rule moved."""
    assert export.identity.key == "doors:/MRAD Program/Requirements/SRS-MRAD-001@2.1"


def test_identity_fields_read_verbatim_from_preamble(export):
    """Every preamble field lands on the right dataclass attribute, unmodified
    -- a transposed field here would misattribute an artifact to the wrong
    CAGE or contract without ever raising."""
    ident = export.identity
    assert ident.project == "MRAD Program"
    assert ident.baseline == "2.1"
    assert ident.prefix == "SRS"
    assert ident.document_number == "SRS-MRAD-001"
    assert ident.revision == "C"
    assert ident.cage_code == "1AB23"
    assert ident.contract_number == "W58RGZ-24-C-0031"


def test_identity_key_does_not_double_the_project_name(export):
    """Guards the exact bug ``key``'s docstring names: prefixing an already-
    absolute module path with the project yields ``project//project/...`` --
    the same module reachable under two spellings. A module path is absolute,
    so it must appear in the key exactly once and never produce a double
    slash."""
    key = export.identity.key
    assert "//" not in key
    assert key.count("MRAD Program") == 1


# ---------------------------------------------------------------------------
# B. Objects
# ---------------------------------------------------------------------------

def test_object_count(export):
    """43 rows in the fixture body -- SRS-1 through SRS-43. A miscount here
    means a row was dropped or merged, most likely by the multi-line quoted
    field in SRS-7 confusing a line-oriented reader."""
    assert len(export.objects) == 43


def test_object_type_tally(export):
    """Exact per-type counts. This is the cheapest way to prove every object
    kept its ``Object Type`` through the DictReader -- a single swapped
    column would shift one count into another bucket without changing the
    total."""
    counts: dict[str, int] = {}
    for obj in export.objects:
        counts[obj.object_type] = counts.get(obj.object_type, 0) + 1
    assert counts == {
        "Heading": 6,
        "Information": 3,
        "Requirement": 4,
        "Table": 2,
        "Table Row": 7,
        "Table Cell": 21,
    }


def test_embedded_newline_survives_in_object_text(export):
    """SRS-7's quoted CSV field contains a real newline between two
    sentences. If the parser split on lines before handing text to the CSV
    reader, this field would be truncated at the first blank line."""
    srs7 = next(o for o in export.objects if o.identifier == "SRS-7")
    text = srs7.text or ""
    assert "\n" in text
    # Both sides of the newline, so a reader that kept the field but dropped
    # everything after the break still fails.
    assert text.startswith("The CSCI shall record each arrestment event")
    assert text.rstrip().endswith("the identity of the commanding channel.")


def test_embedded_literal_quote_survives_in_object_text(export):
    """SRS-5 contains a doubled double-quote (CSV's escape for a literal
    quote) around the word "valid". If quoting were handled by hand rather
    than by ``csv``, this would come through as two quotes or be lost
    entirely."""
    srs5 = next(o for o in export.objects if o.identifier == "SRS-5")
    text = srs5.text or ""
    # One literal quote character on each side of the word, not two of either:
    # `""valid""` would mean the doubling was passed through undecoded.
    assert '"valid"' in text
    assert '""' not in text


# ---------------------------------------------------------------------------
# C. Tables
# ---------------------------------------------------------------------------

def test_exactly_two_tier1_tables_at_expected_anchors(export):
    """Both tables in the fixture are clean rectangles, so both must be
    tier-1, and tier-2 must be empty -- a false ragged classification here
    would silently drop a real table from the artifact set."""
    assert len(export.tables) == 2
    assert all(t.tier == 1 for t in export.tables)
    assert {t.anchor_id for t in export.tables} == {"SRS-10", "SRS-29"}
    assert export.tier2_tables == ()


def test_table_srs10_shape_and_comma_cell(export):
    """4 rows (header + 3 data) x 3 columns, and the comma inside
    "RS-422, channel A" must have survived the Table Cell -> grid walk,
    which strips and joins text but must never split on the comma."""
    table = next(t for t in export.tables if t.anchor_id == "SRS-10")
    assert len(table.rows) == 4
    assert all(len(r) == 3 for r in table.rows)
    assert table.header == ("Interface", "Signal", "Budget (ms)")
    assert any("RS-422, channel A" in r for r in table.body)


def test_table_srs29_shape(export):
    """3 rows (header + 2 data) x 3 columns, with the expected header."""
    table = next(t for t in export.tables if t.anchor_id == "SRS-29")
    assert len(table.rows) == 3
    assert all(len(r) == 3 for r in table.rows)
    assert table.header == ("Requirement", "Method", "Procedure")


# ---------------------------------------------------------------------------
# D. Artifact round-trip
# ---------------------------------------------------------------------------

def test_csv_round_trip_reproduces_rows_exactly(export):
    """``to_csv()`` piped back through ``csv.reader`` must reproduce
    ``table.rows`` exactly, including the comma-bearing cell -- this is the
    whole point of using ``csv.writer`` instead of ``",".join()``."""
    for table in export.tier1_tables:
        reader = csv.reader(table.to_csv().splitlines())
        round_tripped = tuple(tuple(row) for row in reader)
        assert round_tripped == table.rows


def test_json_round_trip_matches_header_and_body(export):
    """``to_json()`` splits header from body explicitly; a consumer must get
    back exactly ``table.header`` and ``table.body``, not row 0 mixed in."""
    for table in export.tier1_tables:
        payload = json.loads(table.to_json())
        assert payload["header"] == list(table.header)
        assert payload["rows"] == [list(r) for r in table.body]


# ---------------------------------------------------------------------------
# E. Artifact key set
# ---------------------------------------------------------------------------

def test_artifacts_returns_exactly_the_four_tier1_keys(export):
    """Exactly these four keys, nothing else -- a tier-2 table leaking into
    this dict would ship a padded or truncated grid as if it were trustworthy."""
    assert set(export.artifacts().keys()) == {
        "tables/SRS-10.csv",
        "tables/SRS-10.json",
        "tables/SRS-29.csv",
        "tables/SRS-29.json",
    }


# ---------------------------------------------------------------------------
# F. Ragged table -> tier 2, never emitted
# ---------------------------------------------------------------------------

_RAGGED_EXPORT = """Project: Test Project
Baseline: 1.0

Object Identifier,Object Level,Object Heading,Object Text,Object Type
T-1,1,,,Table
T-2,2,,,Table Row
T-3,3,,A,Table Cell
T-4,3,,B,Table Cell
T-5,3,,C,Table Cell
T-6,2,,,Table Row
T-7,3,,D,Table Cell
T-8,3,,E,Table Cell
"""


def test_ragged_table_is_tier2_with_a_reason_and_withheld_from_artifacts():
    """A table whose rows have 3 cells and then 2 cells must become tier-2
    with a non-empty, informative ``ragged_reason``, must not appear in
    ``tier1_tables``, and -- the important assertion -- must not appear in
    ``artifacts()`` at all. Padding the short row would put "D"/"E" under
    the wrong header, which is exactly the defect class this module exists
    to refuse."""
    export = parse_doors_export(_RAGGED_EXPORT)
    assert len(export.tables) == 1
    table = export.tables[0]
    assert table.tier == 2
    assert table.ragged_reason
    assert "differing cell counts" in table.ragged_reason
    assert export.tier1_tables == ()
    assert export.artifacts() == {}


# ---------------------------------------------------------------------------
# G. Refusals
# ---------------------------------------------------------------------------

def test_refusal_no_header_row():
    """No line declares any ``HEADER_MARKERS`` column -- refusal 1. Without
    this check, the preamble's own first line would be misread as column
    names and every object would come out as garbage."""
    text = "Project: Test Project\nBaseline: 1.0\nJust some free text, no header.\n"
    with pytest.raises(DoorsParseError):
        parse_doors_export(text)


def test_refusal_no_project_in_preamble_names_keys_actually_present():
    """Refusal 2, the ``project``-missing half. The message must list the
    preamble keys that WERE seen -- that list is the diagnostic a real site
    with a differently-spelled key needs to fix its export."""
    text = (
        "Baseline: 1.0\n\n"
        "Object Identifier,Object Level,Object Heading,Object Text,Object Type\n"
    )
    with pytest.raises(DoorsParseError) as exc_info:
        parse_doors_export(text)
    assert "Baseline" in str(exc_info.value)


def test_refusal_no_baseline_in_preamble_names_keys_actually_present():
    """Refusal 2, the ``baseline``-missing half, with the same diagnostic
    requirement as the project case above."""
    text = (
        "Project: Test Project\n\n"
        "Object Identifier,Object Level,Object Heading,Object Text,Object Type\n"
    )
    with pytest.raises(DoorsParseError) as exc_info:
        parse_doors_export(text)
    assert "Project" in str(exc_info.value)


def test_refusal_table_row_with_no_enclosing_table():
    """Refusal 3: a ``Table Row`` encountered outside any ``Table`` subtree
    means the outline nesting is not what the parser assumes, so it must
    stop rather than build a grid from the wrong rows."""
    text = (
        "Project: Test Project\nBaseline: 1.0\n\n"
        "Object Identifier,Object Level,Object Heading,Object Text,Object Type\n"
        "T-1,1,,,Table Row\n"
    )
    with pytest.raises(DoorsParseError):
        parse_doors_export(text)


def test_refusal_table_with_no_table_row_children():
    """Refusal 3's other half: a ``Table`` object with no ``Table Row``
    children means the level nesting differs from what this parser expects
    -- an empty table subtree, not an author writing an empty table."""
    text = (
        "Project: Test Project\nBaseline: 1.0\n\n"
        "Object Identifier,Object Level,Object Heading,Object Text,Object Type\n"
        "T-1,1,,,Table\n"
    )
    with pytest.raises(DoorsParseError):
        parse_doors_export(text)


def test_refusal_object_level_not_an_integer():
    """A non-integer ``Object Level`` means the outline level this parser
    walks to find rows and cells cannot be trusted -- the grids it would
    build would be wrong, not merely missing."""
    text = (
        "Project: Test Project\nBaseline: 1.0\n\n"
        "Object Identifier,Object Level,Object Heading,Object Text,Object Type\n"
        "T-1,abc,,,Heading\n"
    )
    with pytest.raises(DoorsParseError):
        parse_doors_export(text)
