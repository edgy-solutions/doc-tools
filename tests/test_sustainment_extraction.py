"""Pure-logic tests for the sustainment two-pass extractor (no LLM, no S3).

Covers provenance resolution, doc_type normalization, ltb reconciliation,
multi-crop dedup, and review-item assembly — the logic that decides the demo's
correctness. The plugin's LLM/S3 orchestration is tested separately
(test_sustainment_plugin.py, with the BAML + S3 calls mocked).
"""
from types import SimpleNamespace

from doc_tools.utils import provenance
from doc_tools.utils import sustainment_normalize as norm
from doc_tools.utils import sustainment_merge as merge


# --------------------------------------------------------------------------- #
# doc_type normalization + field reconcile
# --------------------------------------------------------------------------- #
def test_normalize_doc_type_maps_vendor_labels():
    assert norm.normalize_doc_type("PCN") == "PCN"
    assert norm.normalize_doc_type("PDN") == "PDN"
    assert norm.normalize_doc_type("Product Obsolescence Notification") == "PDN"
    assert norm.normalize_doc_type("PTN") == "PDN"
    assert norm.normalize_doc_type("End of Life") == "PDN"
    assert norm.normalize_doc_type("Product/Process Change Notification") == "PCN"
    assert norm.normalize_doc_type("process change") == "PCN"
    assert norm.normalize_doc_type(SimpleNamespace(value="PDN")) == "PDN"  # enum-like
    assert norm.normalize_doc_type("mystery notice") == "PCN"             # conservative default
    assert norm.is_known_doc_type("PTN") is True
    assert norm.is_known_doc_type("mystery notice") is False


def test_effective_ltb_prefers_per_row():
    assert norm.effective_ltb("2024-12-05", "2025-01-01") == "2024-12-05"
    assert norm.effective_ltb(None, "2025-01-01") == "2025-01-01"
    assert norm.effective_ltb("", "2025-01-01") == "2025-01-01"
    assert norm.effective_ltb(None, None) is None


def test_summary_stated_count():
    assert norm.summary_stated_count("~300 LTC parts affected") == 300
    assert norm.summary_stated_count("19 Schottky/diode devices") == 19
    assert norm.summary_stated_count("affecting 3,521 products") == 3521
    assert norm.summary_stated_count("no numbers here") is None


# --------------------------------------------------------------------------- #
# element -> cropped image join
# --------------------------------------------------------------------------- #
def test_resolve_element_image_join_by_basename():
    el = {"type": "Table", "metadata": {"image_path": "/tmp/xyz/table-3-2.jpg"}}
    embedded = {"table-3-2.jpg": "s3://b/sustainment/x/generated/f/images/table-3-2.jpg"}
    assert provenance.resolve_element_image(el, embedded).endswith("table-3-2.jpg")
    assert provenance.resolve_element_image({"metadata": {}}, embedded) is None
    assert provenance.resolve_element_image(el, {}) is None


# --------------------------------------------------------------------------- #
# positioned index + value -> location
# --------------------------------------------------------------------------- #
def _el(t, text, page, pts, html=""):
    return {"type": t, "text": text,
            "metadata": {"page_number": page,
                         "coordinates": {"points": pts, "layout_width": 612, "layout_height": 792},
                         "text_as_html": html}}


def test_build_positioned_index_and_resolve_value():
    els = [
        _el("NarrativeText", "Last Time Buy: 2024-12-05 applies to all.", 1,
            [[10, 10], [300, 10], [300, 30], [10, 30]]),
        _el("Table", "AD7873ACPZ  AD7873ARUZ", 2, [[20, 100], [400, 100], [400, 300], [20, 300]],
            html="<table><tr><td>AD7873ACPZ</td><td>AD7873ARUZ</td></tr></table>"),
    ]
    idx = provenance.build_positioned_index(els)
    assert idx[0]["bbox"] == [10, 10, 300, 30]
    assert idx[0]["page_width"] == 612

    r = provenance.resolve_value("2024-12-05", idx, prefer_region="narrative")
    assert r["found"] and r["page_number"] == 1 and r["match_method"] == "unique"
    assert r["bboxes"] == [[10, 10, 300, 30]] and r["page_dims"] == {"width": 612, "height": 792}

    r2 = provenance.resolve_value("AD7873ACPZ", idx, prefer_region="table")  # from text_as_html
    assert r2["found"] and r2["page_number"] == 2

    r3 = provenance.resolve_value("NONEXISTENT-MPN", idx)  # hallucination signal
    assert not r3["found"] and r3["match_method"] == "not_found"


def test_resolve_value_region_preference_on_ambiguous():
    els = [
        _el("NarrativeText", "part AD7873ACPZ mentioned in prose", 1, [[0, 0], [1, 0], [1, 1], [0, 1]]),
        _el("Table", "AD7873ACPZ row", 2, [[0, 0], [1, 0], [1, 1], [0, 1]]),
    ]
    idx = provenance.build_positioned_index(els)
    r = provenance.resolve_value("AD7873ACPZ", idx, prefer_region="table")
    assert r["found"] and r["match_method"] == "region_preferred" and r["page_number"] == 2


# --------------------------------------------------------------------------- #
# dedup + reconcile
# --------------------------------------------------------------------------- #
def test_dequote_parts_strips_delimiters_but_not_provenance():
    """A notice that prints its part numbers in quotes yields '"090-44310-31"'. The quote
    is a delimiter, never a character of the MPN — but downstream it is treated as one and
    every graph MERGE and join silently misses. The *_source snippets keep their quotes:
    they are provenance and must still match the document character-for-character."""
    parts = [
        {"affected_mpn": '"090-44310-31"', "affected_mpn_source": '"090-44310-31"',
         "replacement_mpn": '"090-44310-32"', "replacement_mpn_source": '"090-44310-32"'},
        {"affected_mpn": "LTC6226HDC#TRMPBF", "replacement_mpn": None},
    ]
    assert merge.dequote_parts(parts) == 2, "two VALUES changed, not the sources"
    assert parts[0]["affected_mpn"] == "090-44310-31"
    assert parts[0]["replacement_mpn"] == "090-44310-32"
    assert parts[0]["affected_mpn_source"] == '"090-44310-31"', "provenance must stay verbatim"
    assert parts[0]["replacement_mpn_source"] == '"090-44310-32"'
    assert parts[1]["affected_mpn"] == "LTC6226HDC#TRMPBF", "untouched when there is no quote"


def test_dequote_runs_before_dedup_so_quoted_twins_collapse():
    """Order matters: de-quoting AFTER dedup would leave '"A"' and 'A' as two separate
    parts — the same part counted twice on the review card."""
    parts = [{"affected_mpn": '"A1"'}, {"affected_mpn": "A1"}]
    merge.dequote_parts(parts)
    assert [p["affected_mpn"] for p in merge.dedup_parts(parts)] == ["A1"]


def test_dedup_parts_across_crops():
    parts = [
        {"affected_mpn": "A"}, {"affected_mpn": "B"}, {"affected_mpn": "A"},  # dup from continued page
        {"affected_mpn": ""}, {"affected_mpn": None},                          # dropped
    ]
    out = merge.dedup_parts(parts)
    assert [p["affected_mpn"] for p in out] == ["A", "B"]


def test_dedup_parts_counts_duplicates_only():
    parts = [
        {"affected_mpn": "A"}, {"affected_mpn": "B"}, {"affected_mpn": "A"}, {"affected_mpn": "A"},
    ]
    counts = {}
    out = merge.dedup_parts(parts, counts=counts)
    assert [p["affected_mpn"] for p in out] == ["A", "B"]
    assert counts == {"duplicate": 2, "no_mpn": 0}


def test_dedup_parts_counts_no_mpn_only():
    parts = [
        {"affected_mpn": "A"}, {"affected_mpn": ""}, {"affected_mpn": None}, {"affected_mpn": "   "},
    ]
    counts = {}
    out = merge.dedup_parts(parts, counts=counts)
    assert [p["affected_mpn"] for p in out] == ["A"]
    assert counts == {"duplicate": 0, "no_mpn": 3}


def test_dedup_parts_counts_duplicate_and_no_mpn_independently():
    parts = [
        {"affected_mpn": "A"}, {"affected_mpn": "A"}, {"affected_mpn": ""},
        {"affected_mpn": "B"}, {"affected_mpn": None}, {"affected_mpn": "A"},
    ]
    counts = {}
    out = merge.dedup_parts(parts, counts=counts)
    assert [p["affected_mpn"] for p in out] == ["A", "B"]
    assert counts == {"duplicate": 2, "no_mpn": 2}


def test_dedup_parts_counts_zero_when_nothing_to_collapse():
    parts = [{"affected_mpn": "A"}, {"affected_mpn": "B"}, {"affected_mpn": "C"}]
    counts = {}
    out = merge.dedup_parts(parts, counts=counts)
    assert [p["affected_mpn"] for p in out] == ["A", "B", "C"]
    assert counts == {"duplicate": 0, "no_mpn": 0}


def test_dedup_parts_without_counts_arg_is_unaffected():
    parts = [
        {"affected_mpn": "A"}, {"affected_mpn": "B"}, {"affected_mpn": "A"},
        {"affected_mpn": ""}, {"affected_mpn": None},
    ]
    out = merge.dedup_parts(parts)
    assert [p["affected_mpn"] for p in out] == ["A", "B"]


def test_dedup_parts_returns_same_list_whether_or_not_counts_passed():
    base = [
        {"affected_mpn": "A"}, {"affected_mpn": "B"}, {"affected_mpn": "A"},
        {"affected_mpn": ""}, {"affected_mpn": None},
    ]
    import copy
    without = merge.dedup_parts(copy.deepcopy(base))
    with_counts = merge.dedup_parts(copy.deepcopy(base), counts={})
    assert without == with_counts


def test_reconcile_ltb_applies_doc_level_fallback():
    parts = [{"affected_mpn": "A", "ltb_date": "2024-01-01"}, {"affected_mpn": "B", "ltb_date": None}]
    merge.reconcile_ltb(parts, "2025-12-31")
    assert parts[0]["ltb_date"] == "2024-01-01"  # per-row wins
    assert parts[1]["ltb_date"] == "2025-12-31"  # doc-level fallback


def test_reconcile_ltb_records_whether_the_date_was_inherited():
    """The flag is the whole point: after the backfill, `ltb_date` looks identical
    whether the row printed it or inherited it, and `ltb_date_source` is None in
    both cases. Without a marker the review builder cannot tell them apart."""
    parts = [
        {"affected_mpn": "A", "ltb_date": "2024-01-01"},
        {"affected_mpn": "B", "ltb_date": None},
        {"affected_mpn": "C", "ltb_date": "   "},   # whitespace is not a date
        {"affected_mpn": "D", "ltb_date": None},
    ]
    merge.reconcile_ltb(parts[:3], "2025-12-31")
    merge.reconcile_ltb(parts[3:], None)            # no doc-level date either
    assert parts[0]["ltb_date"] == "2024-01-01" and parts[0]["ltb_date_inherited"] is False
    assert parts[1]["ltb_date"] == "2025-12-31" and parts[1]["ltb_date_inherited"] is True
    assert parts[2]["ltb_date"] == "2025-12-31" and parts[2]["ltb_date_inherited"] is True
    # No date at all is NOT "inherited" — there is nothing to point at.
    assert parts[3]["ltb_date"] is None and parts[3]["ltb_date_inherited"] is False


def test_an_inherited_ltb_date_carries_the_header_sentence_as_its_evidence():
    """MEASURED defect, 965 of 965 `parts[].ltb_date` items on the 88 deployed
    review.json had no bbox at all. The row prints no date; the document states it
    once in prose. The honest evidence is that sentence, labelled as inherited."""
    els = [
        _el("Table", "AD7873ACPZ", 2, [[0, 0], [1, 0], [1, 1], [0, 1]],
            html="<table><tr><td>AD7873ACPZ</td></tr></table>"),
        _el("NarrativeText", "Last time buy is June 6, 2024 for all affected devices.",
            5, [[0, 2], [1, 2], [1, 3], [0, 3]]),
    ]
    idx = provenance.build_positioned_index(els)
    ocr_norm = provenance._norm("AD7873ACPZ Last time buy is June 6, 2024 for all affected devices.")
    header = {"doc_level_ltb_date": "2024-06-06", "doc_level_ltb_date_source": "June 6, 2024"}
    parts = [{"affected_mpn": "AD7873ACPZ", "affected_mpn_source": "AD7873ACPZ"}]
    merge.reconcile_ltb(parts, header["doc_level_ltb_date"])
    items, _reasons = merge.build_review_items(header, parts, idx, ocr_norm)
    by_fp = {it["field_path"]: it for it in items}

    ltb = by_fp["parts[0].ltb_date"]
    assert ltb["value"] == "2024-06-06"
    assert ltb["page_number"] == 5, "evidence is the prose page, not the table page"
    assert ltb["bboxes"], "an inherited date must still carry a bbox"
    assert ltb["match_method"] == "inherited_doc_level", (
        "an inherited bbox must be DISTINGUISHABLE from a cell this row owns")
    assert ltb["source_snippet"] == "June 6, 2024", "the verbatim sentence, not the ISO value"
    # and it agrees with the header item it borrowed from
    assert ltb["bboxes"] == by_fp["header.doc_level_ltb_date"]["bboxes"]


def test_an_unlocatable_doc_level_date_lends_no_evidence_to_the_rows():
    """If the header date itself did not resolve, there is no sentence to point at.
    Rows must then report not_found rather than borrow an empty box and look sourced."""
    els = [_el("Table", "AD7873ACPZ", 2, [[0, 0], [1, 0], [1, 1], [0, 1]],
               html="<table><tr><td>AD7873ACPZ</td></tr></table>")]
    idx = provenance.build_positioned_index(els)
    header = {"doc_level_ltb_date": "2024-06-06", "doc_level_ltb_date_source": "not in this doc"}
    parts = [{"affected_mpn": "AD7873ACPZ", "affected_mpn_source": "AD7873ACPZ"}]
    merge.reconcile_ltb(parts, header["doc_level_ltb_date"])
    items, _ = merge.build_review_items(header, parts, idx, provenance._norm("AD7873ACPZ"))
    ltb = {it["field_path"]: it for it in items}["parts[0].ltb_date"]
    assert ltb["match_method"] == "not_found" and ltb["bboxes"] == []


def test_a_row_ltb_date_is_resolved_on_its_source_never_on_the_iso_value():
    """A bare ISO date can match an unrelated occurrence and outline the wrong
    thing, so the value is never used as a search key. The row's own source is."""
    els = [
        _el("Table", "AD7873ACPZ 06-Jun-2024", 3, [[0, 0], [1, 0], [1, 1], [0, 1]],
            html="<table><tr><td>AD7873ACPZ</td><td>06-Jun-2024</td></tr></table>"),
        # an unrelated ISO date elsewhere: the trap the value-fallback walked into
        _el("NarrativeText", "Document issued 2024-06-06 by the PCN desk.", 9,
            [[0, 5], [1, 5], [1, 6], [0, 6]]),
    ]
    idx = provenance.build_positioned_index(els)
    ocr_norm = provenance._norm("AD7873ACPZ 06-Jun-2024 Document issued 2024-06-06 by the PCN desk.")
    header = {"doc_level_ltb_date": None}
    sourced = [{"affected_mpn": "AD7873ACPZ", "affected_mpn_source": "AD7873ACPZ",
                "ltb_date": "2024-06-06", "ltb_date_source": "06-Jun-2024"}]
    merge.reconcile_ltb(sourced, None)
    items, _ = merge.build_review_items(header, sourced, idx, ocr_norm)
    ltb = {it["field_path"]: it for it in items}["parts[0].ltb_date"]
    assert ltb["page_number"] == 3, "resolved to the row's own cell, not the prose ISO date"
    assert ltb["match_method"] != "inherited_doc_level"

    # same value, NO source, no doc-level date: not_found, and NOT a match on page 9
    unsourced = [{"affected_mpn": "AD7873ACPZ", "affected_mpn_source": "AD7873ACPZ",
                  "ltb_date": "2024-06-06", "ltb_date_source": None}]
    merge.reconcile_ltb(unsourced, None)
    items2, _ = merge.build_review_items(header, unsourced, idx, ocr_norm)
    ltb2 = {it["field_path"]: it for it in items2}["parts[0].ltb_date"]
    assert ltb2["page_number"] is None and ltb2["bboxes"] == [], (
        "the ISO value must not be used as a search key: page 9 is an unrelated date")
    assert ltb2["source_snippet"] is None


def test_clean_replacement_drops_qualification_vehicle_lists():
    # single replacement kept; comma-separated list (qual vehicles) dropped
    assert norm.clean_replacement("AD7873ARUZ") == "AD7873ARUZ"
    assert norm.clean_replacement("SNSR01F30NXT5G, NSR20F40NXT5G") is None
    assert norm.clean_replacement("") is None and norm.clean_replacement(None) is None
    parts = [{"affected_mpn": "X", "replacement_mpn": "A, B", "replacement_mpn_source": "A, B"},
             {"affected_mpn": "Y", "replacement_mpn": "Z"}]
    merge.clean_replacements(parts)
    assert parts[0]["replacement_mpn"] is None and parts[0]["replacement_mpn_source"] is None
    assert parts[1]["replacement_mpn"] == "Z"


# --------------------------------------------------------------------------- #
# review items (provenance + needs_review flags)
# --------------------------------------------------------------------------- #
def test_build_review_items_flags_and_provenance():
    els = [_el("Table", "AD7873ACPZ AD7873ARUZ", 2, [[0, 0], [1, 0], [1, 1], [0, 1]],
               html="<table><tr><td>AD7873ACPZ</td></tr></table>")]
    idx = provenance.build_positioned_index(els)
    ocr_norm = provenance._norm("AD7873ACPZ AD7873ARUZ")
    header = {"pub_date": "2023-12-05", "pub_date_source": "05-Dec-2023", "mfr": "ADI",
              "mfr_source": None, "doc_level_ltb_date": None, "summary": "one device",
              "categories": ["Discontinuation"]}
    parts = [
        {"affected_mpn": "AD7873ACPZ", "affected_mpn_source": "AD7873ACPZ"},        # ok
        {"affected_mpn": "HALLUCINATED", "affected_mpn_source": "HALLUCINATED"},    # not in ocr
    ]
    items, reasons = merge.build_review_items(header, parts, idx, ocr_norm)
    by_fp = {it["field_path"]: it for it in items}

    assert by_fp["parts[0].affected_mpn"]["needs_review"] is False
    assert by_fp["parts[0].affected_mpn"]["page_number"] == 2
    assert by_fp["parts[1].affected_mpn"]["needs_review"] is True
    assert "not found verbatim" in by_fp["parts[1].affected_mpn"]["review_reason"]
    # pub_date_source '05-Dec-2023' not present in the table-only index -> flagged
    assert by_fp["header.pub_date"]["needs_review"] is True
    # derived summary: present, region derived, no bbox
    assert by_fp["header.summary"]["region"] == "derived" and by_fp["header.summary"]["bboxes"] == []
    assert any("parts[1]" in r for r in reasons)


def test_validate_count_mismatch():
    assert merge.validate_count({"summary": "~19 devices"}, 19) is None
    assert "implies" in merge.validate_count({"summary": "~19 devices"}, 12)


# --------------------------------------------------------------------------- #
# The 2026-10-21 page-fractions ruling, on the REVIEW ROWS
# --------------------------------------------------------------------------- #
def test_a_review_items_bbox_is_page_fractions_and_page_dims_IS_GONE():
    """ARCHITECT RULING 2026-10-21: page fractions, *"the same everywhere
    evidence_ref appears"*. Lane 1 lifted the hold on the rows once cortex a3cf4d1
    went live in 204.

    The dropped `page_dims` is the load-bearing half. Cortex reads its PRESENCE as
    "this box is in pixels": a fraction beside a stale 612x792 would be divided
    again and drawn as a speck in the page corner, with no error and nothing to
    distinguish it from a real tiny box there. So converting the box while keeping
    the dims is worse than converting nothing.
    """
    els = [_el("NarrativeText", "Last Time Buy: 2024-12-05 applies to all.", 1,
               [[61.2, 79.2], [550.8, 79.2], [550.8, 158.4], [61.2, 158.4]])]
    idx = provenance.build_positioned_index(els)
    ocr_norm = provenance._norm("Last Time Buy: 2024-12-05 applies to all.")
    items, _r = merge.build_review_items(
        {"doc_level_ltb_date": "2024-12-05",
         "doc_level_ltb_date_source": "Last Time Buy: 2024-12-05"},
        [], idx, ocr_norm)
    it = {i["field_path"]: i for i in items}["header.doc_level_ltb_date"]

    assert "page_dims" not in it, "the key is OMITTED, not nulled: cortex reads its presence"
    # 61.2/612 = 0.1, 79.2/792 = 0.1, 550.8/612 = 0.9, 158.4/792 = 0.2
    assert it["bboxes"] == [[0.1, 0.1, 0.9, 0.2]]
    for box in it["bboxes"]:
        assert all(0.0 <= v <= 1.0 for v in box), "a fraction is self-describing"
    assert it["page_number"] == 1, "the page is untouched: only the box changed units"


def test_a_row_box_with_no_dims_yields_NO_box_rather_than_a_bare_pixel_box():
    """With `page_dims` gone there is no divisor on either side, so a pixel box left
    behind would read as a wildly out-of-range fraction and flag the row unreadable.
    It was already unusable before the conversion — cortex's pixel form needs
    `page_dims` to scale — so dropping it loses nothing that worked.
    """
    assert merge._row_fractions(
        {"bboxes": [[10, 10, 300, 30]], "page_dims": None}) == []
    assert merge._row_fractions(
        {"bboxes": [[10, 10, 300, 30]]}) == []
    # A degenerate box goes the same way, and for the reason the leaf does it: cortex
    # requires x0 < x1 strictly and drops what it cannot read.
    assert merge._row_fractions(
        {"bboxes": [[700, 100, 800, 200]], "page_dims": {"width": 612, "height": 792}}) == []
    # And a good box among a bad one survives on its own.
    assert merge._row_fractions(
        {"bboxes": [[700, 100, 800, 200], [61.2, 79.2, 550.8, 158.4]],
         "page_dims": {"width": 612, "height": 792}}) == [[0.1, 0.1, 0.9, 0.2]]
