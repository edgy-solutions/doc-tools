"""The passes dispatcher, proved on two real rows and on fake contract cases.

No network, no model. Contract cases use locally built callables patched in
through the dispatcher's resolver rather than edits to ``KIND_MAPPING``.

The S1000D proof is a REFUSAL on the real shipping row -- its declared pass is
a class -- plus a conformance check on the adapter that row will eventually
name. Neither proves anything about ``s1000d_rdf`` itself, which scored 0
content kinds on a real module, and the dispatcher is not wired into any asset
yet.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import doc_tools.passes.dispatch as dispatch
from doc_tools.passes.dispatch import (
    PassContext,
    PassContractError,
    run_pass,
    run_passes_for_kind,
)

DOORS_FIXTURE = (Path(__file__).parent / "fixtures" / "doors"
                 / "SRS-MRAD-001_baseline-2.1.csv")


def _doors_text() -> str:
    return DOORS_FIXTURE.read_text(encoding="utf-8")


def _s1000d_bytes() -> bytes:
    # No S1000D fixture FILE exists in the repo; the only module is this
    # inline constant, which the parser's own tests use.
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from test_parsers_rdf import S1000D_XML
    finally:
        sys.path.pop(0)
    return S1000D_XML


def _patch_resolver(monkeypatch, symbol, module="fake.mod"):
    monkeypatch.setattr(dispatch, "resolve_python_pass",
                        lambda dotted: [(module, symbol)])


# 1 -- DOORS end to end ------------------------------------------------------

def test_doors_end_to_end_is_verbatim_with_preamble_region():
    results = run_passes_for_kind("doors-export", PassContext(text=_doors_text()))
    assert [x.name for x in results] == [
        "identity.identity_from_doors_text", "doors.requirements_rows"]
    r = results[0]  # declared order is meaningful: identity first
    assert r.status == "ok", r
    ident = r.value
    assert ident.region == "doors_preamble"
    assert ident.value("document_number") == "SRS-MRAD-001"
    assert ident.value("revision") == "C"
    assert ident.value("cage_code") == "1AB23"
    assert ident.value("contract_number") == "W58RGZ-24-C-0031"


# 2 -- DOORS scoping is live through the dispatcher --------------------------

def test_doors_object_text_contract_line_is_not_the_identity():
    """Fails if the row is reverted to identity.document_identity, which scans
    everything it is given and would read the requirement body as identity."""
    lines = _doors_text().splitlines()
    assert any(l.startswith("Contract Number:") for l in lines)
    kept = [l for l in lines if not l.startswith("Contract Number:")]
    text = "\n".join(kept) + (
        '\nSRS-99,2,,"The following is quoted:\nContract Number: ZZ-BAD-9999\n'
        'end of quote.",Information,,,,99,12 March 2026\n')
    results = run_passes_for_kind("doors-export", PassContext(text=text))
    r = results[0]
    assert r.status == "ok", r
    # The mutation only drops a preamble line and appends an Information
    # object; the four real Requirement objects are retained, so the second
    # pass (doors.requirements_rows) is expected to be "ok", not "refused".
    assert results[1].name == "doors.requirements_rows"
    assert results[1].status == "ok", results[1]
    assert [x.identifier for x in results[1].value.rows] == [
        "SRS-5", "SRS-6", "SRS-7", "SRS-9"]
    # Positive anchors first: without them an empty read (a pass that bound
    # nothing from the context) would satisfy the negative assertions below
    # vacuously, which is exactly what happens if the row is reverted to
    # identity.document_identity (it binds no `text`).
    assert r.value.region == "doors_preamble"
    assert r.value.value("document_number") == "SRS-MRAD-001"
    assert r.value.value("contract_number") != "ZZ-BAD-9999"
    assert "contract_number" in r.value.refused


# 3 -- S1000D: the SHIPPING row is refused, and the adapter is ready ---------
#
# The second proof is the refusal, not a happy path, and it is the stronger of
# the two: it fires on the REAL registry row rather than on a patched fake.
# ``s1000d-data-module`` declares ``s1000d.S1000dGraphBuilder``, a CLASS whose
# constructor takes config only -- so an unguarded dispatcher would build an
# empty object, parse nothing, and report success. That silent no-op is the
# exact failure this dispatcher was written to make impossible.
#
# The row is NOT changed to the conforming name here. This kind is shared with
# the platform's overlay and sealed by tests/test_overlay_kind_drift.py, so the
# declaration moves on both sides together.

def test_the_shipping_s1000d_row_is_refused_as_a_class():
    with pytest.raises(PassContractError) as e:
        run_passes_for_kind(
            "s1000d-data-module",
            PassContext(raw_bytes=_s1000d_bytes(), doc_id="manual_v2"))
    msg = str(e.value)
    assert "s1000d.S1000dGraphBuilder" in msg
    assert "class" in msg
    # And it RAISES rather than landing as a recorded "refused" result: a
    # mis-declared row is a registration defect, not a document problem.


def test_the_s1000d_adapter_conforms_and_returns_turtle(monkeypatch):
    """The entry point the row will name once both registries move.

    Proves two things the row change will depend on: the function binds only
    vocabulary parameter names, so the dispatcher can call it; and it returns
    Turtle. It proves NOTHING about the parser behind it -- that parser scored
    0 content kinds on a real module, with a DMC that was not a DMC.
    """
    # Driven through run_pass, the same public path the row will take -- only
    # the resolution step is stood in for, so the binding and the call are the
    # dispatcher's own and not a reimplementation here.
    import doc_tools.parsers.s1000d_rdf as s1000d_rdf

    _patch_resolver(monkeypatch, s1000d_rdf.data_module_graph,
                    module="doc_tools.parsers.s1000d_rdf")
    r = run_pass("s1000d.data_module_graph",
                 PassContext(raw_bytes=_s1000d_bytes(), doc_id="manual_v2"))
    assert r.status == "ok", r
    assert isinstance(r.value, str) and r.value.strip()
    assert "@prefix" in r.value


# 4 / 5 -- skipped, not run --------------------------------------------------

def test_xml_is_unbuilt_and_nothing_is_resolved(monkeypatch):
    def boom(dotted):
        raise AssertionError("resolver must not be called for an unbuilt pass")
    monkeypatch.setattr(dispatch, "resolve_python_pass", boom)
    (r,) = run_passes_for_kind("xml", PassContext())
    assert r.status == "unbuilt" and r.error == ""
    assert not any(m.startswith("doc_tools.passes.xml") for m in sys.modules)


def test_baml_pass_is_skipped_without_resolution(monkeypatch):
    def boom(dotted):
        raise AssertionError("resolver must not be called for a BAML pass")
    monkeypatch.setattr(dispatch, "resolve_python_pass", boom)
    (r,) = run_passes_for_kind("work-instructions", PassContext())
    assert r.status == "baml"


# 6 -- contract refusals raise -----------------------------------------------

def test_a_class_is_refused(monkeypatch):
    class Builder:
        def __init__(self, doc_id=""):
            pass
    _patch_resolver(monkeypatch, Builder)
    with pytest.raises(PassContractError) as e:
        run_pass("ns.Builder", PassContext())
    assert "ns.Builder" in str(e.value) and "fake.mod" in str(e.value)
    assert "class" in str(e.value)


def test_kwargs_is_refused(monkeypatch):
    def fn(text, **kwargs):
        return text
    _patch_resolver(monkeypatch, fn)
    with pytest.raises(PassContractError) as e:
        run_pass("ns.fn", PassContext())
    assert "ns.fn" in str(e.value) and "**kwargs" in str(e.value)


def test_args_is_refused(monkeypatch):
    def fn(*args):
        return args
    _patch_resolver(monkeypatch, fn)
    with pytest.raises(PassContractError, match=r"\*args"):
        run_pass("ns.fn", PassContext())


def test_required_parameter_outside_vocabulary_is_refused(monkeypatch):
    def fn(text, export_text):
        return text
    _patch_resolver(monkeypatch, fn)
    with pytest.raises(PassContractError) as e:
        run_pass("ns.fn", PassContext())
    assert "ns.fn" in str(e.value) and "export_text" in str(e.value)
    assert "raw_bytes" in str(e.value)  # names the vocabulary


def test_non_callable_is_refused(monkeypatch):
    _patch_resolver(monkeypatch, 42)
    with pytest.raises(PassContractError) as e:
        run_pass("ns.thing", PassContext())
    assert "ns.thing" in str(e.value) and "not callable" in str(e.value)


def test_unresolvable_and_unknown_kind_raise():
    with pytest.raises(PassContractError, match="no_such_pass"):
        run_pass("identity.no_such_pass", PassContext())
    with pytest.raises(PassContractError, match="unknown content kind"):
        run_passes_for_kind("no-such-kind", PassContext())


def test_default_parameter_outside_vocabulary_is_left_alone(monkeypatch):
    def fn(text, flavour="plain"):
        return (text, flavour)
    _patch_resolver(monkeypatch, fn)
    r = run_pass("ns.fn", PassContext(text="t"))
    assert r.status == "ok" and r.value == ("t", "plain")


# 7 -- a pass's own exception is recorded ------------------------------------

def test_a_raising_pass_is_recorded_not_propagated(monkeypatch):
    def fn(text):
        raise ValueError("cannot read this document")
    _patch_resolver(monkeypatch, fn)
    monkeypatch.setattr(dispatch, "_lookup", lambda k: type(
        "E", (), {"passes": ("ns.fn", "ns.fn")})())
    results = run_passes_for_kind("anything", PassContext())
    assert len(results) == 2
    assert all(r.status == "refused" and "cannot read" in r.error for r in results)


# 8 -- one resolver ----------------------------------------------------------

def test_registry_test_uses_the_dispatchers_resolver():
    """Stated choice: the registry test IMPORTS the function (as _resolve_python)
    and this asserts it is the same object, so a copy cannot creep back in."""
    import test_passes_registry as reg
    assert reg._resolve_python is dispatch.resolve_python_pass
    assert reg.PASS_PACKAGES is dispatch.PASS_PACKAGES
