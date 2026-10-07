"""Tests for ``doc_tools.passes.identity`` — the document-identity pass.

Organised per the measured-expectation groups in the task spec: A (TYC
refusal half), B (DOORS full-house half), C (refusal semantics), D
(same-line truncation), E (pages/precedence), F (the two invariants), G
(the reported shape).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from doc_tools.passes.identity import (
    IDENTITY_FIELDS,
    LABEL_ALIASES,
    IdentityError,
    document_identity,
    identity_from_doors_text,
    _verify_chain,
)

FIXTURES = Path(__file__).parent / "fixtures"
TYC_FIXTURE = FIXTURES / "sustainment" / "tyc_witness_page1.txt"
DOORS_FIXTURE = FIXTURES / "doors" / "SRS-MRAD-001_baseline-2.1.csv"


def _tyc_text() -> str:
    return TYC_FIXTURE.read_text(encoding="utf-8")


def _doors_text() -> str:
    return DOORS_FIXTURE.read_text(encoding="utf-8")


# === A. The TYC seal (the refusal half) ===================================


class TestTycSeal:
    def test_a1_document_number_full_field(self):
        """Catches a regression in the happy path: wrong value, wrong source
        line, wrong label alias, wrong page, wrong region, or wrong method
        would each silently corrupt the one field TYC does print.
        """
        result = document_identity([_tyc_text()])
        f = result.get("document_number")
        assert f is not None
        assert f.value == "PCN-24-210412"
        assert f.source == (
            "Product Change Notification: PCN-24-210412 PCN Date: 07-JUN-24"
        )
        assert f.label == "Product Change Notification"
        assert f.page_number == 1
        assert f.region == "title_block"
        assert f.method == "labelled_line"

    def test_a2_refused_tuple_exact(self):
        """Catches a refusal mechanism that fires for the wrong fields, or
        reports them in the wrong order (refused is a tuple contract, not a
        set) — revision, cage_code and contract_number are simply never
        printed on this notice.
        """
        result = document_identity([_tyc_text()])
        assert result.refused == ("revision", "cage_code", "contract_number")

    def test_a3_agreement_id_is_not_a_contract_number(self):
        """THE TRAP. The notice prints ``Agreement: EU-TTI-MASTK``, not a
        contract number. If any alias loosely matched "Agreement" onto
        contract_number, EU-TTI-MASTK would show up as a field value — a
        false provenance claim about a real document that no later
        substring check would catch, because the chain would still resolve.
        """
        result = document_identity([_tyc_text()])
        values = [f.value for f in result.fields.values()]
        assert "EU-TTI-MASTK" not in values
        for v in values:
            assert "EU-TTI-MASTK" not in v

    def test_a4_same_line_truncation_on_real_data(self):
        """The document_number label and the PCN Date label share one real
        source line. Reading to end-of-line instead of to the next label
        would fold "PCN Date: 07-JUN-24" into the document number — a value
        that still resolves against the page and is still wrong.
        """
        result = document_identity([_tyc_text()])
        value = result.value("document_number")
        assert "PCN Date" not in value
        assert "07-JUN-24" not in value


# === B. The DOORS seal (the full-house half) ===============================


DOORS_EXPECTED = [
    ("document_number", "SRS-MRAD-001", "Document Number: SRS-MRAD-001", "Document Number"),
    ("revision", "C", "Revision: C", "Revision"),
    ("cage_code", "1AB23", "CAGE Code: 1AB23", "CAGE Code"),
    ("contract_number", "W58RGZ-24-C-0031", "Contract Number: W58RGZ-24-C-0031", "Contract Number"),
]


class TestDoorsSeal:
    @pytest.mark.parametrize("name,value,source,label", DOORS_EXPECTED)
    def test_b1_all_four_fields(self, name, value, source, label):
        """Catches a field dropped, truncated, or attributed to the wrong
        alias/source line when reading a DOORS export preamble — the
        full-house case where every field the pass declares is printed.
        """
        result = identity_from_doors_text(_doors_text())
        f = result.get(name)
        assert f is not None
        assert f.value == value
        assert f.source == source
        assert f.label == label

    def test_b2_no_refusals_and_region(self):
        """Catches a refusal that fires even though the DOORS preamble
        prints all four fields, and catches the region tag drifting from
        "doors_preamble" (which a consumer uses to distinguish a DOORS read
        from a title-block read without re-deriving it).
        """
        result = identity_from_doors_text(_doors_text())
        assert result.refused == ()
        assert result.region == "doors_preamble"

    def test_b3_preamble_scoping_excludes_object_text(self):
        """A requirement OBJECT that quotes "Contract Number: W-999" is a
        requirement, not the module's identity. If the preamble boundary
        were not enforced, this object's text would be read as the module's
        real contract number — catches the scoping being dropped or the
        header-row marker being matched incorrectly.
        """
        export_text = (
            "Project: P\n"
            "Baseline: 1.0\n"
            "\n"
            "Object Identifier,Object Level,Object Heading,Object Text,Object Type\n"
            'O-1,1,,"Contract Number: W-999 shall be cited on every drawing.",Requirement\n'
        )
        result = identity_from_doors_text(export_text)
        assert result.refused == tuple(IDENTITY_FIELDS)
        assert result.fields == {}


# === C. Refusal semantics ===================================================


class TestRefusalSemantics:
    def test_c1_bare_banner_line_no_colon(self):
        """Catches a matcher that treats a label alias appearing anywhere on
        a line as a hit even with no colon and no value — the banner line
        "Product Change Notification" with nothing after it must refuse all
        four fields, not synthesize one from the banner itself.
        """
        result = document_identity("Product Change Notification\n")
        assert set(result.refused) == set(IDENTITY_FIELDS)
        assert result.fields == {}

    def test_c2_empty_title_block_cell_is_refusal_not_empty_string(self):
        """Catches a label-with-nothing-after-it being reported as an empty
        string value instead of a refusal — "Revision:" with no text after
        the colon on a flattened title block must land in ``refused``.
        """
        result = document_identity("Revision:\n")
        assert "revision" in result.refused
        assert result.get("revision") is None

    def test_c3_bare_five_char_token_is_not_a_cage_code(self):
        """Catches a shape-matcher sneaking in: a bare five-character token
        is not a CAGE code just because CAGE codes happen to be five
        characters. With no "CAGE" or "CAGE Code" label present, cage_code
        must refuse.
        """
        result = document_identity("1AB23\n")
        assert "cage_code" in result.refused

    def test_c4_empty_string_refuses_everything_without_raising(self):
        """Catches an empty-input crash (e.g. an unguarded index into an
        empty line list) and catches any field surviving on pure absence of
        text.
        """
        result = document_identity("")
        assert set(result.refused) == set(IDENTITY_FIELDS)


# === D. Same-line truncation, synthetic =====================================


class TestSameLineTruncation:
    def test_d1_two_labels_one_line(self):
        """Catches the next-label cutoff failing to apply to BOTH fields on
        a shared line: document_number must stop before "Rev:" and revision
        must be read starting after "Rev:", with each field's source being
        the full original line (not a truncated copy of it).
        """
        line = "Document No.: 12345-002 Rev: B\n"
        result = document_identity(line)
        doc = result.get("document_number")
        rev = result.get("revision")
        assert doc is not None and rev is not None
        assert doc.value == "12345-002"
        assert rev.value == "B"
        assert doc.source == line.rstrip("\n")
        assert rev.source == line.rstrip("\n")

    @pytest.mark.parametrize(
        "line,field",
        [
            ("Sub Document Number: SUB-9", "document_number"),
            ("Parent Document Number: P-1", "document_number"),
            ("Customer Document No: C-4", "document_number"),
            ("Supplier Contract No: S-7", "contract_number"),
            ("Next Rev: D", "revision"),
        ],
    )
    def test_d2_a_qualified_label_is_refused_not_taken(self, line, field):
        """A sub-assembly's, customer's or supplier's number is not THIS
        document's. Each of these lines contains a real alias as a
        substring, so the naive word-boundary match took them -- and the
        resulting field would pass both invariants, because the value IS
        printed on the page. Nothing downstream could catch it; the only
        place it can be refused is here.
        """
        result = document_identity(line + "\n")
        assert field in result.refused
        assert result.get(field) is None

    def test_d3_the_guard_stands_down_after_a_colon_on_the_line(self):
        """The complement of D2, and the reason the guard is not simply
        "no word before the label": once a field has already been read off
        the line, the word before the next label is ambiguous between a
        qualifier and the previous VALUE. Refusing there would cost a real
        field on exactly the flattened-title-block shape this pass is for.
        """
        result = document_identity("Agreement: EU-TTI-MASTK Contract No: W-1\n")
        assert result.value("contract_number") == "W-1"


# === E. Pages and precedence ================================================


class TestPagesAndPrecedence:
    def test_e1_page_number_is_where_the_value_actually_was(self):
        """Catches page numbering being off-by-one or being pinned to page 1
        regardless of which page actually contained the labelled line.
        """
        result = document_identity(["cover\n", "Document No: X-1\n"])
        assert result.get("document_number").page_number == 2

    def test_e2_first_match_wins_in_document_order(self):
        """Catches a later repeat of a field overriding the first: a title
        block is front matter, and a repeat in a later page/footer is not a
        second opinion that should replace it.
        """
        result = document_identity(
            ["Document No: FIRST-1\n", "Document No: SECOND-2\n"]
        )
        f = result.get("document_number")
        assert f.value == "FIRST-1"
        assert f.page_number == 1

    def test_e3_single_string_is_page_one(self):
        """Catches a single bare string (not wrapped in a list) being
        treated as zero pages or mis-numbered instead of page 1.
        """
        result = document_identity("Document No: S-1\n")
        assert result.get("document_number").page_number == 1


# === F. The two invariants ==================================================


class TestInvariants:
    def test_f1_tyc_fixture_satisfies_both_invariants(self):
        """Catches a field whose value is not actually inside its own
        source, or whose source is not actually inside the page text it
        claims to come from, slipping through on real TYC data.
        """
        text = _tyc_text()
        result = document_identity([text])
        # Without this the loop below is vacuous: a pass that found nothing
        # would satisfy both invariants perfectly.
        assert set(result.fields) == {"document_number"}
        for f in result.fields.values():
            assert f.value in f.source
            assert f.source in text

    def test_f1_doors_fixture_satisfies_both_invariants(self):
        """Same as above but for the DOORS export: the source must be a
        substring of the (preamble-scoped) export text used to produce it.
        """
        text = _doors_text()
        result = identity_from_doors_text(text)
        assert set(result.fields) == set(IDENTITY_FIELDS)
        for f in result.fields.values():
            assert f.value in f.source
            assert f.source in text

    def test_f2_verify_chain_raises_when_value_not_in_source(self):
        """Invariant 2 must be checked, and checked FIRST: a value that was
        assembled rather than copied out of its own source must raise, even
        if the source itself is genuinely on the page. A citation that
        resolves proves nothing about the value printed beside it unless
        the value is inside the citation.
        """
        with pytest.raises(IdentityError) as exc_info:
            _verify_chain("NOT-PRESENT", "some source line", "some source line\n", "document_number")
        assert "NOT-PRESENT" in str(exc_info.value)

    def test_f3_verify_chain_raises_when_source_not_in_page_text(self):
        """Invariant 1, checked second: even when the value is genuinely
        inside its source, a source that was not actually copied out of the
        page text (e.g. reconstructed or edited) must raise, because the
        field would not be locatable on the real page.
        """
        with pytest.raises(IdentityError):
            _verify_chain("X", "value is X here", "a completely different page\n", "document_number")


# === G. The reported shape ==================================================


class TestReportedShape:
    def test_g1_as_dict_key_set_on_doors_result(self):
        """Catches ``as_dict`` drifting from the NoticeHeader-mirroring
        contract: missing a per-field key, adding an unexpected one, or
        omitting ``refused``/``region`` would silently break a downstream
        consumer that reads this flat shape.
        """
        result = identity_from_doors_text(_doors_text())
        d = result.as_dict()
        expected_keys = set()
        for name in IDENTITY_FIELDS:
            expected_keys.update(
                {name, f"{name}_source", f"{name}_page", f"{name}_label"}
            )
        expected_keys.update({"refused", "region"})
        assert set(d.keys()) == expected_keys

    def test_g2_as_dict_none_for_refused_fields_on_tyc_result(self):
        """Catches a refused field leaking a stale or default value into
        ``as_dict`` instead of reporting ``None`` across all four of its
        keys — cage_code is refused on the TYC notice and must read as a
        clean absence, not a guess.
        """
        result = document_identity([_tyc_text()])
        d = result.as_dict()
        assert d["cage_code"] is None
        assert d["cage_code_source"] is None
        assert d["cage_code_page"] is None
        assert d["cage_code_label"] is None

    def test_g3_label_aliases_cover_every_field_with_nonempty_tuples(self):
        """The alias table is the pass's whole configuration surface, so a
        field with an empty alias tuple is a field that can never be found
        — catches that silently happening for any declared field.
        """
        assert set(LABEL_ALIASES.keys()) == set(IDENTITY_FIELDS)
        for aliases in LABEL_ALIASES.values():
            assert len(aliases) > 0
