"""Seal for the Jena-writer graph-scoping fix.

The defect: of the four SPARQL-emitting plugins, only ``sustainment.py``
wrapped its triples in a ``GRAPH <...>`` clause. The other three
(``compliance``, ``maintenance``, ``manufacturing``) emitted a bare
``INSERT DATA``, which lands in Jena's default graph — invisible to the
mesh resolver, which scopes every read to
``<http://internal/{DOMAIN}>`` union ``<http://internal/{DOMAIN}_INSTANCES>``.

The fix moves scoping into the single writer, ``JenaClient.execute_update``,
so a plugin cannot emit an unscoped insert: an already-scoped body passes
through unchanged, an unscoped body gets wrapped in
``GRAPH <http://internal/{DOMAIN}_INSTANCES>``, and a body that cannot be
scoped (no ``INSERT DATA``, unbalanced braces, unsafe graph_uri) is refused
via ``UnscopedUpdateError`` rather than silently sent to the default graph.

This file has two parts:

1. Per-plugin outcome tests (parametrized over all four real plugins, using
   the fixture builders from ``test_plugin_sparql_integration.py``): whatever
   ``execute_update`` would decide to do to each plugin's real SPARQL output,
   the final body must end up with exactly one GRAPH clause naming the
   correct INSTANCES graph, with balanced braces. This is deliberately an
   outcome assertion, not a "which side scoped it" assertion, so it does not
   break if a plugin is later fixed to self-scope.
2. Writer-level unit tests of ``update_is_graph_scoped`` /
   ``scope_update_to_graph`` / ``execute_update`` in isolation, with
   ``httpx.Client`` patched so nothing touches the network.
"""
from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest

from doc_tools.utils.jena_client import (
    JenaClient,
    UnscopedUpdateError,
    _ordinary_mask,
    escape_sparql_string,
    scope_update_to_graph,
    update_is_graph_scoped,
)

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


def _count_graph_clauses(body: str) -> int:
    """Count GRAPH occurrences at ordinary (non-literal/IRI/comment)
    positions — the same rule execute_update uses to decide scoping."""
    mask = _ordinary_mask(body)
    count = 0
    for m in re.finditer(r"\bGRAPH\b", body, re.IGNORECASE):
        if mask[m.start()]:
            count += 1
    return count


def _braces_balanced(body: str) -> bool:
    mask = _ordinary_mask(body)
    depth = 0
    for i, ch in enumerate(body):
        if mask[i]:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth < 0:
                    return False
    return depth == 0


# ---------------------------------------------------------------------------
# Part 1 — per-plugin outcome seal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("plugin_builder,name", [
    (_build_maintenance_node, "maintenance"),
    (_build_manufacturing_node, "manufacturing"),
    (_build_compliance_node, "compliance"),
    (_build_sustainment_node, "sustainment"),
], ids=["maintenance", "manufacturing", "compliance", "sustainment"])
def test_plugin_sparql_ends_up_scoped_to_instances_graph(plugin_builder, name):
    """Whatever execute_update's decision logic would do to each plugin's
    real SPARQL output, the final body must contain exactly one GRAPH
    clause naming <http://internal/{DOMAIN}_INSTANCES>, with balanced
    braces — regardless of whether the plugin or the writer did the
    scoping."""
    plugin, node = plugin_builder()
    _, sparql_qs = plugin.to_graph_queries(
        [node], _FakeConfig(), doc_id="TEST-DOC-001", image_prefix=""
    )
    assert sparql_qs, f"{name} plugin produced no SPARQL"

    graph_uri = f"http://internal/{plugin.domain_label}_INSTANCES"
    for i, body in enumerate(sparql_qs):
        if update_is_graph_scoped(body):
            final = body
        else:
            final = scope_update_to_graph(body, graph_uri)

        assert _count_graph_clauses(final) == 1, (
            f"{name} query #{i}: expected exactly one GRAPH clause, got "
            f"{_count_graph_clauses(final)}\n---\n{final}\n---"
        )
        assert f"GRAPH <{graph_uri}>" in final, (
            f"{name} query #{i}: expected GRAPH <{graph_uri}> in body\n"
            f"---\n{final}\n---"
        )
        assert _braces_balanced(final), (
            f"{name} query #{i}: unbalanced braces after scoping\n---\n{final}\n---"
        )


# ---------------------------------------------------------------------------
# Part 2 — writer-level unit tests
# ---------------------------------------------------------------------------

@patch("doc_tools.utils.jena_client.httpx.Client")
def test_unscoped_body_with_no_graph_uri_raises_and_makes_no_request(mock_client_cls):
    client = JenaClient(url="http://jena:3030", dataset="ds", username="u", password="p")
    with pytest.raises(UnscopedUpdateError):
        client.execute_update("INSERT DATA { <a> <b> <c> }")
    mock_client_cls.assert_not_called()


@patch("doc_tools.utils.jena_client.httpx.Client")
def test_already_scoped_body_is_sent_byte_identical(mock_client_cls):
    inner_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = inner_client
    inner_client.post.return_value = MagicMock(raise_for_status=lambda: None)

    body = "INSERT DATA { GRAPH <http://internal/FOO_INSTANCES> { <a> <b> <c> } }"
    JenaClient(url="http://jena:3030", dataset="ds", username="u", password="p").execute_update(
        body, graph_uri="http://internal/FOO_INSTANCES"
    )

    sent = inner_client.post.call_args.kwargs["content"].decode("utf-8")
    assert sent == body
    assert _count_graph_clauses(sent) == 1


def test_literal_containing_braces_is_wrapped_without_breaking_on_inner_braces():
    dirty = escape_sparql_string('summary with { and } inside it')
    body = (
        'PREFIX ex: <http://example.com/>\n'
        'INSERT DATA {\n'
        f'  ex:s ex:hasSummary "{dirty}" .\n'
        '  ex:s ex:hasTrailer "after-literal" .\n'
        '}'
    )
    assert not update_is_graph_scoped(body)
    wrapped = scope_update_to_graph(body, "http://internal/FOO_INSTANCES")

    assert _count_graph_clauses(wrapped) == 1
    assert _braces_balanced(wrapped)
    assert 'ex:hasTrailer "after-literal"' in wrapped
    # The trailing triple (emitted after the brace-laden literal) must be
    # INSIDE the GRAPH clause, i.e. before the final closing braces.
    graph_pos = wrapped.index("GRAPH <http://internal/FOO_INSTANCES>")
    trailer_pos = wrapped.index('ex:hasTrailer "after-literal"')
    assert graph_pos < trailer_pos


def test_literal_containing_the_word_graph_is_not_treated_as_scoped():
    dirty = escape_sparql_string('mentions GRAPH inside text')
    body = (
        'PREFIX ex: <http://example.com/>\n'
        'INSERT DATA {\n'
        f'  ex:s ex:hasNote "{dirty}" .\n'
        '}'
    )
    assert not update_is_graph_scoped(body)
    wrapped = scope_update_to_graph(body, "http://internal/FOO_INSTANCES")
    assert _count_graph_clauses(wrapped) == 1
    assert _braces_balanced(wrapped)


@pytest.mark.parametrize("bad_uri", [
    "http://internal/FOO>",
    "http://internal/FOO BAR",
])
def test_unsafe_graph_uri_raises(bad_uri):
    with pytest.raises(UnscopedUpdateError):
        scope_update_to_graph("INSERT DATA { <a> <b> <c> }", bad_uri)


def test_body_with_no_insert_data_raises_rather_than_sending_unscoped():
    with pytest.raises(UnscopedUpdateError):
        scope_update_to_graph("DELETE WHERE { ?s ?p ?o }", "http://internal/FOO_INSTANCES")
