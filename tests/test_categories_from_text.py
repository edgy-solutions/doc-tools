"""The change categories a DOCUMENT'S OWN TEXT supports, read deterministically.

`sustainment_header_trust.categories_from_text` exists for one path: the header pass
died, so `sustainment_merge.empty_header` wrote `categories: []`, and every PCN
disposition rule matches on a change category — leaving the proposer to return
UNCLASSIFIABLE for every part of a notice whose PARTS pass succeeded. Finding 13,
item 1 (2026-11-18): "when the header pass fails, the fallback still recovers the
change categories where the text supports them, so a failed header does not leave
every part without a proposal."

Two properties are under test here, and they pull against each other:

  * RECOVERY — the categories a notice's own change wording supports are found.
  * NO INVENTION — nothing is written that the text does not support. A category is
    not a cosmetic label: it SELECTS the disposition rule, so a wrong one produces a
    confident proposal where the honest output is a gap. Every "trap" test below is a
    measured way an unanchored or over-broad term set invents one.

The term vocabulary is OURS, not the document's: `category_signals` reports which of
our phrases matched, never a substring of the page. That is deliberate — it feeds a
reason string a person reads, and the ruling of 2026-11-18 keeps raw document and
model text out of records a person reads.

Companion file: tests/test_notice_with_no_date.py seals the WIRING (that the walk runs
on the failed-header path, reaches review.json, and does not run on a healthy one).
A pure-module test alone would have been green on the day the field was lost — the
lesson of tests/test_sustainment_zero_part_flag.py.
"""
import pytest

from doc_tools.utils import sustainment_header_trust as trust
from doc_tools.utils import sustainment_normalize as norm


# --------------------------------------------------------------------------- #
# recovery: the category a notice's own wording supports
# --------------------------------------------------------------------------- #
class TestItFindsWhatTheTextSupports:
    @pytest.mark.parametrize("text,expected", [
        ("Description of change: transfer of assembly to the Penang facility.",
         "Location"),
        ("The mold compound is replaced on the affected packages.", "Material"),
        ("This notification covers a change in the assembly process flow.", "Process"),
        ("The parts below reach end of life on the date in the schedule.",
         "Discontinuation"),
        ("The reel size changes from 7 inch to 13 inch.", "Packaging"),
        ("A new test method is introduced for the affected devices.", "Testing"),
    ])
    def test_one_category_per_wording(self, text, expected):
        cats, source = trust.categories_from_text(text)
        assert cats == [expected], \
            f"{expected} is the category this wording supports; got {cats}"
        assert source == "text", "a category was found, so the source is the text"

    def test_more_than_one_category_is_normal(self):
        """The prompt's own words: "May be more than one." A notice that moves a site
        AND changes a compound is both, and a disposition proposer that sees only one
        of them matches the wrong rule."""
        cats, _ = trust.categories_from_text(
            "The transfer of assembly brings a new mold compound with it.")

        assert cats == ["Material", "Location"], \
            "both categories the text supports must be recovered"

    def test_the_term_that_matched_is_reported_and_is_OURS(self):
        """The reason text a reviewer reads names the phrase to look for. It is one of
        our own terms — never a slice of the document — so no raw page text travels
        into the review record on this path."""
        signals = trust.category_signals(
            "Description of change: transfer of assembly to the Penang facility.")

        assert signals == {"Location": "transfer of assembly"}
        assert all(t in trust._CATEGORY_TERMS[c] for c, t in signals.items()), \
            "a reported term must come from our vocabulary, not from the document"


# --------------------------------------------------------------------------- #
# no invention: the traps an over-broad term set falls into
# --------------------------------------------------------------------------- #
class TestItInventsNothing:
    def test_a_notice_with_no_change_wording_yields_nothing(self):
        cats, source = trust.categories_from_text(
            "This notification informs customers about the parts in the attached "
            "schedule. There is no change to the form, fit or function.")

        assert cats == []
        assert source == "no-text-evidence", \
            "no evidence must be SAID, not implied by an empty list"

    def test_latest_change_is_not_a_test_change(self):
        """THE ANCHORING TRAP, and the reason every term is `\\b`-bounded: "latest
        change" contains the substring "test change". Unanchored, every notice that
        refers to its own latest change becomes a Testing change."""
        assert trust.categories_from_text(
            "This document supersedes our latest change notification.")[0] == []

    def test_a_part_number_containing_ptn_is_not_a_discontinuation(self):
        """`norm._PDN_TERMS` carries "ptn", which is safe against a TITLE and unsafe
        against the whole text: a hyphen is a word boundary, so `\\bptn\\b` fires
        inside a hyphenated part number. The term is dropped here for that reason."""
        cats, _ = trust.categories_from_text(
            "Affected: XC-PTN-5, MPTN-9. No change of status is described.")

        assert "Discontinuation" not in cats
        assert "ptn" in norm._PDN_TERMS, \
            "the title vocabulary still carries it; this walk is what drops it"
        assert "ptn" not in trust._CATEGORY_TERMS["Discontinuation"]

    def test_eol_survives_as_a_term_and_does_not_fire_mid_word(self):
        """The other half: "eol" is KEPT, because a bare EOL token in a notice's text
        is discontinuation evidence, and its boundaries are real."""
        assert trust.categories_from_text("The EOL schedule is attached.")[0] == \
            ["Discontinuation"]
        assert trust.categories_from_text(
            "Rheology of the resin is unchanged.")[0] == [], \
            "'rheology' contains 'eol' and must not read as a discontinuation"

    @pytest.mark.parametrize("label_line", [
        "Manufacturing Site: Penang",
        "Test Method: per the attached specification",
        "Material: copper",
    ])
    def test_a_bare_FORM_LABEL_is_not_a_change(self, label_line):
        """A notice's form prints these labels on documents where that field is not
        what changed. The generic nouns are admitted only inside a change phrase,
        which is what makes this walk conservative by construction."""
        assert trust.categories_from_text(label_line)[0] == [], \
            f"{label_line!r} states a field's value, not a change to it"


# --------------------------------------------------------------------------- #
# the shape of the answer
# --------------------------------------------------------------------------- #
class TestTheAnswerIsStable:
    def test_the_order_is_canonical_not_order_of_appearance(self):
        """The same bytes must always produce the same list in the same order: a
        category list is compared across fires, and an appearance-ordered list would
        read as drift on identical input."""
        early = trust.categories_from_text(
            "A new test method follows the transfer of assembly and a new mold "
            "compound.")[0]
        late = trust.categories_from_text(
            "A new mold compound and a transfer of assembly precede the new test "
            "method.")[0]

        assert early == late == ["Material", "Location", "Testing"]
        assert early == [c for c in trust.CATEGORY_ORDER if c in early]

    def test_a_term_survives_a_line_wrap_and_a_hyphen(self):
        """Extracted text wraps where the page wrapped, and vendors hyphenate. Both
        are the same term: words are joined with `[\\s-]+`."""
        for variant in ("end of life", "end-of-life", "end of\nlife", "end  of  life"):
            assert trust.categories_from_text(variant)[0] == ["Discontinuation"], \
                f"{variant!r} is the same term as 'end of life'"

    def test_every_category_has_a_term_set_and_no_term_set_invents_a_category(self):
        """The enum is `ChangeCategory` in baml_src/sustainment.baml and the ruleset
        keys on exactly these six. A seventh key here would write a category the
        disposition proposer cannot match, which reads downstream as a part with a
        category and no applicable rule — worse than no category at all."""
        assert set(trust._CATEGORY_TERMS) == set(trust.CATEGORY_ORDER)
        assert set(trust.CATEGORY_ORDER) == {
            "Material", "Process", "Location", "Discontinuation", "Packaging",
            "Testing"}

    def test_none_and_empty_text_are_answers_not_exceptions(self):
        """This runs on the FAILURE path. A walk that raises there turns a recoverable
        header failure into a dead extraction."""
        for empty in (None, "", "   "):
            assert trust.categories_from_text(empty) == ([], "no-text-evidence")
