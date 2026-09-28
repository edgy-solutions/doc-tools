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
from typing import List, Optional, Sequence, Tuple

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
def locate_header_source(value, source, index: List[dict]) -> Tuple[bool, str, Optional[str]]:
    """Where (if anywhere) a header value is grounded in the document. Never raises.

    Returns `(ok, method, effective_source)`. First hit wins, in this order:

    1. `source` is non-empty and matches verbatim via `provenance.resolve_value` (region
       preference "narrative" — a header's mfr/date/etc. reads off the notice's own prose,
       not a parts table) -> `(True, <that call's match_method>, source)`.
    2. `source` is non-empty but only matches after `fold_typography` on both sides ->
       `(True, "typographic_fold", source)`.
    3. `source` is empty/None, but the VALUE ITSELF clears the same two checks ->
       `(True, "value_self_sourced" | "value_self_sourced_fold", str(value))`.
    4. Otherwise -> `(False, "no_source" if not source else "not_found", None)`.

    Step 3's rationale is the whole point of this function: the operative rule is that
    the VALUE must be verbatim in the document; `*_source` is the MECHANISM for proving
    that, not the requirement itself. A model that correctly read a manufacturer name
    off page 1 but omitted the source snippet has not fabricated anything — dropping
    that value on a missing-source technicality would throw away a field the model got
    right. A genuine fabrication ("TT Electronics" against a SEMELAB notice) is still
    caught here regardless of whether a source was offered, because the value itself
    is not in the document under ANY folding. This mirrors `build_review_items`
    (`doc_tools/utils/sustainment_merge.py`), which already falls back to `src or val`
    when resolving a header field's location for the review payload.

    Step 3 runs whether `source` was empty OR present-but-unresolvable, and the two are
    distinguished only in the reported METHOD. A source snippet that does not resolve is a
    provenance defect — commonly an over-long quote ("SEMELAB PLC, Coventry" where the page
    prints the name and the town in separate elements) — and refusing a manufacturer that
    IS printed on page 1 because its snippet overreached would discard a correct field for a
    citation error. The thing being tested is the VALUE's presence in the document; a
    snippet that cannot be located weakens the citation, not the value. Fabrication is
    still caught either way: "TT Electronics" is absent from a SEMELAB notice under every
    folding, with or without a source.
    """
    if source:
        rec = provenance.resolve_value(source, index, prefer_region="narrative")
        if rec["found"]:
            return True, rec["match_method"], source
        if _folded_hit(source, index):
            return True, "typographic_fold", source

    if value:
        val_str = str(value)
        rec = provenance.resolve_value(val_str, index, prefer_region="narrative")
        if rec["found"]:
            return True, "value_self_sourced" if not source else "value_over_bad_source", \
                val_str
        if _folded_hit(val_str, index):
            return True, ("value_self_sourced_fold" if not source
                          else "value_over_bad_source_fold"), val_str

    return False, "no_source" if not source else "not_found", None


# --------------------------------------------------------------------------- #
# 2c. The refusal
# --------------------------------------------------------------------------- #

# (field, its *_source companion, the value to write back when refused). The three
# header fields the parts-side identity standard now applies to. `doc_type` is NOT
# here — it is handled separately, from the document's own title (see 2d), because a
# missing/wrong doc_type is a MISROUTING risk (wrong disposition ruleset), not a
# fabricated-value risk, and blanking it would leave nothing for the router to key on.
HEADER_SOURCED_FIELDS = (
    ("mfr", "mfr_source", ""),
    ("pub_date", "pub_date_source", ""),
    ("doc_level_ltb_date", "doc_level_ltb_date_source", None),
)


def refuse_unsourced_header_values(header_d: dict, index: List[dict]) -> List[str]:
    """Drop any header value in `HEADER_SOURCED_FIELDS` that is not verbatim in the
    document. MUTATES `header_d` IN PLACE. Returns the doc-level reason strings (one per
    refused field, never raises).

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
    `effective_source` returned (verbatim value for a self-sourced hit) — so a value the
    model produced with no snippet at all still carries a source afterward, and
    everything downstream (`build_review_items`, the review UI) sees a normal sourced
    field rather than a hole.
    """
    reasons: List[str] = []
    for field, source_field, blank_value in HEADER_SOURCED_FIELDS:
        value = header_d.get(field)
        if not value:
            continue
        source = header_d.get(source_field)
        ok, method, effective_source = locate_header_source(value, source, index)
        if ok:
            header_d[source_field] = effective_source
            continue
        header_d[field] = blank_value
        header_d[source_field] = None
        reasons.append(
            f"header.{field} refused: no verbatim source in the document "
            f"(method: {method}; value dropped: '{value}')"
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
