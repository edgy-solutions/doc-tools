"""THE SEAL for tier-1 grid forwarding: this test module must FAIL if a part string
ever comes from PIXELS again on a page tier 1 declined.

Before this change, a declined grid fell straight to the vision pixel path
(`b.ExtractParts`), which re-reads every MPN from a fresh crop of the table image. On
PCN23-002.pdf that crop is clipped 47% through the glyphs of its LAST row, and
`SYTX9-122HP-1+` — real, verbatim in the source (scripts/pcn_ground_truth.json) — was
silently dropped: 17 of 18 parts, no crops_failed, no crops_truncated, needs_review=False.

After this change, a page carrying a declined grid is handed to `b.LabelGridColumns`
instead: that call returns COLUMN INDICES ONLY (see GridColumnRoles / the NOTE above
LabelGridColumns in baml_src/sustainment.baml), and every part string is read verbatim
out of the pdfplumber-extracted grid cells in Python — never out of the vision
response, never out of pixels. A re-cut or clipped crop can therefore cost a column
LABEL, but it can no longer cost a ROW or corrupt an MPN's characters.

This uses the REAL PCN23-002 ground truth (18 MPNs, in order, SYTX9-122HP-1+ last) so
the fixture is not a toy shape that happens to pass.
"""
from types import SimpleNamespace

import pytest

from doc_tools.baml_client import sync_client as sync_client_module
from doc_tools.baml_client.types import GridColumnRoles
from doc_tools.plugins import sustainment as sustainment_module
from doc_tools.utils import table_text_layer as text_layer
from doc_tools.plugins.sustainment import SustainmentPlugin, VISION_MAX_TOKENS

# The real PCN23-002 ground truth (scripts/pcn_ground_truth.json), in the exact printed
# order, SYTX9-122HP-1+ LAST — the row whose crop is clipped 47% through the glyphs and
# was, before this change, silently dropped by the pixel path.
PCN23_002_MPNS = [
    "SYBDC-20-61WHP+", "SYDC-10-52VHP+", "SYDC-19-52HP+", "SYDC-19-52VHP+",
    "SYDC-25-92VHP+", "SYDC20-171VHP+", "SYPS-2-52HP+", "SYPS-2-52HP-2+",
    "SYTX1-52HP-15W+", "SYTX1-52HP15W1+", "SYTX2-52HP-20W+", "SYTX2-61HP+",
    "SYTX3-7-20W-1+", "SYTX4-13HP+", "SYBDC-15-52VHP+", "SYBDC15-62VHP1+",
    "SYDC-25-92VHP1+", "SYTX9-122HP-1+",
]


def _grid():
    """Header row + 18 part rows, exactly as pdfplumber would hand back a declined
    grid: column 0 the affected MPN, column 1 a replacement value. Neither header cell
    contains a digit, so it can never satisfy `is_part_row` regardless of `header_rows`.
    """
    header = ["Affected Part Number", "Replacement Part Number"]
    rows = [[mpn, f"REPL-{i}"] for i, mpn in enumerate(PCN23_002_MPNS)]
    return [header] + rows


def _decline(page_number=1):
    grid = _grid()
    return {"page_number": page_number, "reason": "no column header, nothing to inherit",
            "n_rows": len(PCN23_002_MPNS), "n_grid_rows": len(grid), "grid": grid}


def _table_element(page_number, image_path=None):
    meta = {"page_number": page_number, "text_as_html": ""}
    if image_path:
        meta["image_path"] = image_path
    return {"type": "Table", "text": "ocr text", "metadata": meta}


def _roles(affected_col=0, replacement_col=1, ltb_date_col=None, header_rows=(0,)):
    return GridColumnRoles(affected_col=affected_col, replacement_col=replacement_col,
                           ltb_date_col=ltb_date_col, header_rows=list(header_rows),
                           reason="column 0 is MPN-shaped, column 1 pairs as its replacement")


class _FakeB:
    """Stand-in for doc_tools.baml_client.sync_client.b. Queues LabelGridColumns
    results (an exception instance is raised instead of returned); ExtractParts is
    tracked but must NEVER be called for a page the grid path successfully handles —
    that is exactly what this seal exists to catch.
    """

    def __init__(self, label_results=(), extract_parts_results=()):
        self._label_results = list(label_results)
        self._extract_parts_results = list(extract_parts_results)
        self.extract_parts_calls = 0

    def LabelGridColumns(self, **kwargs):
        result = self._label_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def ExtractParts(self, **kwargs):
        self.extract_parts_calls += 1
        return self._extract_parts_results.pop(0) if self._extract_parts_results else []


@pytest.fixture(autouse=True)
def _prompt_from_file(monkeypatch):
    """Same pin as test_sustainment_plugin.py: these are pure-logic tests, not a
    Langfuse-availability test."""
    monkeypatch.setenv("PROMPT_SOURCE", "file")


@pytest.fixture
def plugin():
    return SustainmentPlugin(domain_type="sustainment")


def _patch_b(monkeypatch, **kwargs):
    fake = _FakeB(**kwargs)
    monkeypatch.setattr(sync_client_module, "b", fake)
    return fake


def _patch_tokens(monkeypatch, tokens):
    monkeypatch.setattr(sustainment_module, "_vision_output_tokens", lambda collector: tokens)


# --------------------------------------------------------------------------- #
# (1) + (2) + (3): all 18 MPNs emitted verbatim, affected_mpn == affected_mpn_source and
# a subset of grid cell strings, and the pixel path (ExtractParts) never runs.
# --------------------------------------------------------------------------- #
def test_all_18_mpns_emitted_verbatim_from_the_grid_no_pixel_call(plugin, monkeypatch):
    fake = _patch_b(monkeypatch, label_results=[_roles()])
    _patch_tokens(monkeypatch, round(VISION_MAX_TOKENS * 0.1))
    decline = _decline(page_number=2)
    parts, stats = plugin._extract_parts([_table_element(2)], None, None, "full text",
                                         tl_declines=[decline])

    assert [p["affected_mpn"] for p in parts] == PCN23_002_MPNS, \
        "every MPN, in order, including SYTX9-122HP-1+ LAST — the row a clipped crop used to drop"
    grid_cells = {cell for row in _grid() for cell in row}
    for p in parts:
        assert p["affected_mpn"] == p["affected_mpn_source"]
        assert p["affected_mpn"] in grid_cells
        assert p["replacement_mpn"] == p["replacement_mpn_source"]
        assert p["replacement_mpn"] in grid_cells

    assert fake.extract_parts_calls == 0, \
        "the pixel path must NOT run for a page the grid path already handled"
    assert stats["grid_forwarded"] == 1
    assert stats["grid_label_failed"] == 0
    assert stats["grid_rows_emitted"] == 18


def test_outcome_unchanged_whether_the_crop_image_is_absent_or_present_but_re_cut(monkeypatch):
    """A clipped/re-cut crop must not be able to cost a row any more — verified here by
    getting the IDENTICAL 18-part result whether no crop image exists at all, or one
    exists but is a deliberately re-cut (truncated) image blob. LabelGridColumns is
    stubbed either way, so the image's actual bytes are never inspected by this path —
    only the grid text is authoritative."""
    plugin = SustainmentPlugin(domain_type="sustainment")
    decline = _decline(page_number=2)

    # No image at all.
    _patch_b(monkeypatch, label_results=[_roles()])
    _patch_tokens(monkeypatch, round(VISION_MAX_TOKENS * 0.1))
    parts_no_image, _ = plugin._extract_parts([_table_element(2)], None, None, "full text",
                                              tl_declines=[decline])

    # A crop exists but is deliberately re-cut / truncated bytes.
    manifest = {"embedded_images": {"crop2.png": "s3://bucket/crop2.png"}}
    s3_client = SimpleNamespace(
        get_object=lambda Bucket, Key: {"Body": SimpleNamespace(read=lambda: b"\x89PNG-re-cut-garbage")}
    )
    _patch_b(monkeypatch, label_results=[_roles()])
    _patch_tokens(monkeypatch, round(VISION_MAX_TOKENS * 0.1))
    parts_recut_image, _ = plugin._extract_parts(
        [_table_element(2, image_path="crop2.png")], manifest, s3_client, "full text",
        tl_declines=[decline],
    )

    assert [p["affected_mpn"] for p in parts_no_image] == PCN23_002_MPNS
    assert [p["affected_mpn"] for p in parts_recut_image] == PCN23_002_MPNS
    assert parts_no_image == parts_recut_image


# --------------------------------------------------------------------------- #
# (4) DEGRADE, NEVER FAIL: a label call that raises falls back to the pixel path
# without losing the document and without the exception escaping.
# --------------------------------------------------------------------------- #
def test_label_call_raising_falls_back_to_pixel_path_without_raising(plugin, monkeypatch):
    fallback_part = SimpleNamespace(affected_mpn="PIXEL-READ-MPN", affected_mpn_source="PIXEL-READ-MPN",
                                    replacement_mpn=None, replacement_mpn_source=None,
                                    ltb_date=None, ltb_date_source=None)
    fake = _patch_b(monkeypatch, label_results=[RuntimeError("vision endpoint down")],
                    extract_parts_results=[[fallback_part]])
    _patch_tokens(monkeypatch, round(VISION_MAX_TOKENS * 0.1))
    decline = _decline(page_number=2)

    parts, stats = plugin._extract_parts([_table_element(2)], None, None, "full text",
                                         tl_declines=[decline])

    assert fake.extract_parts_calls == 1, "must fall through to the pixel path for this page"
    assert [p["affected_mpn"] for p in parts] == ["PIXEL-READ-MPN"]
    assert stats["grid_label_failed"] == 1
    assert stats["grid_forwarded"] == 0
    assert stats["grid_rows_emitted"] == 0


# --------------------------------------------------------------------------- #
# (5) An out-of-range affected_col is rejected and falls back rather than emitting
# garbage or raising.
# --------------------------------------------------------------------------- #
def test_out_of_range_affected_col_is_rejected_and_falls_back(plugin, monkeypatch):
    fallback_part = SimpleNamespace(affected_mpn="PIXEL-READ-MPN", affected_mpn_source="PIXEL-READ-MPN",
                                    replacement_mpn=None, replacement_mpn_source=None,
                                    ltb_date=None, ltb_date_source=None)
    bad_roles = _roles(affected_col=99)   # out of range for a 2-column grid
    fake = _patch_b(monkeypatch, label_results=[bad_roles],
                    extract_parts_results=[[fallback_part]])
    _patch_tokens(monkeypatch, round(VISION_MAX_TOKENS * 0.1))
    decline = _decline(page_number=2)

    parts, stats = plugin._extract_parts([_table_element(2)], None, None, "full text",
                                         tl_declines=[decline])

    assert fake.extract_parts_calls == 1
    assert [p["affected_mpn"] for p in parts] == ["PIXEL-READ-MPN"], \
        "no garbage row from the invalid column index; the page fell back cleanly"
    assert stats["grid_label_failed"] == 1
    assert stats["grid_forwarded"] == 0


# --------------------------------------------------------------------------- #
# (6) stats["text_layer_declines"] (persisted into extraction.json / review payload)
# must NOT carry `grid`; the list handed to tier 2 must.
# --------------------------------------------------------------------------- #
def test_persisted_text_layer_declines_omit_grid_but_extract_parts_receives_it(plugin, monkeypatch):
    decline = _decline(page_number=3)
    assert "grid" in decline

    monkeypatch.setattr(
        plugin, "_extract_parts_text_layer",
        lambda manifest, s3_client, bucket: ([], {"text_layer_pages": 1, "text_layer_parts": 0,
                                                  "text_layer_used": False,
                                                  "text_layer_declines": [decline]}),
    )
    monkeypatch.setattr(plugin, "_extract_header", lambda full_text: None)
    monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision")

    captured = {}

    def spy_extract_parts(tables, manifest, s3_client, full_text, tl_declines=None):
        captured["tl_declines"] = tl_declines
        return [], {"n_crops_used": 0, "crops_missing": 0, "crops_failed": 0,
                    "crops_truncated": 0, "crops_near_cap": 0, "crops_row_short": 0,
                    "row_short_detail": [], "grid_forwarded": 0, "grid_label_failed": 0,
                    "grid_rows_emitted": 0}

    monkeypatch.setattr(plugin, "_extract_parts", spy_extract_parts)

    nodes = plugin._extract_fulltext(
        "full text", "DOC1", metadata=None, elements=[_table_element(3)],
        manifest={"source_key": "notice.pdf"}, s3_client=object(), bucket="bucket",
    )

    stats = nodes[0].domain_augmentation.stats
    assert "text_layer_declines" in stats
    persisted = stats["text_layer_declines"][0]
    assert "grid" not in persisted, \
        "the grid must not ride into the persisted stats (extraction.json / review payload)"
    for k in ("page_number", "reason", "n_rows", "n_grid_rows"):
        assert persisted[k] == decline[k]

    # Tier 2 got the UNSTRIPPED, grid-bearing list.
    forwarded = captured["tl_declines"]
    assert forwarded is not None and forwarded[0].get("grid") == decline["grid"]


def test_grid_to_text_prints_every_index_the_model_is_asked_to_return():
    """The rendering contract: `cN` is a DATA column heading and `[row N]` is a row NAME.

    This is the one defect in grid forwarding that no behavioural test can reach, because
    every test stubs `LabelGridColumns` and so never sees the wording the model sees. The
    first version of `_grid_to_text` emitted a bare `str(i)` as the leading tab-separated
    field, which renders the row number as if it were column 0 — a model answering a
    0-based column index would then say `1` for the first data column, silently shifting
    `affected_col` onto the replacement column and mispairing every row while every
    assertion in this file still passed.

    So the guard has to be on the TEXT. What is pinned:
      * a heading line naming exactly `n_cols` data columns, `c0 … c{n-1}`;
      * `cN` resolving to `grid[i][N]` — the same DATA-relative convention that
        `row[affected_col]` uses in the emission loop;
      * row labels reading `[row N]`, with N the index `header_rows` expects;
      * no leading field that could be mistaken for a bare data-column index.
    """
    grid = [
        ["Affected Part", "Replacement", "LTB Date"],
        ["SYBDC-20-61WHP+", "SYBDC-20-61WHP-1+", "2023-12-31"],
        ["SYTX9-122HP-1+", None, ""],
    ]
    text = sustainment_module._grid_to_text(grid)
    lines = text.split("\n")

    # One heading line plus one line per grid row - the rendering adds no rows.
    assert len(lines) == 1 + len(grid)

    header = lines[0].split("\t")
    assert header[0] == "[row]", "the row-label column must be named, not left blank"
    assert header[1:] == ["c0", "c1", "c2"], \
        "data columns must be HEADED cN so the index is read off, never counted"

    # cN maps to grid[i][N]: the same data-relative convention as row[affected_col].
    for i, row in enumerate(grid):
        fields = lines[i + 1].split("\t")
        assert fields[0] == f"[row {i}]", \
            "rows must be labelled [row N] - a bare N reads as a data column"
        for j, cell in enumerate(row):
            assert fields[1 + j] == (cell or "").strip(), \
                f"c{j} of [row {i}] must be grid[{i}][{j}]"

    # The leading field of every line must not be parseable as a bare column index.
    for line in lines:
        first = line.split("\t")[0]
        assert not first.strip().lstrip("-").isdigit(), \
            f"leading field {first!r} could be read as a data column"


def test_grid_to_text_pads_ragged_rows_so_cN_stays_aligned():
    """A short row must be PADDED, not left short: pdfplumber emits ragged grids, and an
    unpadded row would slide its trailing cells left under the wrong `cN` heading — the
    same mispairing as the off-by-one above, one row at a time. `n_cols` is
    `max(len(r) ...)` in both `_grid_to_text` and `_extract_parts`, so the widest row sets
    the heading and every other row is padded to match it.
    """
    grid = [["a", "b", "c"], ["x"], ["p", "q"]]
    lines = sustainment_module._grid_to_text(grid).split("\n")

    assert lines[0].split("\t")[1:] == ["c0", "c1", "c2"]
    for line in lines[1:]:
        assert len(line.split("\t")) == 1 + 3, "every row must carry all n_cols fields"
    assert lines[2].split("\t") == ["[row 1]", "x", "", ""]
    assert lines[3].split("\t") == ["[row 2]", "p", "q", ""]




# --------------------------------------------------------------------------- #
# (9) A DECLINED TABLE: affected_col is null. Regression from the real corpus run.
# --------------------------------------------------------------------------- #
# Measured at pin sha256:0136991e (507013f): the corpus went 898/898 -> 897/898, and
# onsemi_Generic_IPCN25300X emitted '20kAlSiCu, 40kAlSi' -- a wire-bond material -- as an
# affected MPN. The label call's own reason said why: "'Before Change Description' in c3
# (affected state) and 'After Change Description' in c4". That table lists no parts at all.
#
# `affected_col` was a required int and the prompt said "always pick your best candidate",
# so the model could not answer correctly: a declined non-parts table could only ever
# produce a guess, and the grid then emitted whatever sat in the guessed column, verbatim
# and confidently. Same defect this feature was built to fix, one tier along -- tier 1
# could not say "declined" and returned [], so tier 2 could not say "no parts here" and
# returned a row.

# The real shape of the onsemi table, trimmed to what matters: no part number anywhere,
# c3/c4 are before/after descriptions of a wire-material change.
CHANGE_DESCRIPTION_GRID = [
    ["Item", "Change Type", "Category", "Before Change Description", "After Change Description"],
    ["", "", "", "", ""],
    ["1", "Assembly", "Wire", "20kAlSiCu, 40kAlSi", "20kAlSiCu, 40kAlSi, 50kAlSi"],
]


def _no_parts_decline(page_number=1):
    return {"page_number": page_number, "reason": "no column header, nothing to inherit",
            "n_rows": 3, "n_grid_rows": len(CHANGE_DESCRIPTION_GRID),
            "grid": CHANGE_DESCRIPTION_GRID}


def test_null_affected_col_emits_nothing_and_falls_back_to_the_pixel_path(plugin, monkeypatch):
    """A table with no parts column must cost a vision call, never a fabricated part."""
    declined = GridColumnRoles(
        affected_col=None, replacement_col=None, ltb_date_col=None, header_rows=[0, 1],
        reason="This table describes a wire-material change; no column holds part numbers.")
    fake = _patch_b(monkeypatch, label_results=[declined], extract_parts_results=[[]])
    _patch_tokens(monkeypatch, round(VISION_MAX_TOKENS * 0.1))

    parts, stats = plugin._extract_parts([_table_element(1)], None, None, "full text",
                                         tl_declines=[_no_parts_decline()])

    assert parts == [], \
        "a table with no parts column must emit NOTHING from the grid - not a guess"
    assert stats["grid_no_parts_col"] == 1, \
        "the decline is its own outcome, counted apart from a label FAILURE"
    assert stats["grid_forwarded"] == 0
    assert stats["grid_rows_emitted"] == 0
    # Recall-safe by design: the page still goes to the pixel path, which is what ran
    # before grid forwarding existed and what scored 898/898 -- and which returned [] on
    # this very table. A model wrongly declining a REAL parts table costs a vision call,
    # never a row.
    assert fake.extract_parts_calls == 1, \
        "the page must degrade to the pixel path, not be silently dropped"


def test_the_material_string_would_pass_looks_like_mpn_so_the_filter_is_not_the_guard():
    """`looks_like_mpn` is not the fix, and must not be mistaken for one.

    '20kAlSiCu, 40kAlSi' passes it -- one space, 18 characters, under `_is_prose_cell`'s
    3-space / 30-character thresholds. Tightening a predicate tier 1 uses EVERYWHERE, to
    catch one wire-bond alloy, trades this precision bug for a recall risk across all 898
    corpus parts. This test documents why that obvious fix was not taken; if it ever goes
    red, re-read _GRID_NO_PARTS_COL_NOTE before assuming the decline path is redundant.
    """
    assert text_layer.looks_like_mpn("20kAlSiCu, 40kAlSi")


def test_valid_grid_roles_accepts_null_affected_col_but_still_rejects_out_of_range():
    """Null is a decline, not an invalid label -- and the range check must survive it."""
    declined = GridColumnRoles(affected_col=None, replacement_col=None, ltb_date_col=None,
                               header_rows=[], reason="no parts column")
    assert sustainment_module._valid_grid_roles(declined, 5) is True

    out_of_range = GridColumnRoles(affected_col=9, replacement_col=None, ltb_date_col=None,
                                   header_rows=[], reason="guess")
    assert sustainment_module._valid_grid_roles(out_of_range, 5) is False

# --------------------------------------------------------------------------- #
# (12) The guard on the WORDING, which is where the 897/898 defect actually lived.
# --------------------------------------------------------------------------- #
def test_the_prompt_and_schema_both_authorize_declining_a_table():
    """The cause of 897/898 was WORDING, so the guard has to be on the wording.

    The schema said `affected_col int` (required) and the canonical prompt said "Always
    pick your best candidate, even if you are not fully certain." Between them the model
    was FORBIDDEN from answering correctly about a table that holds no part numbers -- it
    had to name a column, and every row of the column it named was emitted verbatim as a
    part. No stubbed test can see either string: `LabelGridColumns` is faked in every test
    in this file, so the two files the model actually reads are asserted directly.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    baml = (root / "baml_src" / "sustainment.baml").read_text(encoding="utf-8")
    prompt = (root / "prompts" / "sustainment_grid_columns_instructions.md").read_text(
        encoding="utf-8")

    assert "affected_col int?" in baml,         "affected_col must stay NULLABLE - a required int cannot express 'no parts column'"
    assert "affected_col as null" in baml,         "the BAML prompt block must tell the model null is an available answer"

    low = prompt.lower()
    assert "always pick your best candidate" not in low,         "the instruction that forced a guess on a non-parts table must not come back"
    assert "null only if" in low,         "the canonical prompt must state WHEN null is the right answer"
    assert "invents parts that do not exist" in low,         "the prompt must say what a wrong guess COSTS, not merely that null is allowed"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
