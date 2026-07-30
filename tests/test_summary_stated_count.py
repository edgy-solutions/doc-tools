"""summary_stated_count must not read a PART NUMBER as a part COUNT.

Real failure (Qorvo PCN # 23-0171, 2026-07-29) — a CORRECT extraction refused:
  summary: "EOL of QPB7420 & QPB7425 ... broadband products"
  _COUNT_RE had no LEFT boundary, so it began matching at the 7420 INSIDE QPB7420,
  skipped up to 3 tokens, and hit "products" ->
  validate_count: "cross-check: summary implies ~7420 parts but 2 were extracted"
  -> reason appended -> sustainment.py's `or reasons` set doc-level needs_review
  -> but the 2 parts were extracted CLEANLY so neither carried needs_review
  -> start_review's review_state_is_unsourced tripwire saw {doc flagged, no part
     flagged} = the lossy-projection laundering signature -> REVIEW_STATE_UNSOURCED
  -> the notice was refused outright and never reached a reviewer.

A heuristic that is documented "lenient and non-authoritative" must FAIL TO NONE,
never fail to a WRONG number — a wrong count is not "no check", it is a false
positive that blocks the pipeline. MPNs are alphanumeric/hyphenated, so digits
inside them must never be candidate counts.

Run:  uv run --frozen python -m pytest tests/test_summary_stated_count.py -q
"""
import pytest

from doc_tools.utils.sustainment_normalize import summary_stated_count


# ── the regression: part numbers must never be read as counts ───────────────
@pytest.mark.parametrize("summary", [
    # THE live failure, verbatim shape.
    "EOL of QPB7420 & QPB7425 due to new package offering (SOT-89 vs 3x3 QFN)",
    "Qorvo is discontinuing QPB7420 and QPB7425 broadband products",
    # digits mid-MPN followed by a count noun a few tokens later
    "LTC6226HDC#TRMPBF and related parts are affected",
    "BYVB32-200-E3/81 replacement products are listed",
    # hyphenated module numbers
    "090-44310-31 module devices reach end of life",
    # package/dimension noise that reads like a number near a noun
    "SOT-89 vs 3x3 QFN package change affects these products",
])
def test_part_numbers_are_never_read_as_counts(summary):
    assert summary_stated_count(summary) is None, (
        f"a part number's digits were read as a part COUNT from: {summary!r} — "
        f"this is the Qorvo 23-0171 failure (a correct extraction refused)"
    )


# ── positive control: real stated counts STILL parse (the fix isn't a lobotomy)
@pytest.mark.parametrize("summary,expected", [
    ("This notice affects 12 parts", 12),
    ("3 devices are impacted by the change", 3),
    ("A total of 7 MPNs are discontinued", 7),
    ("1,024 SKUs are affected", 1024),
    ("2 products reach end of life", 2),
    # up to 3 intervening tokens still allowed (the original leniency)
    ("5 different broadband products are affected", 5),
])
def test_real_stated_counts_still_parse(summary, expected):
    assert summary_stated_count(summary) == expected, summary


def test_absent_or_empty_summary_is_none():
    assert summary_stated_count(None) is None
    assert summary_stated_count("") is None
    assert summary_stated_count("No numeric claim in this prose at all.") is None


def test_the_check_fails_to_none_not_to_a_wrong_number():
    """The contract this bug violated: a heuristic that BLOCKS the pipeline on
    mismatch must degrade to 'no check', never to a confident wrong answer."""
    # A summary naming only part numbers makes NO claim about how many parts exist.
    assert summary_stated_count("EOL of QPB7420 & QPB7425") is None
    # And one that does make a claim is still honored.
    assert summary_stated_count("EOL of QPB7420 & QPB7425 — 2 parts total") == 2


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
