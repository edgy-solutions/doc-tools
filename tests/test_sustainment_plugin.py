"""Pure-logic tests for the sustainment plugin's LLM/S3 orchestration — the counterpart
promised by test_sustainment_extraction.py's docstring, and written to cover the paths
that had NO test coverage at all before this: `crops_truncated` and `crops_near_cap`
appeared nowhere under tests/, and the crops_row_short detector (this same change) is new.

`b` is imported INSIDE `_extract_parts` via `from doc_tools.baml_client.sync_client import
b` (so BAML's config-driven client construction stays lazy), which means monkeypatching
the plugin module itself does nothing — the patch has to land on the attribute the
`from ... import` statement will resolve at call time, i.e. `sync_client.b`. `_FakeB`
stands in for it, one queued ExtractParts() result per crop, so a test can script exactly
what each crop "returns" without a real BAML client, S3 bucket, or LLM.

No network, no S3, no LLM: every element handed to `_extract_parts` here carries no
`image_path`, so `provenance.resolve_element_image` returns None and the crop takes the
OCR+HTML-only path that never touches `s3_client` — the tests pass `None` for it.
"""
from types import SimpleNamespace

import pytest

from doc_tools.baml_client import sync_client as sync_client_module
from doc_tools.plugins import sustainment as sustainment_module
from doc_tools.plugins.sustainment import (
    SustainmentPlugin, VISION_MAX_TOKENS, _has_part_shaped_text,
)


def _table_element(page_number):
    """A Table element with NO image_path — the OCR+HTML-only shape every test here
    exercises, so nothing ever tries to fetch a crop from S3."""
    return {"type": "Table", "text": "ocr text", "metadata": {"page_number": page_number,
                                                               "text_as_html": ""}}


def _part(mpn):
    """A duck-typed BAML ExtractedPart. sustainment_merge.part_to_dict reads these
    fields via getattr(obj, name, None), so a plain SimpleNamespace is enough — no BAML
    model class needed."""
    return SimpleNamespace(affected_mpn=mpn, affected_mpn_source=mpn,
                           replacement_mpn=None, replacement_mpn_source=None,
                           ltb_date=None, ltb_date_source=None)


class _FakeB:
    """Stand-in for doc_tools.baml_client.sync_client.b. Queues one ExtractParts()
    return value per crop, consumed in call order, so each test can script what the
    model "said" for that crop without a real round-trip."""

    def __init__(self, results):
        self._results = list(results)

    def ExtractParts(self, **kwargs):
        return self._results.pop(0)


@pytest.fixture(autouse=True)
def _prompt_from_file(monkeypatch):
    """Pin PROMPT_SOURCE=file for every test here. It is already the default, but
    `_extract_parts` resolves its system prompt through `_get_dynamic_prompt`, and under
    `PROMPT_SOURCE=langfuse` that reaches for a live Langfuse client before falling back
    to the committed file. These are pure-logic tests about token accounting and row
    counts; whether they pass must not depend on an environment variable set somewhere
    outside the repo.
    """
    monkeypatch.setenv("PROMPT_SOURCE", "file")


@pytest.fixture
def plugin():
    return SustainmentPlugin(domain_type="sustainment")


def _patch_b(monkeypatch, results):
    monkeypatch.setattr(sync_client_module, "b", _FakeB(results))


def _patch_tokens(monkeypatch, tokens):
    """Stub _vision_output_tokens (module-level in sustainment.py) so a test controls
    the truncation/near-cap decision directly, instead of needing a real Collector with
    real usage stats attached to it."""
    monkeypatch.setattr(sustainment_module, "_vision_output_tokens", lambda collector: tokens)


# --------------------------------------------------------------------------- #
# TRUNCATION. BAML fails OPEN on a response cut at VISION_MAX_TOKENS — it parses to
# whatever complete objects fit and raises nothing — so a truncated crop must be treated
# as a FAILURE, never a partial success, or "17 of 41 parts" reads as the whole table.
# --------------------------------------------------------------------------- #
def test_truncated_crop_is_a_failure_and_its_partial_rows_are_discarded(plugin, monkeypatch):
    _patch_b(monkeypatch, [[_part("A1"), _part("A2")]])   # rows the model DID manage to emit
    _patch_tokens(monkeypatch, VISION_MAX_TOKENS)         # output hit the bound exactly
    parts, stats = plugin._extract_parts([_table_element(1)], None, None, "full text")
    assert parts == [], "a truncated crop's partial rows must never be reported as complete"
    assert stats["crops_truncated"] == 1
    assert stats["crops_failed"] == 1, "crops_truncated is a SUBSET of crops_failed"


def test_near_cap_crop_completes_cleanly_and_keeps_its_parts(plugin, monkeypatch):
    """90% of the bound is short of truncation — the crop finished — but close enough to
    be an early warning that the NEXT document of this shape may not."""
    _patch_b(monkeypatch, [[_part("A1")]])
    _patch_tokens(monkeypatch, round(VISION_MAX_TOKENS * 0.9))
    parts, stats = plugin._extract_parts([_table_element(1)], None, None, "full text")
    assert [p["affected_mpn"] for p in parts] == ["A1"], "a near-cap crop is still a SUCCESS"
    assert stats["crops_near_cap"] == 1
    assert stats["crops_failed"] == 0


def test_comfortable_crop_trips_neither_truncation_nor_near_cap_counters(plugin, monkeypatch):
    _patch_b(monkeypatch, [[_part("A1")]])
    _patch_tokens(monkeypatch, round(VISION_MAX_TOKENS * 0.1))
    parts, stats = plugin._extract_parts([_table_element(1)], None, None, "full text")
    assert [p["affected_mpn"] for p in parts] == ["A1"]
    assert stats["crops_truncated"] == 0
    assert stats["crops_near_cap"] == 0
    assert stats["crops_failed"] == 0


# --------------------------------------------------------------------------- #
# ROW-SHORT. The silent class none of the counters above could ever catch: a crop that
# raised nothing, was not truncated, and still came back with FEWER rows than pdfplumber
# counted on the SAME page — the SYTX9-122HP-1+ shape on PCN23-002 (last row of the
# table, immediately above the page footer, dropped with needs_review=False and nothing
# in crops_failed or crops_truncated to say so).
# --------------------------------------------------------------------------- #
def test_a_completed_crop_short_of_tier_1s_row_count_is_flagged(plugin, monkeypatch):
    seventeen = [_part(f"MPN{i}") for i in range(17)]
    _patch_b(monkeypatch, [seventeen])
    _patch_tokens(monkeypatch, round(VISION_MAX_TOKENS * 0.1))     # comfortable — a clean success
    decline = {"page_number": 2, "reason": "no column header, nothing to inherit, and no "
                                           "caption naming the contents",
              "n_rows": 18, "n_grid_rows": 18}
    parts, stats = plugin._extract_parts([_table_element(2)], None, None, "full text",
                                         tl_declines=[decline])
    assert len(parts) == 17, "the 17 rows the crop DID return are kept — this is not a failure"
    assert stats["crops_row_short"] == 1
    assert stats["row_short_detail"] == [
        {"page_number": 2, "tier1_rows": 18, "vision_rows": 17, "n_declines": 1}
    ], stats["row_short_detail"]


def test_multiple_declines_on_one_page_produce_at_most_one_finding(plugin, monkeypatch):
    """`tl_declines` has one entry per declined TABLE, but `rows_by_page` is a PAGE total.
    Three declines on one page must not produce three findings against the same page
    total — measured 2026-09-23 on onsemi_Generic_IPCN25300X page 2 (2 of its 3 false
    positives were exactly this). The finding takes the MAX across the page's declines,
    not the sum."""
    sixteen = [_part(f"MPN{i}") for i in range(16)]
    _patch_b(monkeypatch, [sixteen])
    _patch_tokens(monkeypatch, round(VISION_MAX_TOKENS * 0.1))
    declines = [
        {"page_number": 2, "reason": "declined", "n_rows": 18, "n_grid_rows": 18},
        {"page_number": 2, "reason": "declined", "n_rows": 20, "n_grid_rows": 20},
        {"page_number": 2, "reason": "declined", "n_rows": 6, "n_grid_rows": 6},
    ]
    parts, stats = plugin._extract_parts([_table_element(2)], None, None, "full text",
                                         tl_declines=declines)
    assert stats["crops_row_short"] == 1, "3 declines on one page -> at most one finding"
    assert stats["row_short_detail"] == [
        {"page_number": 2, "tier1_rows": 20, "vision_rows": 16, "n_declines": 3}
    ], stats["row_short_detail"]


def test_declines_below_the_baseline_floor_produce_no_finding(plugin, monkeypatch):
    """A decline's column-blind row count is not confident evidence below the floor
    (measured: onsemi_Generic_IPCN25300X's false positives were n_rows 1 and 4) — see
    MIN_ROW_SHORT_BASELINE."""
    _patch_b(monkeypatch, [[_part("A1")]])
    _patch_tokens(monkeypatch, round(VISION_MAX_TOKENS * 0.1))
    declines = [{"page_number": 1, "reason": "declined", "n_rows": 1, "n_grid_rows": 1}]
    parts, stats = plugin._extract_parts([_table_element(1)], None, None, "full text",
                                         tl_declines=declines)
    assert stats["crops_row_short"] == 0
    assert stats["row_short_detail"] == []


def test_a_truncated_page_is_not_ALSO_double_flagged_row_short(plugin, monkeypatch):
    """A page whose crop already failed/truncated is covered by the PARTS MAY BE MISSING
    banner; row_short exists to name the OTHER class (completed, no error, still short),
    so a page already known bad for a louder reason must not be counted here too."""
    _patch_b(monkeypatch, [[_part(f"MPN{i}") for i in range(5)]])
    _patch_tokens(monkeypatch, VISION_MAX_TOKENS)   # this page's crop TRUNCATES
    decline = {"page_number": 2, "reason": "declined", "n_rows": 18, "n_grid_rows": 18}
    parts, stats = plugin._extract_parts([_table_element(2)], None, None, "full text",
                                         tl_declines=[decline])
    assert parts == [], "the truncated crop's rows are discarded as usual"
    assert stats["crops_truncated"] == 1
    assert stats["crops_row_short"] == 0, "already covered by crops_failed/crops_truncated"


# --------------------------------------------------------------------------- #
# THE PCN24-029 ROUTER GATE. A single MPN under "MODELS AFFECTED" with no table at all —
# unstructured detects zero Table elements, so this text-level gate is what routes the
# document to vision instead of silently taking the header-only path. Deliberately TIGHT:
# a vision call costs ~100s on the deployed endpoint, so both a label AND an MPN-shaped
# token are required, not either alone.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("full_text,expected", [
    ("MODELS AFFECTED\nTC4-1TX+", True),
    # an MPN-shaped token in prose that never NAMES an affected-parts section — the
    # common case (a revision string, a document number) that must not cost a vision call
    ("Revision history: part TC4-1TX+ was updated on 2024-01-01.", False),
    # the label, but nothing MPN-shaped follows it — nothing to route to vision for
    ("MODELS AFFECTED\nsee your sales representative", False),
    # THE REGRESSION THIS GUARDS: `looks_like_mpn` alone is satisfied by "contains a
    # digit", so a bare year clears it and every notice that merely mentions affected
    # parts in prose would buy a ~100s vision call. The gate requires a letter AND a
    # digit in the same token for exactly this case.
    ("AFFECTED PARTS\nEffective 2026 for all shipments.", False),
])
def test_has_part_shaped_text_requires_both_a_label_and_an_mpn_shaped_token(full_text, expected):
    assert _has_part_shaped_text(full_text) is expected


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
