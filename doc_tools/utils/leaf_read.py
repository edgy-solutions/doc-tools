"""Read a drop's LEAF from the document's own printed title, after parse.

Ordered by the leaf ruling of 2026-10-21, item 4: *"before the title read, a pdf
runs parse + text layer only. The title read is the next step; parts extraction
waits on its leaf."* Item 2 of the same ruling sets this module's output shape:
*"Candidates when not confident: [{leaf, score, evidence_ref}], best first, max 3;
evidence_ref is the title crop the read used."* The same ruling, extended on 2026-10-21
after this module was first written, fixes the crop's coordinates as PAGE FRACTIONS and
the outcome-to-`leaf_source` mapping as this module's to own: see `_page_fractions` and
`leaf_source_for_outcome`, which are the two places those two rulings live.

WHY THIS MODULE EXISTS AT ALL, which is the finding that shaped it. The title read
already existed and was already good — `sustainment_header_trust.doc_type_from_titles`,
9/9 on the nine-notice corpus, 0 ambiguous. It had exactly one caller: the sustainment
plugin. The plugin is selected by `domain_type == "sustainment"`, and the leaf is what
makes the domain sustainment. So you needed the leaf to run the plugin, the plugin held
the read, and the read is what produces the leaf. A drop that declares its kind never
needed the read; a drop that did not could never reach it, and ran green writing
nothing (run `16f30b9a`, PCN24_029.pdf, 2026-10-21). This module is that read, lifted
out from under the decision it is supposed to make.

NOTHING HERE CALLS A MODEL. The whole input is `elements` from the parse — no resource
client, no network, no manifest field. That is what makes item 4 possible as written:
the ruled next step adds no resource to a parse step that is handed only S3, which is
pinned in `tests/test_user_drop_runs_parse_only.py`.

TWO VOCABULARIES, AND CONFLATING THEM PRODUCES A LEAF NO ROW MATCHES. The read's own
vocabulary is BAML's `DocType`, whose members are `PCN` and `PDN`. The ruling's leaf is
a CONTENT KIND — a key of `content_kind.KIND_MAPPING`, lowercase (`pcn`, `pdn`), which
is what selects an extraction row and what the status row carries. They differ only in
case, which is exactly why the mapping below is explicit and sealed against the table
rather than written as `.lower()`: a `.lower()` would silently produce a plausible
leaf for any future DocType member whose name happens not to be a kind.

SCOPE, AND THE ONE QUESTION THIS MODULE DOES NOT ANSWER. The read decides PCN vs PDN
— two of the four domain-declaring leaves. A pdf arriving with no declared kind could
equally be a `work-instruction` or an `s1000d-data-module` drop, and this read cannot
say so: no keyword evidence for either has been measured on any corpus. Widening the
leaf space is the architect's call (asked 2026-10-21, §4b of that day's report) because
inventing it from title keywords is the "choosing a vetted domain for unvetted content"
hazard the 2026-10-02 ruling names. Until it is ruled on, anything that is not a
sustainment signal returns NO leaf — which routes to candidates or to a hold, never to
a guess.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from doc_tools.utils import content_kind
from doc_tools.utils import provenance
from doc_tools.utils import sustainment_header_trust as header_trust

# --------------------------------------------------------------------------- #
# 1. The ruling's enum
# --------------------------------------------------------------------------- #
#: `leaf_source` is one enum everywhere (status row, review route, decision record).
#: It is WRITTEN when the leaf is written and stored on the row — never computed back
#: out of the stored kind.
LEAF_SOURCE_DECLARED = "declared"   # the drop carried a leaf (door or delegate)
LEAF_SOURCE_TITLE = "title"         # read from the document's title — THIS module
LEAF_SOURCE_CORRECTED = "corrected" # a person changed it (with corrected_by)

LEAF_SOURCES: Tuple[str, ...] = (
    LEAF_SOURCE_DECLARED, LEAF_SOURCE_TITLE, LEAF_SOURCE_CORRECTED,
)

# Of the three, this module can only ever emit `title`. `declared` belongs to the
# boundary that reads the sidecar, and `corrected` is Lane 1's: it owns the row and
# `corrected_by`, and a correction arrives through the review route, not through a read.
#
# NOT MEMBERS, deliberately: the read's own `"title-ambiguous"` and
# `"no-title-evidence"` are READ OUTCOMES, not sources. Both mean "no leaf" — which is
# item 2's candidate branch, not a fourth source. They stay on `LeafRead.outcome` and
# are never written to a `leaf_source` column.

# --------------------------------------------------------------------------- #
# 2. DocType -> leaf, sealed against the mapping table
# --------------------------------------------------------------------------- #
# ARCHITECT RULING 2026-10-21 (second ruling): *"Leaf types: don't widen by hand. The
# allowed leaves are the content-kind registry's domain-declaring kinds, read from the
# registry, never a literal list. Today that's pcn and pdn on the PDF path. Make it
# registry-driven after the dry run; for Thursday pcn|pdn stands."*
#
# So this literal stands for Thursday BY THE RULING, and widening it by hand is the
# one thing forbidden. `unmapped_leaf_targets()` below is the half that is already
# registry-bound: the literal cannot name a leaf the registry does not declare.
#
# MEASURED for the deferred swap, so it is not written from the ruling's prose:
# `KIND_MAPPING` has 9 rows and FOUR declare a domain -- pcn (sustainment), pdn
# (sustainment), work-instruction (manufacturing) and s1000d-data-module
# (maintenance). "Domain-declaring" alone is therefore 4, not 2. The ruling's own
# qualifier "on the PDF path" is what cuts it back: s1000d-data-module arrives as XML
# and never reaches a title read, but work-instruction is a PDF kind and WOULD be
# admitted by the bare predicate. The registry-driven version needs that second
# conjunct or it silently widens to manufacturing the day it lands.
#
# And it must key on the registry KEY, not `entry.kind`. The reason used to be that
# they DIVERGED on one row -- `work-instructions` keyed an entry whose kind was
# `work-instruction` -- and the spelling ruling of 2026-10-21 made every row's key and
# kind coincide, so that example no longer demonstrates anything. THE RULE IS
# UNCHANGED: the key is what selects a row and what the door confirmed, and `.kind` is
# not guaranteed to be either. Keying on `.kind` is now merely a latent bug instead of
# a visible one, which is the more dangerous of the two.
_DOC_TYPE_TO_LEAF: Dict[str, str] = {"PCN": "pcn", "PDN": "pdn"}


def leaf_for_doc_type(doc_type: Optional[str]) -> Optional[str]:
    """The content-kind leaf a read `DocType` names, or None.

    None for an unknown DocType rather than a guess: a leaf that is not a
    `KIND_MAPPING` key resolves to no extraction row, and would be a status-row value
    that looks declared and selects nothing.
    """
    return _DOC_TYPE_TO_LEAF.get(doc_type or "")


def unmapped_leaf_targets() -> Tuple[str, ...]:
    """Any target of `_DOC_TYPE_TO_LEAF` that is not a sustainment-declaring row of
    `KIND_MAPPING`. Empty is the healthy answer, and a test asserts it.

    A function rather than an import-time assert on purpose: this module is imported
    by the parse path, and a vocabulary drift should fail a test run, not brick an
    ingest.
    """
    bad = []
    for leaf in _DOC_TYPE_TO_LEAF.values():
        entry = content_kind.KIND_MAPPING.get(leaf)
        if entry is None or entry.domain_type != "sustainment":
            bad.append(leaf)
    return tuple(bad)


# --------------------------------------------------------------------------- #
# 3. Scores
# --------------------------------------------------------------------------- #
# ORDINAL, AND NOT A PROBABILITY. Nothing here is calibrated against an outcome
# frequency and these numbers must not be read as one, averaged, or thresholded as if
# they were. What is claimed is the ORDER, and the order is the measured property:
#
#   * a printed CODE outranks a keyword. "PCN-2683" is the vendor's own label for the
#     document; "end-of-life" is a phrase that can appear in a document about a
#     different notice entirely (TI's page-1 prose, the measured case).
#   * a `Title` element outranks a pre-Title text element. The widened candidate set
#     exists because a partitioner sometimes types a real headline as `NarrativeText`
#     (TI PCN#20210316000.1), which is a recovery, not a preference.
#   * an AMBIGUOUS title scores both leaves low and equally. It is evidence that the
#     document says both, which is a reason to ask, not to rank one above the other.
#
# Ties and ordering: candidates are sorted by score DESCENDING, then by document order
# — never by leaf name. The first-signal-wins property the walk is built on is a
# property of document order, and the candidate list has to carry it, not undo it.
_SCORE_CODE_TITLE = 0.90
_SCORE_CODE_PRE_TITLE = 0.80
_SCORE_KEYWORD_TITLE = 0.60
_SCORE_KEYWORD_PRE_TITLE = 0.50
_SCORE_AMBIGUOUS = 0.30

#: Item 2's cap. Two leaves can be named today, so the cap does not currently bite; it
#: is applied anyway so it is already correct if the leaf space is widened.
MAX_CANDIDATES = 3

#: The coordinate space of every `bbox` this module emits: unstructured's LAYOUT
#: pixels, relative to the `page_width`/`page_height` reported beside it.
#:
#: NAMED ON EVERY REF, because there are three spaces in this pipeline and mixing them
#: silently misplaces a crop — PDF points (what pdfplumber reports), these layout
#: pixels, and the page raster's own pixels. Two notices in the corpus carry row
#: geometry in DIFFERENT spaces (IDT's in image pixels, TI's in PDF points), so a
#: consumer cannot infer the space from the numbers. The sanctioned conversion to
#: raster pixels is `witness_regions.region_pixel_box`, which checks that the two
#: aspect ratios agree before trusting the ratio.
#: ARCHITECT RULING 2026-10-21: *"Crop coordinates: page fractions. [x0, y0, x1, y1]
#: in 0..1, origin top-left, plus page. Unit-free, so no extra key, and the same
#: everywhere evidence_ref appears. Producers convert layout pixels and word-layer
#: points before writing."*
#:
#: So there is NO space key here any more. The space used to need naming because the
#: numbers could not be told apart — a row bbox is image pixels on one notice and PDF
#: points on another, and a reader cannot infer which from the magnitudes. A fraction
#: is self-describing: every value is <= 1, so a box that arrived in the wrong space
#: is visible rather than silent, and a consumer needs no page size, no DPI and no PDF
#: to place it.
#:
#: 6 decimals is ~1/1,000,000 of a page — about 0.0006pt on a letter page, far below
#: any precision the text layer has. It is here so a manifest stays readable and a
#: test can assert an exact value, not because the sixth digit means anything.
_FRACTION_DIGITS = provenance.FRACTION_DIGITS  # the conversion lives there now

#: What the element's own geometry is in BEFORE this module converts it: unstructured
#: LAYOUT pixels, relative to the element's `layout_width`/`layout_height`
#: (`provenance.build_positioned_index` stores those as page_width/page_height, and
#: `witness_regions.py:33-45` names all three spaces). Recorded as the divisor's
#: provenance, so a reader can recover the pixels; never as a wire value.
BBOX_SOURCE_SPACE_LAYOUT_PIXELS = "unstructured-layout-pixels"


# --------------------------------------------------------------------------- #
# 4. The read
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class LeafCandidate:
    """One leaf this document might be, with the evidence that suggested it."""
    leaf: str
    score: float
    evidence_ref: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {"leaf": self.leaf, "score": self.score,
                "evidence_ref": dict(self.evidence_ref)}


@dataclass(frozen=True)
class LeafRead:
    """What the title read concluded.

    `leaf` and `leaf_source` are both None or both set — a source without a leaf is
    the state that makes a column lie, so it cannot be constructed here.
    """
    #: The content-kind leaf, or None when the read could not decide.
    leaf: Optional[str]
    #: `LEAF_SOURCE_TITLE` when a leaf was read, else None. Never an outcome string.
    leaf_source: Optional[str]
    #: How the leaf was settled: "declared" (the drop carried one, no read ran),
    #: "title", "title-ambiguous" or "no-title-evidence".
    outcome: str
    #: The deciding title's ref when a leaf was read, else None.
    evidence_ref: Optional[Dict[str, Any]] = None
    #: Item 2's list, populated ONLY when no leaf was read ("candidates when not
    #: confident"). Best first, max `MAX_CANDIDATES`.
    candidates: Tuple[LeafCandidate, ...] = field(default_factory=tuple)

    @property
    def confident(self) -> bool:
        return self.leaf is not None

    def as_dict(self) -> Dict[str, Any]:
        """The wire shape, for the row and the review card."""
        return {
            "leaf": self.leaf,
            "leaf_source": self.leaf_source,
            "outcome": self.outcome,
            "evidence_ref": dict(self.evidence_ref) if self.evidence_ref else None,
            "candidates": [c.as_dict() for c in self.candidates],
        }


# THE READ'S OUTCOMES — a different vocabulary from `leaf_source`, and the two are one
# word apart in Lane 1's wire body, where the outcome is called `doc_type_source`.
# `title-ambiguous` is a legal outcome and an ILLEGAL leaf_source; assigning either
# field from the other is how an ambiguous read reaches a status row as a source cortex
# refuses, which silently stops the chip being drawn. `leaf_source_for_outcome` is the
# only sanctioned crossing.
#
# The three title values are produced by `header_trust.doc_type_from_titles`, not here;
# they are named so the mapping reads as a mapping, and `test_leaf_read.py` asserts the
# walk emits nothing outside this set, so a change over there fails a test rather than
# falling through the mapping as "no leaf".
OUTCOME_TITLE = "title"
OUTCOME_TITLE_AMBIGUOUS = "title-ambiguous"
OUTCOME_NO_TITLE_EVIDENCE = "no-title-evidence"
OUTCOME_DECLARED = "declared"

#: Every outcome a READ can return. `declared` is not one: it is what `resolve_leaf`
#: records when the drop already carried a leaf and no read ran.
READ_OUTCOMES = (OUTCOME_TITLE, OUTCOME_TITLE_AMBIGUOUS, OUTCOME_NO_TITLE_EVIDENCE)


def resolve_leaf(declared_kind: Optional[str],
                 elements: Optional[Sequence[dict]]) -> LeafRead:
    """What the row should store for this drop: the declared leaf, or the read's.

    This is the boundary half of the ruling's item 1 — *"the source is WRITTEN when
    the leaf is written and stored on the row; never computed from the stored kind"*.
    Only two of the three sources can arise here: `declared` when the drop carried a
    leaf, `title` when the read produced one. `corrected` is Lane 1's, arrives through
    the review route, and is never minted by an ingest.

    MY READING OF ONE THING THE RULING DOES NOT SPELL OUT, stated here so it can be
    overruled in one place: **a format-level kind is not a leaf.** `pdf`, `cad`,
    `engineering-document`, `doors-export` and `xml` are registered kinds that declare
    no domain, so they select no extraction and resolve to "origin unresolved" — the
    live `PCN24_029` case. A drop declaring one has told us its arrival SHAPE and has
    not told us what the document IS, which is the thing a leaf names. So those go to
    the read; only a domain-declaring kind counts as `declared`.

    The leaf returned for a declared drop is the `KIND_MAPPING` KEY as the drop spelled
    it, never `entry.kind`. Since the spelling ruling of 2026-10-21 every row's key and
    kind coincide, so the two happen to be the same string today — but the key is what
    selects a row and what the door confirmed, and nothing holds `.kind` to it. Reading
    `.kind` here would be correct by coincidence.
    """
    entry = content_kind.KIND_MAPPING.get(declared_kind or "")
    if entry is not None and entry.domain_type:
        return LeafRead(leaf=declared_kind, leaf_source=LEAF_SOURCE_DECLARED,
                        outcome=OUTCOME_DECLARED)
    return read_leaf_from_elements(elements)


def evidence_ref_for_element(element: dict, element_index: int,
                             text: str) -> Dict[str, Any]:
    """The locator a crop is cut from: which element decided, and where it sits.

    Geometry comes from `provenance.build_positioned_index`, the same code path the
    header provenance uses, rather than from a second reading of
    `metadata.coordinates` — copied geometry math is how coordinate-space defects
    multiply.

    The bbox is PAGE FRACTIONS, per the 2026-10-21 ruling — see `_page_fractions` for
    the conversion and for the two cases that produce no box at all. A non-PDF source,
    or a fast-strategy parse, legitimately has no coordinates, and that is a missing
    crop, not an error: `bbox` is then `None` and `note` says why, so a consumer is
    never handed a location that does not exist.

    `page` is the ruled key name (`{page, bbox, note?}`), not `page_number`, so that
    `wire_evidence_ref` is a projection of this dict and never a rename — a rename is
    where a key quietly stops being populated.

    The text is carried RAW — the element's own stripped text, unfolded. A folded form
    would be the wrong thing twice: `fold_typography` collapses character runs and is
    not offset-preserving, so an offset taken after folding does not map back; and a
    reviewer needs to see what the page says, including the damage (TYC's layer drops
    every "ti").
    """
    rec = provenance.build_positioned_index([element])
    loc = rec[0] if rec else {}
    bbox, note = _page_fractions(loc.get("bbox"), loc.get("page_width"),
                                 loc.get("page_height"))
    ref = {
        "element_id": element.get("element_id") or f"el_{element_index}",
        "element_index": element_index,
        "element_type": element.get("type"),
        "page": loc.get("page_number"),
        "bbox": bbox,
        # The divisor, and what it was a divisor OF. Kept so the layout pixels are
        # recoverable from the fractions; internal, and never put on the wire.
        "layout_width": loc.get("page_width"),
        "layout_height": loc.get("page_height"),
        "bbox_source_space": BBOX_SOURCE_SPACE_LAYOUT_PIXELS,
        "text": text,
    }
    if note:
        ref["note"] = note
    return ref


def _page_fractions(bbox: Optional[Sequence[float]],
                    width: Optional[float],
                    height: Optional[float]
                    ) -> Tuple[Optional[List[float]], Optional[str]]:
    """Layout pixels -> page fractions. Delegates to the ONE conversion.

    The rules (no divisor, clamp-and-note, refuse a degenerate box) live in
    `provenance.to_page_fractions`, because the ruling says page fractions are
    *"the same everywhere evidence_ref appears"* and the review rows convert through
    the same function. A second copy here is how the leaf crop and the row crop
    would end up disagreeing on a boundary case that costs the whole candidate list.

    Why both spaces divide cleanly: the element bbox is in unstructured's LAYOUT
    pixels and the layout frames the WHOLE page with its origin at the top left
    (PixelSpace counts y downward, which is why `witness_regions.region_pixel_box`
    goes layout -> raster with a single ratio and no flip). So this is a division,
    with no DPI, no PDF and no page size needed by anyone downstream.
    """
    return provenance.to_page_fractions(
        list(bbox) if bbox else None, width, height)


def wire_evidence_ref(ref: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Project an internal ref onto the RULED shape: `{page, bbox, note?}`, nothing else.

    The ruled shape admits no other keys -- an extra one is a 422 at Lane 1's BFF, and
    cortex's candidate reader drops the WHOLE list when one item is invalid (their
    2026-10-21 packet, section 1). So the richer ref stays in the manifest, where no
    shape contract binds it, and only these keys cross.

    ARCHITECT RULING 2026-10-21 (second ruling): *"bbox may be null; page may not.
    Null bbox means 'stated on this page, no box we can draw'. The card jumps to the
    page with no outline and labels it 'on page N, no box'."*

    So the PAGE is the locator and the box only refines it. A ref that has a page and
    no geometry crosses as `{page, bbox: None}` and the card still navigates; dropping
    it, as this function first did, would have thrown away the half that works. Only a
    ref with no page at all yields no evidence_ref -- which is also the derived-field
    case the same ruling settles, since a derived field is on no page.
    """
    if not ref or ref.get("page") is None:
        return None
    bbox = ref.get("bbox")
    out: Dict[str, Any] = {"page": ref["page"], "bbox": list(bbox) if bbox else None}
    if ref.get("note"):
        out["note"] = ref["note"]
    return out


def leaf_source_for_outcome(outcome: Optional[str]) -> Optional[str]:
    """The read's outcome -> the architect's `leaf_source` enum. Written ONCE, here.

    ARCHITECT RULING 2026-10-21: *"doc_type_source -> leaf_source mapping, written
    once in 7f's step 5: title -> title; title-ambiguous -> no leaf, awaiting_kind
    with the candidates. Nothing else crosses."*

    `None` means NO LEAF, and the row holds at `awaiting_kind` carrying the
    candidates. `no-title-evidence` lands here too: the ruling names
    `title-ambiguous` because that is the interesting case, but both are reads that
    produced no leaf, and the hold is the same.

    What this function exists to prevent: `declared` and `corrected` are never minted
    by a READ. A declared leaf came off the drop and a corrected one came from a
    person, so a title read inventing either would be a provenance lie about who
    decided. They are therefore unreachable from any outcome, by construction rather
    than by a reviewer's care.
    """
    return LEAF_SOURCE_TITLE if outcome == OUTCOME_TITLE else None


def _score(signal: str, element_type: Optional[str]) -> float:
    is_title = element_type == "Title"
    if signal == "ambiguous":
        return _SCORE_AMBIGUOUS
    if signal == "code":
        return _SCORE_CODE_TITLE if is_title else _SCORE_CODE_PRE_TITLE
    return _SCORE_KEYWORD_TITLE if is_title else _SCORE_KEYWORD_PRE_TITLE


def read_leaf_from_elements(elements: Optional[Sequence[dict]]) -> LeafRead:
    """Read the leaf from the document's own printed title.

    The DECISION is `doc_type_from_titles`' decision, unchanged and unduplicated: the
    same candidate walk, the same first-signal-wins rule, the same measured 9/9. This
    function adds the two things the ruling asks for and that function cannot express
    in `(value, source)` — WHICH title decided, so a crop can be cut from it, and what
    the document said when nothing decided, so a reviewer is offered candidates
    instead of a dead end.

    When a leaf IS read, `candidates` is empty: the ruling asks for candidates "when
    not confident", and a candidate list beside a decided leaf invites a consumer to
    re-decide a decision that has already been taken from the page.
    """
    pairs = header_trust.headline_candidate_elements(elements)

    # The decision, delegated. Deliberately NOT re-derived from the loop below: one
    # decision, one code path, and the corpus measurement is a measurement of it.
    doc_type, outcome = header_trust.doc_type_from_titles([t for _el, t, _i in pairs])

    # Every signal in the candidate set, in document order, for the evidence halves.
    seen: list = []
    for el, text, idx in pairs:
        value, source, signal = header_trust.title_signal(text)
        if source is None:
            continue
        seen.append((el, text, idx, value, signal))

    if doc_type is not None:
        leaf = leaf_for_doc_type(doc_type)
        if leaf is None:
            # A DocType the mapping does not name. Refuse rather than pass it through:
            # see `leaf_for_doc_type`. `unmapped_leaf_targets` is the tested guard
            # against the other direction.
            return LeafRead(leaf=None, leaf_source=None,
                            outcome=OUTCOME_NO_TITLE_EVIDENCE)
        # The deciding element is the FIRST candidate carrying a signal, by
        # construction: the walk returns on the first non-None source, and an
        # ambiguous first signal returns no leaf — so a decided read is always the
        # first signal's decision. Checked rather than assumed, and on a mismatch the
        # ref is dropped: a leaf with no crop is a gap, a leaf with the WRONG crop is
        # provenance that lies.
        decider = seen[0] if seen and seen[0][3] == doc_type else None
        ref = evidence_ref_for_element(decider[0], decider[2], decider[1]) if decider else None
        return LeafRead(leaf=leaf, leaf_source=LEAF_SOURCE_TITLE,
                        outcome=outcome, evidence_ref=ref)

    # No leaf. Offer what the document did say, best first — one candidate per leaf,
    # keeping its strongest evidence, so the list is a list of LEAVES to choose from
    # and not a list of every title that mentioned one.
    #
    # THE RANKING IS NOT FIRST-SIGNAL-WINS, and that is deliberate. Document order is
    # how the DECISION is taken, and the decision has already refused by the time this
    # runs. What a reviewer wants from a refusal is the strongest evidence anywhere in
    # the document — so a later title printing an explicit code outranks an ambiguous
    # headline, and document order survives only as the tie-break between equals.
    best: Dict[str, Tuple[float, int, Dict[str, Any]]] = {}
    for el, text, idx, value, signal in seen:
        score = _score(signal, el.get("type"))
        # An ambiguous title implicates BOTH leaves — all three of its branches do,
        # which is why the signal carries no further detail.
        leaves = (tuple(_DOC_TYPE_TO_LEAF.values()) if signal == "ambiguous"
                  else tuple(x for x in (leaf_for_doc_type(value),) if x))
        for leaf in leaves:
            prior = best.get(leaf)
            if prior is None or score > prior[0]:
                best[leaf] = (score, idx, evidence_ref_for_element(el, idx, text))

    ordered = sorted(best.items(), key=lambda kv: (-kv[1][0], kv[1][1]))
    candidates = tuple(
        LeafCandidate(leaf=leaf, score=score, evidence_ref=ref)
        for leaf, (score, _idx, ref) in ordered[:MAX_CANDIDATES]
    )
    return LeafRead(leaf=None, leaf_source=None, outcome=outcome,
                    candidates=candidates)
