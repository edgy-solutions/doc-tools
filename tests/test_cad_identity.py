"""STEP AP242 and DXF identity passes, their registry rows, and the halt.

Identity only. The invariants are those of ``identity.py``: every value is
verbatim, every value sits inside the source substring it carries, and a field
that is not printed is refused, never guessed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from doc_tools.passes.cad import dxf_identity, step_ap242_identity
from doc_tools.passes.dispatch import PassContext, run_passes_for_kind
from doc_tools.passes.identity import IdentityError
from doc_tools.utils.content_kind import (
    UnclassifiableContentKindError,
    resolve_content_kind,
)

FIX = Path(__file__).parent / "fixtures" / "cad"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _assert_chain(text: str, f) -> None:
    assert f.source in text
    assert f.value in f.source


def test_step_product_and_revision_verbatim_with_sources():
    text = _read("minimal_ap242.stp")
    ident = step_ap242_identity(text)
    doc, rev = ident.get("document_number"), ident.get("revision")
    assert doc.value == "BRKT-12345-002"
    assert doc.source == "PRODUCT('BRKT-12345-002'"
    assert rev.value == "C"
    assert rev.source == "PRODUCT_DEFINITION_FORMATION('C'"
    _assert_chain(text, doc)
    _assert_chain(text, rev)
    assert ident.value("file_name") == "synthetic_bracket.stp"
    assert ident.value("timestamp") == "2026-01-15T10:30:00"
    assert ident.value("author") == "A. Tester"
    assert ident.value("organization") == "Example Org"
    assert ident.refused == ()


def test_step_schema_reported_verbatim_and_not_asserted():
    text = _read("minimal_ap242.stp")
    ident = step_ap242_identity(text)
    assert ident.value("schema") == (
        "AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF { 1 0 10303 442 1 1 4 }"
    )
    _assert_chain(text, ident.get("schema"))
    # An AP214 file is reported as what it says, not rejected or rewritten.
    ap214 = text.replace(
        "AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF { 1 0 10303 442 1 1 4 }",
        "AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }",
    )
    got = step_ap242_identity(ap214)
    assert got.value("schema") == "AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }"
    assert "schema" not in got.refused


def test_step_header_only_refuses_document_number_and_does_not_use_filename():
    ident = step_ap242_identity(_read("header_only_ap242.stp"))
    assert "document_number" in ident.refused
    assert "revision" in ident.refused
    assert ident.get("document_number") is None
    # The filename is read as a file_name, never as a document number.
    assert ident.value("file_name") == "synthetic_bracket.stp"
    assert all(f.value != "synthetic_bracket.stp"
               for n, f in ident.fields.items() if n != "file_name")


def test_dxf_attrib_tags_read_verbatim_with_sources():
    text = _read("minimal_titleblock.dxf")
    ident = dxf_identity(text)
    assert ident.value("document_number") == "12345-002"
    assert ident.value("revision") == "B"
    assert ident.value("cage_code") == "1ABC2"
    assert ident.value("project_name") == "SYNTH-PROJECT-ALPHA"
    for name in ("document_number", "revision", "cage_code", "project_name"):
        _assert_chain(text, ident.get(name))
    assert ident.get("document_number").label == "DWG_NO"
    assert ident.refused == ("contract_number",)


@pytest.mark.parametrize("tag", [
    "DWG_NO", "DRAWING_NUMBER", "dwgno", "Drawing_No", "DOC_NO", "DOCUMENT_NUMBER",
])
def test_dxf_document_number_aliases(tag):
    text = _read("minimal_titleblock.dxf").replace("DWG_NO", tag)
    ident = dxf_identity(text)
    assert ident.value("document_number") == "12345-002"
    assert ident.get("document_number").label == tag


def test_dxf_no_titleblock_refuses_every_titleblock_field():
    ident = dxf_identity(_read("no_titleblock.dxf"))
    assert ident.fields == {}
    assert set(ident.refused) == {
        "project_name", "document_number", "revision", "cage_code", "contract_number",
    }


@pytest.mark.parametrize("text", [
    "AutoCAD Binary DXF\r\n\x1a\x00\x00\x00junk",
    "this is not a drawing at all\nat all\n",
    "",
])
def test_dxf_binary_or_garbage_raises_not_empty_identity(text):
    with pytest.raises(IdentityError, match="binary DXF"):
        dxf_identity(text)


@pytest.mark.parametrize("fn,name", [
    (step_ap242_identity, "minimal_ap242.stp"),
    (dxf_identity, "minimal_titleblock.dxf"),
])
def test_passes_are_pure(fn, name):
    text = _read(name)
    before = str(text)
    first, second = fn(text), fn(text)
    assert first == second
    assert text == before


def test_registry_rows_resolve_exactly_as_declared():
    step = resolve_content_kind({"content_kind": "step-ap242"}, "")
    assert step.passes == ("cad.step_ap242_identity",)
    assert step.outputs == ("mesh:StepAp242Artifact",)
    assert step.domain_type is None
    dxf = resolve_content_kind({"content_kind": "dxf"}, "")
    assert dxf.passes == ("cad.dxf_identity",)
    assert dxf.outputs == ("mesh:DxfArtifact",)
    assert dxf.domain_type is None


@pytest.mark.parametrize("kind", ["iges", "sldprt"])
def test_unregistered_cad_format_still_halts(kind):
    with pytest.raises(UnclassifiableContentKindError):
        resolve_content_kind({"content_kind": kind}, "")


@pytest.mark.parametrize("kind,name,field", [
    ("step-ap242", "minimal_ap242.stp", "document_number"),
    ("dxf", "minimal_titleblock.dxf", "document_number"),
])
def test_declared_passes_resolve_through_the_real_dispatcher(kind, name, field):
    ctx = PassContext(text=_read(name))
    (result,) = run_passes_for_kind(kind, ctx)
    assert result.status == "ok", result.error
    assert result.value.value(field)
