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
    cypher_qs, sparql_qs = plugin.to_graph_queries(
        [node], _FakeConfig(), doc_id=dirty_doc_id, image_prefix=""
    )

    assert sparql_qs, "plugin produced no SPARQL — schema may have changed"
    for i, sparql in enumerate(sparql_qs):
        ok, reason = _all_literals_well_formed(sparql)
        assert ok, (
            f"Maintenance plugin SPARQL #{i} is malformed: {reason}\n"
            f"---\n{sparql}\n---"
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
    cypher_qs, sparql_qs = plugin.to_graph_queries(
        [node], _FakeConfig(), doc_id=dirty_doc_id, image_prefix=""
    )

    assert sparql_qs, "plugin produced no SPARQL"
    for i, sparql in enumerate(sparql_qs):
        ok, reason = _all_literals_well_formed(sparql)
        assert ok, (
            f"Manufacturing plugin SPARQL #{i} is malformed: {reason}\n"
            f"---\n{sparql}\n---"
        )


def test_compliance_plugin_emits_well_formed_sparql(dirty_doc_id: str):
    from doc_tools.plugins.compliance import (
        CompliancePlugin, ComplianceRule, ComplianceAugmentation
    )

    class _FakeConfig:
        graph_child_label = "ComplianceSection"

    rule = ComplianceRule(
        manual_reference='Section 4.2 "Safety"',
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
    cypher_qs, sparql_qs = plugin.to_graph_queries(
        [node], _FakeConfig(), doc_id=dirty_doc_id, image_prefix=""
    )

    assert sparql_qs, "plugin produced no SPARQL"
    for i, sparql in enumerate(sparql_qs):
        ok, reason = _all_literals_well_formed(sparql)
        assert ok, (
            f"Compliance plugin SPARQL #{i} is malformed: {reason}\n"
            f"---\n{sparql}\n---"
        )


# ---------------------------------------------------------------------------
# Live Jena tier — runs only when JENA_INTEGRATION_URL is set
# ---------------------------------------------------------------------------

def _maybe_skip_no_jena():
    if not os.environ.get("JENA_INTEGRATION_URL"):
        pytest.skip(
            "set JENA_INTEGRATION_URL (+ DS, USER, PASSWORD) to run the live-Jena tier"
        )


def test_maintenance_plugin_dirty_sparql_executes_against_live_jena(dirty_doc_id: str):
    """End-to-end: plugin → SPARQL → live Fuseki /update → HTTP 204.

    The exact path that returned HTTP 400 at work before commit 5bebcbf.
    If anything regresses (new field bypassing escape, helper deleted,
    plugin imports break), this fails before merge.
    """
    _maybe_skip_no_jena()

    from doc_tools.plugins.maintenance import (
        MaintenancePlugin, MaintenanceStep, MroAugmentation
    )
    from doc_tools.utils.jena_client import JenaClient

    class _FakeConfig:
        graph_child_label = "MroSection"

    step = MaintenanceStep(
        procedure_id="LIVE-P-001",
        step_id="LIVE-P-001-S1",
        instruction_text=DIRTY_TEXT,
        action_verb=DIRTY_ACTION,
        tooling=[DIRTY_TOOL],
        consumables=[],
        is_safety_critical=False,
        justification="live test",
    )
    aug = MroAugmentation(steps=[step])
    sec = BaseSection(
        title="Live test section", level=1, page_start=1,
        content="ignored", node_id="mro_live_test_section",
    )
    node = DocumentNode(base_extraction=sec, domain_augmentation=aug)

    plugin = MaintenancePlugin("maintenance")
    _, sparql_qs = plugin.to_graph_queries(
        [node], _FakeConfig(), doc_id=dirty_doc_id, image_prefix=""
    )

    client = JenaClient(
        url=os.environ["JENA_INTEGRATION_URL"],
        dataset=os.environ.get("JENA_INTEGRATION_DS", "ds"),
        username=os.environ.get("JENA_INTEGRATION_USER", "admin"),
        password=os.environ.get("JENA_INTEGRATION_PASSWORD", ""),
    )
    failures = []
    for i, sparql in enumerate(sparql_qs):
        try:
            r = client.execute_update(sparql)
            if r.status_code != 204:
                failures.append((i, f"unexpected status {r.status_code}", sparql))
        except Exception as e:
            failures.append((i, f"{type(e).__name__}: {e}", sparql))
    assert not failures, (
        f"{len(failures)} of {len(sparql_qs)} SPARQL queries failed against live Fuseki:\n"
        + "\n".join(f"  #{i}: {reason}\n     {sp[:200]}" for i, reason, sp in failures)
    )
