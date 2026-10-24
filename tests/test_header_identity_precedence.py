"""THE HEADER IDENTITY PRECEDENCE — the text layer reads first, the model corroborates.

The architect's ruling of 2026-10-24, for ``doc_id``, ``mfr``, ``pub_date`` and
``doc_level_ltb_date`` alike:

 1. A text-layer value, when the arm yields one, IS the written value. The header
    (model) pass corroborates it; a disagreement keeps the text-layer value and sets
    ``needs_review`` with BOTH values in the reason.
 2. The model pass fills only what the text layer did not yield, and every model-filled
    field marks ``needs_review=true``.
 3. A model ``AbortError`` with a text-layer value present is not a failure of the
    field; with none present, the field is absent and ``needs_review=true``, never a
    filename.

SEALED ON ADI ``PCN-24_0003``'s OWN ``review.json`` SHAPE, as ordered. That document is
why the ruling exists, and its two review.json copies are the measurement:

    v0.2.0  doc_id='PCN-24_0003'  part rows 0     needs_review=False  reasons 0
    v0.2.1  doc_id='PCN-24_0003'  part rows 1571  needs_review=True   reasons 6
              - header pass failed: AbortError
              - header.mfr not written: the header pass returned none and the
                document does not name one itself
              ...

So the shape held here is: a header pass that DIED, a ``doc_id`` that is nevertheless
``PCN-24_0003`` because the page prints it, an ``mfr`` that is absent because the page
does not, and ``needs_review`` true. ``TestClauseThreeTheHeaderPassDied`` is that shape.

THE ABORT IS REAL, NOT STUBBED AT THE SEAM. ``_FakeHeaderAborts.ExtractHeader`` RAISES,
so the plugin's own ``except`` arm is what records the failure — the same path 24_0003
took. Stubbing ``_extract_header`` to return ``None`` would have skipped the one line
under test. The fake is a fake of the MODEL; every assertion is on the plugin's own
output.

WHY THE ARM-LEVEL CLASSES EXIST TOO. Clause 1's disagreement needs a model value and a
document value that differ, which is two lines on the arm and a whole fixture through the
plugin. The plugin class seals the WIRING (that the arm runs at all, in the right order,
and reaches review.json); the arm classes seal the DECISIONS. A pure-module test alone
would have been green on the day the field was lost -- the lesson of
tests/test_sustainment_zero_part_flag.py -- so both halves are here.

WHY THE ARM-LEVEL FIXTURE IS NOT AN ADI PAGE, which is not a detail: this arm CANNOT
read ADI's name. See ``TestTheArmsOwnShapeTests`` -- measured, and a defect the
precedence ruling does not reach.

``doc_id``'s own arm has its own file, tests/test_doc_id_text_layer_arm.py, where the key
fallback and ``doc_id_raw`` live; two tests there were REVERSED by this ruling and say so.
"""
import pytest

from doc_tools.baml_client import sync_client as sync_client_module
from doc_tools.plugins.sustainment import SustainmentPlugin
from doc_tools.utils import provenance
from doc_tools.utils import sustainment_header_trust as trust


# --------------------------------------------------------------------------- #
# the fixture
# --------------------------------------------------------------------------- #
# Five paragraphs, carried over from tests/test_doc_id_text_layer_arm.py, because their
# LIGATURE PROFILE is measured: `text_layer_health.assess_elements` judges this text
# healthy (worst retention 0.54 against a 0.35 threshold) and a paraphrase of it does not
# necessarily do so. A fixture the health witness calls degraded gates every arm under
# test OFF, and the clause-3 class then passes for the wrong reason -- which is exactly
# what the first run of this file did.
_PARAGRAPHS = [
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

PRINTED_DOC_ID = "PCN-24_0003"

# The pipeline key, derived from the FILE. Clause 3 says the field is never a filename,
# and this is the string that would appear if it were.
PIPELINE_KEY = "ADI_PCN_24_0003_Rev_-_Form_pdf"


def _el(text, el_type="NarrativeText", page=1):
    return {"type": el_type, "text": text,
            "metadata": {"page_number": page,
                         "coordinates": {"points": [[0, 0], [100, 0], [100, 20], [0, 20]],
                                         "layout_width": 612, "layout_height": 792}}}


def _elements(names_itself=True, printed=None):
    """The control page. `names_itself` keeps or drops the standalone brand heading;
    `printed` appends a run containing a notice number."""
    paras = _PARAGRAPHS if names_itself else [_PARAGRAPHS[0]] + _PARAGRAPHS[2:]
    titles = 2 if names_itself else 1
    els = [_el(p, "Title" if i < titles else "NarrativeText")
           for i, p in enumerate(paras)]
    if printed:
        els.append(_el(f"Product Change Notification: {printed} Rev -"))
    return els


def _index(names_itself=True):
    return provenance.build_positioned_index(_elements(names_itself=names_itself))


# === Clause 1: the arm reads first, the model corroborates ================= #


class TestClauseOneTheTextLayerWins:
    def test_a_disagreement_keeps_the_text_layer_value(self):
        """The behaviour the ruling CHANGES. Before it the cascade was MODEL-FIRST: the
        document was asked only once the model's value had failed the verbatim check, so
        a model `mfr` printed SOMEWHERE in the document passed and was kept even where
        the document's own heading named a different manufacturer. The two readings never
        met. Now the arm reads first and the model's value becomes corroboration."""
        header_d = {"mfr": "Linear Technology", "mfr_source": "Linear Technology"}
        _, needs_review, arms = trust.apply_text_layer_primacy(header_d, _index())

        assert header_d["mfr"] == "TE Connectivity"
        assert needs_review is True
        assert arms["mfr"]["origin"] == "document"
        assert arms["mfr"]["agrees"] is False

    def test_the_reason_carries_BOTH_values(self):
        """Ordered explicitly: "with both values in the reason". A reason naming only the
        winner leaves the human re-deriving what was discarded, which is the one thing
        the review exists to show them."""
        header_d = {"mfr": "Linear Technology", "mfr_source": "Linear Technology"}
        reasons, _, _ = trust.apply_text_layer_primacy(header_d, _index())

        joined = " ".join(reasons)
        assert "TE Connectivity" in joined, "the written value is missing from the reason"
        assert "Linear Technology" in joined, "the DISCARDED value is missing"

    def test_agreement_is_silent_and_forces_no_review(self):
        """Corroboration is the normal case: it must not put a line in every document's
        narrative, nor flag it. Compared on `_name_key`, so a casing difference is not
        reported as a disagreement a human then has to dismiss."""
        header_d = {"mfr": "TE CONNECTIVITY", "mfr_source": "TE CONNECTIVITY"}
        reasons, needs_review, arms = trust.apply_text_layer_primacy(header_d, _index())

        assert header_d["mfr"] == "TE Connectivity"
        assert arms["mfr"]["agrees"] is True
        assert needs_review is False
        assert reasons == []

    def test_a_model_silent_field_records_which_arm_wrote_it_without_flagging(self):
        """Not a clause of the ruling, and kept deliberately: before it,
        `_DOCUMENT_WINS` was consulted from the unsourced refusal even when the model
        returned nothing, and the reason it left was the only place a reader could see
        that the DOCUMENT supplied the value. Moving the arm in front of the model
        removed that line (measured: it broke
        tests/test_mfr_survives_a_cut_header.py::test_the_record_says_which_arm_wrote_it)
        so it is re-emitted here. No review: clause 1 makes this reading authoritative,
        and `needs_review` is a corpus-gate exemption that must not be spent on the
        normal case."""
        header_d = {"mfr": None, "mfr_source": None}
        reasons, needs_review, arms = trust.apply_text_layer_primacy(header_d, _index())

        assert header_d["mfr"] == "TE Connectivity"
        assert arms["mfr"]["origin"] == "document"
        assert arms["mfr"]["agrees"] is None, "nothing was there to agree with"
        assert needs_review is False
        assert len(reasons) == 1 and "TE Connectivity" in reasons[0]

    def test_the_arm_writes_its_own_source_not_the_models(self):
        """A value written from the text layer must carry the run it was read out of, or
        the unsourced refusal that follows checks the new value against the old
        citation."""
        header_d = {"mfr": "Linear Technology", "mfr_source": "a snippet nobody checked"}
        trust.apply_text_layer_primacy(header_d, _index())

        assert header_d["mfr_source"] == "TE Connectivity"


# === Clause 2: the model fills only what the arm did not yield ============= #


class TestClauseTwoAModelFilledFieldIsFlagged:
    def test_a_model_filled_mfr_forces_review(self):
        """No text-layer reading stands behind it. The document here names nobody, so
        the arm declines and the model's value is the only one — written, and flagged
        because of that."""
        header_d = {"mfr": "Analog Devices", "mfr_source": "Analog Devices"}
        reasons, needs_review, arms = trust.apply_text_layer_primacy(
            header_d, _index(names_itself=False))

        assert header_d["mfr"] == "Analog Devices", "clause 2 writes it, it only flags"
        assert arms["mfr"]["origin"] == "model"
        assert needs_review is True
        assert any("filled by the header pass" in r for r in reasons)

    def test_a_field_neither_side_yields_is_not_flagged_by_this_arm(self):
        """An absent `doc_level_ltb_date` is the COMMON case. Clause 2 is about a value
        the model DID produce; flagging a field nobody claimed would put a spurious
        review on most of the corpus."""
        reasons, needs_review, arms = trust.apply_text_layer_primacy(
            {}, _index(names_itself=False))

        assert arms["doc_level_ltb_date"]["origin"] is None
        assert needs_review is False
        assert reasons == []


class TestTheFieldsWithNoArm:
    """`pub_date` and `doc_level_ltb_date` have no text-layer arm, so clause 1 is vacuous
    for them and clause 2 governs. Sealed so that adding an arm later is a deliberate act
    that has to come past a test saying what the behaviour was before it.

    Why no arm yet — the measured reason, not a shrug. `TYC-PCN-24-210412` returned
    `pub_date` 2024-06-10 and PASSED the verbatim check, because that date really is
    printed: it is the portal's PRINT STAMP, not the issue date. An arm reading the first
    date-shaped run off the header block would make that wrong answer AUTHORITATIVE
    rather than merely corroborated, which is worse than having no arm at all.
    """

    @pytest.mark.parametrize("field", ["pub_date", "doc_level_ltb_date"])
    def test_the_arm_is_absent_and_the_instrument_says_so(self, field):
        header_d = {field: "2024-06-10", f"{field}_source": "Date: 2024-06-10"}
        reasons, needs_review, arms = trust.apply_text_layer_primacy(
            header_d, _index(names_itself=False))

        assert arms[field]["has_text_layer_arm"] is False
        assert arms[field]["origin"] == "model"
        assert arms[field]["document_value"] is None
        assert needs_review is True
        assert any("no text-layer arm" in r for r in reasons)

    @pytest.mark.parametrize("field", ["pub_date", "doc_level_ltb_date"])
    def test_the_value_itself_is_untouched(self, field):
        """Clause 2 flags; it does not blank. The unsourced refusal that runs after this
        is what can still drop the value, and that is a separate decision."""
        header_d = {field: "2024-06-10", f"{field}_source": "Date: 2024-06-10"}
        trust.apply_text_layer_primacy(header_d, _index(names_itself=False))

        assert header_d[field] == "2024-06-10"


class TestTheDegradedGate:
    """The arm is switched OFF on a MEASURED-degraded text layer, for the same reason
    `_DOCUMENT_WINS` is: a damaged layer cannot be trusted to SPELL a name.
    `TYC-PCN-24-210412`'s embedded font drops every `ti`, so it prints `TE Connecvity`
    — making that layer PRIMARY there would promote the misspelling from refused to
    authoritative. On those documents the region witness supplies the value.
    """

    def test_the_document_is_not_asked_and_the_model_stands(self):
        header_d = {"mfr": "Linear Technology", "mfr_source": "Linear Technology"}
        _, needs_review, arms = trust.apply_text_layer_primacy(
            header_d, _index(), text_layer_degraded=True)

        assert header_d["mfr"] == "Linear Technology"
        assert arms["mfr"]["document_value"] is None
        assert arms["mfr"]["gated_off_degraded"] is True
        # Still clause 2: nothing in the text layer stands behind the value, and on a
        # degraded document that is the honest reading rather than a second-class one.
        assert arms["mfr"]["origin"] == "model"
        assert needs_review is True


class TestTheArmsOwnShapeTests:
    """A SEPARATE DEFECT, measured while sealing the ruling, recorded here because the
    next person to read 24_0003's `header.mfr not written` will otherwise conclude the
    page prints no manufacturer.

    `_is_name_shaped` refuses `Analog Devices`, because `devices` is in
    `_FURNITURE_WORDS`, and `ON Semiconductor`, because `on` is in `_CONNECTIVE_WORDS`.
    The arm's own comments name both as names it covers (`_MAX_NAME_TOKENS`: "Three
    tokens covers `Analog Devices, Inc.`, `Texas Instruments Incorporated`,
    `ON Semiconductor` and `TT Electronics`"), so this is a contradiction between the
    code and its stated intent, not a judgement that was made and written down.

    NOT FIXED IN THE PRECEDENCE PR, deliberately. Dropping `devices` makes the heading
    `Devices Affected` name-shaped, which on a page that also prints a brand heading
    leaves TWO surviving candidates, and the uniqueness rule then REFUSES -- so the fix
    can take an `mfr` the corpus writes today and blank it. That is a corpus measurement,
    not a drive-by. The tests below assert the behaviour AS IT IS so that changing it is
    deliberate and arrives with that measurement.
    """

    @pytest.mark.parametrize("name", ["Analog Devices", "Analog Devices, Inc.",
                                      "ON Semiconductor"])
    def test_these_real_manufacturer_names_are_refused_today(self, name):
        assert trust._is_name_shaped(name) is False, (
            f"{name!r} is now name-shaped: good, but the uniqueness rule has to be "
            "re-measured against the corpus before this is shipped")

    @pytest.mark.parametrize("name", ["TE Connectivity", "Texas Instruments"])
    def test_and_these_are_accepted_so_the_test_above_is_not_vacuous(self, name):
        assert trust._is_name_shaped(name) is True

    def test_the_consequence_a_page_that_names_adi_yields_nothing(self):
        """The whole arm, not just the predicate: a page printing `Analog Devices` as a
        standalone heading and again in its narrative still yields no manufacturer."""
        els = _elements()
        els[1] = _el("Analog Devices", "Title")
        els[3] = _el("Customers with further questions should contact their Analog "
                     "Devices field sales engineer, who will coordinate the transition.")
        assert trust.mfr_from_document(provenance.build_positioned_index(els)) == (
            None, None)


# === Clause 3: the 24_0003 shape, on the real dispatch ===================== #


class _FakeHeaderAborts:
    """The header pass DIES. 24_0003's review.json records `header pass failed:
    AbortError`, and this is that: the plugin's own `except` arm records the failure and
    leaves `header` None.
    """

    def ExtractHeader(self, doc, system_instructions, baml_options=None):
        raise RuntimeError("AbortError")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "file")
    monkeypatch.delenv("VISION_LLM_BASE_URL", raising=False)


def _run(monkeypatch, printed=None):
    """The real `_extract_fulltext` dispatch, with only the model faked. The page names
    no manufacturer, as 24_0003's review.json reports of its own."""
    monkeypatch.setattr(sync_client_module, "b", _FakeHeaderAborts())
    els = _elements(names_itself=False, printed=printed)
    plugin = SustainmentPlugin(domain_type="sustainment")
    nodes = plugin._extract_fulltext(
        " ".join(e["text"] for e in els), PIPELINE_KEY, elements=els)
    return nodes[0].domain_augmentation


class TestClauseThreeTheHeaderPassDied:
    def test_the_abort_is_recorded_at_all(self, monkeypatch):
        """The control for every assertion below: if the fake stopped raising, the rest
        of this class would be testing a healthy pass and still look green."""
        aug = _run(monkeypatch, printed=PRINTED_DOC_ID)

        assert any("header pass failed" in r for r in aug.review_reasons)

    def test_the_text_layer_is_healthy_so_no_arm_is_gated_off(self, monkeypatch):
        """The second control, and the one the first draft of this file needed: a
        degraded fixture switches every arm under test off, and the assertions below
        then pass while measuring nothing."""
        aug = _run(monkeypatch, printed=PRINTED_DOC_ID)

        assert aug.stats["text_layer_degraded"] is False

    def test_the_doc_id_the_page_prints_survives_a_dead_header_pass(self, monkeypatch):
        """THE SHAPE, as 24_0003's review.json carries it: the pass failed and the notice
        number is still the one printed on the page."""
        aug = _run(monkeypatch, printed=PRINTED_DOC_ID)

        assert aug.notice.doc_id == PRINTED_DOC_ID
        assert aug.stats["doc_id_arm"]["origin"] == "document"
        assert aug.review["doc_id_raw"] == PRINTED_DOC_ID

    def test_the_surviving_field_is_named_as_the_text_layers_own(self, monkeypatch):
        """Clause 3's words: the model's failure "is not a failure of the field". The
        pass failure alone reads as "no identity was extracted", and on this document
        that is measurably false."""
        aug = _run(monkeypatch, printed=PRINTED_DOC_ID)

        assert any("not affected by it" in r and "doc_id" in r
                   for r in aug.review_reasons)

    def test_a_field_the_page_does_not_print_is_absent_not_invented(self, monkeypatch):
        """24_0003's review.json: "header.mfr not written: the header pass returned none
        and the document does not name one itself". Absent is the correct answer."""
        aug = _run(monkeypatch, printed=PRINTED_DOC_ID)

        assert not aug.notice.mfr
        assert aug.needs_review is True

    def test_with_nothing_printed_the_doc_id_is_NEVER_the_filename(self, monkeypatch):
        """The other half of clause 3, and the defect it closes. `doc_id` is a KEY and
        must not be null, so the pipeline id stays in that slot — but the DISPLAY field
        must not present it as an extracted notice number. Measured precedent:
        fa231498 / 0096a523, two 606-byte PDFs named PCN23-002.pdf whose header pass
        produced nothing and whose review payload offered `PCN23-002` as "the raw printed
        notice number".
        """
        aug = _run(monkeypatch)

        assert aug.review["doc_id_raw"] is None, (
            "the filename-derived key reached the display field")
        assert aug.stats["doc_id_arm"]["origin"] is None
        assert any("absent, not defaulted" in r for r in aug.review_reasons)
        assert aug.needs_review is True

    def test_the_absent_fields_are_named_rather_than_left_to_inference(self, monkeypatch):
        """A reader of the narrative must not have to work out which fields are gone by
        elimination."""
        aug = _run(monkeypatch, printed=PRINTED_DOC_ID)

        absent_line = [r for r in aug.review_reasons if "absent, not defaulted" in r]
        assert len(absent_line) == 1
        for field in ("mfr", "pub_date", "doc_level_ltb_date"):
            assert field in absent_line[0], field
        assert "doc_id" not in absent_line[0], (
            "doc_id was read off the page; naming it absent would be false")


class TestTheInstrument:
    def test_every_ruled_field_is_instrumented(self, monkeypatch):
        """The corpus gate has no header ground truth for these fields, so the arms are
        the only way to tell afterwards which reading was used. All four of the ruling's
        fields must be visible: three in `header_identity_arms` and `doc_id` in its own
        `doc_id_arm`, which is where its key handling lives."""
        aug = _run(monkeypatch, printed=PRINTED_DOC_ID)

        arms = aug.stats["header_identity_arms"]
        assert set(arms) == {"mfr", "pub_date", "doc_level_ltb_date"}
        assert aug.stats["doc_id_arm"], "doc_id's arm is instrumented separately"
        for field, arm in arms.items():
            assert set(arm) >= {"origin", "document_value", "model_value", "agrees",
                                "has_text_layer_arm", "gated_off_degraded"}, field
