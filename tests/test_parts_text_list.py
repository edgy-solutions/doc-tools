"""Unit tests for doc_tools/utils/parts_text_list.py (pure; no network, no vision)."""
import pytest

from doc_tools.utils import parts_text_list as ptl
from doc_tools.plugins.sustainment import _text_list_pages

LEGACY_LABELS = ("models affected", "affected models", "affected parts",
                 "parts affected", "affected part numbers", "affected devices",
                 "affected model", "model affected")

TIER1_KEYS = {"affected_mpn", "affected_mpn_source", "replacement_mpn",
              "replacement_mpn_source", "ltb_date", "ltb_date_source",
              "text_layer_bbox", "text_layer_replacement_bbox",
              "text_layer_page", "text_layer_page_dims"}

PAIRS_TEXT = ("AD7400 / AD7400ARZ ADA4000 / ADA4000-1ARZ LT1001 / LT1001ACN8\n"
              "AD8221 / AD8221ARMZ ADG704 / ADG704BRMZ LTC2050 / LTC2050HS6\n")


@pytest.mark.parametrize("label", LEGACY_LABELS)
def test_legacy_labels_still_match(label):
    assert ptl.AFFECTED_HEADING_RE.search(label)
    assert ptl.names_affected_section(label)


def test_affected_adi_models_matches():
    assert ptl.names_affected_section("Appendix A - Affected ADI Models:")


def test_long_run_between_affected_and_parts_does_not_match():
    assert not ptl.names_affected_section(
        "The customers affected by this change should review the attached parts list")


def test_caption_count():
    cap = "Added Parts On This Revision - Product Family / Model Number (1,577)"
    assert ptl.caption_part_count(cap) == 1577
    assert ptl.caption_part_count("Total revenue for the year (1,577)") is None
    assert ptl.caption_part_count("See parts note (1)") is None


def test_parse_family_model_six_pairs():
    rows = ptl.parse_family_model(PAIRS_TEXT, page_number=3)
    assert len(rows) == 6
    assert rows[0]["affected_mpn"] == "AD7400ARZ"
    assert rows[0]["text_layer_page"] == 3
    for r in rows:
        assert set(r) == TIER1_KEYS
        assert r["affected_mpn_source"] == r["affected_mpn"]


def test_date_and_year_are_not_pairs():
    assert ptl.parse_family_model("Effective Jan / 2026 and Process / 2026-10-23") == []


def test_salvage_declines_single_pair_and_unadvertised_text():
    rows, stats = ptl.salvage([(1, "Affected Models: AD7400 / AD7400ARZ")])
    assert rows == [] and stats["text_list_parts"] == 0
    rows, stats = ptl.salvage([(1, PAIRS_TEXT)])  # nothing advertises a parts list
    assert rows == []


def test_salvage_happy_path_and_stats_keys():
    rows, stats = ptl.salvage([(2, "Affected ADI Models\n" + PAIRS_TEXT)])
    assert len(rows) == 6
    assert set(stats) == {"text_list_parts", "text_list_caption_count", "text_list_pages",
                          "text_list_shortfall", "text_list_shortfall_detail"}
    assert stats["text_list_pages"] == 1


def _salvage_against(n_rows, caption):
    pairs = " ".join(f"FAM{i} / MOD{i:05d}X" for i in range(n_rows))
    text = f"Affected ADI Models\nProduct Family / Model Number ({caption:,})\n{pairs}"
    return ptl.salvage([(1, text)])


def test_shortfall_tolerance():
    rows, stats = _salvage_against(1575, 1577)
    assert len(rows) == 1575 and stats["text_list_shortfall"] is False
    rows, stats = _salvage_against(900, 1577)
    assert stats["text_list_shortfall"] is True
    assert "900" in stats["text_list_shortfall_detail"]
    rows, stats = _salvage_against(1600, 1577)
    assert stats["text_list_shortfall"] is False


def test_text_list_pages_falls_back_without_source():
    assert _text_list_pages({}, None, None, "abc") == [(None, "abc")]
    assert _text_list_pages(None, object(), "b", "abc") == [(None, "abc")]
