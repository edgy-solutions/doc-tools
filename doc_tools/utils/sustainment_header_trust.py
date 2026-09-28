"""Header-value trust: a value the header pass extracts is only as good as its proof.

`ExtractHeader` (BAML function, client `LLM`, gpt-oss) reads the SAME 1713 input tokens
every fire and answers differently. Two observed defects on the real corpus, both from an
un-pinned temperature (see `HEADER_TEMPERATURE` in `doc_tools/plugins/sustainment.py`,
which stops the sampling going forward — this module is the second, independent guard for
whatever a sampled — or even a greedy but wrong — call still produces):

  - `EOL-36_BYV34-400,-BYV34-500` (a SEMELAB document) came back with `mfr` =
    "TT Electronics" — a manufacturer name that is not in the PDF under any reading.
  - `doc_type` flipped PCN/PDN/PCN across repeated fires on byte-identical input.

Pinning temperature makes the model *repeatable*; it does not make it *honest*. A greedy
decode can still confidently emit a value the document never printed. So this module
enforces the independent, document-grounded check: a header value is trusted only when it
is VERBATIM SOMEWHERE IN THE POSITIONED ELEMENT INDEX (`provenance.build_positioned_index`)
— the same standard the parts side already holds MPNs to (`build_review_items`'s
OCR-verbatim check). A value that fails is REFUSED (dropped, not flagged) — see
`refuse_unsourced_header_values`.

Pure module — importable without Dagster/BAML, same rule as `sustainment_merge.py`:
imports only `re`, `unicodedata`, `typing`, `doc_tools.utils.provenance`, and
`doc_tools.utils.sustainment_normalize`.
"""
import re
import unicodedata
from typing import Dict, List, Optional, Sequence, Tuple

from doc_tools.utils import provenance
from doc_tools.utils import sustainment_normalize as norm


# --------------------------------------------------------------------------- #
# 2a. Typographic folding
# --------------------------------------------------------------------------- #

# Unicode dash variants (hyphen, non-breaking hyphen, figure dash, en dash, em dash,
# horizontal bar, minus sign) that a vendor's PDF and a model's transcription of it
# disagree on despite being "the same" text to a human reader.
_DASHES = "".join(chr(c) for c in range(0x2010, 0x2016)) + "−"
_DASH_RE = re.compile("[" + re.escape(_DASHES) + "]")

# Curly quote variants.
_SINGLE_QUOTES = "‘’"
_DOUBLE_QUOTES = "“”"
_SINGLE_QUOTE_RE = re.compile("[" + _SINGLE_QUOTES + "]")
_DOUBLE_QUOTE_RE = re.compile("[" + _DOUBLE_QUOTES + "]")

# Non-breaking / thin / figure spaces that render identically to a plain space but do
# not compare equal to one.
_SPACES_RE = re.compile("[   ]")

_WS_RE = re.compile(r"\s+")


def fold_typography(s: Optional[str]) -> str:
    """Collapse cosmetic Unicode variation (dashes, curly quotes, exotic spaces) so a
    value and a document snippet that a human would call identical also compare equal.

    Order: NFKC normalize, fold dash variants to '-', curly quotes to straight ones,
    NBSP/thin/figure space to a plain space, collapse whitespace runs, strip, uppercase.

    Deliberately NOT applied to `provenance._norm` (the PRIMARY matcher used by
    `resolve_value` and everywhere on the parts side) and NOT applied to any value this
    module WRITES back into `*_source` fields. Folding the primary matcher would change
    parts-side matching behaviour this change is not scoped to touch. Folding what gets
    STORED would corrupt the verbatim join key: `*_source` snippets exist to be matched
    character-for-character against the document later (review UI highlighting, repeat
    resolution), and a folded copy is no longer that. This function exists ONLY as a
    second chance inside `locate_header_source`, after the primary exact match has
    already failed — a widened SEARCH, never a stored VALUE.
    """
    s = unicodedata.normalize("NFKC", s or "")
    s = _DASH_RE.sub("-", s)
    s = _SINGLE_QUOTE_RE.sub("'", s)
    s = _DOUBLE_QUOTE_RE.sub('"', s)
    s = _SPACES_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s.upper()


def _folded_hit(snippet: str, index: List[dict]) -> bool:
    """True when `fold_typography(snippet)` appears in some element's folded text (+ its
    folded HTML) — the widened, second-chance search `locate_header_source` falls back to
    once the exact-match `provenance.resolve_value` has already missed."""
    folded = fold_typography(snippet)
    if not folded:
        return False
    for el in index:
        hay = fold_typography(el.get("text", "")) + " " + fold_typography(el.get("text_as_html", ""))
        if folded in hay:
            return True
    return False


# --------------------------------------------------------------------------- #
# 2b. Is a header value backed by the document?
# --------------------------------------------------------------------------- #
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTH_ABBR = ("jan", "feb", "mar", "apr", "may", "jun",
               "jul", "aug", "sep", "oct", "nov", "dec")


def _date_components_consistent(iso_value: str, source_text: str) -> bool:
    """Does `source_text` denote the same calendar date as ISO `iso_value`?

    Deliberately NOT a date parser. A printed "05/12/2023" is 5 December or 12 May
    depending on the vendor's country, and guessing which would trade a fabrication risk
    for a silent off-by-seven-months risk. Instead this asks the weaker question that has
    no ambiguous answer: does the cited text contain this date's YEAR, its DAY and its
    MONTH (as a number or an English abbreviation), each on a token boundary?

    That is enough to kill the two shapes that matter — a citation with no date in it at
    all (the measured URL case), and a citation naming a DIFFERENT date than the value —
    while accepting every vendor typography for the right date. It cannot distinguish
    05/12 from 12/05 when both numbers appear, and does not claim to.
    """
    m = _ISO_DATE_RE.match(iso_value.strip())
    if not m:
        return False
    year, month, day = m.group(1), int(m.group(2)), int(m.group(3))
    low = fold_typography(source_text).lower()

    # A 2-digit year counts: "6/10/24" is how TYC's own page prints 10 June 2024, and
    # measured, demanding the 4-digit form refused a date the citation really did name.
    # Loose on its own, but it is one of three components that must ALL hit in one snippet.
    if not re.search(rf"\b({year}|{year[2:]})\b", low):
        return False
    if not re.search(rf"\b0?{day}\b", low):
        return False
    month_num = re.search(rf"\b0?{month}\b", low)
    month_name = 1 <= month <= 12 and _MONTH_ABBR[month - 1] in low
    return bool(month_num or month_name)


def locate_header_source(value, source, index: List[dict],
                         mode: str = "verbatim") -> Tuple[bool, str, Optional[str]]:
    """Where (if anywhere) a header value is grounded in the document. Never raises.

    THE VALUE IS THE ANCHOR, NOT THE CITATION. Only `value` is looked for in the
    document; `source` never grants trust on its own. Returns
    `(ok, method, effective_source)`:

    1. `value` matches verbatim via `provenance.resolve_value` (region preference
       "narrative" — a header's mfr/date/etc. reads off the notice's own prose, not a
       parts table) -> `(True, <that call's match_method>, str(value))`.
    2. `value` matches only after `fold_typography` on both sides ->
       `(True, "typographic_fold", str(value))`.
    3. Otherwise refused, with the METHOD naming the shape of the failure:
       `"value_absent_source_resolves"` (see below), `"value_absent_source_unresolvable"`,
       `"value_absent_no_source"`, or `"no_value"`.

    MEASURED, and it is why this function was rewritten. An earlier version trusted a
    `source` that resolved, on the reasoning that a located citation proves the field.
    Two real fires on `EOL-36_BYV34-400,-BYV34-500` (a SEMELAB notice) both returned
    `mfr` = "TT Electronics", which appears nowhere in the PDF; one of them cited
    `mfr_source` = "https://www.ttelectronics.com/brands/semelab/", and that URL IS
    printed in the document's footer — Semelab being a TT Electronics brand. So the
    citation resolved, the source-anchored rule returned `(True, "region_preferred", …)`,
    and the fabricated manufacturer would have been WRITTEN by the very check meant to
    stop it. A resolving citation is not evidence for a value it does not contain. Note
    this is also the failure mode `mfr_source`-as-a-review-flag could not catch: the flag
    fired only on the fire that happened to cite nothing.

    On success the `effective_source` is the VALUE string, not the model's snippet: it is
    the text actually located, so `*_source` means one thing everywhere downstream — the
    verbatim document text that was verified — rather than an unverified quote.

    A cited source that cannot be located is still reported distinctly
    (`"value_absent_source_unresolvable"` vs `"value_absent_source_resolves"`), because
    an overreaching quote ("SEMELAB PLC, Coventry" where the page prints the name and the
    town in separate elements) is a citation defect, while a quote that resolves around an
    absent value is the fabrication shape above. Neither rescues the value; the difference
    is diagnostic, and it goes in the reason string a human reads.

    `mode="date"` IS A DIFFERENT RULE, and it has to be. `pub_date` and
    `doc_level_ltb_date` are ISO-normalized by the model — a notice printing "05–Dec 2023"
    yields "2023-12-05", which is not verbatim in the document and never will be. Value-
    anchoring alone would therefore refuse every correctly-read date in the corpus. For a
    DERIVED value the citation is the only possible proof, so the rule becomes: the cited
    source must RESOLVE in the document AND must denote the same calendar date
    (`_date_components_consistent`). That is strictly stronger than the rule this replaced,
    which accepted any citation that resolved even when it named a different date, and it
    still refuses a citation carrying no date at all — the measured URL shape. A document
    that does print an ISO date is matched verbatim first, before any of this.
    """
    if not value:
        return False, "no_value", None

    val_str = str(value)
    rec = provenance.resolve_value(val_str, index, prefer_region="narrative")
    if rec["found"]:
        return True, rec["match_method"], val_str
    if _folded_hit(val_str, index):
        return True, "typographic_fold", val_str

    if source:
        src = str(source)
        exact = provenance.resolve_value(src, index, prefer_region="narrative")["found"]
        src_resolves = exact or _folded_hit(src, index)
        if mode == "date" and src_resolves:
            if _date_components_consistent(val_str, src):
                return True, ("source_dates_value" if exact
                              else "source_dates_value_fold"), src
            return False, "source_is_a_different_date", None
        return False, ("value_absent_source_resolves" if src_resolves
                       else "value_absent_source_unresolvable"), None
    return False, "value_absent_no_source", None


# --------------------------------------------------------------------------- #
# 2b-bis. Recovery — the document names the manufacturer, the model only nominates
# --------------------------------------------------------------------------- #
_NAME_KEY_RE = re.compile(r"[^a-z0-9]+")

# A token inside a URL or an email address is NOT evidence of a manufacturer's name,
# and this exclusion is the entire safety of the rule below. MEASURED, not stylistic:
# `EOL-36_BYV34-400,-BYV34-500` is a SEMELAB notice whose footer really does print
# `https://www.ttelectronics.com/brands/semelab/`, and two real fires put
# `mfr = "TT Electronics"` on it — a name the document never states in prose. Tokenize
# that URL and recovery hands back `ttelectronics`, so the refusal would end up WRITING
# the exact fabrication it exists to stop, one layer further down. A vendor's web domain
# says where its documents are hosted, not who made the part.
_URLISH_RE = re.compile(r"@|://|\bwww\.|\.(?:com|net|org|io|co|cn|de|jp|tw|uk)\b",
                        re.IGNORECASE)

# Below this many alphanumerics a "contraction" is an initialism that collides with
# everything: `TE` opens TECONNECTIVITY but equally TEXASINSTRUMENTS, and `TT` opens
# TTELECTRONICS. Four is the shortest length at which no token in the 9-notice corpus
# produces a cross-vendor collision — a floor read off the corpus, not a taste.
_NAME_MIN_KEY = 4

# Punctuation a printed name carries at a token edge (`ONSEM.` is the TYC-style wordmark
# rendering, `(onsemi)` an aside). Stripped at the EDGES only — never from the middle,
# where it is part of the name.
_NAME_EDGE_PUNCT = ".,;:!?()[]{}<>\"'“”‘’…"


def _name_key(s) -> str:
    """Casefolded alphanumerics only, so `ON Semiconductor`, `onsemi` and `ONSEM.`
    compare on the same footing."""
    return _NAME_KEY_RE.sub("", str(s or "").lower())


def recover_mfr_from_document(nominated, index: List[dict]) -> Tuple[Optional[str],
                                                                    Optional[str]]:
    """The manufacturer the DOCUMENT prints, when the model named one it does not.

    Returns `(value, source)` — both the verbatim printed form — or `(None, None)`.

    THE MODEL NOMINATES, THE DOCUMENT IS THE SOURCE. This is the same standard the
    parts side already holds MPNs to, applied to the one header field that has a
    document-supported answer available when the model's answer fails. Measured on
    `onsemi_Generic_IPCN25300X`: one fire in three emitted `ON Semiconductor`, which the
    notice never prints, while the notice prints `onsemi` six times in its own prose.
    Before this function the refusal wrote `''` there — it could see the nominated value
    was unsupported but had no way to reach the supported one sitting beside it.

    The nominated string is used ONLY as a search key; the bytes written are the
    document's. A token qualifies when its `_name_key` is a PREFIX of the nomination's —
    i.e. the document prints a CONTRACTION of the name the model gave (`onsemi` opens
    `onsemiconductor`). It is deliberately not the other direction and not a fuzzy
    distance: a contraction is a claim the document actually makes, whereas an expansion
    is a claim only the model makes, and that is exactly the fabrication shape.

    UNIQUENESS COMES FREE, WHICH IS NOT THE SAME AS IT BEING UNGUARDED. Every surviving
    candidate is a prefix of the same nomination, and prefixes of one string are totally
    ordered, so the survivors are always one name at different truncations (`onsem`
    inside `onsemi` — this corpus prints both, the wordmark losing its last glyph) and
    the longest is the most complete printed form. Two genuinely different names cannot
    both survive. The work of NOT recovering is therefore done by the three filters
    above the collapse — the URL/email exclusion, the `_NAME_MIN_KEY` floor and the
    past-the-head rule — and by there being no candidate at all, which is the common
    case: recovery never invents, it only reaches for what is printed.

    WHAT THIS DELIBERATELY DOES NOT RESCUE. `TYC-PCN-24-210412` nominates
    `TE Connectivity` against a text layer that prints `TE Connecvity` — the `ti` is
    dropped by the font, document-wide (see `text_layer_health`). `teconnecvity` is not a
    prefix of `teconnectivity`, so no candidate survives and the field stays empty, which
    is correct: preferring the printed form there would write a MISSPELLED manufacturer
    into the graph. A damaged text layer is not a naming disagreement and is not fixed
    here — it is detected, and answered with a second witness.

    Single tokens only. A multi-word name printed in full would have matched verbatim
    upstream and never reached recovery, since `resolve_value` already compares
    case- and whitespace-insensitively.
    """
    target = _name_key(nominated)
    if len(target) < _NAME_MIN_KEY:
        return None, None

    # A contraction has to reach PAST the nomination's first word, or it is just that
    # first word and identifies nobody. `onsemi` spans `ON` + `Semi…`, which is why it
    # reads as the vendor's trade name; `Micro` out of `Micro Devices Micronics` spans
    # only the head and would be written as a manufacturer on the strength of one shared
    # word. This also declines every single-word nomination, deliberately: a truncation
    # of one word is not a distinct trade name, it is a shorter word.
    head = _name_key(_WS_RE.split(str(nominated).strip())[0])

    counts: Dict[str, int] = {}
    first_seen: Dict[str, int] = {}
    position = 0
    for el in index:
        # Narrative only: a manufacturer reads off the notice's own prose and title
        # block, not out of a parts table, which is the same region preference
        # `locate_header_source` already applies.
        if el.get("region") != "narrative":
            continue
        for raw in _WS_RE.split(el.get("text") or ""):
            position += 1
            if not raw or _URLISH_RE.search(raw):
                continue
            form = raw.strip(_NAME_EDGE_PUNCT)
            key = _name_key(form)
            if (len(key) < _NAME_MIN_KEY or len(key) <= len(head)
                    or not target.startswith(key)):
                continue
            counts[form] = counts.get(form, 0) + 1
            first_seen.setdefault(form, position)

    if not counts:
        return None, None

    # UNIQUENESS IS STRUCTURAL HERE, and saying so is worth more than a check that
    # cannot fire. Every surviving key is a prefix of the same `target`, and prefixes of
    # one string are totally ordered by the prefix relation — so the survivors are always
    # one name at different truncations (`onsem` inside `onsemi`), never two names, and
    # the longest is always the most complete form the document prints. An earlier draft
    # carried a "candidates diverge -> refuse" branch; no fixture could reach it, because
    # no such pair can exist. What actually does the discriminating is upstream: the URL
    # exclusion, the `_NAME_MIN_KEY` floor, and the past-the-head rule.
    longest = max({_name_key(f) for f in counts}, key=len)

    # Among printed forms of the SAME key (`onsemi` vs `Onsemi`), the one the document
    # uses most often, and on a tie the one it uses first.
    best = sorted((f for f in counts if _name_key(f) == longest),
                  key=lambda f: (-counts[f], first_seen[f]))[0]

    # Belt and braces: the value written must itself pass the check that refused the
    # model's. It does by construction — it was read out of the index — so a failure
    # here means the tokenizer drifted from `resolve_value`, and silence would be worse
    # than an empty field.
    if not provenance.resolve_value(best, index, prefer_region="narrative")["found"]:
        return None, None
    return best, best


# Only `mfr` has a document-supported answer to reach for. A date does not: a notice
# prints many dates and nothing in the text says which one is the publication date, so
# "the document supports exactly one candidate" is never true for `pub_date` and a
# recovery there would be a guess wearing a citation.
_RECOVERABLE = {"mfr": recover_mfr_from_document}


# --------------------------------------------------------------------------- #
# 2c. The refusal
# --------------------------------------------------------------------------- #

# (field, its *_source companion, the value to write back when refused). The three
# header fields the parts-side identity standard now applies to. `doc_type` is NOT
# here — it is handled separately, from the document's own title (see 2d), because a
# missing/wrong doc_type is a MISROUTING risk (wrong disposition ruleset), not a
# fabricated-value risk, and blanking it would leave nothing for the router to key on.
# The refusal reason has to tell a human WHICH failure this was, because the three read
# very differently in a review queue: a resolving citation around an absent value is the
# fabrication shape (measured: "TT Electronics" cited to a ttelectronics.com URL that the
# footer really does print), an unresolvable citation is usually an overreaching quote,
# and no citation at all is the model declining to show its work.
_REFUSAL_CLAUSE = {
    "value_absent_source_resolves":
        "is not printed in the document; its cited source resolves but does not contain "
        "it — cited",
    "value_absent_source_unresolvable":
        "is not printed in the document, and its cited source could not be located "
        "either — cited",
    "value_absent_no_source": "is not printed in the document, and no source was cited",
    "source_is_a_different_date":
        "is not supported by the document; its cited source names a different date — cited",
    "no_value": "is not a usable value",
}


def _clip(s, limit: int = 80) -> str:
    """A cited source can be a whole paragraph; a reason string is read in a queue."""
    s = str(s)
    return s if len(s) <= limit else s[:limit - 1] + "…"


HEADER_SOURCED_FIELDS = (
    ("mfr", "mfr_source", "", "verbatim"),
    ("pub_date", "pub_date_source", "", "date"),
    ("doc_level_ltb_date", "doc_level_ltb_date_source", None, "date"),
)


def refuse_unsourced_header_values(header_d: dict, index: List[dict],
                                   witness_index: Optional[List[dict]] = None) -> List[str]:
    """Drop any header value in `HEADER_SOURCED_FIELDS` that is not verbatim in the
    document. MUTATES `header_d` IN PLACE. Returns the doc-level reason strings (one per
    refused field, never raises).

    THE SECOND WITNESS. `witness_index` is an optional second positioned index built from
    the page's own PIXELS — the vision tier's transcription of the page image — and it is
    consulted ONLY when the text layer fails to corroborate a value. Verbatim in either
    witness passes; verbatim in neither refuses.

    It exists because "the document does not print this" and "this document's text layer
    cannot print this" are different facts that the refusal could not tell apart.
    `TYC-PCN-24-210412` prints its vendor's name as `TE Connecvity`: the embedded font has
    no mapping for the `ti` ligature, so every `ti` in the document is dropped on
    extraction. A human reading that PDF sees `TE Connectivity`. The model reads the page
    and says `TE Connectivity`. The text layer cannot agree, so the refusal drops a
    CORRECT value — and the same mechanism will silently corrupt an MPN containing `ti`
    on the next such notice, which is the more expensive half.

    The caller decides whether to build a witness at all, gated on
    `doc_tools.utils.text_layer_health.assess_elements` firing. A healthy document never
    pays for one, and — this is the part that matters — an UNGATED witness would be a
    standing second chance for every fabrication to be ratified by a noisy transcription.
    The witness is admitted on a MEASURED condition of the document, not on the model
    having been contradicted.

    It is passed as a separate index rather than concatenated onto `index` on purpose: the
    same string would then be found twice, and `provenance.resolve_value` would downgrade
    every previously-unique match to `region_preferred` at confidence 0.7. Corroboration
    must not degrade the provenance of documents that never needed it.

    This is a REFUSAL, not a review flag — the same rule the parts side already applies
    via identity scoring: a value the document does not contain is not written at all,
    rather than written-but-flagged for a human to catch. Deliberately does NOT set
    `needs_review`. See the `or reasons` REMOVED comment at ~line 1030 of
    `doc_tools/plugins/sustainment.py`: `reasons` (returned here, folded into that same
    list) is the full, honest narrative; every condition that should force a human
    review says so explicitly AT ITS OWN SITE, not by leaking into this list. A refused
    field is, by construction, no longer present for a reviewer to look at — there is
    nothing left to flag.

    A field that clears `locate_header_source` gets its `*_source` REWRITTEN to the
    `effective_source` returned — which is now always the VERIFIED VALUE STRING, never
    the model's own snippet. So a value produced with no snippet at all still carries a
    source afterward (downstream `build_review_items` and the review UI see a normal
    sourced field, not a hole), and a snippet that was never checked can no longer
    masquerade as proof.
    """
    reasons: List[str] = []
    for field, source_field, blank_value, mode in HEADER_SOURCED_FIELDS:
        value = header_d.get(field)
        if not value:
            continue
        source = header_d.get(source_field)
        ok, method, effective_source = locate_header_source(value, source, index, mode=mode)
        if not ok and witness_index:
            # Asked in the SAME way, against pixels instead of the text layer. The value
            # is still the anchor; the witness grants no standing to a citation that the
            # text layer would not have accepted.
            w_ok, w_method, w_source = locate_header_source(value, source, witness_index,
                                                            mode=mode)
            if w_ok:
                ok, effective_source = True, w_source
                reasons.append(
                    f"header.{field} corroborated by the page image: '{_clip(value)}' is "
                    f"absent from this document's degraded text layer but is printed on "
                    f"the page ({w_method})"
                )
        if ok:
            header_d[source_field] = effective_source
            continue
        # The model's value failed. Before blanking the field, ask the document
        # whether it names one itself — see `recover_mfr_from_document`. The
        # substitution is recorded in `reasons` like everything else here: a written
        # value that did not come from the model is exactly the kind of thing a human
        # reading the narrative must be able to see.
        recover = _RECOVERABLE.get(field)
        if recover:
            recovered, recovered_source = recover(value, index)
            if recovered:
                header_d[field] = recovered
                header_d[source_field] = recovered_source
                reasons.append(
                    f"header.{field} recovered: model value '{_clip(value)}' is not "
                    f"printed in the document; written from the document's own "
                    f"'{_clip(recovered)}' instead"
                )
                continue
        header_d[field] = blank_value
        header_d[source_field] = None
        clause = _REFUSAL_CLAUSE.get(method, f"was refused ({method})")
        reasons.append(
            f"header.{field} refused: '{value}' {clause}"
            + (f": '{_clip(source)}'" if source and clause.endswith("cited") else "")
        )
    return reasons


# --------------------------------------------------------------------------- #
# 2d. doc_type from the document's own title
# --------------------------------------------------------------------------- #
_CODE_RE = re.compile(r"\b(pcn|pdn)\b")


def doc_type_from_titles(titles: Sequence[str]) -> Tuple[Optional[str], str]:
    """Classify PCN vs PDN from the document's own title text — NOT from the header
    model's `doc_type` field, which flipped PCN/PDN/PCN across repeated fires on
    identical input (see module docstring). A vendor's title is printed once, on the
    page, and does not sample.

    Titles are read IN ORDER and the FIRST one carrying any signal decides. It is not
    one flat blob of every title in the document, because the later ones are section
    headings and table captions — subject matter, not the document's label for itself.
    Measured: `Diodes_PCN_2683_Rev1_EOL` is headed "PRODUCT CHANGE NOTICE" / "PCN-2683"
    and, five titles later, captions a table "Table 2 - EOL Devices with Life-time Buy
    Opportunity and No Replacement Parts". Under a blob scan that caption's "EOL" is a
    PDN keyword contradicting the form's own PCN, and both Diodes notices came back
    unstated — a document that labels itself in capitals on page 1, refused. The
    headline walk reads it as the vendor prints it.

    Returns `(doc_type_or_None, source)` with `source` one of:
      - "title": the deciding title carried exactly one signal — an explicit code, or,
        absent a code, one keyword class.
      - "title-ambiguous": the deciding title carries BOTH codes, or a code alongside
        the OPPOSITE keyword class, or both keyword classes and no code. Only that one
        title can be ambiguous; a later caption cannot make an unambiguous headline
        ambiguous.
      - "no-title-evidence": no titles, or no title with a code or keyword hit.

    Measured over the 9-notice corpus: 9/9 derived from the title, 0 ambiguous, and
    every one agrees with ground truth (7 by explicit code or headline keyword, TYC
    from its third title because ligature loss mangles its first into "Noﬁcaon").

    KNOWN TENSION, left deliberately: `norm.normalize_doc_type` holds that "a
    discontinuance stated as a 'change' is still a discontinuance for routing", and by
    that reading the two EOL-bearing Diodes notices might route as PDN. This function
    does not apply it, because its job is narrower — report the type the DOCUMENT
    states, which is what `doc_type_source: "title"` attests to. A router that wants
    the discontinuance reading owns making it, from the per-part LTB dates and the
    "No Replacement Parts" captions, and it can see that this value came from a title.
    """
    for title in titles or []:
        if not title or not title.strip():
            continue
        low = title.lower()
        codes = set(_CODE_RE.findall(low))
        pdn_kw = any(t in low for t in norm._PDN_TERMS)
        pcn_kw = any(t in low for t in norm._PCN_TERMS)

        if not codes and not pdn_kw and not pcn_kw:
            continue  # a title that says nothing about the type is not evidence either way

        if len(codes) >= 2:
            return None, "title-ambiguous"

        if len(codes) == 1:
            code = next(iter(codes)).upper()
            opposite_kw = pdn_kw if code == "PCN" else pcn_kw
            if opposite_kw:
                return None, "title-ambiguous"
            return code, "title"

        # No code in THIS title: classify by keyword, and refuse if it says both.
        if pdn_kw and pcn_kw:
            return None, "title-ambiguous"
        return ("PDN" if pdn_kw else "PCN"), "title"

    return None, "no-title-evidence"


def titles_from_elements(elements) -> List[str]:
    """Every `Title`-typed element's text, stripped, non-empty, in document order.

    Page 1 is NOT sufficient: two Diodes notices in the corpus carry their classifying
    title on a LATER page, not the first. Callers must pass the whole document's
    elements, not a head slice.
    """
    out: List[str] = []
    for el in elements or []:
        if not isinstance(el, dict) or el.get("type") != "Title":
            continue
        text = (el.get("text") or "").strip()
        if text:
            out.append(text)
    return out
