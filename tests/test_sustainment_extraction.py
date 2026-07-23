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
def test_dedup_parts_across_crops():
    parts = [
        {"affected_mpn": "A"}, {"affected_mpn": "B"}, {"affected_mpn": "A"},  # dup from continued page
        {"affected_mpn": ""}, {"affected_mpn": None},                          # dropped
    ]
    out = merge.dedup_parts(parts)
    assert [p["affected_mpn"] for p in out] == ["A", "B"]


def test_reconcile_ltb_applies_doc_level_fallback():
    parts = [{"affected_mpn": "A", "ltb_date": "2024-01-01"}, {"affected_mpn": "B", "ltb_date": None}]
    merge.reconcile_ltb(parts, "2025-12-31")
    assert parts[0]["ltb_date"] == "2024-01-01"  # per-row wins
    assert parts[1]["ltb_date"] == "2025-12-31"  # doc-level fallback


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
