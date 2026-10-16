"""Do two READINGS OF ONE PRINTED MANUFACTURER NAME contradict each other?

Pure module -- imports only `re` and `typing`.

WHY THIS EXISTS. TYC-PCN-24-210412.pdf has a degraded text layer that drops the `ti`
ligature. Its manufacturer is read three ways, and ALL THREE are correct readings of the
real page:

    `TE Connectivity`  the printed heading
    `TE Connecvity`    what the damaged text layer hands an extractor
    `TE`               the logo wordmark, which renders as TE over "connectivity"

A three-fire corpus run on 2026-10-09 wrote mfr=`TE` in fire 1 and `TE Connectivity` in
fires 2 and 3, while the region witness ran successfully in ALL THREE (text_layer_degraded
True, witness_regions=2, witness_regions_lost=0). So the instability was in the
COMPARATOR -- an exact string compare that treated three correct readings as three
different answers -- not in the witness. The 2026-10-09 ruling: compare canonical-after-
alias, never the raw string; an mfr needs corroboration from the witness; an
uncorroborated mfr is null + review, never the uncorroborated value.

WHAT IT DECIDES. Both failure shapes SHORTEN the string: a dropped character
(`Connecvity`) and an abbreviation (`TE`). So two readings agree when one is the other
with characters missing (a strict subsequence) or the other cut at a word boundary (a
prefix of whole words). That is a directional test, the same discriminator
`text_layer_health.uncorroborated_parts` uses for MPNs -- see its "THE DIRECTIONAL FIX"
docstring, which `_is_subsequence` below reuses as a precedent.

NON-GOALS, stated because the function names invite the misuse:

  - This is NOT a general company-name matcher. It must not be used to decide that two
    DIFFERENT manufacturers are the same. It decides only whether two READINGS OF ONE
    PRINTED NAME on one page contradict each other. `Vishay` and `onsemi` disagree, and
    so would any two names a human would call different companies.
  - Rule 3 (word-boundary prefix) is separate from rule 2 (subsequence) rather than a
    lower floor on rule 2 for a measured reason: `TE` IS a subsequence of
    `Texas Instruments` (T from Texas, e from Texas), so a 2-character subsequence match
    would equate two unrelated manufacturers. A word-boundary prefix will not -- `te` is
    not followed by a space in `texas instruments`.
"""
import re
from typing import Optional

_WS_RE = re.compile(r"\s+")
_EDGE_PUNCT_RE = re.compile(r"^[^\w]+|[^\w]+$", re.UNICODE)

# Below this a string is a subsequence of almost anything (rule 2).
_MIN_SUBSEQUENCE_LEN = 4
# The abbreviation floor (rule 3). Safe at 2 only because the match must end on a word
# boundary; see the module docstring for why it is not folded into rule 2.
_MIN_PREFIX_LEN = 2


def fold(name) -> Optional[str]:
    """Casefold, collapse every whitespace run to one space, strip edge punctuation.
    None, empty and whitespace-only all fold to None."""
    if name is None:
        return None
    s = _WS_RE.sub(" ", str(name).casefold()).strip()
    # Edge punctuation only; interior punctuation (`Texas Instruments, Inc`) is kept so
    # the comparison never invents a join the page did not print.
    s = _EDGE_PUNCT_RE.sub("", s).strip()
    return s or None


def _is_subsequence(key: str, token: str) -> bool:
    """True if every character of `key` appears in `token`, in order (not necessarily
    contiguous). Local copy on purpose: it reuses the precedent of
    `text_layer_health._is_subsequence` (and the "THE DIRECTIONAL FIX" paragraph of its
    `uncorroborated_parts` docstring) -- a dropped character leaves a subsequence -- but
    that module's version is MPN-keyed and differently normalized, so it is not imported."""
    it = iter(token)
    return all(ch in it for ch in key)


def readings_agree(a, b) -> bool:
    """True when two readings of the same printed manufacturer name do not contradict.

    False if either folds to None. True when ANY of:
      1. the folded forms are equal;
      2. one is a STRICT subsequence of the other and the shorter is >= 4 characters
         (`te connecvity` in `te connectivity`: the dropped-character shape);
      3. one is a WORD-BOUNDARY PREFIX of the other (longer == shorter + " " + at least
         one more character) and the shorter is >= 2 characters (`te` prefixing
         `te connectivity`: the abbreviation / logo shape).

    NOT a general company-name matcher; it decides only whether two READINGS OF ONE
    PRINTED NAME contradict each other. See the module docstring for why rule 3 is not a
    lower floor on rule 2 (`TE` is a subsequence of `Texas Instruments`).
    """
    fa, fb = fold(a), fold(b)
    if fa is None or fb is None:
        return False
    if fa == fb:
        return True
    short, long_ = (fa, fb) if len(fa) <= len(fb) else (fb, fa)
    if len(short) == len(long_):
        return False  # same length, not equal: a substitution, never a drop
    if len(short) >= _MIN_SUBSEQUENCE_LEN and _is_subsequence(short, long_):
        return True
    if (len(short) >= _MIN_PREFIX_LEN and long_.startswith(short + " ")
            and len(long_) > len(short) + 1):
        return True
    return False


def canonical_reading(*readings) -> Optional[str]:
    """The fullest form among `readings`, or None if none survives folding.

    Readings that fold to None are dropped; of the rest the one whose FOLDED form is
    longest wins (ties: first given). Both failure shapes SHORTEN the string -- a dropped
    character and an abbreviation -- so the longest reading is the fullest form of the
    name, and it is what the page prints. The ORIGINAL (unfolded) string is returned.

    Only meaningful over readings that `readings_agree`; it does not check, and must not
    be used to pick between different manufacturers.
    """
    best, best_len = None, -1
    for r in readings:
        f = fold(r)
        if f is None:
            continue
        if len(f) > best_len:
            best, best_len = r, len(f)
    return best
