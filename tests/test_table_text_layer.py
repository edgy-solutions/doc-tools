"""Text-layer table extraction — tier 1 of the extraction ladder.

Pinned against REAL failures measured on Diodes PCN 2683 (2026-07-29/30), where the
vision pass produced ZERO parts at work (runaway decode, killed at LiteLLM's 60s) while
the same tables read exactly from the PDF's own text layer in under a second.

The column logic is pure (grids of strings), so it tests without pdfplumber or a PDF.
"""
import pytest

from doc_tools.utils.table_text_layer import (
    find_header_row, find_title_row, header_pairing, looks_like_mpn, pair_columns,
    parts_from_grid, parts_from_pages, strip_enclosing_quotes,
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


# --------------------------------------------------------------------------- #
# CONTINUATION TABLES. A parts table that spans pages prints its header once, so every
# page after the first is an anonymous grid. Read in isolation it hits the caption rule
# and EVERY column becomes an affected part — including the replacement half of an
# `EOL | Replacement` table.
#
# NOTE ON THE MOTIVATING NUMBER. This was originally justified by "136 of 402 extracted
# affected parts (34%) appeared ONLY in replacement columns", measured on Diodes PCN
# 2683. Run against the real notice on 2026-09-21 that figure did not hold: all 136 sit
# on pages captioned "...and No Replacement Parts", and the diagnostic had produced them
# by applying THIS SAME inheritance without a caption check. Inheritance remains the
# right reading for a true continuation page — but the corpus never showed the defect,
# and the near-miss it did show runs the other way (see the caption-veto tests below).
# docs/pcn-corpus-validation-2026-09-21.md has the measurement.
#
# The whole risk here is trading one wrong assumption for another, so BOTH directions
# are pinned: a genuine bare list must still read all-affected, and a continuation of a
# paired table must not.
# --------------------------------------------------------------------------- #

# The continuation page: same six columns, same meaning, no header printed.
_CONT_ROW = ["FJ4800016", "FJ4800400", "FKA000028Q", "HX3AA0006Q", "HX1110001Q", "HX1A10001Q"]


def test_a_headed_table_offers_its_pairing_for_inheritance():
    """Only a table that DECLARES its columns can lend them to the next page."""
    inherited = header_pairing([_HEADER, _ROW1])
    assert inherited is not None
    assert inherited.pairs == [(0, 1), (2, 3), (4, 5)]
    assert inherited.width == 6, "the column count is the guard against a stale header"


def test_a_caption_only_table_is_NOT_inheritable():
    """A caption states what THIS table holds. Carrying "every column is affected"
    forward to the next grid would assert it about columns nobody labelled — the exact
    unguarded guess this module declines to make."""
    assert header_pairing([["Table 3 - EOL Devices", "", ""], ["A1", "B2", "C3"]]) is None


def test_continuation_of_a_paired_table_does_not_emit_replacements_as_affected():
    """THE defect. Without the inherited header this grid reads as six affected parts,
    three of which are replacements being reported as discontinued."""
    inherited = header_pairing([_HEADER, _ROW1])
    grid = [["Table 1 - EOL Devices", "", "", "", "", ""], _CONT_ROW]

    defect = parts_from_grid(grid)
    assert [p["affected_mpn"] for p in defect] == _CONT_ROW, "precondition: the old shape"

    fixed = parts_from_grid(grid, inherited=inherited)
    assert [p["affected_mpn"] for p in fixed] == ["FJ4800016", "FKA000028Q", "HX1110001Q"]
    assert [p["replacement_mpn"] for p in fixed] == ["FJ4800400", "HX3AA0006Q", "HX1A10001Q"]
    for mpn in ("FJ4800400", "HX3AA0006Q", "HX1A10001Q"):
        assert mpn not in [p["affected_mpn"] for p in fixed], f"{mpn} is a replacement"


def test_headerless_continuation_without_a_caption_is_now_READ_not_dropped():
    """The other half of the same defect: with no caption to fall back on, a continuation
    page was declined outright and its parts were lost. The header makes it readable."""
    assert parts_from_grid([_CONT_ROW]) == [], "precondition: dropped without a header"
    fixed = parts_from_grid([_CONT_ROW], inherited=header_pairing([_HEADER, _ROW1]))
    assert [(p["affected_mpn"], p["replacement_mpn"]) for p in fixed] == [
        ("FJ4800016", "FJ4800400"), ("FKA000028Q", "HX3AA0006Q"), ("HX1110001Q", "HX1A10001Q")]


def test_column_count_mismatch_must_not_inherit_a_stale_header():
    """The guard. An unrelated later table inheriting a stale header would mislabel parts
    CONFIDENTLY — worse than the defect being fixed, which at least declines."""
    inherited = header_pairing([_HEADER, _ROW1])            # width 6
    grid = [["Table 3 - EOL Devices", "", ""],              # width 3 — a different table
            ["WT21120001", "WC3110001Q", "WL2511F0048.000000"]]
    parts = parts_from_grid(grid, inherited=inherited)
    assert [p["affected_mpn"] for p in parts] == ["WT21120001", "WC3110001Q", "WL2511F0048.000000"]
    assert all(p["replacement_mpn"] is None for p in parts), "fell through to the caption rule"


def test_a_genuine_bare_list_still_reads_every_column_as_affected():
    """The case the original code was written for, and it is REAL — Diodes page 5. An
    inheritable header from an earlier table must not be allowed to override a table that
    carries its own caption and a different shape."""
    grid = [["Table 3 - EOL Devices", "", "", ""],
            ["WT21120001", "WC3110001Q", "WL2511F0048.000000", "WT21388001"]]
    for inherited in (None, header_pairing([_HEADER, _ROW1])):
        parts = parts_from_grid(grid, inherited=inherited)
        assert len(parts) == 4, f"inherited={inherited}"
        assert all(p["replacement_mpn"] is None for p in parts)


def test_a_caption_numbering_a_DIFFERENT_table_refuses_the_inherited_pairing():
    """Diodes PCN 2683, measured against the real notice on 2026-09-21. Pages 3, 4 and 5
    are THREE different tables, and the width guard only saves us because pdfplumber
    happens to give pages 4/5 eight columns against page 3's six. In the unstructured
    `text.json` grid space all three are SIX wide, the guard passes, and page 3's
    `EOL | Replacement` pairing lands on tables whose own captions read "...and No
    Replacement Parts" — 144 genuine EOL devices silently reclassified as replacements.

    The document already says these are different tables. Read the caption.
    """
    declaring = header_pairing([_CAPTION, _HEADER, _ROW1])      # "Table 1 -", width 6
    assert declaring.label == "1"

    # page 4: same width, its OWN table number, no header of its own
    page4 = [["Table 2 - EOL Devices with Life-time Buy Opportunity and No Replacement "
              "Parts", "", "", "", "", ""],
             ["TLC271ACS-13", "TLC27L1ACS-13", "HX5112001Q", "FN0800047", "FN3600027",
              "S1700C-12.2880(T)"]]
    parts = parts_from_grid(page4, inherited=declaring)

    assert [p["affected_mpn"] for p in parts] == [
        "TLC271ACS-13", "TLC27L1ACS-13", "HX5112001Q", "FN0800047", "FN3600027",
        "S1700C-12.2880(T)"], "every column here is an EOL device; the caption says so"
    assert all(p["replacement_mpn"] is None for p in parts), \
        "Table 2 declares NO replacement parts — none may be invented by inheritance"


def test_a_continuation_repeating_its_parents_table_number_still_inherits():
    """The veto must fire on POSITIVE evidence only. A continuation page that reprints
    the same caption is still the same table, and must keep reading as the paired table
    it is — otherwise the fix undoes itself."""
    declaring = header_pairing([_CAPTION, _HEADER, _ROW1])      # "Table 1 -"
    cont = [["Table 1 - EOL Devices", "", "", "", "", ""], _CONT_ROW]

    parts = parts_from_grid(cont, inherited=declaring)
    assert [p["affected_mpn"] for p in parts] == ["FJ4800016", "FKA000028Q", "HX1110001Q"]
    assert [p["replacement_mpn"] for p in parts] == ["FJ4800400", "HX3AA0006Q", "HX1A10001Q"]


def test_an_unnumbered_caption_does_not_veto_inheritance():
    """A caption with no table number carries no claim about WHICH table this is, so it
    is not evidence of a different one. Unchanged behaviour: inherit."""
    declaring = header_pairing([_CAPTION, _HEADER, _ROW1])
    cont = [["EOL Devices", "", "", "", "", ""], _CONT_ROW]
    parts = parts_from_grid(cont, inherited=declaring)
    assert [p["replacement_mpn"] for p in parts] == ["FJ4800400", "HX3AA0006Q", "HX1A10001Q"]


def test_a_declaring_table_with_no_caption_never_vetoes():
    """Symmetric: if the table that lent the pairing never numbered itself, a later
    caption cannot contradict it, so inheritance stands."""
    declaring = header_pairing([_HEADER, _ROW1])                # no caption row
    assert declaring.label is None
    cont = [["Table 9 - EOL Devices", "", "", "", "", ""], _CONT_ROW]
    parts = parts_from_grid(cont, inherited=declaring)
    assert [p["replacement_mpn"] for p in parts] == ["FJ4800400", "HX3AA0006Q", "HX1A10001Q"]


def test_an_unlabelled_grid_is_still_declined_when_there_is_nothing_to_inherit():
    """Inheritance must not become a licence to guess. No header, no caption, nothing
    carried forward -> still decline."""
    assert parts_from_grid([["1234", "5678"], ["4321", "8765"]], inherited=None) == []


def test_values_are_verbatim_never_normalized():
    """MPNs must match the document exactly — no hyphenation, padding or 'correction'."""
    grid = [["Affected Part", "Replacement"], ["BYVB32-200-E3/81", "LTC6226HDC#TRMPBF"]]
    p = parts_from_grid(grid)[0]
    assert p["affected_mpn"] == "BYVB32-200-E3/81"
    assert p["replacement_mpn"] == "LTC6226HDC#TRMPBF"


# --------------------------------------------------------------------------- #
# ALIAS COLUMNS. A notice carries `Alias Part Number(s)` / `Substitute Alias Part
# Number(s)` beside the real ones, and those values were being emitted as affected parts
# (14 instances in the work corpus). An alias is not the discontinued part; putting one on
# a review card asks a human to disposition a part the notice never discontinued.
# --------------------------------------------------------------------------- #

_ALIAS_HEADER = ["EOL Device", "Alias Part Number(s)", "Replacement",
                 "Substitute Alias Part Number(s)"]


def test_alias_columns_are_neither_affected_nor_replacement():
    """The alias wording CONTAINS the other vocabularies — "Alias Part Number(s)" matches
    "part number", "Substitute Alias Part Number(s)" matches "substitute" — so alias must
    be tested first or it reads as the very column it is not."""
    assert pair_columns(_ALIAS_HEADER) == [(0, 2)], "alias columns must not be paired"


def test_an_alias_value_never_becomes_a_part():
    grid = [_ALIAS_HEADER,
            ["AD7873ACPZ", "AD7873-FAMILY", "AD7873ACPZ-RL", "AD7873-FAM-RL"]]
    parts = parts_from_grid(grid)
    assert [p["affected_mpn"] for p in parts] == ["AD7873ACPZ"]
    assert parts[0]["replacement_mpn"] == "AD7873ACPZ-RL"
    emitted = [v for p in parts for v in (p["affected_mpn"], p["replacement_mpn"]) if v]
    assert not any("FAM" in v for v in emitted), emitted


def test_an_inherited_header_carries_the_alias_veto_too():
    """The two fixes compose: a continuation page of an alias-bearing table must not
    resurrect the alias columns it inherits."""
    inherited = header_pairing([_ALIAS_HEADER, ["A1", "A2", "A3", "A4"]])
    assert inherited.pairs == [(0, 2)]
    cont = parts_from_grid([["AD7879ACPZ", "AD7879-FAMILY", "AD7879ACPZ-RL", "AD7879-FAM-RL"]],
                           inherited=inherited)
    assert [p["affected_mpn"] for p in cont] == ["AD7879ACPZ"]


def test_an_mpn_containing_an_alias_WORD_is_not_dropped_as_a_header():
    """The alias vocabulary describes HEADERS. Applying it to a cell that is a VALUE would
    silently drop real part numbers that merely contain one of those words — the terms are
    ordinary English ("series", "generic", "family"), and a dropped part is invisible."""
    grid = [["Affected Part", "Replacement"],
            ["GENERIC-1000", "SERIES-2000"],
            ["FAMILY-30A", "SIMILAR-40B"]]
    parts = parts_from_grid(grid)
    assert [p["affected_mpn"] for p in parts] == ["GENERIC-1000", "FAMILY-30A"], parts
    assert [p["replacement_mpn"] for p in parts] == ["SERIES-2000", "SIMILAR-40B"]


def test_the_alias_vocabulary_matches_the_one_the_measurement_used():
    """Anti-drift. The 34% and 14-instance figures were measured with
    pdn_parts_diagnostic.ALIAS_HEADERS; if production quietly diverges, the next corpus
    run compares two different rulers and reports the difference as a result. Pinned
    here so a change to either list has to be a deliberate change to BOTH."""
    from doc_tools.utils.table_text_layer import ALIAS_HEADERS
    assert ALIAS_HEADERS == (
        "product family", "family", "alias", "cross reference", "cross-reference",
        "xref", "equivalent", "pin to pin", "pin-to-pin", "compatible", "base part",
        "generic", "series", "similar", "second source",
    )


def test_the_ordinary_vocabulary_is_unchanged_by_the_alias_veto():
    """The veto must not eat plain columns. This is the regression that would silently
    empty the common case."""
    assert pair_columns(_HEADER) == [(0, 1), (2, 3), (4, 5)]
    assert len(parts_from_grid([_CAPTION, _HEADER, _ROW1, _ROW2])) == 6


# --------------------------------------------------------------------------- #
# ENCLOSING QUOTES. A notice that prints its part numbers in quotes yields
# '"090-44310-31"'. The quote is a delimiter around the MPN, never a character of it —
# but downstream it is treated as one, and every graph MERGE and join silently misses.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw,clean", [
    ('"090-44310-31"', "090-44310-31"),
    ('“AD7873ACPZ”', "AD7873ACPZ"),          # typographic quotes occur too
    ('""FJ3330013""', "FJ3330013"),
    ("'BYVB32-200-E3/81'", "BYVB32-200-E3/81"),
])
def test_enclosing_quotes_are_removed(raw, clean):
    assert strip_enclosing_quotes(raw) == clean


@pytest.mark.parametrize("value", [
    "LTC6226HDC#TRMPBF", "BYVB32-200-E3/81", "090-44310-31", "S1613E-20.0000(T)",
    '"unbalanced',          # a lone quote is NOT a delimiter pair — leave it alone
    "6'",                   # ditto, trailing only
])
def test_everything_else_stays_verbatim(value):
    """Narrow on purpose. The MPN contract is verbatim and part numbers really do carry
    odd characters; only a BALANCED enclosing pair is a delimiter."""
    assert strip_enclosing_quotes(value) == value


def test_de_quoting_never_empties_a_value():
    assert strip_enclosing_quotes(None) is None
    assert strip_enclosing_quotes('""') == '""'


# --------------------------------------------------------------------------- #
# ACROSS PAGES. The pure-grid tests above pin the DECISION; this one pins the THREADING,
# which is where the defect actually lives — a table printed across pages declares its
# columns once, on the first page, and every per-page call after that sees an anonymous
# grid. Fake pages stand in for pdfplumber so this still runs without a PDF.
# --------------------------------------------------------------------------- #

class _FakeTable:
    def __init__(self, grid):
        self._grid = grid
        # one bbox per cell, distinct so a mixed-up cell would be visible
        self.rows = [type("R", (), {"cells": [(c, r, c + 1, r + 1) for c in range(len(row))]})()
                     for r, row in enumerate(grid)]

    def extract(self):
        return self._grid


class _FakePage:
    width, height = 612.0, 792.0

    def __init__(self, *grids):
        self._tables = [_FakeTable(g) for g in grids]

    def find_tables(self):
        return self._tables


def test_header_is_inherited_ACROSS_pages_not_just_within_one():
    """Page 1 declares `EOL | Replacement` x3; pages 2 and 3 are bare continuations. Read
    per-page they had no header and no caption, so they were dropped entirely; with a
    caption they were worse — every column, replacements included, became an affected
    part. Threaded, all three pages read as the one paired table they are."""
    page1 = _FakePage([_HEADER, _ROW1])
    page2 = _FakePage([_CONT_ROW])
    page3 = _FakePage([["Table 1 - EOL Devices", "", "", "", "", ""], _ROW2])

    parts = parts_from_pages([(1, page1), (2, page2), (3, page3)])
    affected = [p["affected_mpn"] for p in parts]

    assert len(parts) == 9, affected                     # 3 pairs x 3 pages
    assert [p["page_number"] for p in parts] == [1, 1, 1, 2, 2, 2, 3, 3, 3]
    # not one replacement may appear as an affected part
    for rep in ("FJ3330401", "FJ4800400", "HX3AA0006Q", "HX1A10001Q", "FKA000400"):
        assert rep not in affected, f"{rep} is a replacement, reported as discontinued"
    assert all(p["replacement_mpn"] for p in parts), "every row here has a replacement"
    assert all(p["bbox"] and p["replacement_bbox"] for p in parts), "per-cell provenance"


def test_a_page_with_no_tables_ends_the_run():
    """A spanning table has demonstrably finished if a whole page carries no table at all.
    Without this the header survives the gap and a later, unrelated grid that merely
    happens to have the same column count inherits it — confident mislabelling, which is
    worse than the defect being fixed."""
    page1 = _FakePage([_HEADER, _ROW1])      # declares 6 paired columns
    prose = _FakePage()                       # no tables
    later = _FakePage([_CONT_ROW])            # unrelated 6-column grid, no header

    parts = parts_from_pages([(1, page1), (2, prose), (3, later)])
    assert [p["page_number"] for p in parts] == [1, 1, 1], "page 3 must not inherit"
    assert len(parts) == 3


def test_a_new_headed_table_replaces_what_is_carried_forward():
    """Inheritance must not outlive its table. A later table that declares its OWN columns
    becomes the thing subsequent continuations inherit."""
    first = _FakePage([_HEADER, _ROW1])                                  # 6 cols, paired
    second = _FakePage([["Affected Part", "Replacement"], ["A100", "B200"]])   # 2 cols
    cont = _FakePage([["C300", "D400"]])                                  # continues #2

    parts = parts_from_pages([(1, first), (2, second), (3, cont)])
    assert [(p["affected_mpn"], p["replacement_mpn"]) for p in parts][-2:] == [
        ("A100", "B200"), ("C300", "D400")]


def test_a_single_page_call_still_works_and_inherits_nothing():
    """parts_from_page stays the single-page convenience; it must not silently carry
    state from anywhere."""
    from doc_tools.utils.table_text_layer import parts_from_page
    assert parts_from_page(_FakePage([_CONT_ROW]), 1) == []


# --------------------------------------------------------------------------- #
# DECLINE RECORDS. A decline is NOT an empty table — pdfplumber read the grid fine; what
# could not be decided is what the COLUMNS MEAN. The row count it carries is the only
# independent check on the vision pass that runs afterwards (doc_tools/plugins/
# sustainment.py's crops_row_short detector: tier 1 saw N MPN-shaped rows on a page, a
# vision crop of the SAME page came back with fewer, nothing else would have caught it —
# the SYTX9-122HP-1+ shape on PCN23-002). Before this, `parts_from_grid` returned a bare
# `[]` on decline and that row count was simply gone.
# --------------------------------------------------------------------------- #

def test_headerless_captionless_grid_declines_but_carries_its_row_count():
    """The PCN23-002 shape: 18 bare MPNs, one per row, no header and no caption. Back-compat
    (`parts_from_grid`) must still return exactly the bare `[]` every existing caller
    expects; `grid_outcome` must additionally say WHY and how many rows were really there."""
    from doc_tools.utils.table_text_layer import grid_outcome
    grid = [[f"MPN{i:04d}0"] for i in range(18)]
    assert parts_from_grid(grid) == [], "back-compat: still declines, still a bare list"
    outcome = grid_outcome(grid)
    assert outcome.parts == []
    assert outcome.decline is not None
    assert outcome.decline.n_rows == 18, "all 18 rows carry an MPN-shaped cell"
    assert outcome.decline.n_grid_rows == 18, "pdfplumber saw all 18 rows too — nothing to diverge on here"
    assert outcome.decline.reason == (
        "no column header, nothing to inherit, and no caption naming the contents")


def test_decline_row_count_excludes_captions_and_blanks_but_grid_row_count_does_not():
    """n_rows counts only rows an MPN could plausibly come from; n_grid_rows counts
    LITERALLY everything pdfplumber returned, captions and blanks included. They must
    diverge on a grid that mixes MPN rows with spacer/caption rows, or the
    crops_row_short comparison would be checking vision against an inflated baseline."""
    from doc_tools.utils.table_text_layer import grid_outcome
    grid = [
        ["Some caption row with no digits at all"],
        ["MPN00010"],
        [""],
        ["MPN00020"],
        ["   "],
        ["MPN00030"],
    ]
    outcome = grid_outcome(grid)
    assert outcome.decline is not None
    assert outcome.decline.n_rows == 3, "only the three MPN-bearing rows"
    assert outcome.decline.n_grid_rows == 6, "every row pdfplumber returned, blanks and caption included"


# --------------------------------------------------------------------------- #
# _mpn_bearing_rows — the row_short baseline denominator. `looks_like_mpn` alone
# ("contains a digit" after length/space caps) is correct for column PAIRING but
# over-counts as a shortfall baseline: a JEDEC qualification-standard row carries a
# cell like "JESD22-A103" that trivially looks_like_mpn even though the row is prose,
# not a part row. Measured on onsemi_Generic_IPCN25300X.
# --------------------------------------------------------------------------- #
def test_mpn_bearing_rows_counts_the_pcn23_002_shape():
    """18 bare single-cell MPN rows, no prose anywhere — every row counts."""
    from doc_tools.utils.table_text_layer import _mpn_bearing_rows
    grid = [[f"MPN{i:04d}0"] for i in range(18)]
    assert _mpn_bearing_rows(grid) == 18


def test_mpn_bearing_rows_excludes_jedec_prose_rows():
    """The real onsemi_Generic_IPCN25300X shape: JESD22-A103 etc. contain digits and
    would pass looks_like_mpn on their own, but each row also carries a prose cell
    (a sentence-length or multi-space description) and must not count as a part row."""
    from doc_tools.utils.table_text_layer import _mpn_bearing_rows
    grid = [
        ["", "High Temperature Storage Life", "", "", "JESD22-A103", "", "",
         "Ta= -40°C to +125°C", "", "", "1008 hrs"],
        ["", "Preconditioning", "", "", "J-STD-020 JESD-A113", "", "",
         "MSL 1 @ 260 °C", "", "", ""],
        ["", "Temperature Cycling", "", "", "JESD22-A104", "", "",
         "-65°C to +150°C, 500 cycles", "", "", ""],
        ["", "Autoclave", "", "", "JESD22-A118", "", "",
         "130°C, 85% RH, 18.8psi", "", "", "96 hrs"],
    ]
    assert _mpn_bearing_rows(grid) == 0


def test_looks_like_mpn_is_unchanged_for_column_pairing():
    """Regression guard: the row_short prose exclusion lives ABOVE looks_like_mpn, not
    inside it. looks_like_mpn is still used, unmodified, by pair_columns/cell-to-column
    matching — a JEDEC standard id must still register as MPN-shaped for THAT job."""
    assert looks_like_mpn("JESD22-A103") is True


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
