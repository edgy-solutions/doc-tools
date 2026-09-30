"""When the model names a manufacturer the document does not, the DOCUMENT's own name
is written — if the document unambiguously has one.

The refusal in `test_header_source_refusal.py` closed the fabrication hole by dropping a
value the document never prints. That left a measured residual on
`onsemi_Generic_IPCN25300X`: one fire in three emitted `ON Semiconductor`, a string the
notice never prints, so `mfr` was written EMPTY — while the same notice printed `onsemi`
six times in its own prose. The refusal could see the nominated value was unsupported and
had no way to reach the supported one beside it.

So the model nominates and the document is the source, which is the standard the parts
side already holds MPNs to. These tests pin the three outcomes that matter: the recovery
that should happen, and the two that must NOT.

THE REGRESSION GUARD IS THE POINT OF THIS FILE. `EOL-36_BYV34-400,-BYV34-500` is the
SEMELAB notice that produced the original `TT Electronics` fabrication, and its footer
really does print `https://www.ttelectronics.com/brands/semelab/`. A recovery rule that
tokenized URLs would read `ttelectronics` out of that footer and WRITE it — the refusal
re-supplying, one layer down, the exact value it was built to refuse. That case is
`test_a_vendor_url_is_not_a_name_...` below and it is the reason the rule excludes
URL and email tokens at all.

Pure, no LLM: hand-built positioned indexes in the element shape
`provenance.build_positioned_index` produces, same as the refusal tests.
"""
from doc_tools.utils import provenance
from doc_tools.utils.sustainment_header_trust import (
    recover_mfr_from_document,
    refuse_unsourced_header_values,
)


def _el(text, page=1, html="", etype="NarrativeText"):
    return {"type": etype, "text": text,
            "metadata": {"page_number": page,
                         "coordinates": {"points": [[0, 0], [100, 0], [100, 20], [0, 20]],
                                         "layout_width": 612, "layout_height": 792},
                         "text_as_html": html}}


def _onsemi_index():
    """The measured shape of `onsemi_Generic_IPCN25300X`: the name in prose six times,
    the wordmark truncated to `ONSEM.`, and the contact address — which is the only
    place the string `onsemi` appears attached to a domain."""
    return provenance.build_positioned_index([
        _el("ONSEM.", etype="Title"),
        _el("Initial Product/Process Change Notification"),
        _el("onsemi is notifying it customers of the following change."),
        _el("Please contact your local onsemi Sales Office with questions."),
        _el("For further information contact PCN.Support@onsemi.com"),
        _el("onsemi reserves the right to make changes without notice."),
        _el("ONSEM.", etype="Title"),
    ])


def _semelab_index():
    """`EOL-36_BYV34-400,-BYV34-500`: SEMELAB in prose, and a TT Electronics URL in the
    footer — the footer really is printed, which is what made the fabrication resolve."""
    return provenance.build_positioned_index([
        _el("SENSORS AND SPECIALIST COMPONENTS", etype="Title"),
        _el("This notice is issued by SEMELAB PLC regarding discontinuance."),
        _el("https://www.ttelectronics.com/brands/semelab/"),
        _el("Contact quality@ttelectronics.com for further information."),
    ])


def _tyc_index():
    """`TYC-PCN-24-210412`, whose text layer drops `ti` document-wide: the name is
    printed only as the damaged `TE Connecvity`."""
    return provenance.build_positioned_index([
        _el("Product Change Nofficaon", etype="Title"),
        _el("TE Connecvity", etype="Title"),
        _el("For quesons, please contact your TE Connecvity Sales Engineer."),
        _el("www.te.com"),
    ])


# --------------------------------------------------------------------------- #
# the recovery that should happen
# --------------------------------------------------------------------------- #
def test_the_document_name_is_written_when_the_model_names_an_expansion_it_lacks():
    value, source = recover_mfr_from_document("ON Semiconductor", _onsemi_index())
    assert value == "onsemi"
    # The source is the located text, not the model's snippet — the same convention
    # `locate_header_source` established for every other sourced field.
    assert source == "onsemi"


def test_the_refusal_writes_the_recovered_name_instead_of_emptying_the_field():
    """End to end through the refusal: this is the residual the measurement named."""
    header_d = {"mfr": "ON Semiconductor", "mfr_source": "onsemi is a supplier"}
    reasons = refuse_unsourced_header_values(header_d, _onsemi_index())

    assert header_d["mfr"] == "onsemi"
    assert header_d["mfr_source"] == "onsemi"
    # The substitution is visible in the narrative. A written value that did not come
    # from the model is exactly what a human reviewing the notice has to be able to see.
    assert any("recovered" in r and "onsemi" in r for r in reasons), reasons
    assert not header_d.get("needs_review")


def test_the_recovered_value_survives_a_second_pass_of_the_very_check_that_refused():
    """Idempotence, and it is not a formality: the recovered value is written by the
    refusal, so if it could not itself pass the refusal the pipeline would blank it on
    any later re-check and the recovery would be silently undone."""
    header_d = {"mfr": "ON Semiconductor", "mfr_source": None}
    refuse_unsourced_header_values(header_d, _onsemi_index())
    first = dict(header_d)

    reasons = refuse_unsourced_header_values(header_d, _onsemi_index())
    assert header_d == first
    assert not [r for r in reasons if "refused" in r]


def test_a_truncated_wordmark_does_not_count_as_a_second_candidate():
    """`ONSEM.` and `onsemi` are one name at two truncations, not two names: `onsem`
    opens `onsemi`. The rule collapses the chain and writes the longest, so the wordmark
    must not make the document look ambiguous."""
    value, _ = recover_mfr_from_document("ON Semiconductor", _onsemi_index())
    assert value == "onsemi"


# --------------------------------------------------------------------------- #
# the two recoveries that must NOT happen
# --------------------------------------------------------------------------- #
def test_a_vendor_url_is_not_a_name_and_cannot_resupply_the_original_fabrication():
    """THE regression guard. `TT Electronics` is the measured fabrication on the SEMELAB
    notice. Its footer prints a ttelectronics.com URL, so a rule that read names out of
    URLs would recover `ttelectronics` and write it — the refusal handing back the value
    it exists to refuse. A domain says where the document is hosted, not who made the
    part."""
    value, source = recover_mfr_from_document("TT Electronics", _semelab_index())
    assert value is None
    assert source is None


def test_the_fabrication_still_ends_as_an_empty_field_through_the_refusal():
    header_d = {"mfr": "TT Electronics", "mfr_source": None}
    reasons = refuse_unsourced_header_values(header_d, _semelab_index())
    assert header_d["mfr"] == ""
    assert header_d["mfr_source"] is None
    assert any("refused" in r for r in reasons), reasons
    assert not any("recovered" in r for r in reasons), reasons


def test_a_damaged_text_layer_is_not_a_naming_disagreement_and_is_not_recovered():
    """TYC prints `TE Connecvity` because its font drops `ti`, not because the vendor is
    called that. `teconnecvity` is not a contraction of `teconnectivity` — it diverges
    mid-string — so nothing is recovered and the field stays empty. Preferring the
    printed form here would write a MISSPELLED manufacturer into the graph, which is
    worse than writing nothing. The answer to this notice is a second witness, not a
    precedence rule."""
    value, _ = recover_mfr_from_document("TE Connectivity", _tyc_index())
    assert value is None

    # `text_layer_degraded=True` is what the plugin passes for this notice, from the
    # measurement in `text_layer_health.assess_elements` (TYC is the 1 of 9 that trips
    # it). It is stated rather than inferred because `witness_index=None` cannot carry
    # it — see the companion test below for what it buys.
    header_d = {"mfr": "TE Connectivity", "mfr_source": None}
    refuse_unsourced_header_values(header_d, _tyc_index(), text_layer_degraded=True)
    assert header_d["mfr"] == ""


def test_document_wins_is_off_ONLY_because_the_caller_measured_the_damage():
    """The companion to the test above, and the reason the plugin call site is part of
    this change rather than a follow-up. Document-wins has no way to see that
    `TE Connecvity` is a misspelling — it is a standalone Title of perfect name shape, so
    on the DEFAULT (undamaged) path it is read and written. The flag is the whole
    protection; a caller that forgets it puts the misspelling in the graph."""
    header_d = {"mfr": "TE Connectivity", "mfr_source": None}
    refuse_unsourced_header_values(header_d, _tyc_index())
    assert header_d["mfr"] == "TE Connecvity"


# --------------------------------------------------------------------------- #
# the guards the rule rests on
# --------------------------------------------------------------------------- #
def test_two_candidates_cannot_diverge_so_the_longest_is_always_the_whole_answer():
    """Written after trying to build the opposite fixture and failing. Every candidate is
    a prefix of the SAME nomination, and prefixes of one string are totally ordered — so
    a pair that disagrees about the name cannot exist, and the collapse to the longest is
    never a choice between rival readings. `Nipponden` below does not open
    `nipponseiden`, so it is not a candidate at all; only the chain survives."""
    index = provenance.build_positioned_index([
        _el("Nipponsei and Nipponden both appear, and Nipponseid too."),
    ])
    assert recover_mfr_from_document("Nippon Seiden", index) == ("Nipponseid",
                                                                 "Nipponseid")


def test_a_candidate_that_is_only_the_first_word_identifies_nobody():
    """Caught by the test above before the rule had this guard: `Micro` opens
    `Micro Devices Micronics Holdings`, is printed, is unique — and would have been
    WRITTEN as the manufacturer on the strength of one shared word. A contraction has to
    reach past the head of the name, the way `onsemi` reaches into `Semiconductor`."""
    index = provenance.build_positioned_index([
        _el("Micro Devices and Micronics jointly issue this notice."),
    ])
    assert recover_mfr_from_document("Micro Devices Micronics Holdings", index) == (None,
                                                                                    None)


def test_a_single_word_nomination_is_never_contracted():
    """A truncation of one word is a shorter word, not a trade name."""
    index = provenance.build_positioned_index([_el("Microch issued this notice.")])
    assert recover_mfr_from_document("Microchip", index) == (None, None)


def test_an_initialism_is_too_short_to_identify_anyone():
    """`TE` opens TECONNECTIVITY and equally TEXASINSTRUMENTS; a two-letter token is not
    evidence of which. The four-character floor is what keeps the rule from matching on
    a coincidence."""
    index = provenance.build_positioned_index([_el("TE is the issuing entity.")])
    assert recover_mfr_from_document("TE Connectivity", index) == (None, None)


def test_a_nomination_too_short_to_search_recovers_nothing():
    index = provenance.build_positioned_index([_el("onsemi issues this notice.")])
    assert recover_mfr_from_document("ON", index) == (None, None)


def test_a_name_in_a_parts_table_is_not_a_document_level_manufacturer():
    """Region preference, same as `locate_header_source`: a manufacturer reads off the
    notice's prose, not out of a row of a parts table where a component's own maker may
    appear."""
    index = provenance.build_positioned_index([
        _el("Affected parts follow.", etype="Table"),
        _el("onsemi", etype="Table"),
    ])
    assert recover_mfr_from_document("ON Semiconductor", index) == (None, None)


def test_recovery_never_runs_for_a_value_the_document_does_print():
    """A verbatim value is untouched — recovery is reached only after a refusal, so it
    can never overwrite a good read."""
    header_d = {"mfr": "onsemi", "mfr_source": None}
    reasons = refuse_unsourced_header_values(header_d, _onsemi_index())
    assert header_d["mfr"] == "onsemi"
    assert not any("recovered" in r for r in reasons), reasons


def test_dates_are_not_recoverable_because_a_document_prints_many_of_them():
    """Only `mfr` is recoverable. A notice prints several dates and nothing in the text
    says which is the publication date, so "the document supports exactly one candidate"
    is never true there and a recovery would be a guess wearing a citation."""
    from doc_tools.utils.sustainment_header_trust import _RECOVERABLE
    assert set(_RECOVERABLE) == {"mfr"}
