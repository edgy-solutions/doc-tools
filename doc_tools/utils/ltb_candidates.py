"""Deterministic last-time-buy (LTB) date candidates, extracted from the text layer.

`ExtractHeader` is intermittently asked to PRODUCE `doc_level_ltb_date`, and on real
fires of `Diodes_PCN_2683_Rev1_EOL.pdf` it missed the date on 2 of 3 identical calls
(`None | None | '2024-12-22'`) despite the document printing it once, plainly, next to
the phrase "last order date". Asking a sampled model to both FIND a date substring and
NORMALIZE it is asking it to do two jobs; this module does the finding deterministically
so the model's only job is to CHOOSE among a short list (or say null).

A FIRST VERSION OF THIS UNDER-SERVED THE CHOICE ITSELF. The Diodes sentence states a
last-ORDER date and a last-SHIP date back to back, one sentence apart, and only one
phrase in it ("life-time buy") is close enough to qualify BOTH dates -- so an
implementation that attributes each candidate to the first-starting qualifying phrase
renders both candidates under the SAME "near phrase: life-time buy" line, with nearly
identical ~240-char snippets, and hands the model no structured signal for which date is
which. The text that actually decides is immediately before each date ("last order date
of" vs "last ship date of"), so `governing` carries it verbatim and `phrase` is now the
NEAREST qualifying phrase by character distance rather than the first one found -- see
`ltb_candidates`'s inner loop and `LtbCandidate.governing`.

Pure module: `re`, `datetime`, `dataclasses`, `typing`, and
`doc_tools.utils.sustainment_header_trust.fold_typography` only.
"""
import re
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Sequence, Tuple

from doc_tools.utils.sustainment_header_trust import fold_typography

# --------------------------------------------------------------------------- #
# Typographic folding that preserves string length/offsets.
# --------------------------------------------------------------------------- #
# `fold_typography` is written to normalize a whole VALUE for comparison (NFKC, dash/
# quote/space folding, whitespace-RUN collapse, strip, uppercase) and is NOT
# offset-preserving on arbitrary document text: a run of two spaces collapses to one and
# leading/trailing whitespace is stripped, both of which shift every index after them.
# Measured directly (see the handoff task): `fold_typography("a  b\n\nc")` returns a
# STRING SHORTER than its input. Applying it to the whole page text would corrupt the
# offset mapping back to the original for exactly the multi-space/newline runs a real
# PDF's extracted text is full of.
#
# So folding here is done ONE CHARACTER AT A TIME, calling `fold_typography` per
# character (still the same dash/quote/space/case rules, still the required import) and
# falling back to the original character whenever a single character does not fold to
# exactly one character (NFKC ligature expansion, `ß` -> `SS` under `.upper()` — neither
# occurs in the real corpus, but the fallback keeps this correct rather than assuming
# it). A whitespace character is mapped to a single plain space directly, because
# `fold_typography(" ")` on its OWN strips to `""` (there is nothing else in that
# one-character string to keep) — the per-char loop has to special-case exactly the thing
# that broke the whole-string version.
#
# Result: `fold_preserving_offsets(s)` always has `len(s) == len(fold_preserving_offsets(s))`,
# with `folded[i]` corresponding to `s[i]`, so a regex match span found in the folded text
# is the SAME span in the original text.
def fold_preserving_offsets(s: str) -> str:
    out = []
    for ch in s:
        if ch.isspace():
            out.append(" ")
            continue
        folded = fold_typography(ch)
        out.append(folded if len(folded) == 1 else ch.upper())
    return "".join(out)


# --------------------------------------------------------------------------- #
# LTB phrases
# --------------------------------------------------------------------------- #
# Word groups a real notice uses for "the last-time-buy date", each compiled to allow a
# dash, whitespace (any run), or nothing between words -- "last-time-buy" and
# "last time buy" are the same phrase to a vendor's typesetter. Deliberately excludes
# "last ship", "final ship", "EOL", "end of life": those name a DIFFERENT date (see the
# Diodes fixture, which prints both a last-ORDER and a last-SHIP date in one sentence),
# and including them would destroy precision, not improve recall.
_PHRASE_WORD_GROUPS: Tuple[Tuple[str, ...], ...] = (
    ("last", "time", "buy"),           # "last time buy" / "last-time-buy"
    ("last", "time", "to", "buy"),     # "last time to buy"
    ("last", "order"),                 # "last order"
    ("last", "order", "date"),         # "last order date"
    ("last", "buy"),                   # "last buy"
    ("lifetime", "buy"),               # "lifetime buy" / "lifetime-buy"
    ("life", "time", "buy"),           # "life-time buy"
)

_SEP = r"[\s-]*"


def _compile_phrase_patterns() -> List[re.Pattern]:
    patterns = [
        re.compile(r"\b" + _SEP.join(re.escape(w) for w in words) + r"\b", re.IGNORECASE)
        for words in _PHRASE_WORD_GROUPS
    ]
    patterns.append(re.compile(r"\bLTB\b", re.IGNORECASE))
    return patterns


_PHRASE_PATTERNS = _compile_phrase_patterns()


# --------------------------------------------------------------------------- #
# Date formats
# --------------------------------------------------------------------------- #
_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# day-month-year, month as a name: "22 Dec, 2024" / "22 Dec 2024" / "11 June, 2025"
_DMY_NAME_RE = re.compile(
    r"\b(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]{3,9})\.?,?\s+(?P<year>\d{4})\b"
)
# month-year-day, month as a name: "December 5, 2023" / "Dec 5 2023"
_MDY_NAME_RE = re.compile(
    r"\b(?P<month>[A-Za-z]{3,9})\.?\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})\b"
)
# day-month-year, month as a name, dash-separated: "06-Jun-2024" / "08-JUN-2024"
_DMY_DASH_RE = re.compile(
    r"\b(?P<day>\d{1,2})-(?P<month>[A-Za-z]{3,9})-(?P<year>\d{2,4})\b"
)
# US numeric, month first: "12/22/2024"
_MDY_SLASH_RE = re.compile(
    r"\b(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})\b"
)
# ISO, dash: "2024-12-22"
_ISO_DASH_RE = re.compile(
    r"\b(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\b"
)
# ISO, slash: "2024/12/05"
_ISO_SLASH_RE = re.compile(
    r"\b(?P<year>\d{4})/(?P<month>\d{2})/(?P<day>\d{2})\b"
)


def _month_num(token: str) -> Optional[int]:
    return _MONTHS.get(token.lower())


def _try_date(year_s: str, month, day_s: str) -> Optional[date]:
    """Build a `date`, rejecting anything `datetime.date` itself would reject (month 13,
    day 32, Feb 30, ...). Never raises -- returns None on any failure."""
    try:
        year = int(year_s)
        if len(year_s) == 2:
            year += 2000
        month_num = _month_num(month) if isinstance(month, str) else int(month)
        if not month_num:
            return None
        day = int(day_s)
        return date(year, month_num, day)
    except (TypeError, ValueError):
        return None


def _find_dates(folded_text: str) -> List[Tuple[int, int, str]]:
    """All (start, end, iso) date matches in `folded_text`, in document order, with
    overlapping matches from different patterns collapsed to the first one found."""
    found: List[Tuple[int, int, str]] = []
    claimed: List[Tuple[int, int]] = []

    def _overlaps(a_start, a_end):
        return any(a_start < c_end and c_start < a_end for c_start, c_end in claimed)

    for regex, kind in (
        (_DMY_NAME_RE, "dmy_name"),
        (_MDY_NAME_RE, "mdy_name"),
        (_DMY_DASH_RE, "dmy_name"),
        (_MDY_SLASH_RE, "mdy_num"),
        (_ISO_DASH_RE, "iso"),
        (_ISO_SLASH_RE, "iso"),
    ):
        for m in regex.finditer(folded_text):
            start, end = m.start(), m.end()
            if _overlaps(start, end):
                continue
            gd = m.groupdict()
            if kind in ("dmy_name",):
                d = _try_date(gd["year"], gd["month"], gd["day"])
            elif kind == "mdy_name":
                d = _try_date(gd["year"], gd["month"], gd["day"])
            elif kind == "mdy_num":
                d = _try_date(gd["year"], gd["month"], gd["day"])
            else:  # iso
                d = _try_date(gd["year"], gd["month"], gd["day"])
            if d is None:
                continue
            claimed.append((start, end))
            found.append((start, end, d.isoformat()))

    found.sort(key=lambda t: t[0])
    return found


# --------------------------------------------------------------------------- #
# Window
# --------------------------------------------------------------------------- #
# Measured gaps in the real corpus, between the END of the qualifying phrase and the
# START of the date (or vice versa): Diodes ("last order date of 22 Dec, 2024") ~4
# chars; ADI ("Last Order Date (Obsolete Parts Only): 08-JUN-2024") ~35 chars; TE
# ("The last order date for the obsolete parts is 06-Jun-2024") ~35 chars. The windows
# below are generous multiples of the worst observed gap, not the gap itself.
_WINDOW_AFTER = 120   # date appears up to this many chars after the phrase ends
_WINDOW_BEFORE = 80   # date appears up to this many chars before the phrase starts

_WS_RUN_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class LtbCandidate:
    iso: str         # normalized YYYY-MM-DD
    source: str      # the date substring EXACTLY as printed in the text (verbatim)
    governing: str   # up to 48 chars immediately BEFORE the date, whitespace-collapsed --
                      # THE DISCRIMINATOR: "last order date of" vs "last ship date of" is
                      # the one signal that tells two same-sentence dates apart, and it
                      # sits right here, not in `phrase` (see module docstring, "the two
                      # candidates were indistinguishable" defect).
    phrase: str      # the NEAREST qualifying LTB phrase to the date, by character
                      # distance, as printed
    snippet: str     # exactly 80 chars before/after the DATE (not the phrase),
                      # whitespace-collapsed, with a leading/trailing "..." when the
                      # window was truncated rather than hitting the text's own edge


_MAX_CANDIDATES = 8
_GOVERNING_RADIUS = 48
_SNIPPET_RADIUS = 80


def _qualifies(phrase_span: Tuple[int, int], date_span: Tuple[int, int]) -> bool:
    p_start, p_end = phrase_span
    d_start, d_end = date_span
    if d_start >= p_end and (d_start - p_end) <= _WINDOW_AFTER:
        return True
    if d_end <= p_start and (p_start - d_end) <= _WINDOW_BEFORE:
        return True
    return False


def ltb_candidates(full_text: Optional[str]) -> List[LtbCandidate]:
    """Deterministic LTB date candidates found near an LTB phrase in `full_text`.

    Never raises. Empty/None input, no phrase, or no date near a phrase all yield `[]`.
    """
    if not full_text:
        return []

    folded = fold_preserving_offsets(full_text)

    phrase_spans: List[Tuple[int, int]] = []
    for pattern in _PHRASE_PATTERNS:
        for m in pattern.finditer(folded):
            phrase_spans.append((m.start(), m.end()))
    if not phrase_spans:
        return []
    phrase_spans.sort(key=lambda t: t[0])

    date_matches = _find_dates(folded)
    if not date_matches:
        return []

    raw: List[Tuple[int, LtbCandidate]] = []
    for d_start, d_end, iso in date_matches:
        # NEAREST qualifying phrase by character distance -- not the first-starting one.
        # A sentence stating two dates ("last order date of X ... last ship date of Y")
        # has one phrase, "life-time buy", that qualifies BOTH dates equally by starting
        # position; picking the nearest one instead is what lets `phrase` (and the
        # `governing` text below it) actually discriminate X from Y.
        best_phrase = None
        best_dist = None
        for p_start, p_end in phrase_spans:
            if not _qualifies((p_start, p_end), (d_start, d_end)):
                continue
            if d_start >= p_end:
                dist = d_start - p_end
            elif d_end <= p_start:
                dist = p_start - d_end
            else:
                dist = 0
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_phrase = (p_start, p_end)
        if best_phrase is None:
            continue

        p_start, p_end = best_phrase
        source = full_text[d_start:d_end]
        phrase_text = full_text[p_start:p_end]

        gov_start = max(0, d_start - _GOVERNING_RADIUS)
        governing = _WS_RUN_RE.sub(" ", full_text[gov_start:d_start]).strip()

        snip_start = d_start - _SNIPPET_RADIUS
        snip_end = d_end + _SNIPPET_RADIUS
        lead_ellipsis = snip_start > 0
        trail_ellipsis = snip_end < len(full_text)
        clipped = full_text[max(0, snip_start):min(len(full_text), snip_end)]
        collapsed = _WS_RUN_RE.sub(" ", clipped).strip()
        snippet = (("..." if lead_ellipsis else "") + collapsed
                  + ("..." if trail_ellipsis else ""))

        raw.append((d_start, LtbCandidate(iso=iso, source=source, governing=governing,
                                          phrase=phrase_text, snippet=snippet)))

    raw.sort(key=lambda t: t[0])

    seen = set()
    out: List[LtbCandidate] = []
    for _, cand in raw:
        if cand.iso in seen:
            continue
        seen.add(cand.iso)
        out.append(cand)
        if len(out) >= _MAX_CANDIDATES:
            break
    return out


def render_candidate_block(cands: Sequence[LtbCandidate]) -> str:
    """A prompt-ready block listing `cands`, or `""` for an empty list (so a caller can
    unconditionally concatenate it onto a prompt)."""
    if not cands:
        return ""

    lines = [
        "",
        "### LAST-TIME-BUY DATE CANDIDATES ###",
        "The following dates were found in the document text near a last-time-buy / "
        "last-order phrase.",
        "For doc_level_ltb_date you MUST choose one of these, or null. Do not supply a "
        "date that is not",
        "on this list. Set doc_level_ltb_date_source to the \"as printed\" text of the "
        "option you choose.",
        "Beware: a document often states a last-ORDER date and a last-SHIP date in the "
        "same sentence.",
        "Only the last-time-buy / last-order date belongs in doc_level_ltb_date. Read "
        "each context line.",
        "",
    ]
    for i, cand in enumerate(cands, start=1):
        lines.append(f'  {i}. as printed: "{cand.source}"   ISO: {cand.iso}')
        lines.append(f'     text immediately before this date: "...{cand.governing}"')
        lines.append(f'     nearest LTB phrase: "{cand.phrase}"')
        lines.append(f"     context: {cand.snippet}")
    return "\n".join(lines)
