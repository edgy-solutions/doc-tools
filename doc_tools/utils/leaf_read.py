"""Read a drop's LEAF from the document's own printed title, after parse.

Ordered by the leaf ruling of 2026-10-21, item 4: *"before the title read, a pdf
runs parse + text layer only. The title read is the next step; parts extraction
waits on its leaf."* Item 2 of the same ruling sets this module's output shape:
*"Candidates when not confident: [{leaf, score, evidence_ref}], best first, max 3;
evidence_ref is the title crop the read used."*

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
equally be a `work-instructions` or an `s1000d-data-module` drop, and this read cannot
say so: no keyword evidence for either has been measured on any corpus. Widening the
leaf space is the architect's call (asked 2026-10-21, §4b of that day's report) because
inventing it from title keywords is the "choosing a vetted domain for unvetted content"
hazard the 2026-10-02 ruling names. Until it is ruled on, anything that is not a
sustainment signal returns NO leaf — which routes to candidates or to a hold, never to
a guess.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Tuple

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
BBOX_SPACE_LAYOUT_PIXELS = "unstructured-layout-pixels"


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
    #: The read's own outcome: "title", "title-ambiguous" or "no-title-evidence".
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


def evidence_ref_for_element(element: dict, element_index: int,
                             text: str) -> Dict[str, Any]:
    """The locator a crop is cut from: which element decided, and where it sits.

    Geometry comes from `provenance.build_positioned_index`, the same code path the
    header provenance uses, rather than from a second reading of
    `metadata.coordinates` — copied geometry math is how coordinate-space defects
    multiply.

    `bbox_space` is present only when `bbox` is: naming a space for a box that does
    not exist would let a consumer believe it had a location. A non-PDF source, or a
    fast-strategy parse, legitimately has no coordinates, and that is a missing crop,
    not an error.

    The text is carried RAW — the element's own stripped text, unfolded. A folded form
    would be the wrong thing twice: `fold_typography` collapses character runs and is
    not offset-preserving, so an offset taken after folding does not map back; and a
    reviewer needs to see what the page says, including the damage (TYC's layer drops
    every "ti").
    """
    rec = provenance.build_positioned_index([element])
    loc = rec[0] if rec else {}
    bbox = loc.get("bbox")
    return {
        "element_id": element.get("element_id") or f"el_{element_index}",
        "element_index": element_index,
        "element_type": element.get("type"),
        "page_number": loc.get("page_number"),
        "bbox": bbox,
        "bbox_space": BBOX_SPACE_LAYOUT_PIXELS if bbox else None,
        "page_width": loc.get("page_width"),
        "page_height": loc.get("page_height"),
        "text": text,
    }


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
            return LeafRead(leaf=None, leaf_source=None, outcome="no-title-evidence")
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
