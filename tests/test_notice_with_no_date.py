"""A NOTICE WITH NO DATE IS A VALID NOTICE — and a failed header still proposes.

Two defects, one shape, both ordered 2026-11-18.

ORDER A: "the header extraction rejects a null publication date although its own
prompt allows null. The schema and the prompt must agree; a notice with no date is a
valid notice."

    The mechanism, and why it is not a cosmetic field problem: `pub_date` was declared
    `string` (required) in baml_src/sustainment.baml, so BAML could not coerce the null
    the model correctly returned for an undated notice, and `ExtractHeader` RAISED. The
    plugin's `except` arm then set `header = None` and the pipeline fell back to
    `sustainment_merge.empty_header(doc_id)` — losing doc_id, mfr, doc_type, categories,
    summary and both LTB fields. One absent date cost the WHOLE header. Nor was there a
    retry: `looks_cancelled` is false for a coercion error. Same shape as the known trap
    "a required int in a BAML class drops the whole item on a null".

FINDING 13, ITEM 1: "when the header pass fails, the fallback still recovers the change
categories where the text supports them, so a failed header does not leave every part
without a proposal."

    Because `empty_header` sets `categories: []`, and every PCN disposition rule matches
    on a change category — so a failed header pass makes the proposer return
    UNCLASSIFIABLE for every part of a notice whose PARTS pass succeeded.

The two belong in one file because they are the same failure seen twice: the null date
was one way INTO the empty header, and the category recovery is the floor under every
other way in (a cancel, a host 400, the AbortError 24_0003 took).

WHAT THE SCHEMA TESTS CAN AND CANNOT SEE. The real gate is BAML's coercion inside
`ExtractHeader`, which cannot be exercised without a model call. The generated pydantic
class is that coercion's TARGET TYPE and the committed artifact of the schema, so a
required `str` there is exactly what made the coercion raise — asserting the class
accepts the null is the honest offline seal, and `TestTheSchemaAndThePromptAgree` also
pins the two source files against each other so they cannot drift apart again.

The fixture is SYNTHETIC (tests/fixtures/sustainment/no_pub_date_notice_text.txt): a
notice that prints no date anywhere, names a manufacturer that exists nowhere, and
describes a site transfer and a compound change so the category walk has something to
recover. No corpus document is used or named here.
"""
import re
from pathlib import Path

import pytest

from doc_tools.baml_client import sync_client as sync_client_module
from doc_tools.baml_client.types import ChangeCategory, DocType, NoticeHeader
from doc_tools.plugins.sustainment import SustainmentPlugin
from doc_tools.utils import sustainment_header_trust as trust

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "baml_src" / "sustainment.baml"
PROMPT = REPO / "prompts" / "sustainment_header_instructions.md"
FIXTURE = REPO / "tests" / "fixtures" / "sustainment" / "no_pub_date_notice_text.txt"

PIPELINE_KEY = "Northgate_PCN_SYN_0001_pdf"
PRINTED_DOC_ID = "PCN-SYN-0001"
MFR = "Northgate Microsystems"

# A notice that describes NO change at all: the control for "nothing is invented".
_NO_CHANGE_PARAGRAPHS = [
    "Product Change Notification",
    MFR,
    "This notification informs customers about the parts identified in the attached "
    "schedule. There is no change to the form, fit or function of the affected parts.",
    "Customers with further questions about this notification should contact their "
    f"{MFR} field sales engineer, who will gather the information and coordinate the "
    "transition with the operations team.",
]


# The dated control, for the one test that checks the dated path still works. The date
# is PRINTED here and cited as the header's source snippet, because an uncited value is
# refused by `refuse_unsourced_header_values` whatever the schema allows.
PRINTED_DATE = "04-Mar-2026"
_DATED_PARAGRAPHS = _NO_CHANGE_PARAGRAPHS + [
    f"Notification date: {PRINTED_DATE}",
]


def _el(text, el_type="NarrativeText", page=1):
    """The element shape tests/test_header_identity_precedence.py uses, including the
    coordinates the positioned index needs to call a value verbatim."""
    return {"type": el_type, "text": text,
            "metadata": {"page_number": page,
                         "coordinates": {"points": [[0, 0], [100, 0], [100, 20], [0, 20]],
                                         "layout_width": 612, "layout_height": 792}}}


def _elements(paragraphs):
    """First two paragraphs are Titles (the headline and the brand), the rest prose,
    plus a run carrying the printed notice number."""
    els = [_el(p, "Title" if i < 2 else "NarrativeText")
           for i, p in enumerate(paragraphs)]
    els.append(_el(f"Product Change Notification: {PRINTED_DOC_ID} Rev -"))
    return els


def _fixture_paragraphs():
    return [ln.strip() for ln in FIXTURE.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


class _FakeHeaderReturns:
    """A fake of the MODEL, not of the seam: it returns what an undated notice makes
    the model return — a header whose `pub_date` is null. Before the schema change this
    object could not even be CONSTRUCTED (`pub_date: str`, no default), which is what
    makes every assertion below a mutation check on the schema.
    """

    def __init__(self, header):
        self._header = header

    def ExtractHeader(self, doc, system_instructions, baml_options=None):
        return self._header


class _FakeHeaderAborts:
    """The header pass DIES, as ADI PCN-24_0003's review.json records ("header pass
    failed: AbortError"). The plugin's own `except` arm records it and leaves `header`
    None — the empty-header path, reached without depending on the null-date bug that
    used to be one way into it."""

    def ExtractHeader(self, doc, system_instructions, baml_options=None):
        raise RuntimeError("AbortError")


def _header(pub_date=None, pub_date_source=None,
            categories=(ChangeCategory.Material,)):
    return NoticeHeader(
        doc_id=PRINTED_DOC_ID, doc_type=DocType.PCN, revision=None,
        pub_date=pub_date, pub_date_source=pub_date_source,
        mfr=MFR, mfr_source=MFR, mfr_parent=None, mfr_parent_source=None,
        categories=list(categories),
        summary="Affected parts transfer to a new assembly site.",
        doc_level_ltb_date=None, doc_level_ltb_date_source=None)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "file")
    monkeypatch.delenv("VISION_LLM_BASE_URL", raising=False)


def _run(monkeypatch, fake, paragraphs=None):
    monkeypatch.setattr(sync_client_module, "b", fake)
    els = _elements(paragraphs or _fixture_paragraphs())
    plugin = SustainmentPlugin(domain_type="sustainment")
    nodes = plugin._extract_fulltext(
        " ".join(e["text"] for e in els), PIPELINE_KEY, elements=els)
    return nodes[0].domain_augmentation


# --------------------------------------------------------------------------- #
# Order A, half 1: the two declarations agree
# --------------------------------------------------------------------------- #
class TestTheSchemaAndThePromptAgree:
    def test_the_fixture_really_prints_no_date(self):
        """The control for this whole file. A fixture with a date in it would exercise
        the dated path and still look green."""
        text = FIXTURE.read_text(encoding="utf-8")

        assert not re.search(r"\d{4}-\d{2}-\d{2}", text), "no ISO date"
        assert not re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", text), "no slashed date"
        assert not re.search(
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}",
            text), "no printed month-and-day"

    def test_the_schema_declares_pub_date_nullable(self):
        """`string?`, not `string`. This is the line whose required-ness cost the whole
        header; it is asserted on the SOURCE schema because that is what regenerates
        the client."""
        header_block = SCHEMA.read_text(encoding="utf-8").split("class NoticeHeader")[1]
        header_block = header_block.split("\n}")[0]

        assert re.search(r"^\s*pub_date\s+string\?", header_block, re.M), \
            "NoticeHeader.pub_date must be declared nullable in baml_src"

    def test_the_prompt_says_a_null_is_CORRECT(self):
        """The prompt's first line is "Use ONLY information present in the provided
        document text. Do not invent values." Against a REQUIRED date that left the
        model two choices on an undated notice — invent one, or lose the header. The
        clause says which answer is wanted, in the same words the `mfr` clause uses."""
        prompt = PROMPT.read_text(encoding="utf-8")

        assert "return **null** for BOTH pub_date and pub_date_source" in prompt
        assert re.search(r"null is a CORRECT answer here", prompt, re.I)

    def test_the_generated_client_accepts_the_null(self):
        """The coercion target. `NoticeHeader(pub_date=None)` raising a ValidationError
        here IS the defect, one layer up from BAML."""
        assert _header(pub_date=None).pub_date is None
        assert NoticeHeader.model_fields["pub_date"].is_required() is False

    @pytest.mark.parametrize("field", ["doc_id", "doc_type", "summary", "categories"])
    def test_nothing_ELSE_became_optional(self, field):
        """Scope guard. The order was about one field; a schema change that quietly
        relaxed the others would make every malformed header a successful one."""
        assert NoticeHeader.model_fields[field].is_required() is True


# --------------------------------------------------------------------------- #
# Order A, half 2: the null date keeps the whole header
# --------------------------------------------------------------------------- #
class TestANullDateCostsOnlyTheDate:
    def test_the_header_pass_did_not_fail(self, monkeypatch):
        """The control: if the null still raised, the reasons would carry "header pass
        failed" and every assertion below would be measuring the empty header."""
        aug = _run(monkeypatch, _FakeHeaderReturns(_header()))

        assert not any("header pass failed" in r for r in aug.review_reasons)

    def test_the_text_layer_is_healthy_so_no_arm_is_gated_off(self, monkeypatch):
        """The second control, and the one a new fixture needs: a fixture the health
        witness calls degraded switches the identity arms OFF, and the assertions below
        then pass while measuring nothing."""
        aug = _run(monkeypatch, _FakeHeaderReturns(_header()))

        assert aug.stats["text_layer_degraded"] is False

    def test_the_identity_survives_the_missing_date(self, monkeypatch):
        """THE DEFECT, stated as the outcome: an undated notice keeps its notice
        number, its manufacturer and its categories. Under the required-string schema
        all three were lost to `empty_header`."""
        aug = _run(monkeypatch, _FakeHeaderReturns(_header()))

        assert aug.notice.doc_id == "PCN-SYN-0001"
        assert aug.review["doc_id_raw"] == PRINTED_DOC_ID
        assert aug.notice.mfr == MFR
        assert aug.review["categories"] == ["Material"]

    def test_the_absent_date_is_the_blank_sentinel_not_a_none(self, monkeypatch):
        """`pub_date` blanks to `""` everywhere in this pipeline — `empty_header`,
        `_LABEL_ECHO_FIELDS`, `HEADER_SOURCED_FIELDS` — while `mfr_parent` blanks to
        None. The convention is not mine to change in this PR, so the null arrives as
        the blank this field already uses, and the plugin's own `SustainmentNotice`
        keeps `pub_date: str`."""
        aug = _run(monkeypatch, _FakeHeaderReturns(_header()))

        assert aug.notice.pub_date == ""

    def test_a_date_that_IS_printed_still_lands(self, monkeypatch):
        """The other direction. Making a field nullable is a way to lose it quietly;
        this is the seal that the dated path is untouched.

        The date has to be PRINTED and CITED, which is not a detail of the test setup:
        `refuse_unsourced_header_values` blanks a header value that is not verbatim in
        the document with no source snippet, so a dated header over the undated fixture
        is refused — correctly — and would have read here as the nullable change losing
        the field. Measured, on the first run of this file."""
        aug = _run(monkeypatch,
                   _FakeHeaderReturns(_header(pub_date="2026-03-04",
                                              pub_date_source=PRINTED_DATE)),
                   paragraphs=_DATED_PARAGRAPHS)

        assert aug.notice.pub_date == "2026-03-04"

    def test_the_categories_are_the_MODELS_and_say_so(self, monkeypatch):
        """`categories_source` attests where the value came from, the same way
        `doc_type_source` does. On a successful pass it is the model's judgment, and
        the keyword walk must NOT have run."""
        aug = _run(monkeypatch, _FakeHeaderReturns(
            _header(categories=(ChangeCategory.Testing,))))

        assert aug.review["categories"] == ["Testing"]
        assert aug.review["categories_source"] == "model", \
            "a healthy header's categories are the model's judgment, not keywords"


# --------------------------------------------------------------------------- #
# Finding 13 item 1: a failed header still proposes
# --------------------------------------------------------------------------- #
class TestAFailedHeaderStillRecoversCategories:
    def test_the_abort_is_recorded_at_all(self, monkeypatch):
        """The control for this class."""
        aug = _run(monkeypatch, _FakeHeaderAborts())

        assert any("header pass failed" in r for r in aug.review_reasons)
        assert aug.needs_review is True

    def test_the_categories_the_text_supports_are_recovered(self, monkeypatch):
        """THE FINDING: without this, `categories: []` makes the proposer return
        UNCLASSIFIABLE for every part of a notice whose parts pass succeeded. The
        fixture describes a site transfer and a new mold compound."""
        aug = _run(monkeypatch, _FakeHeaderAborts())

        assert aug.review["categories"] == ["Material", "Location"]
        assert aug.review["categories_source"] == "text"

    def test_the_reviewer_is_told_they_are_keyword_derived(self, monkeypatch):
        """A recovered category is not the same claim as a judged one, and the person
        accepting the dispositions is the one who needs the difference. It goes in
        `doc_review_reasons` — the reviewer-facing subset — not only in `reasons`."""
        aug = _run(monkeypatch, _FakeHeaderAborts())

        assert any("derived from the document's text" in f
                   for f in aug.review["doc_review_reasons"])
        assert any("keyword-derived" in r for r in aug.review_reasons)

    def test_the_reason_names_the_term_that_matched(self, monkeypatch):
        """Evidence, not an assertion: the reviewer is given the phrase to look for.
        It is one of OUR terms, never a slice of the document."""
        aug = _run(monkeypatch, _FakeHeaderAborts())
        reason = next(r for r in aug.review_reasons if "keyword-derived" in r)

        assert "transfer of assembly" in reason
        assert "mold compound" in reason

    def test_a_notice_describing_no_change_recovers_NOTHING(self, monkeypatch):
        """The invention control, and the one that matters most: a category selects the
        disposition rule, so a wrong one produces a confident proposal where the honest
        output is a gap."""
        aug = _run(monkeypatch, _FakeHeaderAborts(),
                   paragraphs=_NO_CHANGE_PARAGRAPHS)

        assert aug.review["categories"] == []
        assert aug.review["categories_source"] == "no-text-evidence"
        assert any("supports no change category" in r for r in aug.review_reasons)

    def test_that_gap_is_told_to_the_reviewer_too(self, monkeypatch):
        """"Every part will read as needing a disposition" is a fact about the review
        the human is about to do, so it belongs in the banner, not only in the record."""
        aug = _run(monkeypatch, _FakeHeaderAborts(),
                   paragraphs=_NO_CHANGE_PARAGRAPHS)

        assert any("no change category could be established" in f
                   for f in aug.review["doc_review_reasons"])

    def test_the_walk_is_the_one_under_test(self, monkeypatch):
        """Ties the plugin's output to the module's own answer, so this class cannot
        pass against a second, drifted implementation of the rule."""
        text = " ".join(e["text"] for e in _elements(_fixture_paragraphs()))

        assert trust.categories_from_text(text) == (["Material", "Location"], "text")
