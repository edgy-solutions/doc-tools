"""Tests for `doc_tools.utils.ltb_candidates` and its wiring into
`SustainmentPlugin._extract_header`.

BACKGROUND. `doc_level_ltb_date` is intermittently missed by the header model: three
production fires of `Diodes_PCN_2683_Rev1_EOL.pdf` on the SAME document read
`None | None | '2024-12-22'`, even though the notice prints the date once, plainly, next
to the phrase "last order date". Asking a sampled model to both FIND a date substring
and NORMALIZE it is two jobs; `ltb_candidates` does the finding deterministically from
the text layer so the model's only job is to CHOOSE from a short list, or say null.

`tests/fixtures/sustainment/diodes_rev1_eol_text.txt` is the real page text of that
notice, copied verbatim out of a production fire log -- read, not rewritten.

A SECOND DEFECT, caught in review before this ever shipped: the Diodes sentence states a
last-ORDER date and a last-SHIP date one sentence apart, and only one phrase in it
("life-time buy") is close enough to qualify BOTH dates -- so attributing each candidate
to the first-starting qualifying phrase rendered both candidates under the identical
"near phrase: life-time buy" line, with the model given no structured way to tell them
apart. `test_diodes_fixture_the_two_dates_are_distinguishable` below is the test that
would have caught it: it pins `governing` (the text immediately before each date, which
IS where "last order date" vs "last ship date" lives) and the now-nearest-not-first
`phrase`.
"""
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from doc_tools.utils.ltb_candidates import ltb_candidates, render_candidate_block

_FIXTURE_PATH = (Path(__file__).parent / "fixtures" / "sustainment"
                 / "diodes_rev1_eol_text.txt")


@pytest.fixture(scope="module")
def diodes_text():
    return _FIXTURE_PATH.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1. THE SEAL -- the defect this module exists to fix.
# --------------------------------------------------------------------------- #

def test_diodes_fixture_yields_the_last_order_date(diodes_text):
    cands = ltb_candidates(diodes_text)
    assert cands, "expected at least one candidate from the Diodes fixture"

    isos = [c.iso for c in cands]
    assert "2024-12-22" in isos

    match = next(c for c in cands if c.iso == "2024-12-22")
    assert "22 Dec, 2024" in match.source
    assert "last order date" in match.snippet
    # The nearest-by-distance phrase to THIS date is "last order date" itself, not the
    # more distant (but earlier-starting) "life-time buy" -- see defect note above.
    assert match.phrase == "last order date"
    assert "last order date" in match.governing


# --------------------------------------------------------------------------- #
# 1b. THE PIN -- the two dates must be distinguishable from one another, not just
#     individually findable. This is the assertion that would have caught the
#     "both candidates say near phrase: life-time buy" defect.
# --------------------------------------------------------------------------- #

def test_diodes_fixture_the_two_dates_are_distinguishable(diodes_text):
    cands = ltb_candidates(diodes_text)
    order_cand = next(c for c in cands if c.iso == "2024-12-22")
    ship_cand = next(c for c in cands if c.iso == "2025-06-11")

    # `governing` -- the text immediately before each date -- is where "last order date"
    # vs "last ship date" actually lives, and is the field that decides which is which.
    assert "last order date" in order_cand.governing
    assert "last ship date" in ship_cand.governing

    # `governing` is whitespace-collapsed, so it is not always an exact substring of the
    # original text (runs of whitespace/newlines collapse to a single space). It IS a
    # substring of the original text with the same collapsing applied -- assert on that
    # form rather than silently dropping the verbatim-ness check.
    collapsed_full = re.sub(r"\s+", " ", diodes_text)
    assert order_cand.governing in collapsed_full
    assert ship_cand.governing in collapsed_full

    # Snippets are centred on the DATE (80 chars each side), not the phrase, so each
    # snippet's own date must appear in it even though the two snippets overlap heavily.
    assert order_cand.source in order_cand.snippet
    assert ship_cand.source in ship_cand.snippet

    # Length bound: the spec's own estimate was "~165 chars". Measured against this
    # fixture the actual length is 178-179 chars (80 + 80 + a 12-13-char date + up to 6
    # ellipsis chars structurally lands in the high 170s/180s, not 165, whenever the
    # window doesn't get truncated by a text boundary -- it doesn't here). 165 is too
    # tight and would fail on real data; bounding at 200 instead still catches a
    # regression (e.g. windows silently doubled) without failing on this correct output.
    assert len(order_cand.snippet) <= 200
    assert len(ship_cand.snippet) <= 200


# --------------------------------------------------------------------------- #
# 2. Both dates offered -- disambiguation is the model's job, not the regex's.
# --------------------------------------------------------------------------- #

def test_diodes_fixture_offers_both_the_order_and_the_ship_date(diodes_text):
    cands = ltb_candidates(diodes_text)
    isos = [c.iso for c in cands]
    assert "2024-12-22" in isos  # last ORDER date
    assert "2025-06-11" in isos  # last SHIP date -- NOT excluded by the regex

    block = render_candidate_block(cands)
    assert "last-SHIP" in block or "last-ship" in block.lower()


# --------------------------------------------------------------------------- #
# 3. An LTB phrase with no date anywhere near it stays null, and never crashes.
# --------------------------------------------------------------------------- #

def test_ltb_phrase_with_no_nearby_date_yields_nothing():
    text = (
        "Customers should review their future demand and discuss with TT sales. Any "
        "decision regarding last time buy or re-design would be based on future demand."
    )
    assert ltb_candidates(text) == []
    assert render_candidate_block([]) == ""


# --------------------------------------------------------------------------- #
# 4. Non-breaking hyphen -- the real defect `fold_typography` exists to catch.
# --------------------------------------------------------------------------- #

def test_non_breaking_hyphen_date_is_found_and_source_is_verbatim():
    text = (
        "The last order date for the obsolete parts is 06‑Jun‑2024, with the "
        "final ship date on 07‑Jun‑2024"
    )
    cands = ltb_candidates(text)
    isos = [c.iso for c in cands]
    assert "2024-06-06" in isos

    match = next(c for c in cands if c.iso == "2024-06-06")
    # Verbatim-ness survived folding: the returned source is an exact substring of the
    # ORIGINAL (non-breaking-hyphen) input, not a folded copy with plain ASCII hyphens.
    assert match.source in text
    assert "‑" in match.source


# --------------------------------------------------------------------------- #
# 5. ADI shape -- "Last Order Date (Obsolete Parts Only): 08-JUN-2024 ..."
# --------------------------------------------------------------------------- #

def test_adi_shape_yields_the_order_date():
    text = ("Estimated Dates:\nLast Order Date (Obsolete Parts Only): 08-JUN-2024 "
            "First Ship Date of Changed Items")
    cands = ltb_candidates(text)
    assert [c.iso for c in cands] == ["2024-06-08"]


# --------------------------------------------------------------------------- #
# 6. A date far from any LTB phrase is not a candidate.
# --------------------------------------------------------------------------- #

def test_date_with_no_nearby_phrase_is_not_a_candidate():
    assert ltb_candidates("DATE: 06/25/2024") == []


# --------------------------------------------------------------------------- #
# 7. No phrase at all.
# --------------------------------------------------------------------------- #

def test_no_phrase_at_all_yields_nothing():
    assert ltb_candidates("no phrase and no date anywhere in this sentence") == []


# --------------------------------------------------------------------------- #
# 8. Impossible dates are rejected, never raise.
# --------------------------------------------------------------------------- #

def test_impossible_month_is_rejected_without_raising():
    assert ltb_candidates("last order date of 45 Xxx, 2024") == []


def test_impossible_day_is_rejected_without_raising():
    assert ltb_candidates("last order date 2024-13-45") == []


# --------------------------------------------------------------------------- #
# 9. None / empty input.
# --------------------------------------------------------------------------- #

def test_none_and_empty_input_yield_nothing():
    assert ltb_candidates(None) == []
    assert ltb_candidates("") == []


# --------------------------------------------------------------------------- #
# 10. All-numeric dates. Three of the six declared formats were wholly inert.
#
# `_month_num` looked names up only, and every regex in the module captures `month`
# through a regex group -- so `month` is always a `str` and "06" was looked up in a
# month-NAME dict, returning None. _MDY_SLASH_RE, _ISO_DASH_RE and _ISO_SLASH_RE
# matched their text, failed to build a date and were silently dropped. The two tests
# below that already existed (sections 6 and 8) PASSED throughout, because an inert
# pattern and a correctly-rejected date are indistinguishable from the outside -- which
# is why this needed a test that asserts a numeric date IS found, not one that asserts
# a bad one is not.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "printed, expected_iso",
    [
        # name-month forms, which worked all along -- kept here so this test is a
        # statement about all six declared formats rather than only the repaired three
        ("14 October, 2019", "2019-10-14"),
        ("October 14, 2019", "2019-10-14"),
        ("06-Jun-2024", "2024-06-06"),
        # the three that found nothing at all before the `_month_num` repair
        ("12/22/2024", "2024-12-22"),
        ("2024-06-07", "2024-06-07"),
        ("2024/06/07", "2024-06-07"),
    ],
)
def test_every_declared_date_format_yields_a_candidate(printed, expected_iso):
    cands = ltb_candidates(f"Last Buy Deadline for Submission of Order: {printed}")
    assert [c.iso for c in cands] == [expected_iso]
    # `source` stays verbatim: the model is told to echo the printed text, so a folded
    # or re-rendered copy here would make `doc_level_ltb_date_source` unverifiable.
    assert cands[0].source == printed


def test_numeric_month_out_of_range_is_still_refused_by_date():
    # Section 8 asserted this and passed vacuously -- _ISO_DASH_RE never built a date
    # at all. Now the pattern is live, so this finally tests what it claims: `date()`
    # is the validator and month 13 / day 45 is refused there.
    assert ltb_candidates("last order date 2024-13-45") == []
    assert ltb_candidates("last order date 2024-02-30") == []


def test_slash_date_is_read_month_first_and_the_assumption_is_on_record():
    # "07/06/2024" is 6 July month-first and 7 June day-first, and nothing in the
    # string decides it. Month-first is the declared assumption at _MDY_SLASH_RE and
    # every manufacturer in the corpus is US, so this pins the choice as a decision on
    # record rather than an accident -- a future European notice is a known hazard,
    # not a surprise.
    cands = ltb_candidates("Last Buy Deadline: 07/06/2024")
    assert [c.iso for c in cands] == ["2024-07-06"]

    # Where the first number cannot be a month the ambiguity resolves itself: `date()`
    # refuses month 22, so the candidate is DROPPED rather than silently reordered into
    # a date the document does not state.
    assert ltb_candidates("Last Buy Deadline: 22/12/2024") == []


# --------------------------------------------------------------------------- #
# 11. Wiring -- `_extract_header` appends the candidate block only when there is one.
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _prompt_source_file(monkeypatch):
    # Pin the canonical, git-committed prompt path (the production default) rather than
    # whatever a developer's shell happens to have set for PROMPT_SOURCE -- same fixture
    # as tests/test_second_witness_wiring.py.
    monkeypatch.setenv("PROMPT_SOURCE", "file")


class _FakeB:
    """Records the `system_instructions` it was called with; returns a fixed header."""

    def __init__(self):
        self.calls = []

    def ExtractHeader(self, doc, system_instructions, baml_options=None):
        self.calls.append(system_instructions)
        return SimpleNamespace(
            doc_id="X", doc_type="PCN", revision=None,
            pub_date=None, pub_date_source=None,
            mfr=None, mfr_source=None, categories=[], summary=None,
            doc_level_ltb_date=None, doc_level_ltb_date_source=None,
        )


def _patch_b(monkeypatch, fake_b):
    # `_extract_header` does `from doc_tools.baml_client.sync_client import b` as a LOCAL
    # import inside the method -- patch the module attribute, same approach as
    # tests/test_second_witness_wiring.py.
    from doc_tools.baml_client import sync_client as sync_client_module
    monkeypatch.setattr(sync_client_module, "b", fake_b)


def test_extract_header_appends_candidate_block_when_candidates_exist(monkeypatch, diodes_text):
    from doc_tools.plugins.sustainment import SustainmentPlugin

    fake_b = _FakeB()
    _patch_b(monkeypatch, fake_b)
    plugin = SustainmentPlugin(domain_type="sustainment")

    plugin._extract_header(diodes_text)

    assert len(fake_b.calls) == 1
    # The prompt file's own bullet also mentions the heading string (it tells the model
    # what to look for), so the marker that proves the BLOCK was appended has to be text
    # unique to `render_candidate_block`'s output, not the heading alone.
    assert "were found in the document text near a last-time-buy" in fake_b.calls[0]
    assert "2024-12-22" in fake_b.calls[0]


def test_extract_header_omits_candidate_block_when_none_found(monkeypatch):
    from doc_tools.plugins.sustainment import SustainmentPlugin

    fake_b = _FakeB()
    _patch_b(monkeypatch, fake_b)
    plugin = SustainmentPlugin(domain_type="sustainment")

    text = "This document has no last-time-buy phrase or date in it at all."
    plugin._extract_header(text)

    assert len(fake_b.calls) == 1
    # Same distinction as above: the prompt file's bullet always mentions the heading, so
    # absence of the BLOCK is proven by the render-only marker text, not the heading.
    assert "were found in the document text near a last-time-buy" not in fake_b.calls[0]


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
