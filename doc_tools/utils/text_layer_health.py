"""Is this PDF's text layer telling us what the page actually says?

`TYC-PCN-24-210412` prints its own vendor name as `TE Connecvity` and the word
"Notification" as "Nofficaon". Nothing is wrong with the page -- a human reading the PDF
sees the right words. The embedded font's `ti` ligature simply has no character mapping,
so every `ti` in the document vanishes on extraction. Downstream that is indistinguishable
from a vendor genuinely being called "TE Connecvity", which is how a header fire came to
write a MISSPELLED manufacturer and how the next such notice will quietly turn an MPN
containing `ti` into a different part number.

The fix is not to special-case that notice. A damaged text layer is a MEASURED CONDITION
of a document, and a condition you can measure is a condition you can route on: detect it,
record it, and when it holds, admit a second witness (the page's own pixels) before
refusing a value the text layer failed to corroborate.

HOW THE MEASUREMENT WORKS

Ligature pairs (`ti`, `fi`, `ff`, `fl`, `ct`, `st`, `tt`) are the ones a broken font
mapping drops, because they are the pairs a typeface actually ligates. English fixes their
frequency tightly, so "how much `ti` should this document contain" is answerable -- but
only relative to the document's own volume of prose, since a two-page notice and a
twenty-page one are not comparable in absolute counts. So every count is expressed against
a CONTROL: `th` + `er`, two of the most common English bigrams, which no typeface ligates
and which therefore survive a font mapping that has lost its ligatures. The control is the
document's own yardstick, carried in the same text, subject to the same extraction.

    expected(ti) = BASELINE_RATIOS["ti"] x (count(th) + count(er))
    retention(ti) = observed(ti) / expected(ti)

A healthy document lands near 1.0. A document whose `ti` has been deleted lands near 0.

WHY THE MINIMUM COUNT IS LOAD-BEARING

A bigram is judged only when its expected count reaches MIN_EXPECTED. This is not
defensive boilerplate -- it is the whole detector, and 5 is measured to be the knee.
Sweeping the guard over the corpus (`scripts/text_layer_baseline.py` prints the inputs;
the sweep is in the commit message):

    guard <= 4   worst healthy retention 0.0000   separation 0.00x
    guard >= 5   worst healthy retention 0.4954   separation 3.87x

Below 5 a HEALTHY notice scores a perfect zero on some pair -- a bigram expected four
times and observed none -- and there is no line anywhere that separates it from real
damage. That is small-sample noise, not font damage: at expected counts of two or three,
missing one by chance reads as a 50% loss. At 5 and above the separation is stable and
does not improve further, so the guard sits at the knee rather than past it.

The threshold then goes at the geometric midpoint of the two measured populations, 0.25 --
1.95x above the damaged notice (0.128) and 1.98x below the worst healthy one (0.495).
Balanced deliberately: too low and the next TYC goes undetected, too high and a healthy
notice is handed a second witness it did not earn.

An earlier design scored each pair against a fixed corpus-wide density instead of the
document's own control, and could not separate the two populations -- a short healthy
notice and a damaged long one look alike on absolute density. Carrying the yardstick
inside the document is what buys the separation above.

NFKC FIRST, ALWAYS

A PDF may encode a ligature as its own codepoint -- U+FB01 for `fi`. That is a text layer
working CORRECTLY, and counting bytes would score it as a total `fi` loss and condemn a
healthy document. NFKC normalization decomposes those codepoints back to their letters
before anything is counted, so a present-as-ligature pair counts as present.

The baseline ratios below were computed over the eight healthy notices of the PCN corpus
with the exact code in this module; `scripts/text_layer_baseline.py` recomputes them.
"""
import re
import unicodedata
from typing import Dict, Iterable, List, Optional

# Bigrams a typeface ligates, and therefore the ones a broken font mapping drops.
LIGATURE_BIGRAMS = ("ti", "fi", "ff", "fl", "ct", "st", "tt")

# The yardstick: common English bigrams that no typeface ligates, so they survive the
# damage being measured and carry the document's own prose volume.
CONTROL_BIGRAMS = ("th", "er")

# count(bigram) / (count(th) + count(er)), measured over the corpus's healthy notices.
BASELINE_RATIOS: Dict[str, float] = {
    "ti": 0.8219,
    "fi": 0.2329,
    "ff": 0.1199,
    "fl": 0.0068,
    "ct": 0.4452,
    "st": 0.3938,
    "tt": 0.1301,
}

# A bigram is judged only when this many occurrences are expected. See the docstring --
# at 3 the detector stops separating damaged from healthy at all.
MIN_EXPECTED = 5.0

# Retention below this is damage. Measured: 0.133 damaged, 0.591 worst healthy.
DEGRADED_THRESHOLD = 0.35

_NON_LETTER_RE = re.compile(r"[^a-z]+")


def _words(text: Optional[str]) -> List[str]:
    """NFKC-normalized lowercase letter runs.

    Bigrams are counted WITHIN words. Counting across the joins would manufacture pairs
    that were never printed -- "at the" would contribute a `tt` no typeface ever set --
    and `tt` is one of the pairs being judged.
    """
    folded = unicodedata.normalize("NFKC", str(text or "")).lower()
    return [w for w in _NON_LETTER_RE.split(folded) if w]


def _counts(words: Iterable[str], bigrams: Iterable[str]) -> Dict[str, int]:
    wanted = set(bigrams)
    out = {b: 0 for b in wanted}
    for w in words:
        for i in range(len(w) - 1):
            pair = w[i:i + 2]
            if pair in out:
                out[pair] += 1
    return out


def text_of_elements(elements: Optional[List[dict]]) -> str:
    """Flatten a positioned index (or raw unstructured elements) to plain prose."""
    parts = []
    for el in elements or []:
        if isinstance(el, dict):
            parts.append(str(el.get("text") or ""))
    return "\n".join(parts)


def assess_text_layer(text: Optional[str]) -> dict:
    """Score one document's text layer. Never raises.

    Returns a dict that is safe to store as-is on a notice:

        text_layer_degraded  bool   -- did any judged ligature pair fall below threshold
        text_layer_retention float  -- the WORST judged pair's observed/expected, or None
                                       when the document is too short to judge
        text_layer_detail    dict   -- per-bigram observed/expected/retention, the control
                                       count, and which pairs fired

    A document too short to judge is reported as NOT degraded with a retention of None.
    That is the deliberate choice: an unjudgeable document must not silently acquire a
    second witness it did not earn, and must not be recorded as damaged on no evidence.
    """
    words = _words(text)
    control_n = sum(_counts(words, CONTROL_BIGRAMS).values())
    observed = _counts(words, LIGATURE_BIGRAMS)

    judged: Dict[str, dict] = {}
    for b in LIGATURE_BIGRAMS:
        expected = BASELINE_RATIOS.get(b, 0.0) * control_n
        if expected < MIN_EXPECTED:
            continue
        judged[b] = {
            "observed": observed[b],
            "expected": round(expected, 2),
            "retention": round(observed[b] / expected, 4),
        }

    fired = sorted(b for b, d in judged.items()
                   if d["retention"] < DEGRADED_THRESHOLD)
    retention = min((d["retention"] for d in judged.values()), default=None)

    return {
        "text_layer_degraded": bool(fired),
        "text_layer_retention": retention,
        "text_layer_detail": {
            "control_bigram_count": control_n,
            "judged": judged,
            "degraded_bigrams": fired,
            "threshold": DEGRADED_THRESHOLD,
            "unjudgeable": not judged,
        },
    }


def assess_elements(elements: Optional[List[dict]]) -> dict:
    """`assess_text_layer` over a positioned index or raw element list."""
    return assess_text_layer(text_of_elements(elements))


# --------------------------------------------------------------------------- #
# the same witness, for parts
# --------------------------------------------------------------------------- #
_MPN_KEY_RE = re.compile(r"[^A-Z0-9]+")


def _mpn_key(s: Optional[str]) -> str:
    """Uppercase alphanumerics only.

    Deliberately aggressive. A transcription may set a hyphen as an en dash, space a
    reel code differently or drop a slash, and NONE of that is the failure being hunted.
    What survives this normalization is a difference in the LETTERS AND DIGITS -- which
    is exactly the shape of a dropped ligature, and the only shape worth raising.
    """
    return _MPN_KEY_RE.sub("", unicodedata.normalize("NFKC", str(s or "")).upper())


# A witness token has to be LONGER than the MPN key it is offered as evidence for, and
# not implausibly longer -- see `uncorroborated_parts` for why.
_MAX_WITNESS_SLACK = 3
_MIN_KEY_LEN_FOR_EVIDENCE = 4


def _is_subsequence(key: str, token: str) -> bool:
    """True if every character of `key` appears in `token`, in order (not necessarily
    contiguous). This is the shape a DROPPED character leaves behind: delete letters from
    a string and what remains is a subsequence of the original."""
    it = iter(token)
    return all(ch in it for ch in key)


def _witness_tokens(rec: dict) -> List[tuple]:
    """`(mpn_key, raw_token)` for each whitespace-separated token in one witness record's
    raw text. Used only for the positive-evidence test below -- the containment test
    keeps using the concatenated per-record key, unchanged."""
    raw = str(rec.get("text") or "")
    out = []
    for tok in raw.split():
        key = _mpn_key(tok)
        if key:
            out.append((key, tok))
    return out


def uncorroborated_parts(parts: Optional[List[dict]],
                         witness_index: Optional[List[dict]]) -> List[dict]:
    """Which text-layer MPNs the page's own pixels give POSITIVE evidence against.

    Returns `[{field, mpn, page_number, witness_value}]`, one entry per uncorroborated
    value. Empty when there is no witness -- an absent witness is not evidence against
    anything (verified 2026-09-29: fire 1 had `witness_pages=0` and this function already
    returned zero findings on that path; nothing below changes it).

    NON-CONTAINMENT ALONE IS NOT EVIDENCE. An earlier version of this check flagged every
    MPN whose key did not appear verbatim in the witness text. Measured against the real
    TYC-PCN-24-210412 fire-2 witness (`tests/fixtures/sustainment/tyc_witness_page1.txt`,
    the exact string this function received), that raised 9 flags on a notice that is
    100% correct: 898/898 exact under set-identity scoring, 0 spurious / 0 missing / 0
    malformed. The witness page corroborated 17 of the notice's 26 MPNs (~65%) and simply
    failed to read the other 9 -- not because the text layer misprinted them, but because
    the VISION WITNESS substitutes characters. Every one of the 9 misses is a same-length
    near-miss or a shorter misread: text layer `1056703-1` / witness `1056701-1`,
    `1057465-1` / `1057485-1`, `1052926-1` / `502926-1`, `9501815SP-1` / `95018155P-1`,
    `160303P1` / `16030P301`. Absence from a character-fallible transcription is not
    evidence against a text-layer value; it is evidence the transcription is imperfect,
    which was never in question.

    THE DIRECTIONAL FIX. The failure this check exists to catch is the text layer
    DROPPING characters (the `ti`-ligature drop). A dropped character makes the
    text-layer string SHORTER than the truth -- the text-layer key is a strict
    SUBSEQUENCE of what the witness read. A vision substitution is the same length (or
    shorter) and is NOT a subsequence of a longer witness token. That asymmetry is the
    discriminator: a finding now requires BOTH (a) the MPN key absent from the witness
    haystack (the original test, unchanged) AND (b) some individual witness TOKEN
    strictly containing the MPN key as a subsequence -- longer by 1-3 characters. Absent
    such a token, the witness cannot read that value at all, which is "no evidence", not
    "uncorroborated", and must not be flagged. A key shorter than 4 characters never gets
    the benefit of (b) -- too little text to make a subsequence match mean anything.

    WHY THIS FLAGS RATHER THAN CORRECTS. A header field that fails its check is dropped,
    because an empty manufacturer is obviously missing and a wrong one is not. A PART is
    the opposite: the corpus is scored on parts, tier 1 currently reads 898 of 898, and
    dropping or rewriting an MPN on the strength of a vision transcription would put that
    number at the mercy of the noisiest reader in the pipeline. So this raises the row for
    a human and records the stat; it does not edit the data. `witness_value` names the
    witness token that supplied the positive evidence, so the row a reviewer opens says
    what the pixels actually showed instead of just accusing the text layer.

    The failure it exists to catch is specifically a SILENT one. A text layer that drops
    `ti` turns an MPN into a different, well-formed, plausible part number carrying
    correct per-cell provenance -- there is nothing downstream that would notice. Only the
    pixels disagree, so the pixels have to be asked -- but only when they actually say
    something.
    """
    if not parts or not witness_index:
        return []
    by_page: Dict[Optional[int], str] = {}
    everywhere = []
    page_tokens: Dict[Optional[int], List[tuple]] = {}
    all_tokens: List[tuple] = []
    for rec in witness_index:
        page = rec.get("page_number")
        key = _mpn_key(rec.get("text"))
        by_page[page] = by_page.get(page, "") + key
        everywhere.append(key)
        toks = _witness_tokens(rec)
        page_tokens.setdefault(page, []).extend(toks)
        all_tokens.extend(toks)
    all_pages = "".join(everywhere)

    out: List[dict] = []
    for part in parts:
        # TWO ROW SHAPES, ONE PAGE. A tier-1 (text-layer) row carries its page as
        # `text_layer_page` -- it has no `page_number` key at all -- while a vision row
        # carries `page_number`. Reading only the latter is not a crash and not even a
        # missed detection, because the whole-witness fallback below still finds the MPN;
        # it silently degrades to reporting page None on every tier-1 finding, which is
        # the half of the output a reviewer actually navigates by. Tier 1 is also the
        # exact population this check exists for.
        page = part.get("text_layer_page")
        if page is None:
            page = part.get("page_number")
        # The part's own page first; the whole witness as a fallback, because a table
        # spanning a page break can carry a row whose page number is one off.
        haystack = by_page.get(page) or ""
        for field in ("affected_mpn", "replacement_mpn"):
            mpn = part.get(field)
            key = _mpn_key(mpn)
            if not key:
                continue
            if key in haystack or key in all_pages:
                continue
            if len(key) < _MIN_KEY_LEN_FOR_EVIDENCE:
                continue
            # Positive evidence only: some witness token, on this MPN's own page or
            # anywhere else on the witness, has to strictly contain the key as a
            # subsequence and be no more than _MAX_WITNESS_SLACK characters longer.
            candidates = page_tokens.get(page, []) + all_tokens
            witness_value = None
            for tok_key, raw_tok in candidates:
                slack = len(tok_key) - len(key)
                if slack <= 0 or slack > _MAX_WITNESS_SLACK:
                    continue
                if _is_subsequence(key, tok_key):
                    witness_value = raw_tok
                    break
            if witness_value is None:
                continue
            out.append({"field": field, "mpn": mpn, "page_number": page,
                        "witness_value": witness_value})
    return out
