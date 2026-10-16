"""The ingress-user seam's legal shapes come from the kind registry."""
import pytest

from doc_tools.passes import dispatch
from doc_tools.utils import content_kind as ck

SHIPPED_PDF_LITERAL = r"^ingress-user/pdf/[0-9a-f]{64}/[^/]+\.pdf$"


def test_generated_pdf_pattern_equals_the_shipped_literal():
    assert ck.ingress_user_prefixes()["pdf"] == SHIPPED_PDF_LITERAL
    assert ck.ingress_user_key_pattern(ck.KIND_MAPPING["pdf"]) == SHIPPED_PDF_LITERAL


def test_xml_pattern_is_generated():
    assert ck.ingress_user_prefixes()["xml"] == r"^ingress-user/xml/[0-9a-f]{64}/[^/]+\.xml$"


def test_only_format_level_rows_declare_a_prefix():
    assert set(ck.ingress_user_prefixes()) == {"pdf", "xml"}


def test_a_row_without_a_prefix_raises():
    with pytest.raises(ValueError):
        ck.ingress_user_key_pattern(ck.KIND_MAPPING["pcn"])


def test_doors_registration_fields():
    e = ck.KIND_MAPPING["doors-export"]
    assert e.identity_field is None
    # identity_field and seeds_workflow are event-branch only in the SDK; doors-export is a document row.
    assert e.seeds_workflow is None


def test_processable_kinds_is_a_strict_subset_of_registered():
    registered = {e.kind for e in ck.KIND_MAPPING.values()}
    assert set(ck.processable_kinds()) < registered


def test_xml_not_processable_because_its_only_pass_is_unbuilt():
    assert "xml" not in ck.processable_kinds(), (
        "xml's only pass xml.xml_document_identity is in UNBUILT_PASSES")


def test_s1000d_not_processable_because_its_pass_is_a_class():
    assert "s1000d-data-module" not in ck.processable_kinds(), (
        "s1000d.S1000dGraphBuilder is a class; dispatch refuses it by contract")


def test_pcn_and_doors_are_processable():
    p = ck.processable_kinds()
    assert "pcn" in p and "doors-export" in p


def test_every_processable_pass_resolves_or_is_baml():
    for kind in ck.processable_kinds():
        for name in ck._BY_KIND[kind].passes:
            if "::" in name:
                continue
            hits = dispatch.resolve_python_pass(name)
            assert hits and len(hits) == 1, name
            assert callable(hits[0][1]) and not isinstance(hits[0][1], type), name
