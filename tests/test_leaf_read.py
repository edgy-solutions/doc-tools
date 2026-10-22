"""The title read, lifted: leaf, `leaf_source`, candidates and `evidence_ref`.

Steps 2-3 of the plan in the 2026-10-21 report, against the ruling of the same day.
Two halves, and the first matters more than the second:

  1. THE DECISION IS UNCHANGED. `doc_type_from_titles` was measured 9/9 on the
     nine-notice corpus with 0 ambiguous. The lift refactors its loop body into
     `title_signal` and adds an element-carrying twin of `headline_candidates`, and
     those are only safe if they decide exactly what they decided before. Section 1
     pins that, including the two cases the measurement actually turned on.
  2. THE NEW OUTPUT SHAPE. Sections 2-4: the enum, the leaf vocabulary, the candidate
     list and the crop locator.

No model, no resource, no network in this file — which is itself the point of item 4
and is pinned from the other side in `test_user_drop_runs_parse_only.py`.
"""
import pytest

from doc_tools.utils import content_kind
from doc_tools.utils import leaf_read
from doc_tools.utils import sustainment_header_trust as header_trust


def _el(type_, text, *, page=1, box=None, eid=None):
    """An element in the shape the parse produces. `box` is (x0, y0, x1, y1) in
    unstructured's layout pixels; omitted means a parse with no coordinates, which is
    a real case (non-PDF source, fast strategy) and not an error."""
    el = {"type": type_, "text": text, "metadata": {"page_number": page}}
    if eid:
        el["element_id"] = eid
    if box:
        x0, y0, x1, y1 = box
        el["metadata"]["coordinates"] = {
            "points": [[x0, y0], [x0, y1], [x1, y1], [x1, y0]],
            "layout_width": 1700, "layout_height": 2200,
            "system": "PixelSpace",
        }
    return el


# --------------------------------------------------------------------------- #
# 1. The refactor decides what it decided before.
# --------------------------------------------------------------------------- #
# Each case is (titles, expected_value, expected_source). The first four are the
# branches of the walk; the last three are the measured corpus cases the function's
# docstring names, which is why they are here rather than only in a corpus fire.
WALK_CASES = [
    (["PRODUCT CHANGE NOTICE"], "PCN", "title"),
    (["PCN-2683"], "PCN", "title"),
    (["Product Discontinuation Notice"], "PDN", "title"),
    (["PCN and PDN combined notice"], None, "title-ambiguous"),
    # A code alongside the OPPOSITE keyword class.
    (["PCN-2683 end-of-life"], None, "title-ambiguous"),
    # Nothing at all to go on.
    ([], None, "no-title-evidence"),
    (["Table of Contents", "Revision History"], None, "no-title-evidence"),
    # MEASURED: the Diodes case. A later table caption carrying a PDN keyword cannot
    # overturn a headline that labels the document in capitals on page 1 — a blob scan
    # refused both Diodes notices on exactly this.
    (["PRODUCT CHANGE NOTICE", "PCN-2683",
      "Table 2 - EOL Devices with Life-time Buy Opportunity and No Replacement Parts"],
     "PCN", "title"),
    # MEASURED: a title with no signal is walked PAST, not treated as evidence.
    (["Diodes Incorporated", "PRODUCT CHANGE NOTICE"], "PCN", "title"),
]


@pytest.mark.parametrize("titles,value,source", WALK_CASES)
def test_the_walk_decides_what_it_decided_before_the_lift(titles, value, source):
    assert header_trust.doc_type_from_titles(titles) == (value, source)


@pytest.mark.parametrize("titles,value,source", WALK_CASES)
def test_title_signal_agrees_with_the_walk_on_the_deciding_title(titles, value, source):
    """The factoring's own seal: walking the titles with `title_signal` and taking the
    first non-None source reproduces the walk. If these two ever disagree, the leaf
    read and the sustainment plugin are classifying the same document differently.
    """
    for title in titles:
        v, s, signal = header_trust.title_signal(title)
        if s is not None:
            assert (v, s) == (value, source)
            assert signal in ("code", "keyword", "ambiguous")
            return
    assert (value, source) == (None, "no-title-evidence")


def test_the_candidate_twin_cannot_drift_from_the_candidate_strings():
    """`headline_candidates` is now a projection of `headline_candidate_elements`.
    Drift between them would mean an `evidence_ref` pointing at an element that is not
    the one the decision came from — provenance that looks right and is not.
    """
    elements = [
        _el("NarrativeText", "Vendor Semiconductor Inc."),
        _el("Title", "PRODUCT CHANGE NOTICE"),
        _el("NarrativeText", "x" * (header_trust.HEADLINE_MAX_CHARS + 1)),
        _el("Title", "Table 2 - EOL Devices"),
        _el("Image", ""),
        "not a dict",
    ]
    strings = header_trust.headline_candidates(elements)
    pairs = header_trust.headline_candidate_elements(elements)

    assert strings == [t for _el_, t, _i in pairs]
    # The index addresses the element in the list AS PASSED, skips included.
    for el, text, i in pairs:
        assert elements[i] is el
        assert (el.get("text") or "").strip() == text


def test_the_long_pre_title_narrative_is_still_excluded():
    """TI's page-1 prose ("This notice does not change the end-of-life status...")
    carries a PDN keyword and is about a PREVIOUS notice. The length bound is what
    keeps it out, and the lift must not have widened it.
    """
    long_prose = ("This notice does not change the end-of-life status of any product "
                  "and is provided for information only, further to the previous "
                  "notification issued by the manufacturer regarding those devices.")
    assert len(long_prose) > header_trust.HEADLINE_MAX_CHARS
    elements = [_el("NarrativeText", long_prose),
                _el("Title", "PRODUCT CHANGE NOTICE")]
    assert header_trust.headline_candidates(elements) == ["PRODUCT CHANGE NOTICE"]


# --------------------------------------------------------------------------- #
# 2. The enum and the leaf vocabulary.
# --------------------------------------------------------------------------- #
def test_the_leaf_source_enum_is_the_ruled_three():
    assert leaf_read.LEAF_SOURCES == ("declared", "title", "corrected")


def test_the_retired_names_and_the_read_outcomes_are_not_sources():
    """`ingest` and `extraction-title` are retired by the ruling. The read's own
    `title-ambiguous` / `no-title-evidence` are OUTCOMES: both mean "no leaf", which is
    the candidate branch, not a fourth source.
    """
    for not_a_source in ("ingest", "extraction-title",
                         "title-ambiguous", "no-title-evidence"):
        assert not_a_source not in leaf_read.LEAF_SOURCES


def test_every_leaf_this_read_can_emit_is_a_sustainment_row():
    """The seal that keeps the two vocabularies from drifting apart. A leaf that is not
    a `KIND_MAPPING` key selects no extraction row, so it would be a status-row value
    that looks declared and does nothing.
    """
    assert leaf_read.unmapped_leaf_targets() == ()
    for leaf in ("pcn", "pdn"):
        assert content_kind.KIND_MAPPING[leaf].domain_type == "sustainment"


def test_the_bare_registry_predicate_is_WIDER_than_the_leaves_we_allow():
    """ARCHITECT RULING 2026-10-21 (second): *"The allowed leaves are the content-kind
    registry's domain-declaring kinds, read from the registry, never a literal list.
    Today that's pcn and pdn on the PDF path. Make it registry-driven after the dry
    run; for Thursday pcn|pdn stands."*

    This test is the deferral made visible. "Domain-declaring" on its own is NOT
    pcn|pdn today: it also admits work-instructions (manufacturing) and
    s1000d-data-module (maintenance). So the registry-driven version is not a no-op
    refactor of this literal -- it widens unless the ruling's own "on the PDF path"
    qualifier is carried into the predicate. If this assertion ever flips to equal,
    that is the signal the predicate can be swapped in as stated.
    """
    declaring = {k for k, e in content_kind.KIND_MAPPING.items()
                 if getattr(e, "domain_type", None)}
    allowed = set(leaf_read._DOC_TYPE_TO_LEAF.values())
    assert allowed < declaring, (
        "the literal must stay a STRICT subset; if it is now equal, read the ruling")
    assert declaring - allowed, "and the gap is what the bare predicate would admit"



def test_the_leaf_is_the_kind_key_not_the_doc_type():
    """Case is the whole difference between the two vocabularies, which is exactly why
    the mapping is explicit rather than `.lower()`."""
    assert leaf_read.leaf_for_doc_type("PCN") == "pcn"
    assert leaf_read.leaf_for_doc_type("PDN") == "pdn"
    assert leaf_read.leaf_for_doc_type("WORK-INSTRUCTIONS") is None
    assert leaf_read.leaf_for_doc_type(None) is None


# --------------------------------------------------------------------------- #
# 3. The read, confident.
# --------------------------------------------------------------------------- #
def test_a_confident_read_names_the_leaf_the_source_and_the_deciding_title():
    elements = [
        _el("NarrativeText", "Vendor Semiconductor Inc.", box=(100, 80, 600, 120)),
        _el("Title", "PRODUCT CHANGE NOTICE", box=(300, 200, 1400, 260), eid="abc123"),
        _el("Title", "Table 2 - EOL Devices with Life-time Buy", box=(100, 900, 1500, 940)),
    ]
    read = leaf_read.read_leaf_from_elements(elements)

    assert read.leaf == "pcn"
    assert read.leaf_source == leaf_read.LEAF_SOURCE_TITLE
    assert read.outcome == "title"
    assert read.confident is True
    # "Candidates when not confident" — a decided leaf offers none, because a
    # candidate list beside a decision invites re-deciding what the page already said.
    assert read.candidates == ()

    ref = read.evidence_ref
    assert ref["element_id"] == "abc123"
    assert ref["element_index"] == 1
    assert ref["text"] == "PRODUCT CHANGE NOTICE"
    assert ref["page"] == 1
    # PAGE FRACTIONS (architect, 2026-10-21): the layout box (300, 200, 1400, 260)
    # over a 1700x2200 layout. Asserted as the literal values a consumer receives, not
    # as the arithmetic that produced them — a test that recomputes the conversion
    # passes when the conversion is wrong in both places.
    assert ref["bbox"] == [0.176471, 0.090909, 0.823529, 0.118182]
    assert all(0.0 <= v <= 1.0 for v in ref["bbox"])
    assert "note" not in ref  # nothing to say: the box is on the page
    # The divisor is kept so the pixels stay recoverable, and it is named as the
    # space it came FROM, never as the space the bbox is in.
    assert (ref["layout_width"], ref["layout_height"]) == (1700, 2200)
    assert ref["bbox_source_space"] == leaf_read.BBOX_SOURCE_SPACE_LAYOUT_PIXELS
    assert "bbox_space" not in ref  # the ruling removed it: a fraction is unit-free


def test_the_deciding_title_is_the_headline_not_the_later_caption():
    """The evidence half of first-signal-wins: the crop must be cut from the title that
    DECIDED, not from a later one that happens to agree."""
    elements = [
        _el("Title", "PRODUCT CHANGE NOTICE", box=(300, 200, 1400, 260)),
        _el("Title", "PCN-2683", box=(300, 300, 800, 340)),
    ]
    read = leaf_read.read_leaf_from_elements(elements)
    assert read.leaf == "pcn"
    assert read.evidence_ref["element_index"] == 0


def test_a_headline_the_partitioner_typed_as_narrative_text_still_reads():
    """TI PCN#20210316000.1: the printed headline is `NarrativeText` and all four real
    Titles are section headings. The widened candidate set is the recovery, and the
    `evidence_ref` has to point at the element that actually carried the signal.
    """
    elements = [
        _el("NarrativeText",
            "PCN#20210316000.1 Die Coat addition - Change Notification / Sample Request",
            box=(100, 150, 1600, 210)),
        _el("Title", "Affected Devices", box=(100, 500, 700, 540)),
    ]
    read = leaf_read.read_leaf_from_elements(elements)
    assert (read.leaf, read.leaf_source) == ("pcn", "title")
    assert read.evidence_ref["element_type"] == "NarrativeText"
    assert read.evidence_ref["element_index"] == 0


def test_a_crop_is_absent_rather_than_invented_when_the_parse_has_no_geometry():
    """A non-PDF source or a fast-strategy parse has no coordinates. That is a missing
    crop, not an error — and nothing may stand in for the box, or a consumer will
    believe it has a location.
    """
    read = leaf_read.read_leaf_from_elements([_el("Title", "PRODUCT CHANGE NOTICE")])
    assert read.leaf == "pcn"
    assert read.evidence_ref["bbox"] is None
    # No points at all: there is nothing to report, so no note is invented either.
    assert "note" not in read.evidence_ref
    # It DOES cross, per the second ruling: the page is the locator and the box only
    # refines it, so the card navigates to page 1 and draws no outline.
    assert leaf_read.wire_evidence_ref(read.evidence_ref) == {"page": 1, "bbox": None}


# --------------------------------------------------------------------------- #
# 4. The read, not confident: item 2's candidate list.
# --------------------------------------------------------------------------- #
def test_an_ambiguous_headline_offers_both_leaves_and_no_leaf():
    elements = [_el("Title", "PCN / PDN Combined Change and End-of-Life Notice",
                    box=(300, 200, 1400, 260))]
    read = leaf_read.read_leaf_from_elements(elements)

    assert (read.leaf, read.leaf_source) == (None, None)
    assert read.outcome == "title-ambiguous"
    assert read.confident is False
    assert {c.leaf for c in read.candidates} == {"pcn", "pdn"}
    # Equal evidence, scored equally: the document says both, which is a reason to
    # ask, not to rank one above the other.
    assert len({c.score for c in read.candidates}) == 1
    for c in read.candidates:
        assert c.evidence_ref["bbox"] == [0.176471, 0.090909, 0.823529, 0.118182]
        assert c.evidence_ref["bbox_source_space"] == (
            leaf_read.BBOX_SOURCE_SPACE_LAYOUT_PIXELS)


def test_a_later_printed_code_outranks_the_ambiguous_headline_that_refused():
    """The ranking is NOT first-signal-wins, deliberately. Document order decides, and
    it has already refused by the time candidates are built; what a reviewer wants from
    a refusal is the strongest evidence anywhere in the document.
    """
    elements = [
        _el("Title", "Product Change and End-of-Life Notification",
            box=(300, 200, 1400, 260)),
        _el("Title", "PCN-2683", box=(300, 400, 800, 440)),
    ]
    read = leaf_read.read_leaf_from_elements(elements)

    assert read.leaf is None and read.outcome == "title-ambiguous"
    assert read.candidates[0].leaf == "pcn"
    assert read.candidates[0].evidence_ref["element_index"] == 1
    assert read.candidates[0].score > read.candidates[-1].score


def test_the_pcn_keyword_class_needs_a_CONTIGUOUS_phrase_and_a_split_one_reads_pdn():
    """Measured while writing this file, and worth pinning because it reads like a
    defect and is not. "Change and End-of-Life Notification" classifies as **PDN**,
    confidently: `_PCN_TERMS` holds phrases ("change notification", "product change"),
    and this title splits that phrase across the conjunction, so only the PDN keyword
    hits. A vendor who writes it this way gets the discontinuance reading — which
    agrees with `normalize_doc_type`'s rule that a discontinuance stated as a change is
    still a discontinuance. Pinned so a future widening of the keyword lists has to
    face the case rather than discover it.
    """
    read = leaf_read.read_leaf_from_elements(
        [_el("Title", "Change and End-of-Life Notification")])
    assert (read.leaf, read.leaf_source, read.outcome) == ("pdn", "title", "title")


def test_no_title_evidence_yields_no_leaf_and_no_candidates():
    """The PCN24_029 shape: nothing in the document's own printing says what it is.
    A hold, not a guess — and emphatically not the filename, which is the one thing
    this pipeline refuses to treat as evidence."""
    read = leaf_read.read_leaf_from_elements([
        _el("Title", "Table of Contents"), _el("NarrativeText", "Page 1 of 4")])
    assert (read.leaf, read.leaf_source, read.outcome) == (
        None, None, "no-title-evidence")
    assert read.candidates == ()


def test_the_candidate_list_is_capped_at_the_ruled_three():
    assert leaf_read.MAX_CANDIDATES == 3
    elements = [_el("Title", "PCN PDN ambiguous", box=(1, 1, 2, 2))] * 4
    read = leaf_read.read_leaf_from_elements(elements)
    assert len(read.candidates) <= leaf_read.MAX_CANDIDATES
    # One candidate per LEAF, not one per title that mentioned one.
    assert len({c.leaf for c in read.candidates}) == len(read.candidates)


def test_an_empty_or_absent_element_list_does_not_raise():
    for elements in (None, [], ["not a dict"], [{"type": "Title"}]):
        read = leaf_read.read_leaf_from_elements(elements)
        assert read.leaf is None
        assert read.outcome == "no-title-evidence"


# --------------------------------------------------------------------------- #
# 5. The wire shape, which is what Lane 1 stores on the row.
# --------------------------------------------------------------------------- #
def test_the_wire_shape_carries_the_ruled_keys():
    read = leaf_read.read_leaf_from_elements(
        [_el("Title", "PRODUCT CHANGE NOTICE", box=(300, 200, 1400, 260))])
    d = read.as_dict()
    assert set(d) == {"leaf", "leaf_source", "outcome", "evidence_ref", "candidates"}
    assert (d["leaf"], d["leaf_source"]) == ("pcn", "title")
    assert d["candidates"] == []

    amb = leaf_read.read_leaf_from_elements(
        [_el("Title", "PCN / PDN notice", box=(1, 1, 2, 2))]).as_dict()
    assert amb["leaf"] is None and amb["leaf_source"] is None
    for c in amb["candidates"]:
        assert set(c) == {"leaf", "score", "evidence_ref"}


# --------------------------------------------------------------------------- #
# 6. The boundary: `declared` when the drop carried a leaf, `title` when read.
# --------------------------------------------------------------------------- #
def test_a_domain_declaring_kind_is_declared_and_no_read_runs():
    """The drop carried a leaf (door or delegate). The title read must not second-
    guess it: the door confirmed the kind, and the source is written as `declared`."""
    elements = [_el("Title", "Product Discontinuation Notice")]
    read = leaf_read.resolve_leaf("pcn", elements)

    assert (read.leaf, read.leaf_source, read.outcome) == ("pcn", "declared", "declared")
    # The elements SAY pdn. A declared leaf is not re-read, so it stays pcn.
    assert read.candidates == ()
    assert read.evidence_ref is None


def test_the_declared_leaf_is_the_mapping_KEY_and_the_two_now_COINCIDE():
    """The key/kind divergence this test was written for is GONE as of 2026-10-21.

    It used to read `KIND_MAPPING["work-instructions"]` and assert its `kind`
    was the singular — the one row where the table key and the registered kind
    disagreed. The architect renamed the key (*"the plural is the bug"*), so
    there is no longer a row that diverges and that assertion has no witness.

    What is still worth pinning is the PROPERTY, not the old example: a row's
    leaf is the mapping key, and nothing in the registry depends on the two
    spellings differing. If a future row reintroduces a divergence, the
    `_BY_KIND` test below is what catches it.
    """
    for key, entry in content_kind.KIND_MAPPING.items():
        assert entry.kind_source_value == key, (
            f"{key!r} is keyed by something other than its kind_source_value")
        assert entry.kind == key, (
            f"{key!r} diverges from its registered kind {entry.kind!r} — "
            "legal, but it reintroduces the spelling split the 10-21 ruling "
            "closed, so say so deliberately")
    assert leaf_read.resolve_leaf("work-instruction", []).leaf == "work-instruction"


def test_the_DEPRECATED_plural_still_resolves_because_live_s3_paths_carry_it():
    """The rename cannot be a rename alone, and this is the half that bites.

    `content_kind` also derives a kind from the S3 path, and live objects sit
    under `manufacturing/work-instructions/`. Those keys are already written
    and nothing rewrites them. Drop the plural outright and every such drop
    derives a value no table has a key for, so ADR-0021's halt fires on a kind
    that IS registered — a hard failure on real documents, caused by a spelling
    change.

    The architect granted the BFF one release of accepting the plural on read;
    this is the same grace on this side, and it is deliberately a SEPARATE
    table from the registry so that refusing it later is a deletion, not a
    surgical edit.
    """
    entry = content_kind.resolve_content_kind(
        {"content_kind": "work-instructions"}, "")
    assert entry.kind == "work-instruction"
    assert entry.kind_source_value == "work-instruction", (
        "the alias must resolve to the CANONICAL row, not echo the plural back")
    # And the path form, which is the case already on disk. Path-derive needs
    # `domain_type` to know which segment to read AFTER (ADR-0021
    # §Path-derived), so a bare key derives nothing at all — the plural only
    # reaches the registry when the domain is declared alongside it.
    by_path = content_kind.resolve_content_kind(
        {"domain_type": "manufacturing"},
        "manufacturing/work-instructions/M67/grenade-assembly.pdf")
    assert by_path.kind == "work-instruction"


@pytest.mark.parametrize(
    "format_kind", ["pdf", "cad", "engineering-document", "doors-export", "xml"])
def test_a_format_level_kind_is_not_a_leaf_and_goes_to_the_read(format_kind):
    """MY READING, stated in `resolve_leaf` so it can be overruled in one place: a
    registered kind that declares no domain has told us the arrival SHAPE, not what
    the document IS. It selects no extraction — which is the live PCN24_029 case —
    so it goes to the title read rather than counting as a declared leaf.
    """
    assert content_kind.KIND_MAPPING[format_kind].domain_type is None
    read = leaf_read.resolve_leaf(
        format_kind, [_el("Title", "PRODUCT CHANGE NOTICE", box=(1, 1, 2, 2))])
    assert (read.leaf, read.leaf_source, read.outcome) == ("pcn", "title", "title")
    # This test is about the routing, so the box is only checked for being a real
    # unit-free locator; the conversion itself is pinned to literal values above.
    assert len(read.evidence_ref["bbox"]) == 4
    assert all(0.0 <= v <= 1.0 for v in read.evidence_ref["bbox"])


@pytest.mark.parametrize("declared", [None, "", "not-a-registered-kind"])
def test_an_absent_or_unregistered_kind_goes_to_the_read(declared):
    """An unregistered kind halts earlier, at the sidecar guard; this is only the
    belt, and it must not treat the string as a leaf."""
    read = leaf_read.resolve_leaf(declared, [_el("Title", "PRODUCT CHANGE NOTICE")])
    assert (read.leaf, read.leaf_source) == ("pcn", "title")


def test_the_pcn24_029_shape_end_to_end():
    """The live case: a pdf-declared drop whose document labels itself in capitals.
    Today it resolves `content_kind='pdf'`, returns origin-unresolved and writes
    nothing. The read is what gives it an answer — and the answer is a leaf that
    names a real extraction row."""
    read = leaf_read.resolve_leaf("pdf", [
        _el("NarrativeText", "Vendor Semiconductor Inc.", box=(100, 80, 600, 120)),
        _el("Title", "PRODUCT CHANGE NOTICE", box=(300, 200, 1400, 260)),
    ])
    assert read.leaf in content_kind.KIND_MAPPING
    assert content_kind.KIND_MAPPING[read.leaf].domain_type == "sustainment"
    assert read.leaf_source == "title"


def test_a_source_cannot_be_written_without_a_leaf():
    """The state that makes a column lie. Both set or both None, in every branch this
    module can take."""
    for elements in (
        [_el("Title", "PRODUCT CHANGE NOTICE")],
        [_el("Title", "PCN and PDN")],
        [_el("Title", "Table of Contents")],
        [],
    ):
        read = leaf_read.read_leaf_from_elements(elements)
        assert (read.leaf is None) == (read.leaf_source is None)


# --------------------------------------------------------------------------- #
# 7. The 2026-10-21 coordinate ruling, and the one sanctioned crossing.
#
# ARCHITECT: *"Crop coordinates: page fractions. [x0, y0, x1, y1] in 0..1, origin
# top-left, plus page. Unit-free, so no extra key, and the same everywhere
# evidence_ref appears."* And: *"doc_type_source -> leaf_source mapping, written once
# in 7f's step 5: title -> title; title-ambiguous -> no leaf, awaiting_kind with the
# candidates. Nothing else crosses."*
# --------------------------------------------------------------------------- #
def test_a_box_with_no_divisor_yields_no_box_and_says_why():
    """The hazard the ruling removes. Points with no `layout_width` cannot be made
    unit-free, and emitting the raw numbers would hand a consumer PIXELS labelled as
    fractions — a crop that is confidently wrong, which is worse than one absent.
    """
    bbox, note = leaf_read._page_fractions([300, 200, 1400, 260], None, None)
    assert bbox is None
    assert "unit-free" in note


def test_a_box_past_the_page_edge_is_clamped_and_the_clamp_is_noted():
    """A box a little over the edge is ordinary and clamping is what cutting a crop
    does anyway. One WILDLY over it means the geometry was in another space before it
    arrived, and once the numbers are unit-free the note is the only place that shows.
    """
    bbox, note = leaf_read._page_fractions([-10, 0, 1800, 2300], 1700, 2200)
    assert bbox == [0.0, 0.0, 1.0, 1.0]
    assert "clamped" in note

def test_a_box_clamped_to_NO_AREA_yields_no_box_because_it_would_drop_the_LIST():
    """Found by reading cortex's a3cf4d1 contract, not by a failing assertion.

    Their reader requires `x0 < x1` and `y0 < y1` STRICTLY, and a single bad item
    drops the WHOLE candidate list; Lane 1's live 204 answers the same box with a 422.
    Clamping a box that lies entirely past an edge collapses it to exactly that:
    `[1.0, y, 1.0, y]`. So the clamp must refuse its own degenerate output -- a
    zero-area box is worse than no box, because no box costs this candidate and a
    zero-area one costs every candidate.
    """
    for box in ([1800, 200, 1900, 260],   # entirely right of the page
                [300, -80, 1400, -10],    # entirely above the page
                [-50, 200, -10, 260]):    # entirely left of the page
        bbox, note = leaf_read._page_fractions(box, 1700, 2200)
        assert bbox is None, f"{box} clamped to a degenerate box"
        assert "no area" in note or "outside the page" in note
    # An inverted box is refused by the same line: cortex requires x0 < x1, so a
    # reversed pair is not a thin box, it is an unreadable one.
    assert leaf_read._page_fractions([1400, 200, 300, 260], 1700, 2200)[0] is None
    # And the ordinary over-the-edge case still clamps and still has area.
    bbox, note = leaf_read._page_fractions([-10, 0, 1800, 2300], 1700, 2200)
    assert bbox == [0.0, 0.0, 1.0, 1.0] and "clamped" in note



def test_the_wire_ref_carries_the_RULED_KEYS_AND_NOTHING_ELSE():
    """An extra key is a 422 at Lane 1's BFF, and cortex drops the WHOLE candidate
    list when one item is invalid. So the projection is the contract: the nine-key
    internal ref must not leak a single key past it.
    """
    read = leaf_read.read_leaf_from_elements(
        [_el("Title", "PRODUCT CHANGE NOTICE", box=(300, 200, 1400, 260))])
    wire = leaf_read.wire_evidence_ref(read.evidence_ref)
    assert set(wire) == {"page", "bbox"}
    assert wire["page"] == 1 and wire["page"] >= 1
    assert wire["bbox"] == [0.176471, 0.090909, 0.823529, 0.118182]
    # The projection must not alias the internal list: a consumer mutating what it
    # was handed would rewrite the manifest block it came from.
    wire["bbox"][0] = 9.9
    assert read.evidence_ref["bbox"][0] == 0.176471


def test_a_null_bbox_crosses_WITH_its_page_rather_than_being_dropped():
    """ARCHITECT RULING 2026-10-21 (second): *"bbox may be null; page may not. Null
    bbox means 'stated on this page, no box we can draw'."*

    The first cut of this projection dropped a boxless ref whole. That threw away the
    half that works: the card can still jump to the page, and a candidate with a page
    and no outline is strictly more locatable than one with no evidence_ref at all.
    """
    wire = leaf_read.wire_evidence_ref(
        {"page": 3, "bbox": None, "element_id": "x", "layout_width": None})
    assert wire == {"page": 3, "bbox": None}
    # `bbox` is PRESENT and null, not omitted: an absent key and a null one are the
    # same to a reader that uses .get(), but not to a schema that requires the key.
    assert "bbox" in wire


def test_a_boxless_ref_keeps_the_note_that_says_why_there_is_no_box():
    """The no-divisor case is the one that has something to say: the geometry existed
    and could not be made unit-free. Under the first cut that note died with the ref.
    """
    bbox, note = leaf_read._page_fractions([300, 200, 1400, 260], None, None)
    assert bbox is None and note
    wire = leaf_read.wire_evidence_ref({"page": 2, "bbox": bbox, "note": note})
    assert wire["page"] == 2 and wire["bbox"] is None
    assert "unit-free" in wire["note"]


def test_only_a_PAGELESS_ref_fails_to_cross():
    """*"page may not [be null]"* — so the page is the one load-bearing key, and a ref
    without one is not a locator in any sense. This is also the derived-field case:
    *"Derived fields carry no evidence_ref at all, as ruled."* A derived value is on
    no page, so it arrives here pageless and is correctly refused.
    """
    assert leaf_read.wire_evidence_ref({"page": None, "bbox": [0.1, 0.1, 0.2, 0.2]}) is None
    assert leaf_read.wire_evidence_ref({"bbox": [0.1, 0.1, 0.2, 0.2]}) is None
    assert leaf_read.wire_evidence_ref(None) is None
    assert leaf_read.wire_evidence_ref({}) is None


def test_the_wire_ref_carries_a_note_when_there_is_one():
    ref = {"page": 2, "bbox": [0.0, 0.0, 1.0, 1.0], "note": "clamped",
           "element_id": "x", "layout_width": 1700}
    assert leaf_read.wire_evidence_ref(ref) == {
        "page": 2, "bbox": [0.0, 0.0, 1.0, 1.0], "note": "clamped"}


def test_only_title_crosses_to_a_leaf_source():
    """*"title -> title; title-ambiguous -> no leaf ... Nothing else crosses."*"""
    assert leaf_read.leaf_source_for_outcome(
        leaf_read.OUTCOME_TITLE) == leaf_read.LEAF_SOURCE_TITLE
    assert leaf_read.leaf_source_for_outcome(
        leaf_read.OUTCOME_TITLE_AMBIGUOUS) is None
    # Named only as `title-ambiguous` in the ruling because that is the interesting
    # case, but a read with no evidence is equally a read that produced no leaf.
    assert leaf_read.leaf_source_for_outcome(
        leaf_read.OUTCOME_NO_TITLE_EVIDENCE) is None


@pytest.mark.parametrize("never", ["declared", "corrected", "ingest",
                                   "extraction-title", "defaulted", None, ""])
def test_declared_and_corrected_are_UNREACHABLE_from_a_read(never):
    """A declared leaf came off the drop and a corrected one came from a person. A
    title read minting either would be a provenance lie about who decided, so it is
    unreachable by construction rather than by a reviewer's care.
    """
    assert leaf_read.leaf_source_for_outcome(never) is None


def test_the_walk_emits_no_outcome_the_mapping_does_not_name():
    """The drift guard. `doc_type_from_titles` owns these strings; if one changes over
    there, this fails rather than falling through the mapping as a silent "no leaf".
    """
    seen = set()
    for titles, _expected_leaf in [
        (["PRODUCT CHANGE NOTICE"], "pcn"),
        (["PCN / PDN Combined Change and End-of-Life Notice"], None),
        (["Table of Contents"], None),
        ([], None),
    ]:
        seen.add(header_trust.doc_type_from_titles(titles)[1])
    assert seen <= set(leaf_read.READ_OUTCOMES)
    assert leaf_read.OUTCOME_DECLARED not in seen
