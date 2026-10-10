"""Seal for the Jena-writer graph-scoping guarantee.

The defect this file originally sealed: of the four SPARQL-emitting plugins,
only ``sustainment.py`` wrapped its triples in a ``GRAPH <...>`` clause. The
other three (``compliance``, ``maintenance``, ``manufacturing``) emitted a
bare ``INSERT DATA``, which lands in Jena's default graph — invisible to the
mesh resolver, which scopes every read to
``<http://internal/{DOMAIN}>`` union ``<http://internal/{DOMAIN}_INSTANCES>``
(see the "Domain Semantic Graph" invariant in AGENTS.md).

THE MECHANISM CHANGED (iagent-mesh SDK v0.9.8,
``iagent_mesh.writers.jena.JenaOntologyWriter``), but the invariant it
protects did not. A plugin no longer emits a raw SPARQL Update string that a
downstream writer might have to detect and wrap; it emits a
``{"graph": ..., "iri": ..., "triples": [...]}`` batch (built by
``doc_tools.plugins.base.sparql_batch``), and ``graph`` is a REQUIRED keyword
argument to ``JenaOntologyWriter.upsert()`` — there is no optional-graph
overload and no raw-SPARQL passthrough, so an unscoped write is not a call a
plugin can make anymore. ``upsert()`` additionally REFUSES (rather than
silently defaulting) any ``graph`` that is empty or contains a character that
could break out of the ``GRAPH <...>`` IRI reference it builds internally
(``<``, ``>``, or whitespace) — the same injection concern the old
``scope_update_to_graph`` used to guard by hand.

This file has two parts:

1. Per-plugin outcome seal (parametrized over all four real plugins, using
   the fixture builders from ``test_plugin_sparql_integration.py``): every
   batch a real plugin emits carries a well-formed ``graph`` naming its own
   domain's INSTANCES graph, and the writer accepts it (a mocked 200 from
   Fuseki resolves to ``result.applied``).
2. Writer-level unit tests: ``JenaOntologyWriter.upsert()`` refuses an empty
   or malformed ``graph`` — ``result.applied`` is ``False`` and, crucially,
   no HTTP request is made at all (``httpx.post`` is asserted not called).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from iagent_mesh.interfaces import Initiator
from iagent_mesh.writers.jena import JenaOntologyWriter

# Reuse the existing per-plugin fixture builders rather than duplicating them.
# There's no conftest.py / __init__.py in doc_tools_tests/, so pytest's default
# "prepend" import mode puts this directory on sys.path and a plain module
# import works (verified: this import succeeds under `pytest -q`).
from test_plugin_sparql_integration import (  # noqa: E402
    _FakeConfig,
    _build_compliance_node,
    _build_maintenance_node,
    _build_manufacturing_node,
    _build_sustainment_node,
)


def _initiator() -> Initiator:
    # A Dagster run is non-human: kind="delegate" is the admitted non-person
    # kind for a write (kind="service" is refused — see Initiator.require_
    # person_or_delegate in the pinned SDK source).
    return Initiator(subject="test-run", kind="delegate", on_behalf_of="doc-tools-tests")


# ---------------------------------------------------------------------------
# Part 1 — per-plugin outcome seal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("plugin_builder,name", [
    (_build_maintenance_node, "maintenance"),
    (_build_manufacturing_node, "manufacturing"),
    (_build_compliance_node, "compliance"),
    (_build_sustainment_node, "sustainment"),
], ids=["maintenance", "manufacturing", "compliance", "sustainment"])
def test_plugin_batches_carry_well_formed_instances_graph(plugin_builder, name):
    """Every batch a real plugin emits names its own domain's INSTANCES graph,
    and JenaOntologyWriter accepts it (does not refuse for a graph reason)."""
    plugin, node = plugin_builder()
    _, sparql_batches = plugin.to_graph_queries(
        [node], _FakeConfig(), doc_id="TEST-DOC-001", image_prefix=""
    )
    assert sparql_batches, f"{name} plugin produced no SPARQL batches"

    expected_graph = f"http://internal/{plugin.domain_label}_INSTANCES"
    writer = JenaOntologyWriter(base_url="http://jena:3030", dataset="ds")
    initiator = _initiator()

    for i, batch in enumerate(sparql_batches):
        assert batch["graph"] == expected_graph, (
            f"{name} batch #{i}: expected graph={expected_graph!r}, got "
            f"{batch['graph']!r}"
        )
        with patch("iagent_mesh.writers.jena.httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            result = writer.upsert(
                initiator, graph=batch["graph"], iri=batch["iri"], triples=batch["triples"]
            )
        assert result.applied, (
            f"{name} batch #{i}: writer refused a real plugin-emitted graph "
            f"({batch['graph']!r}): outcome={result.outcome!r} detail={result.detail!r}"
        )


# ---------------------------------------------------------------------------
# Part 2 — writer-level refusal seal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_graph", [
    "",
    "   ",
    "http://internal/FOO>",
    "http://internal/FOO BAR",
    "<http://internal/FOO>",
])
def test_upsert_refuses_empty_or_malformed_graph_and_makes_no_request(bad_graph):
    writer = JenaOntologyWriter(base_url="http://jena:3030", dataset="ds")
    with patch("iagent_mesh.writers.jena.httpx.post") as mock_post:
        result = writer.upsert(
            _initiator(), graph=bad_graph, iri="http://internal/x", triples=["<a> <b> <c> ."]
        )
    assert not result.applied
    assert result.outcome == "refused"
    mock_post.assert_not_called()


def test_upsert_accepts_a_well_formed_graph_and_posts_once():
    writer = JenaOntologyWriter(base_url="http://jena:3030", dataset="ds")
    with patch("iagent_mesh.writers.jena.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        result = writer.upsert(
            _initiator(),
            graph="http://internal/TEST_INSTANCES",
            iri="http://internal/x",
            triples=["<a> <b> <c> ."],
        )
    assert result.applied
    mock_post.assert_called_once()
