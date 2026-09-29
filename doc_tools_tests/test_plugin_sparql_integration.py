"""Plugin → SPARQL → Jena integration tests.

The unit test in ``test_sparql_escape.py`` proves the helper works in
isolation. This file proves each plugin **uses** the helper at every
interpolation site, by:

  1. Constructing minimal-but-realistic plugin inputs with deliberately
     dirty content (multi-line text, embedded quotes, backslashes,
     control chars — exactly the shape extracted text takes after
     real PDF/XML parsing).
  2. Calling the plugin's ``to_graph_queries`` to get back the actual
     SPARQL strings the production code would emit.
  3. Asserting every emitted SPARQL string is well-formed (no raw
     newlines / unescaped quotes inside double-quoted literals).
  4. (Optional, when a Jena fixture URL is set) POSTing each SPARQL
     to live Fuseki and asserting HTTP 204 — proves end-to-end the
     fix doesn't regress.

This catches the exact regression class that produced HTTP 400s at
work: a plugin field added without going through ``escape_sparql_string``.
The well-formed regex check fails on the unescaped output, so the test
goes red BEFORE the change ships.

Run with:

  pytest doc_tools_tests/test_plugin_sparql_integration.py -v

For the live-Jena tier:

  JENA_INTEGRATION_URL=http://localhost:13030 \
  JENA_INTEGRATION_DS=ds \
  JENA_INTEGRATION_USER=admin \
  pytest doc_tools_tests/test_plugin_sparql_integration.py -v
"""
from __future__ import annotations

import os
import re

import pytest

from doc_tools.plugins.models import BaseSection, DocumentNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Same well-formed check used in test_sparql_escape.py — kept here so this
# file stands alone (CI can run either independently).
_DOUBLE_QUOTED_LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _all_literals_well_formed(sparql: str) -> tuple[bool, str]:
    """Return (ok, reason). All ``"..."`` literals must have only escaped
    specials. Catches the historical 400 cause: raw newline / raw
    backslash / unescaped quote inside the literal.
    """
    for m in _DOUBLE_QUOTED_LITERAL.finditer(sparql):
        body = m.group(1)
        for bad, name in [("\n", "newline"), ("\r", "CR"), ("\t", "tab")]:
            if bad in body:
                return False, f"raw {name} in literal: {body[:60]!r}"
        i = 0
        while i < len(body):
            if body[i] == "\\":
                if i + 1 >= len(body) or body[i + 1] not in '"\\nrt':
                    return False, f"bad escape in literal at index {i}: {body[i:i+10]!r}"
                i += 2
            else:
                i += 1
    return True, "ok"


# Dirty content that mimics what real PDF/XML extraction produces. Each
# field exercises a different escape: multi-line, embedded quote, raw
# backslash. The plugins must escape all of them.
DIRTY_TEXT = "Step 1:\nUse the \"Allen\" key.\nTorque to 5 N·m.\nAvoid C:\\Windows path."
DIRTY_ACTION = 'Operate "drive" lever'
DIRTY_TOOL = 'Spanner (3/4\" socket)'


@pytest.fixture
def dirty_doc_id() -> str:
    return "TEST-DIRTY-DOC-001"


# ---------------------------------------------------------------------------
# Per-plugin integration tests
# ---------------------------------------------------------------------------

def test_maintenance_plugin_emits_well_formed_sparql(dirty_doc_id: str):
    """MaintenancePlugin.to_graph_queries with dirty step text must
    produce well-formed SPARQL string literals (no raw newlines / quotes
    leaking into the body)."""
    from doc_tools.plugins.maintenance import (
        MaintenancePlugin, MaintenanceStep, MroAugmentation
    )

    class _FakeConfig:
        graph_child_label = "MroSection"

    step = MaintenanceStep(
        procedure_id="P-001",
        step_id="P-001-S1",
        instruction_text=DIRTY_TEXT,
        action_verb=DIRTY_ACTION,
        tooling=[DIRTY_TOOL, "Torque wrench"],
        consumables=["WD-40 \"spray\""],
        is_safety_critical=False,
        justification="Routine maintenance",
        figure_references=["Fig 3"],
    )
    aug = MroAugmentation(steps=[step])
    sec = BaseSection(
        title='Section "1" with quote',
        level=1,
        page_start=1,
        content="ignored",
        node_id="mro_test_section",
    )
    node = DocumentNode(base_extraction=sec, domain_augmentation=aug)

    plugin = MaintenancePlugin("maintenance")  # domain_label auto-derived
    cypher_qs, sparql_batches = plugin.to_graph_queries(
        [node], _FakeConfig(), doc_id=dirty_doc_id, image_prefix=""
    )

    assert sparql_batches, "plugin produced no SPARQL — schema may have changed"
    for i, batch in enumerate(sparql_batches):
        body = " ".join(batch["triples"])
        ok, reason = _all_literals_well_formed(body)
        assert ok, (
            f"Maintenance plugin SPARQL batch #{i} is malformed: {reason}\n"
            f"---\n{body}\n---"
        )


def test_manufacturing_plugin_emits_well_formed_sparql(dirty_doc_id: str):
    """Same guarantee for ManufacturingPlugin — emits both base fields
    plus overlay-driven literals, both paths must escape."""
    from doc_tools.plugins.manufacturing import (
        ManufacturingPlugin, ManufacturingStep, MatAugmentation, StrategicAssessment
    )

    class _FakeConfig:
        graph_child_label = "MatSection"

    step = ManufacturingStep(
        procedure_id="MP-001",
        step_id="MP-001-S1",
        instruction_text=DIRTY_TEXT,
        action_verb=DIRTY_ACTION,
        tooling=[DIRTY_TOOL],
        consumables=["WD-40 \"spray\""],
        is_value_added=True,
        is_safety_critical=False,
        process_category="ASSEMBLY",
        justification="Routine assembly",
        figure_references=["Fig A"],
    )
    assessment = StrategicAssessment(proprietary_score=0.3, outsourceable=True)
    aug = MatAugmentation(steps=[step], assessment=assessment)
    sec = BaseSection(
        title='Mfg Section "X"',
        level=1, page_start=1,
        content="ignored",
        node_id="mfg_test_section",
    )
    node = DocumentNode(base_extraction=sec, domain_augmentation=aug)

    plugin = ManufacturingPlugin("manufacturing")
    cypher_qs, sparql_batches = plugin.to_graph_queries(
        [node], _FakeConfig(), doc_id=dirty_doc_id, image_prefix=""
    )

    assert sparql_batches, "plugin produced no SPARQL"
    for i, batch in enumerate(sparql_batches):
        body = " ".join(batch["triples"])
        ok, reason = _all_literals_well_formed(body)
        assert ok, (
            f"Manufacturing plugin SPARQL batch #{i} is malformed: {reason}\n"
            f"---\n{body}\n---"
        )


def test_sustainment_plugin_emits_well_formed_sparql(dirty_doc_id: str):
    """SustainmentPlugin mostly uses ``<URI>`` not string literals for its
    triples, but the ``ltb_date`` field is a literal that ships through
    ``escape_sparql_string``. Verify dirty input doesn't break the body."""
    from doc_tools.plugins.sustainment import (
        SustainmentPlugin, SustainmentNotice, SustainmentAugmentation, PartImpact
    )

    class _FakeConfig:
        graph_child_label = "SustainmentSection"
        graph_node_label = "SustainmentDocument"

    part = PartImpact(
        affected_mpn="MPN-123\nDIRTY",
        replacement_mpn="MPN-456",
        ltb_date='2026-06-10"\nbad',  # dirty date payload
    )
    notice = SustainmentNotice(
        doc_id="LEGAL-001",
        doc_type="PCN",
        pub_date="2026-06-10",
        mfr="Acme Corp",
        categories=["EOL"],
        summary="multi-line\nnotice\twith \"quote\"",
        impacted_parts=[part],
    )
    aug = SustainmentAugmentation(notice=notice)
    sec = BaseSection(
        title="Sustainment notice", level=1, page_start=1,
        content="ignored", node_id="sus_test_section",
    )
    node = DocumentNode(base_extraction=sec, domain_augmentation=aug)

    plugin = SustainmentPlugin("sustainment")
    cypher_qs, sparql_batches = plugin.to_graph_queries(
        [node], _FakeConfig(), doc_id=dirty_doc_id, image_prefix=""
    )

    assert sparql_batches, "sustainment plugin produced no SPARQL"
    for i, batch in enumerate(sparql_batches):
        body = " ".join(batch["triples"])
        ok, reason = _all_literals_well_formed(body)
        assert ok, (
            f"Sustainment plugin SPARQL batch #{i} is malformed: {reason}\n"
            f"---\n{body}\n---"
        )


def test_compliance_plugin_emits_well_formed_sparql(dirty_doc_id: str):
    from doc_tools.plugins.compliance import (
        CompliancePlugin, ComplianceRule, ComplianceAugmentation
    )

    class _FakeConfig:
        graph_child_label = "ComplianceSection"

    # See _build_compliance_node docstring re: URI-construction issue.
    rule = ComplianceRule(
        manual_reference='Section_4_2_Safety',
        rule_type="MANDATORY",
        rule_description=DIRTY_TEXT,
        target_metric="< 5 m/s\nwith \"safety\" margin",
        applicable_hazard_class="Class \"B\"",
    )
    aug = ComplianceAugmentation(rules=[rule])
    sec = BaseSection(
        title="Compliance section",
        level=1, page_start=1,
        content="ignored",
        node_id="comp_test_section",
    )
    node = DocumentNode(base_extraction=sec, domain_augmentation=aug)

    plugin = CompliancePlugin("compliance")
    cypher_qs, sparql_batches = plugin.to_graph_queries(
        [node], _FakeConfig(), doc_id=dirty_doc_id, image_prefix=""
    )

    assert sparql_batches, "plugin produced no SPARQL"
    for i, batch in enumerate(sparql_batches):
        body = " ".join(batch["triples"])
        ok, reason = _all_literals_well_formed(body)
        assert ok, (
            f"Compliance plugin SPARQL batch #{i} is malformed: {reason}\n"
            f"---\n{body}\n---"
        )


# ---------------------------------------------------------------------------
# Negative control — the well-formed checker MUST catch the bad case
# ---------------------------------------------------------------------------

def test_negative_control_unescaped_sparql_fails_well_formed_check():
    """Sanity check on the checker itself.

    If the well-formed regex ever accidentally accepts a raw-newline /
    unescaped-quote body, every plugin test in this file silently
    passes and we lose the regression guard. This test simulates the
    pre-fix code path (the .replace('"','') strip) and asserts the
    checker correctly REJECTS its output. If this test passes, the
    above tests' assertions are actually meaningful.
    """
    # Mimics the old maintenance.py interpolation: only strips quotes,
    # leaves newlines + backslashes intact.
    dirty_text = "Step 1:\nUse the \"Allen\" key.\nTorque to 5 N·m."
    bad_strip = dirty_text.replace('"', '')
    bad_sparql = f"""
    PREFIX mro: <http://example.com/maintenance#>
    INSERT DATA {{
        mro:step1 mro:hasText "{bad_strip}" .
    }}
    """
    ok, reason = _all_literals_well_formed(bad_sparql)
    assert not ok, (
        "The well-formed checker accepted a body that contains raw newlines. "
        "This means the regex regressed and the plugin tests above are "
        f"no-op. Reason returned: {reason!r}"
    )


# ---------------------------------------------------------------------------
# Fixture builders — shared by the no-live-Jena-required guards below AND
# the live Jena tier at the bottom of this file.
# ---------------------------------------------------------------------------

def _maybe_skip_no_jena():
    if not os.environ.get("JENA_INTEGRATION_URL"):
        pytest.skip(
            "set JENA_INTEGRATION_URL (+ DS, USER, PASSWORD) to run the live-Jena tier"
        )


def _build_maintenance_node():
    from doc_tools.plugins.maintenance import (
        MaintenancePlugin, MaintenanceStep, MroAugmentation
    )
    step = MaintenanceStep(
        procedure_id="LIVE-MRO-001", step_id="LIVE-MRO-001-S1",
        instruction_text=DIRTY_TEXT, action_verb=DIRTY_ACTION,
        tooling=[DIRTY_TOOL], consumables=[],
        is_safety_critical=False, justification="live test",
    )
    aug = MroAugmentation(steps=[step])
    sec = BaseSection(title="Live test section", level=1, page_start=1,
                      content="ignored", node_id="mro_live_section")
    node = DocumentNode(base_extraction=sec, domain_augmentation=aug)
    return MaintenancePlugin("maintenance"), node


def _build_manufacturing_node():
    from doc_tools.plugins.manufacturing import (
        ManufacturingPlugin, ManufacturingStep, MatAugmentation, StrategicAssessment
    )
    step = ManufacturingStep(
        procedure_id="LIVE-MFG-001", step_id="LIVE-MFG-001-S1",
        instruction_text=DIRTY_TEXT, action_verb=DIRTY_ACTION,
        tooling=[DIRTY_TOOL], consumables=['WD-40 "spray"'],
        is_value_added=True, is_safety_critical=False,
        process_category="ASSEMBLY", justification="live test",
    )
    aug = MatAugmentation(
        steps=[step],
        assessment=StrategicAssessment(proprietary_score=0.3, outsourceable=True),
    )
    sec = BaseSection(title="Live test section", level=1, page_start=1,
                      content="ignored", node_id="mfg_live_section")
    node = DocumentNode(base_extraction=sec, domain_augmentation=aug)
    return ManufacturingPlugin("manufacturing"), node


def _build_compliance_node():
    """Compliance live test focuses on the STRING-LITERAL escape concern
    (rule_description, target_metric, hazard_class are interpolated into
    "...". Use clean manual_reference because compliance.py builds the URI
    prefixed name from it directly (raw_ref = manual_reference.replace(' ','_')
    .replace('.','_').replace('-','_')) — non-alphanumeric chars in
    manual_reference leak into the URI and produce an invalid prefixed
    name. That's a separate URI-construction bug; not the scope of this
    test (which guards the string-literal fix from 5bebcbf). Reported
    separately so it can be fixed in its own commit."""
    from doc_tools.plugins.compliance import (
        CompliancePlugin, ComplianceRule, ComplianceAugmentation
    )
    rule = ComplianceRule(
        manual_reference='Section_4_2_Safety',  # clean — see docstring
        rule_type="MANDATORY",
        rule_description=DIRTY_TEXT, target_metric='< 5 m/s\nwith "safety" margin',
        applicable_hazard_class='Class "B"',
    )
    aug = ComplianceAugmentation(rules=[rule])
    sec = BaseSection(title="Compliance section", level=1, page_start=1,
                      content="ignored", node_id="comp_live_section")
    node = DocumentNode(base_extraction=sec, domain_augmentation=aug)
    return CompliancePlugin("compliance"), node


def _build_sustainment_node():
    from doc_tools.plugins.sustainment import (
        SustainmentPlugin, SustainmentNotice, SustainmentAugmentation, PartImpact
    )
    part = PartImpact(
        affected_mpn="MPN-123", replacement_mpn="MPN-456",
        ltb_date='2026-06-10',  # use clean date for live; sustainment uses xsd:date
    )
    notice = SustainmentNotice(
        doc_id="LIVE-SUS-001", doc_type="PCN", pub_date="2026-06-10",
        mfr="Acme Corp", categories=["EOL"],
        summary='multi-line\nnotice\twith "quote"',
        impacted_parts=[part],
    )
    aug = SustainmentAugmentation(notice=notice)
    sec = BaseSection(title="Sustainment notice", level=1, page_start=1,
                      content="ignored", node_id="sus_live_section")
    node = DocumentNode(base_extraction=sec, domain_augmentation=aug)
    return SustainmentPlugin("sustainment"), node


class _FakeConfig:
    graph_child_label = "LiveSection"
    graph_node_label = "LiveDocument"  # sustainment uses this for root node


# ---------------------------------------------------------------------------
# New guarantees from the JenaOntologyWriter migration (iagent-mesh SDK
# @8e4a881) — no live Jena required for either of these.
# ---------------------------------------------------------------------------

# Matches a full <...> IRI reference or a "..." string literal (with escapes).
# Stripping every match of THIS out of a triple body should leave nothing but
# whitespace and the keyword `a` — any leftover `word:word` is a bare
# prefixed name, which JenaOntologyWriter.upsert() cannot render (fact 3:
# it emits INSERT DATA with NO PREFIX block, so Fuseki 400s on one).
_IRI_OR_LITERAL = re.compile(r'<[^<>]*>|"(?:[^"\\]|\\.)*"(?:\^\^<[^<>]*>)?')
_BARE_PREFIXED_NAME = re.compile(r'\b[A-Za-z][\w-]*:[A-Za-z_][\w.-]*\b')


def _find_bare_prefixed_names(body: str) -> list[str]:
    stripped = _IRI_OR_LITERAL.sub(" ", body)
    return _BARE_PREFIXED_NAME.findall(stripped)


@pytest.mark.parametrize("plugin_builder,name", [
    (_build_maintenance_node, "maintenance"),
    (_build_manufacturing_node, "manufacturing"),
    (_build_compliance_node, "compliance"),
    (_build_sustainment_node, "sustainment"),
], ids=["maintenance", "manufacturing", "compliance", "sustainment"])
def test_plugin_emits_no_bare_prefixed_names(plugin_builder, name):
    """Fact 3 (spec_jena_writer.md): JenaOntologyWriter.upsert() emits
    ``INSERT DATA { GRAPH <g> { ...triples... } }`` with NO ``PREFIX`` block.
    A bare prefixed name (``mro:``, ``iof:``, ``mfg:``, ``pcn:``) was legal
    under the old ``JenaClient.execute_update`` path (which prepended a
    PREFIX block by hand) but is a silent SPARQL syntax error under the new
    writer. This is the single most likely way to regress this migration,
    per the spec — so it gets its own guard that needs no live Fuseki.
    """
    plugin, node = plugin_builder()
    _, sparql_batches = plugin.to_graph_queries(
        [node], _FakeConfig(), doc_id="TEST-NO-PREFIX-001", image_prefix=""
    )
    assert sparql_batches, f"{name} plugin produced no SPARQL batches"
    for i, batch in enumerate(sparql_batches):
        for key in ("graph", "iri"):
            assert not _find_bare_prefixed_names(batch[key]), (
                f"{name} batch #{i}: {key}={batch[key]!r} is not a full IRI"
            )
        body = " ".join(batch["triples"])
        bad = _find_bare_prefixed_names(body)
        assert not bad, (
            f"{name} batch #{i} contains bare prefixed name(s) {bad!r} — "
            f"JenaOntologyWriter emits no PREFIX block, so this is a SPARQL "
            f"syntax error at Fuseki:\n---\n{body}\n---"
        )


def test_sustainment_batch_iri_is_the_document_not_a_component():
    """Fact 2 (spec_jena_writer.md): ``upsert()`` is DELETE-by-subject then
    INSERT in one request — it deletes every triple previously written for
    ``iri`` within ``graph`` before inserting the new ones. Measured live in
    ``<http://internal/SUSTAINMENT_INSTANCES>``: 468 distinct
    ``http://internal/components/{mpn}`` subjects across only 7 notices, many
    carrying 3 ``pcn:subjectToNotice`` edges apiece — keying the upsert on a
    component IRI would delete OTHER notices' edges on every re-extraction.
    So the sustainment batch's ``iri`` must be the notice document IRI
    (``http://internal/sustainment/doc/{safe_notice_id}``), never one of the
    ``http://internal/components/{mpn}`` subjects that also appear inside its
    own ``triples``.
    """
    plugin, node = _build_sustainment_node()
    _, sparql_batches = plugin.to_graph_queries(
        [node], _FakeConfig(), doc_id="LIVE-SUS-001", image_prefix=""
    )
    assert sparql_batches, "sustainment plugin produced no SPARQL batches"
    for i, batch in enumerate(sparql_batches):
        assert batch["iri"].startswith("http://internal/sustainment/doc/"), (
            f"sustainment batch #{i}: iri={batch['iri']!r} is not a notice "
            f"document IRI"
        )
        assert not batch["iri"].startswith("http://internal/components/"), (
            f"sustainment batch #{i}: iri={batch['iri']!r} is a component "
            f"IRI — an upsert keyed on it would delete OTHER notices' "
            f"edges to that shared component (fact 2)"
        )
        # The component IRIs referenced INSIDE this batch's triples are a
        # different, shared subject — they must be inserted, never chosen
        # as the delete-by-subject key.
        component_iris_in_triples = {
            term.strip("<>")
            for triple in batch["triples"]
            for term in triple.split()
            if term.startswith("<http://internal/components/")
        }
        assert batch["iri"] not in component_iris_in_triples, (
            f"sustainment batch #{i}: iri equals a component IRI that also "
            f"appears inside its own triples ({batch['iri']!r})"
        )


# ---------------------------------------------------------------------------
# Live Jena tier — runs only when JENA_INTEGRATION_URL is set
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("plugin_builder,name", [
    (_build_maintenance_node, "maintenance"),
    (_build_manufacturing_node, "manufacturing"),
    (_build_compliance_node, "compliance"),
    (_build_sustainment_node, "sustainment"),
], ids=["maintenance", "manufacturing", "compliance", "sustainment"])
def test_plugin_dirty_sparql_executes_against_live_jena(plugin_builder, name, dirty_doc_id):
    """End-to-end across all plugins: plugin → SPARQL batch → live Fuseki → applied.

    Each parametrize case constructs that plugin's dirty-input DocumentNode,
    gets the generated SPARQL batches, and upserts every one to live Fuseki
    via JenaOntologyWriter (iagent-mesh SDK @8e4a881). If anything regresses
    (escape helper deleted, a plugin field bypasses it, a new plugin schema
    adds an unescaped literal or a bare prefixed name), the failing case
    pinpoints the offending plugin.
    """
    _maybe_skip_no_jena()
    from iagent_mesh.interfaces import Initiator
    from iagent_mesh.writers.jena import JenaOntologyWriter

    plugin, node = plugin_builder()
    _, sparql_batches = plugin.to_graph_queries(
        [node], _FakeConfig(), doc_id=dirty_doc_id, image_prefix=""
    )
    assert sparql_batches, f"{name} plugin produced no SPARQL"

    writer = JenaOntologyWriter(
        base_url=os.environ["JENA_INTEGRATION_URL"],
        dataset=os.environ.get("JENA_INTEGRATION_DS", "ds"),
    )
    initiator = Initiator(
        subject="test_plugin_sparql_integration", kind="delegate", on_behalf_of="doc-tools-tests"
    )
    failures = []
    for i, batch in enumerate(sparql_batches):
        try:
            result = writer.upsert(
                initiator, graph=batch["graph"], iri=batch["iri"], triples=batch["triples"]
            )
            if not result.applied:
                failures.append((i, f"outcome={result.outcome!r} detail={result.detail!r}", batch))
        except Exception as e:
            failures.append((i, f"{type(e).__name__}: {str(e)[:150]}", batch))
    assert not failures, (
        f"{name}: {len(failures)} of {len(sparql_batches)} SPARQL batches failed:\n"
        + "\n".join(f"  #{i}: {reason}\n     {b}" for i, reason, b in failures)
    )
