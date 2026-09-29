"""A damaged text layer is a measured condition, and a measured condition can be routed on.

`TYC-PCN-24-210412` prints its own vendor name as `TE Connecvity` and the word
"Notification" as "Nofficaon". The PDF is fine -- a human reading it sees the right
words. Its embedded font has no mapping for the `ti` ligature, so every `ti` in the
document disappears on extraction. Two things then follow, and the second is the
expensive one:

  * the header refusal drops `TE Connectivity` as unsupported, which is a CORRECT value
    refused, and
  * an MPN containing `ti` would be read out of that text layer as a DIFFERENT PART
    NUMBER -- silently, with per-cell provenance, looking exactly like a good read. The
    corpus sits at 898 of 898; that is how it becomes 897 without anything going red.

So: measure the damage, and when it is present let the page's own pixels testify. These
tests pin the detector's two decisions (fires on damage, stays silent on health) and the
witness's two (a value on the page passes, a value on neither witness still refuses).

THE SYNTHETIC FIXTURE IS THE SEAL. `_strip_ti` takes a healthy control document and
deletes exactly what TYC's font deletes. The same prose therefore appears here in both
states, from one source, so a test that passes cannot be passing because two hand-written
fixtures were written to differ in a convenient way. The healthy version doubles as the
second witness, which is what the page image transcription is: the same words, read from
pixels instead of from a broken font map.
"""
import pytest

from doc_tools.utils import provenance
from doc_tools.utils import text_layer_health as H
from doc_tools.utils.sustainment_header_trust import refuse_unsourced_header_values


# --------------------------------------------------------------------------- #
# the control document, in both states
# --------------------------------------------------------------------------- #
_CONTROL_PARAGRAPHS = [
    "Product Change Notification",
    "TE Connectivity",
    "This notification informs customers that the identified parts are transitioning to "
    "a new manufacturing site. The qualification testing is complete and the "
    "certification report is available on request.",
    "Customers with further questions about this notification should contact their TE "
    "Connectivity field sales engineer, who will gather the information and coordinate "
    "the transition with the operations team.",
    "There is no change to the form, fit or function of the affected parts. The "
    "estimated date of the first shipment from the new location is stated in the "
    "attached schedule, together with the last time buy instructions.",
]


def _strip_ti(text):
    """Exactly what TYC's broken font mapping does: delete every `ti`."""
    return text.replace("ti", "")


def _el(text, page=1, etype="NarrativeText"):
    return {"type": etype, "text": text,
            "metadata": {"page_number": page,
                         "coordinates": {"points": [[0, 0], [100, 0], [100, 20], [0, 20]],
                                         "layout_width": 612, "layout_height": 792}}}


def _healthy_elements():
    return [_el(p, etype="Title" if i < 2 else "NarrativeText")
            for i, p in enumerate(_CONTROL_PARAGRAPHS)]


def _degraded_elements():
    return [_el(_strip_ti(p), etype="Title" if i < 2 else "NarrativeText")
            for i, p in enumerate(_CONTROL_PARAGRAPHS)]


@pytest.fixture
def healthy_index():
    return provenance.build_positioned_index(_healthy_elements())


@pytest.fixture
def degraded_index():
    return provenance.build_positioned_index(_degraded_elements())


# --------------------------------------------------------------------------- #
# the detector
# --------------------------------------------------------------------------- #
def test_the_control_document_reads_as_healthy():
    res = H.assess_elements(_healthy_elements())
    assert res["text_layer_degraded"] is False
    assert res["text_layer_retention"] >= H.DEGRADED_THRESHOLD
    # Judged at all -- otherwise "healthy" would only mean "too short to tell", and the
    # degraded assertion below would be measuring nothing.
    assert "ti" in res["text_layer_detail"]["judged"]


def test_deleting_ti_from_that_same_document_fires_the_detector():
    res = H.assess_elements(_degraded_elements())
    assert res["text_layer_degraded"] is True
    assert res["text_layer_retention"] < H.DEGRADED_THRESHOLD

    judged = res["text_layer_detail"]["judged"]
    fired = res["text_layer_detail"]["degraded_bigrams"]
    assert "ti" in fired
    assert judged["ti"]["retention"] == res["text_layer_retention"]

    # `ct` fires too, and that is not fixture noise -- it is collateral damage the real
    # notice takes as well. Every "-ction" word ("function", "section") carries its `ct`
    # immediately before a `ti`, so deleting the `ti` deletes the `t` that made the `ct`.
    # One missing ligature mapping damages MORE pairs than the one it maps, which is a
    # reason to judge every ligature pair rather than watch `ti` alone.
    assert "ct" in fired
    # The control pairs are what make this measurable: `th` and `er` are untouched by the
    # damage, so the document still says how much prose it contains.
    assert res["text_layer_detail"]["control_bigram_count"] > 0


def test_the_damage_is_measured_against_the_documents_own_volume_not_its_length():
    """Half the document, same verdict. An absolute count of `ti` would halve with it and
    a fixed threshold would move; the control halves too, so the ratio does not."""
    half = _degraded_elements()[:3] + _degraded_elements()[3:]
    full = H.assess_elements(_degraded_elements())
    doubled = H.assess_elements(_degraded_elements() + half)
    assert doubled["text_layer_degraded"] == full["text_layer_degraded"] is True
    assert abs(doubled["text_layer_retention"] - full["text_layer_retention"]) < 0.05


def test_a_ligature_codepoint_is_not_a_missing_ligature():
    """U+FB01 is a text layer working CORRECTLY. Counting codepoints would score a
    perfectly good document as a total `fi` loss; NFKC decomposes it first."""
    composed = "ﬁ" .join(["", ""])  # noqa: F841 -- documents the codepoint
    text = " ".join(p.replace("fi", "ﬁ") for p in _CONTROL_PARAGRAPHS)
    assert "ﬁ" in text
    res = H.assess_text_layer(text)
    plain = H.assess_text_layer(" ".join(_CONTROL_PARAGRAPHS))
    assert res["text_layer_degraded"] is False
    assert res["text_layer_retention"] == plain["text_layer_retention"]


def test_a_document_too_short_to_judge_is_not_called_damaged():
    """The honest answer to "is this text layer broken" on two sentences is "cannot
    tell", and the consequence of guessing either way is real: guessing damaged hands a
    document a second witness it did not earn."""
    res = H.assess_text_layer("Product Change Notification. One part is affected.")
    assert res["text_layer_degraded"] is False
    assert res["text_layer_retention"] is None
    assert res["text_layer_detail"]["unjudgeable"] is True


def test_empty_input_is_unjudgeable_rather_than_an_error():
    for empty in (None, "", "   "):
        res = H.assess_text_layer(empty)
        assert res["text_layer_degraded"] is False
        assert res["text_layer_retention"] is None


# --------------------------------------------------------------------------- #
# the second witness
# --------------------------------------------------------------------------- #
def test_without_a_witness_the_degraded_layer_refuses_a_correct_manufacturer(
        degraded_index):
    """The state of things before this change, and the reason for it: the vendor really
    is called TE Connectivity, the model really did read it off the page, and the field
    is emptied because the text layer cannot print it."""
    header_d = {"mfr": "TE Connectivity", "mfr_source": "TE Connectivity"}
    reasons = refuse_unsourced_header_values(header_d, degraded_index)
    assert header_d["mfr"] == ""
    assert any("refused" in r for r in reasons), reasons


def test_the_page_image_witness_lets_the_correct_manufacturer_through(
        degraded_index, healthy_index):
    """The seal. Same degraded document, same model output — but the page's own pixels
    are allowed to testify, and they print the name."""
    header_d = {"mfr": "TE Connectivity", "mfr_source": "TE Connectivity"}
    reasons = refuse_unsourced_header_values(header_d, degraded_index,
                                             witness_index=healthy_index)
    assert header_d["mfr"] == "TE Connectivity"
    assert header_d["mfr_source"] == "TE Connectivity"
    assert any("corroborated by the page image" in r for r in reasons), reasons
    assert not any("refused" in r for r in reasons), reasons


def test_a_value_on_neither_witness_is_still_refused(degraded_index, healthy_index):
    """The witness widens what counts as corroboration; it does not make the refusal
    optional. `TT Electronics` is the measured fabrication from the SEMELAB notice and it
    appears in neither the text layer nor the page."""
    header_d = {"mfr": "TT Electronics", "mfr_source": None}
    reasons = refuse_unsourced_header_values(header_d, degraded_index,
                                             witness_index=healthy_index)
    assert header_d["mfr"] == ""
    assert any("refused" in r for r in reasons), reasons
    assert not any("corroborated" in r for r in reasons), reasons


def test_the_witness_is_never_consulted_for_a_value_the_text_layer_already_prints(
        healthy_index):
    """A healthy read must not acquire a page-image citation it did not need — the
    narrative would then claim a corroboration that never happened."""
    header_d = {"mfr": "TE Connectivity", "mfr_source": None}
    reasons = refuse_unsourced_header_values(header_d, healthy_index,
                                             witness_index=healthy_index)
    assert header_d["mfr"] == "TE Connectivity"
    assert reasons == []


def test_corroboration_does_not_downgrade_provenance_of_the_untouched_fields(
        degraded_index, healthy_index):
    """Why the witness is a SEPARATE index and not extra rows appended to the first one.
    Concatenated, every string would resolve twice and `provenance.resolve_value` would
    drop each previously-unique match to `region_preferred` at confidence 0.7. Measured
    here on the mechanism itself, and note WHICH strings pay: the damage touches only the
    pairs it deletes, so every UNDAMAGED phrase -- the overwhelming majority of the
    document, and every field that was reading correctly already -- appears in both
    indexes and has its candidate count doubled by the merge."""
    both = degraded_index + healthy_index
    undamaged = "no change to the form"
    alone = provenance.resolve_value(undamaged, degraded_index, prefer_region="narrative")
    joined = provenance.resolve_value(undamaged, both, prefer_region="narrative")

    assert alone["match_method"] == "unique" and alone["match_confidence"] == 1.0
    assert joined["candidate_count"] == 2 * alone["candidate_count"]
    assert joined["match_method"] != "unique"
    assert joined["match_confidence"] < alone["match_confidence"]


# --------------------------------------------------------------------------- #
# the same witness, for parts -- the expensive half
# --------------------------------------------------------------------------- #
def _page_witness(*texts):
    """The shape `_transcribe_pages_witness` produces: one record per page."""
    return [{"element_id": f"page_ocr_{i}", "type": "PageTranscription",
             "region": "page_image", "page_number": i, "bbox": None,
             "page_width": 612, "page_height": 792, "text": t, "text_as_html": ""}
            for i, t in enumerate(texts, start=1)]


def test_an_mpn_the_page_does_not_print_is_raised():
    """The whole reason parts need the witness. A text layer missing `ti` turns
    `CTI-4200` into `C-4200`: still well formed, still plausible, still carrying correct
    per-cell provenance pointing at the cell it really came from. Nothing downstream can
    tell it from a good read -- the corpus would go from 898 to 897 with everything
    green. Only the pixels disagree."""
    parts = [{"affected_mpn": "C-4200", "replacement_mpn": None, "page_number": 1}]
    witness = _page_witness("Affected part CTI-4200 is replaced by CTI-4300.")

    flagged = H.uncorroborated_parts(parts, witness)
    assert [f["mpn"] for f in flagged] == ["C-4200"]
    assert flagged[0]["field"] == "affected_mpn"
    assert flagged[0]["page_number"] == 1


def test_an_mpn_the_page_does_print_is_left_alone():
    parts = [{"affected_mpn": "CTI-4200", "replacement_mpn": "CTI-4300",
              "page_number": 1}]
    witness = _page_witness("Affected part CTI-4200 is replaced by CTI-4300.")
    assert H.uncorroborated_parts(parts, witness) == []


def test_punctuation_and_spacing_differences_are_not_raised_as_damage():
    """A transcription sets a hyphen as an en dash and spaces a reel code differently;
    none of that is a dropped ligature. Raising it would bury the one finding that
    matters under a queue of typography, which is how a detector stops being read."""
    parts = [{"affected_mpn": "CTI-4200#REEL", "replacement_mpn": None,
              "page_number": 1}]
    witness = _page_witness("Affected part CTI–4200 # REEL is discontinued.")
    assert H.uncorroborated_parts(parts, witness) == []


def test_a_part_found_on_another_page_is_not_raised():
    """A parts table spanning a page break can carry a row whose recorded page number is
    the table's, not the row's. That is an off-by-one in bookkeeping, not a misread part,
    and flagging it would train a reviewer to ignore the flag."""
    parts = [{"affected_mpn": "CTI-4200", "replacement_mpn": None, "page_number": 1}]
    witness = _page_witness("Continued from previous page.",
                            "Affected part CTI-4200 is discontinued.")
    assert H.uncorroborated_parts(parts, witness) == []


def test_a_tier_one_row_reports_the_page_it_actually_carries():
    """THE ROW SHAPE THIS CHECK IS FOR. A tier-1 (text-layer) part row records its page as
    `text_layer_page` and has no `page_number` key whatsoever -- `sustainment_merge` reads
    `p.get("text_layer_page")` to build every review item's provenance. Reading only
    `page_number` here does not miss the finding, because the whole-witness fallback still
    matches; it degrades silently to reporting page None on exactly the population this
    check exists to protect, stripping the reviewer of the one thing they open the PDF
    by. Tier 1 is the tier that reads MPNs off the damaged text layer."""
    parts = [{"affected_mpn": "C-4200", "replacement_mpn": None, "text_layer_page": 2}]
    witness = _page_witness("Page one prose.", "Affected part CTI-4200 is discontinued.")

    flagged = H.uncorroborated_parts(parts, witness)
    assert [f["page_number"] for f in flagged] == [2]


def test_no_witness_means_no_accusation():
    """An absent witness is not evidence against anything. If vision is unavailable or
    every page failed to transcribe, the correct output is silence -- not a queue
    declaring every part in the document uncorroborated."""
    parts = [{"affected_mpn": "CTI-4200", "replacement_mpn": None, "page_number": 1}]
    for witness in (None, []):
        assert H.uncorroborated_parts(parts, witness) == []
    assert H.uncorroborated_parts(None, _page_witness("anything")) == []


def test_a_witness_that_failed_to_transcribe_changes_nothing(degraded_index):
    """Vision can time out, and an empty or absent witness must degrade to exactly the
    behaviour before this change rather than to an exception."""
    for witness in (None, [], provenance.build_positioned_index([])):
        header_d = {"mfr": "TE Connectivity", "mfr_source": None}
        refuse_unsourced_header_values(header_d, degraded_index, witness_index=witness)
        assert header_d["mfr"] == ""
