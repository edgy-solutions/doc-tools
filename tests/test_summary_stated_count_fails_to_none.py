"""`summary_stated_count` must FAIL TO NONE — never to a wrong number.

That is the function's own stated contract, and it broke it twice in production on
2026-07-31. Both false positives came back through the cross-check as reasons a reviewer
would have had to dismiss:

    "cross-check: summary implies ~2024 parts but 1 were extracted"   (Qorvo PCN-23-0168)
    "cross-check: summary implies ~89 parts but 2 were extracted"     (Qorvo PCN-23-0171)

TWO INDEPENDENT DEFECTS, both in guards that already existed and looked correct:

1. A TRAILING COMMA SWITCHED OFF THE YEAR GUARD. `[\\d,]` is greedy enough to swallow
   SENTENCE punctuation, so "...June 20 2024, after which the part..." matched raw="2024,".
   The year guard keys on the comma as the THOUSANDS-SEPARATOR discriminator ("1,024 SKUs"
   is a real count, "2024" is a year) — so a trailing comma made it conclude "grouped
   number, not a year" and skip the check entirely. **The guard designed to exclude years
   was disabled by a year.** Now: strip trailing separators first, and test POSITIVELY for
   digit-grouping (`\\d{1,3}(,\\d{3})+`) instead of asking "is there a comma".

2. THE BOUNDARY CLASS KNEW ONLY THE ASCII HYPHEN. The header summary is LLM-GENERATED
   prose and routinely uses U+2011 NON-BREAKING HYPHEN: "SOT‑89 package parts". The
   lookbehind listed '-' but not '‑', so it saw no identifier boundary and read 89 out of a
   package type. An identifier is an identifier whichever dash the generator chose.

WHY THIS CLASS KEEPS RECURRING (the docstring already names QPB7420 and the onsemi 2024
case as FIXED): every guard here is a negative — a list of things that are NOT a count —
and a negative list is only as good as its enumeration. The cure is not more entries; it
is testing against REAL generated prose, which is what this file does.

Run:  uv run --frozen python -m pytest tests/test_summary_stated_count_fails_to_none.py -q
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "sn_count", _ROOT / "doc_tools" / "utils" / "sustainment_normalize.py"
)
sn = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sn)  # type: ignore[union-attr]
f = sn.summary_stated_count


# Verbatim from the live artifacts — NOT paraphrased. The Unicode characters ARE the bug;
# retyping these with ASCII hyphens would produce a fixture that passes while production
# fails, which is how both defects survived the guards written for them.
_0168 = (
    "This PCN announces the end‑of‑life of the CMD279C3 product, requiring customers "
    "to place orders by the last‑time‑buy date of June 20 2024, after which "
    "the part will no longer be available for shipment."
)
_0171 = (
    "This PCN announces the end‑of‑life of QPB7420 and QPB7425, replacing them with "
    "new SOT‑89 package parts (QPL7420, QPL7425). Customers must place final orders by "
    "the Last Time Buy date of July 22 2024, after which the parts will no longer be "
    "available."
)


# ── the two live regressions ───────────────────────────────────────────────
def test_a_year_with_a_trailing_comma_is_not_a_count():
    """PCN-23-0168. raw was "2024," — the trailing sentence comma made the year guard
    believe it was looking at a thousands-grouped number."""
    assert f(_0168) is None


def test_a_package_type_with_a_unicode_hyphen_is_not_a_count():
    """PCN-23-0171. "SOT‑89" uses U+2011, which the ASCII-only boundary class missed."""
    assert f(_0171) is None


# ── the guards must not have been widened into uselessness ─────────────────
@pytest.mark.parametrize(
    "summary,expected",
    [
        ("...affecting 1,024 SKUs across the family", 1024),   # genuine grouped count
        ("...affecting 25 parts in this notice", 25),          # genuine small count
        ("...affecting 2,500 devices in total", 2500),   # grouped, under the implausible ceiling
    ],
)
def test_genuine_counts_still_parse(summary, expected):
    """FAILS-TO-NONE is not FAILS-ALWAYS. A guard that returns None for everything would
    pass both regressions above and silently retire the check."""
    assert f(summary) == expected


# ── the previously-fixed cases stay fixed ──────────────────────────────────
@pytest.mark.parametrize(
    "summary",
    [
        "...end-of-life of QPB7420 parts",                  # identifier digits (ASCII)
        "...end‑of‑life of QPB7420 parts",        # identifier digits (U+2011)
        "...by March 2024 for the affected products",       # bare year (onsemi)
        "...new SOT-89 package parts",                      # package type (ASCII)
        "...LTC6226HDC#TRMPBF and 090-44310-31 parts",      # '#' and '/' bearing MPNs
    ],
)
def test_identifiers_and_years_never_become_counts(summary):
    assert f(summary) is None


def test_every_dash_the_generator_might_use_is_a_boundary():
    """Derived rather than hand-listed: each dash in the boundary class must actually block
    a match, so adding one to the class without it working fails HERE."""
    for dash in "-‐‑‒–—−":
        assert f(f"...new SOT{dash}89 package parts") is None, (
            f"U+{ord(dash):04X} does not block an identifier match — a summary using it "
            f"reads a package type as a part count"
        )


def test_a_grouped_numbers_suffix_cannot_match_as_its_own_count():
    """Found by this file's own fixture. The boundary blocks the HEAD of "12,500", and the
    regex then happily matched the SUFFIX "500" — blocking an identifier's head while
    leaving its tail matchable is the same defect the class exists to prevent, one character
    in. ',' is now a boundary too."""
    assert f("Rev.2,500 devices") is None, "the suffix 500 must not match when the head is blocked"
    assert f("affecting 2,500 devices") == 2500


def test_the_implausible_ceiling_still_drops_huge_counts():
    """Not a bug — a deliberate trade, pinned so nobody "fixes" it later. A grouped 12,500
    returns None because a five-figure "count" is likelier a misread identifier than a part
    tally. The cost is real (a genuine 12,500-part notice gets no cross-check) and it is the
    right side to err on, since this feeds a check that used to REFUSE notices."""
    assert f("affecting 12,500 devices") is None


def test_no_count_at_all_is_none():
    assert f("") is None
    assert f(None) is None
    assert f("This PCN announces an end-of-life with no stated quantity.") is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
