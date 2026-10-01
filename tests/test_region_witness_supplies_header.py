"""THE SUPPLIER: what the region witness READ actually gets written.

`tests/test_witness_regions.py` proves the regions are located and the prompt sections
resolve. `tests/test_second_witness_wiring.py` proves the crops are cut and the call is
made. Neither of those shows the step that makes the whole exercise worth paying a vision
call for: a correct reading has to reach the header.

THE DEFECT THIS FILE PINS, measured on TYC-PCN-24-210412 (2026-10-01, three fires, live
host). The region witness answered every question correctly on every fire:

    Manufacturer: TE Connectivity   Document Number: PCN-24-210412
    Notice Date: 07-JUN-24          Current Date: 10-Jun-2024
    Last Order Date: 06-JUN-2024    Last Ship Date: 07-JUN-2024

and the shipped header was still `mfr='TE Connecvity'`, `pub_date='2024-06-10'`,
`doc_level_ltb_date=None` -- 0 of 3 correct. Not because corroboration failed, but
because corroboration is a FILTER and neither wrong value was unsourced:

  - `TE Connecvity` is printed verbatim by the damaged text layer, so the broken layer
    corroborated its own misspelling and the filter had no grounds to act;
  - `2024-06-10` really is printed on the page -- it is the portal's print stamp.

A filter cannot fix recall (the same lesson as a refusal that cannot write a value the
model never produced, one field wider). So the witness supplies, and these tests pin
BOTH halves of that: that it writes the correct value, and that the two guards built
into the questions stop it writing a wrong one.
"""
import pytest

from doc_tools.utils import sustainment_header_trust as header_trust
from doc_tools.utils import witness_regions as wr


# --------------------------------------------------------------------------- #
# The real answers, verbatim from fire 1 (/tmp/fire1_regions.json on the sandbox
# pod, 2026-10-01). Copied rather than paraphrased: a hand-written fixture that
# says `Notice Date: 2024-06-07` would be testing a cooperative shape, and the
# whole point is that the model answers in the page's own typography and
# something has to normalize it.
# --------------------------------------------------------------------------- #
TYC_HEADER_ANSWER = (
    "Manufacturer: TE Connectivity\n"
    "Document Number: PCN-24-210412\n"
    "Notice Date: 07-JUN-24\n"
    "Current Date: 10-Jun-2024"
)
TYC_DATES_ANSWER = (
    "Last Order Date: 06-JUN-2024\n"
    "Last Ship Date: 07-JUN-2024\n"
    "All Dates: Last Order Date (Obsolete Parts Only): 06-JUN-2024 | "
    "Last Ship Date of Changed items (Obsolete Parts Only): 07-JUN-2024"
)


def _witness(header=TYC_HEADER_ANSWER, dates=TYC_DATES_ANSWER, page=1):
    """The witness records exactly as `_read_regions_witness` emits them."""
    out = []
    for name, text in (("header_block", header), ("estimated_dates", dates)):
        if text is None:
            continue
        out.append({"element_id": f"page_region_{page}_{name}",
                    "type": "RegionTranscription", "region": "region_image",
                    "page_number": page, "bbox": [70.0, 42.4, 1620.1, 484.6],
                    "page_width": 1700, "page_height": 2200,
                    "text": text, "text_as_html": ""})
    return out


def _degraded_header():
    """The header TYC's damaged text layer actually produced, with its citations."""
    return {"doc_id": "PCN-24-210412", "doc_type": "PCN", "revision": None,
            "mfr": "TE Connecvity", "mfr_source": "TE Connecvity",
            "pub_date": "2024-06-10", "pub_date_source": "10-Jun-2024",
            "doc_level_ltb_date": "2024-06-06", "doc_level_ltb_date_source": "-2024",
            "categories": [], "summary": None}


# --------------------------------------------------------------------------- #
# parsing the answer
# --------------------------------------------------------------------------- #

class TestParseRegionAnswer:
    def test_the_real_answers_parse_to_their_labels(self):
        got = wr.parse_region_answer(TYC_HEADER_ANSWER)
        assert got == {"manufacturer": "TE Connectivity",
                       "documentnumber": "PCN-24-210412",
                       "noticedate": "07-JUN-24",
                       "currentdate": "10-Jun-2024"}

    def test_decoration_the_model_adds_back_is_tolerated(self):
        """The prompt asks for plain text and a model returns bullets and backticks
        anyway. That is not worth a retry and must not cost a field: the decoration is
        stripped, and the VALUE is still taken verbatim inside it."""
        got = wr.parse_region_answer(
            "- `Manufacturer:` TE Connectivity\n"
            "  * Notice Date: 07-JUN-24\n"
            "• Current Date: 10-Jun-2024")
        assert got["manufacturer"] == "TE Connectivity"
        assert got["noticedate"] == "07-JUN-24"
        assert got["currentdate"] == "10-Jun-2024"

    def test_a_line_that_is_not_a_labelled_answer_is_dropped_not_guessed_at(self):
        """A model that prefaces its answer with commentary must not have the commentary
        read as a value. Dropping the line loses nothing -- the labelled answer is still
        there -- while guessing would write a sentence into `mfr`."""
        got = wr.parse_region_answer(
            "Here is what I can read in the crop:\n"
            "Manufacturer: TE Connectivity\n"
            "I could not make out the rest.")
        assert got == {"manufacturer": "TE Connectivity"}

    def test_a_repeated_label_keeps_the_first_answer(self):
        got = wr.parse_region_answer("Notice Date: 07-JUN-24\nNotice Date: 10-Jun-2024")
        assert got["noticedate"] == "07-JUN-24"

    def test_no_text_is_no_answers_rather_than_a_crash(self):
        assert wr.parse_region_answer(None) == {}
        assert wr.parse_region_answer("") == {}


# --------------------------------------------------------------------------- #
# what the witness is willing to assert
# --------------------------------------------------------------------------- #

class TestHeaderValuesFromRegions:
    def test_the_real_tyc_answers_assert_all_four_fields(self):
        values, notes = wr.header_values_from_regions(_witness())
        assert values["mfr"] == ("TE Connectivity", "TE Connectivity")
        assert values["doc_id"] == ("PCN-24-210412", "PCN-24-210412")
        # normalized to ISO, with the page's own typography kept as the citation --
        # the citation has to be verbatim on the page or the refusal that runs next
        # would reject the value this function just supplied.
        assert values["pub_date"] == ("2024-06-07", "07-JUN-24")
        assert values["doc_level_ltb_date"] == ("2024-06-06", "06-JUN-2024")
        assert notes == []

    def test_the_current_date_is_asked_for_and_never_supplied(self):
        """`Current Date:` exists in the prompt ONLY to give the print stamp somewhere
        to go that is not `pub_date`. Nothing may write it: 2024-06-10 is the exact
        wrong answer this whole mechanism was built to stop."""
        values, _ = wr.header_values_from_regions(_witness())
        assert "2024-06-10" not in [v for v, _s in values.values()]
        assert set(values) <= set(header_trust.REGION_SUPPLIABLE_FIELDS)

    def test_not_printed_supplies_nothing(self):
        """The prompt's own escape hatch. A model that cannot see a value says
        `not printed`, and that string must not be written into a header field."""
        values, notes = wr.header_values_from_regions(_witness(
            header="Manufacturer: not printed\nNotice Date: N/A\nDocument Number: -",
            dates=None))
        assert values == {}
        assert notes == []

    def test_a_date_answer_naming_no_date_is_declined_and_narrated(self):
        values, notes = wr.header_values_from_regions(_witness(
            header="Notice Date: see the attached schedule", dates=None))
        assert "pub_date" not in values
        assert any("names no single date" in n for n in notes), notes

    def test_two_dates_in_a_single_date_answer_is_a_mispairing_not_a_value(self):
        """Asked for ONE date and given two, the model has read across a row boundary --
        the known failure mode for these two-column date grids. Picking either one would
        be a coin flip written into a customer-facing field."""
        values, notes = wr.header_values_from_regions(_witness(
            header="Notice Date: 07-JUN-24 or 10-Jun-2024", dates=None))
        assert "pub_date" not in values
        assert any("names no single date" in n for n in notes), notes

    def test_a_missing_region_costs_only_its_own_fields(self):
        values, _ = wr.header_values_from_regions(_witness(dates=None))
        assert "mfr" in values and "pub_date" in values
        assert "doc_level_ltb_date" not in values

    def test_an_empty_witness_asserts_nothing(self):
        assert wr.header_values_from_regions([]) == ({}, [])
        assert wr.header_values_from_regions(None) == ({}, [])


# --------------------------------------------------------------------------- #
# THE GUARDS -- both are questions, not post-hoc checks
# --------------------------------------------------------------------------- #

class TestTheDistractorGuard:
    def test_answering_the_notice_date_with_the_print_stamp_supplies_nothing(self):
        """The measured failure, reproduced as the model collapsing the two questions.
        If `Notice Date` and `Current Date` come back as the SAME date then the
        distinction the prompt asked for was not made, and the one answer cannot be
        trusted to be the issue date rather than the stamp. Supplying it would write
        2024-06-10 -- precisely the value that was already wrong before any of this."""
        values, notes = wr.header_values_from_regions(_witness(
            header="Manufacturer: TE Connectivity\n"
                   "Notice Date: 10-Jun-2024\nCurrent Date: 10-Jun-2024"))
        assert "pub_date" not in values
        assert any("SAME date" in n for n in notes), notes
        # the guard is scoped: the other fields in the same region still come through
        assert values["mfr"] == ("TE Connectivity", "TE Connectivity")

    def test_the_same_date_in_two_typographies_still_trips_the_guard(self):
        """`07-JUN-24` and `2024-06-07` are the same calendar date printed two ways. The
        guard compares the NORMALIZED dates for exactly this reason -- a string compare
        would let a reformatted stamp through."""
        values, notes = wr.header_values_from_regions(_witness(
            header="Notice Date: 07-JUN-24\nCurrent Date: 2024-06-07", dates=None))
        assert "pub_date" not in values
        assert any("SAME date" in n for n in notes), notes

    def test_a_crop_with_no_print_stamp_supplies_the_notice_date(self):
        """The common case: most notices print no retrieval stamp at all. An absent
        distractor is not a reason to withhold the answer -- absence from a witness is
        not evidence, and treating it as a block would cost the field on eight notices
        to protect against one."""
        values, notes = wr.header_values_from_regions(_witness(
            header="Notice Date: 07-JUN-24\nCurrent Date: not printed", dates=None))
        assert values["pub_date"] == ("2024-06-07", "07-JUN-24")
        assert notes == []


class TestTheRedundantLineGuard:
    def test_a_disagreement_with_its_own_row_reading_blocks_the_supply(self):
        """`All Dates:` re-reads the block as explicit label=date pairs, so the model's
        answer can be checked against its own second reading. The dates in these grids
        are a day apart (06-JUN and 07-JUN here), which is why a mispairing is invisible
        from the value alone -- and why this cross-check is the only thing that can see
        it without the ground truth."""
        values, notes = wr.header_values_from_regions(_witness(
            header=None,
            dates="Last Order Date: 07-JUN-2024\n"
                  "All Dates: Last Order Date (Obsolete Parts Only): 06-JUN-2024 | "
                  "Last Ship Date: 07-JUN-2024"))
        assert "doc_level_ltb_date" not in values
        assert any("disagreement blocks the supply" in n for n in notes), notes

    def test_an_absent_all_dates_line_does_not_block(self):
        """Silence is not a disagreement. A crop with a single date can legitimately
        produce no pair, and refusing on that would lose the field whenever the model
        skipped the redundant question."""
        values, notes = wr.header_values_from_regions(_witness(
            header=None, dates="Last Order Date: 06-JUN-2024"))
        assert values["doc_level_ltb_date"] == ("2024-06-06", "06-JUN-2024")
        assert notes == []

    def test_an_all_dates_line_naming_no_last_order_row_does_not_block(self):
        values, notes = wr.header_values_from_regions(_witness(
            header=None,
            dates="Last Order Date: 06-JUN-2024\n"
                  "All Dates: Effective Date: 01-JUL-2024"))
        assert values["doc_level_ltb_date"] == ("2024-06-06", "06-JUN-2024")

    def test_the_label_is_matched_through_the_parenthetical_a_real_notice_prints(self):
        """ADI and TE both print `Last Order Date (Obsolete Parts Only):`. A guard that
        only matched the bare label would silently never fire on the real corpus --
        which is indistinguishable, from the outside, from a guard that works."""
        pairs = wr._all_dates_pairs(
            "Last Order Date (Obsolete Parts Only): 06-JUN-2024 | "
            "Last Ship Date of Changed items (Obsolete Parts Only): 07-JUN-2024")
        assert ("lastorderdateobsoletepartsonly", "2024-06-06") in pairs
        assert any(any(k in label for k in wr._LAST_ORDER_KEYS) for label, _ in pairs)


# --------------------------------------------------------------------------- #
# the write itself
# --------------------------------------------------------------------------- #

class TestSupplyHeaderFromRegions:
    def test_the_seal_the_three_tyc_fields_come_out_right(self):
        """What the whole build is for. Same degraded header the live run produced, same
        witness answers the live host returned, and the three ground-truth fields."""
        header_d = _degraded_header()
        reasons = header_trust.supply_header_from_regions(
            header_d, _witness(), text_layer_degraded=True)

        assert header_d["mfr"] == "TE Connectivity"
        assert header_d["pub_date"] == "2024-06-07"
        assert header_d["doc_level_ltb_date"] == "2024-06-06"
        assert len([r for r in reasons if "supplied from the region witness" in r]) == 2

    def test_the_supplied_citation_survives_the_refusal_that_runs_next(self):
        """The supplier is NOT an exemption from corroboration. `supply` then `refuse` is
        the shipped order, and the point of citing the model's verbatim answer is that
        the refusal can then find it in the witness. If this ever starts failing, a
        supplied value is being written and immediately blanked -- worse than not
        supplying it, because the narrative would claim a value that is gone."""
        header_d = _degraded_header()
        witness = _witness()
        header_trust.supply_header_from_regions(header_d, witness,
                                                text_layer_degraded=True)
        header_trust.refuse_unsourced_header_values(
            header_d, index=[], witness_index=witness, text_layer_degraded=True)

        assert header_d["mfr"] == "TE Connectivity"
        assert header_d["pub_date"] == "2024-06-07"
        assert header_d["doc_level_ltb_date"] == "2024-06-06"

    def test_a_healthy_text_layer_is_not_overwritten(self):
        """The gate is the MEASUREMENT, not a disagreement. On a healthy document the
        text layer is exact, free and complete, and a vision read that disagrees with it
        is far likelier to be the wrong one -- overwriting would trade a measured defect
        for an unmeasured one. In practice no witness is even built for a healthy
        document; this pins the behaviour if one ever is."""
        header_d = _degraded_header()
        reasons = header_trust.supply_header_from_regions(
            header_d, _witness(), text_layer_degraded=False)
        assert header_d["mfr"] == "TE Connecvity"
        assert header_d["pub_date"] == "2024-06-10"
        assert reasons == []

    def test_no_witness_is_a_no_op_not_a_blanking(self):
        """The three no-witness deployment shapes (no VISION_LLM_BASE_URL, no page
        manifest, a vision timeout) all arrive here with nothing to supply. They must
        leave the header exactly as the text layer produced it and let the ordinary
        refusal decide -- a supplier that blanked on absence would turn a missing
        endpoint into data loss."""
        for witness in (None, []):
            header_d = _degraded_header()
            assert header_trust.supply_header_from_regions(
                header_d, witness, text_layer_degraded=True) == []
            assert header_d == _degraded_header()

    def test_a_value_already_correct_is_not_narrated_as_a_substitution(self):
        """A reason string is read by a human in a review queue. "supplied ... replacing
        'TE Connectivity' with 'TE Connectivity'" is noise that makes the real
        substitutions harder to see."""
        header_d = _degraded_header()
        header_d["mfr"] = "TE Connectivity"
        reasons = header_trust.supply_header_from_regions(
            header_d, _witness(), text_layer_degraded=True)
        assert not any("header.mfr supplied" in r for r in reasons)
        assert header_d["mfr"] == "TE Connectivity"

    def test_every_write_is_narrated_with_what_it_replaced(self):
        header_d = _degraded_header()
        reasons = header_trust.supply_header_from_regions(
            header_d, _witness(), text_layer_degraded=True)
        pub = next(r for r in reasons if r.startswith("header.pub_date supplied"))
        assert "2024-06-07" in pub
        assert "2024-06-10" in pub, "the replaced value has to be in the narrative"

    def test_a_field_the_prompt_does_not_ask_about_cannot_be_supplied(self):
        """A model that volunteers an answer to a question it was not asked must not be
        able to write it. The suppliable set is a fixed list, not whatever came back."""
        header_d = _degraded_header()
        header_d["summary"] = "original"
        header_trust.supply_header_from_regions(
            header_d, _witness(header=TYC_HEADER_ANSWER + "\nSummary: rewritten by me"),
            text_layer_degraded=True)
        assert header_d["summary"] == "original"

    def test_an_unparseable_witness_degrades_rather_than_losing_the_document(self):
        """Every other failure in this path costs one field. A crash here would cost the
        whole document, in the same broad handler that would log it as an extraction
        failure -- so the narrative says so instead."""
        header_d = _degraded_header()
        reasons = header_trust.supply_header_from_regions(
            header_d, [{"element_id": "page_region_1_header_block", "text": object()}],
            text_layer_degraded=True)
        assert header_d["mfr"] == "TE Connecvity"
        assert reasons == [] or any("could not be parsed" in r for r in reasons)


# --------------------------------------------------------------------------- #
# coverage owed to the fields
# --------------------------------------------------------------------------- #

def test_every_field_a_region_claims_to_answer_has_an_answer_mapping():
    """`REGION_SPECS[*]['fields']` is the coverage this module OWES the header. A field
    listed there with no label mapped to it is a region that is paid for, cropped, asked
    and then discarded for that field -- which looks like working corroboration from
    every angle except the result."""
    mapped = {field for mapping in wr.REGION_FIELD_ANSWERS.values()
              for _label, field, _kind in mapping}
    for spec in wr.REGION_SPECS:
        for field in spec["fields"]:
            assert field in mapped, f"{spec['name']} claims {field} and cannot answer it"


def test_the_answer_mappings_only_name_fields_the_supplier_may_write():
    """The two lists are in different modules and must not drift: a label mapped to a
    field the writer refuses is a silent no-op."""
    for mapping in wr.REGION_FIELD_ANSWERS.values():
        for _label, field, _kind in mapping:
            assert field in header_trust.REGION_SUPPLIABLE_FIELDS, field


def test_every_mapped_label_is_actually_asked_by_the_committed_prompt():
    """The labels here are the keys of an agreement with the prompt file. If the prompt
    is reworded to ask `Publication Date:` and this still looks for `noticedate`, the
    parse silently returns nothing and the field is never supplied -- a defect with no
    error, no exception and no failing assertion anywhere else."""
    import pathlib
    markdown = pathlib.Path("prompts/sustainment_read_region.md").read_text(
        encoding="utf-8")
    sections = wr.split_prompt_sections(markdown)
    for region_name, mapping in wr.REGION_FIELD_ANSWERS.items():
        body = sections[region_name]
        asked = {wr._label_key(lbl) for lbl in
                 __import__("re").findall(r"`([A-Za-z][A-Za-z ()/]{0,40}?):`", body)}
        for label, field, _kind in mapping:
            assert label in asked, (
                f"{region_name} maps '{label}' -> {field} but the prompt asks {asked}")


def test_the_distractor_is_asked_by_the_prompt_and_mapped_to_nothing():
    """Both halves of the guard, in one assertion. The prompt must ASK for the current
    date (otherwise there is nothing to compare against and the guard can never fire),
    and nothing may map it to a field (otherwise the print stamp has a path into
    `pub_date` after all)."""
    import pathlib
    import re
    body = wr.split_prompt_sections(pathlib.Path(
        "prompts/sustainment_read_region.md").read_text(encoding="utf-8"))["header_block"]
    asked = {wr._label_key(lbl) for lbl in
             re.findall(r"`([A-Za-z][A-Za-z ()/]{0,40}?):`", body)}
    assert "currentdate" in asked
    mapped = {label for mapping in wr.REGION_FIELD_ANSWERS.values()
              for label, _f, _k in mapping}
    assert "currentdate" not in mapped
