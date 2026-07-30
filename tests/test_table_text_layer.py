"""Text-layer table extraction — tier 1 of the extraction ladder.

Pinned against REAL failures measured on Diodes PCN 2683 (2026-07-29/30), where the
vision pass produced ZERO parts at work (runaway decode, killed at LiteLLM's 60s) while
the same tables read exactly from the PDF's own text layer in under a second.

The column logic is pure (grids of strings), so it tests without pdfplumber or a PDF.
"""
import pytest

from doc_tools.utils.table_text_layer import (
    find_header_row, find_title_row, looks_like_mpn, pair_columns, parts_from_grid,
)

# The real page-3 shape: a CAPTION, then a header declaring THREE (EOL, Replacement) pairs.
_CAPTION = ["Table 1 - EOL Devices with Life-time Buy Opportunity and Replacement Parts", "", "", "", "", ""]
_HEADER = ["EOL Devices", "Replacements", "EOL Devices", "Replacements", "EOL Devices", "Replacements"]
_ROW1 = ["FJ3330013", "FJ3330401", "FKA000010", "FKA000400", "HX1112202Q", "HX1A12202Q"]
_ROW2 = ["FJ4800016", "FJ4800400", "FKA000028Q", "HX3AA0006Q", "HX1110001Q", "HX1A10001Q"]


def test_caption_is_not_mistaken_for_the_header():
    """THE bug that lost two thirds of a 111-part page. The caption contains "EOL Devices",
    so first-match header detection selected it — one labelled cell in an otherwise-empty
    row — collapsing three column-pairs into a single unpaired column: 37 parts instead of
    111, and not one replacement. The header must be the BEST-scoring row with >1 non-empty
    cell, never a caption."""
    grid = [_CAPTION, _HEADER, _ROW1, _ROW2]
    assert find_header_row(grid) == 1, "picked the caption instead of the real header"


def test_three_column_pairs_are_all_read():
    """Vendors repeat (affected, replacement) ACROSS the page to save paper. Reading one
    part per row silently drops the rest."""
    pairs = pair_columns(_HEADER)
    assert pairs == [(0, 1), (2, 3), (4, 5)], pairs
    parts = parts_from_grid([_CAPTION, _HEADER, _ROW1, _ROW2])
    assert len(parts) == 6, f"expected 3 pairs x 2 rows = 6 parts, got {len(parts)}"
    assert parts[0] == {"affected_mpn": "FJ3330013", "replacement_mpn": "FJ3330401",
                        "row": 2, "col": 0, "rep_col": 1}, parts[0]
    assert [p["affected_mpn"] for p in parts[:3]] == ["FJ3330013", "FKA000010", "HX1112202Q"]


def test_caption_only_table_treats_every_column_as_affected():
    """Diodes page 5: caption "Table 3 - EOL Devices", then six columns of part numbers and
    NO replacements column. With no header, the caption is the only statement of what the
    cells are — reading it is the difference between 257 parts and skipping the page."""
    grid = [
        ["Table 3 - EOL Devices", "", "", ""],
        ["WT21120001", "WC3110001Q", "WL2511F0048.000000", "WT21388001"],
        ["WT21120003", "WC31409001", "", ""],
    ]
    assert find_header_row(grid) is None
    assert find_title_row(grid) == 0
    parts = parts_from_grid(grid)
    assert len(parts) == 6, [p["affected_mpn"] for p in parts]
    assert all(p["replacement_mpn"] is None for p in parts), "a bare EOL list has no replacements"


def test_unlabelled_grid_is_declined_not_guessed():
    """No header AND no caption -> we do NOT know what the columns are. Guessing parts out
    of an unknown grid is how a table of dates or quantities becomes fabricated MPNs."""
    grid = [["1234", "5678"], ["4321", "8765"]]
    assert parts_from_grid(grid) == []


def test_prose_block_is_not_a_part():
    """find_tables() also returns text blocks that merely look tabular. Before the MPN
    plausibility floor, a 130-character sentence ("Unless a Diodes Incorporated Sales
    representative is contacted in writing within 30 days...") was emitted as a part."""
    sentence = ("Unless a Diodes Incorporated Sales representative is contacted in writing "
                "within 30 days of the posting of this notice, all changes are approved.")
    assert not looks_like_mpn(sentence)
    grid = [["EOL Devices", "Replacements"], [sentence, ""], ["FJ3330013", "FJ3330401"]]
    parts = parts_from_grid(grid)
    assert [p["affected_mpn"] for p in parts] == ["FJ3330013"]


@pytest.mark.parametrize("mpn", [
    "FJ3330013", "HX1112202Q", "WL2511F0048.000000", "PI3HDX511AZLSEX",
    "TLC271ACS-13", "090-44310-31", "S1613E-20.0000(T)", "LTC6226HDC#TRMPBF",
])
def test_real_mpn_shapes_survive_the_plausibility_floor(mpn):
    """The floor must not eat legitimate non-standard schemes — slashes, '#' reel codes,
    module dashes and decimal frequencies are all real part numbers in this corpus."""
    assert looks_like_mpn(mpn), mpn


@pytest.mark.parametrize("junk", ["", "   ", "Replacements", "a much longer sentence than any real part number would ever be, by far"])
def test_non_mpn_values_are_rejected(junk):
    assert not looks_like_mpn(junk)


def test_repeated_header_mid_table_is_skipped():
    """Tables continued across pages repeat their header; it is not a part."""
    grid = [_HEADER, _ROW1, _HEADER, _ROW2]
    parts = parts_from_grid(grid)
    assert all(p["affected_mpn"] != "EOL Devices" for p in parts)
    assert len(parts) == 6


def test_replacement_carries_its_own_column_for_per_cell_provenance():
    """The replacement sits in a DIFFERENT cell from the affected part, so it must carry
    its own column index — reusing the affected cell's bbox would highlight the wrong cell.
    Before per-cell provenance every part on a page shared one whole-table box."""
    parts = parts_from_grid([_CAPTION, _HEADER, _ROW1])
    assert [(p["col"], p["rep_col"]) for p in parts] == [(0, 1), (2, 3), (4, 5)]
    # an unpaired affected column has no replacement cell to point at
    solo = parts_from_grid([["EOL Devices"], ["FJ3330013"]])
    assert solo[0]["rep_col"] is None and solo[0]["replacement_mpn"] is None


def test_values_are_verbatim_never_normalized():
    """MPNs must match the document exactly — no hyphenation, padding or 'correction'."""
    grid = [["Affected Part", "Replacement"], ["BYVB32-200-E3/81", "LTC6226HDC#TRMPBF"]]
    p = parts_from_grid(grid)[0]
    assert p["affected_mpn"] == "BYVB32-200-E3/81"
    assert p["replacement_mpn"] == "LTC6226HDC#TRMPBF"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
