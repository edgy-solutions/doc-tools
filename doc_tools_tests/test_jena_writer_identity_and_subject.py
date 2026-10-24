"""The Jena write path under the three rulings, asserted at the wire.

1. DELEGATE IDENTITY: ``JenaOntologyWriter.upsert`` refuses an initiator that is
   neither a person nor a delegate, and makes no request.
2. CREDENTIALS BY THE CALLER: the credential is passed as ``auth=(user, pass)``
   and reaches ``httpx.post``; userinfo in ``base_url`` is refused (it would print
   the password into every log). The test values are throwaway literals, not config.
3. THE PER-SUBJECT REPLACE HAZARD: ``upsert`` is DELETE-then-INSERT keyed on ``iri``
   -- ``DELETE WHERE { GRAPH <g> { <iri> ?p ?o } }`` removes EVERY triple whose
   subject is ``iri`` in that graph. Component IRIs are shared across notices
   (measured: 468 subjects over 7 notices), so ``iri`` must be the per-document
   node. These tests capture the SPARQL that actually leaves ``httpx.post`` and
   parse the DELETE subject out of it; they do not rely on a name or a comment.
"""
import re
from unittest.mock import MagicMock, patch

import httpx
import pytest

from iagent_mesh.interfaces import Initiator
from iagent_mesh.writers.jena import JenaOntologyWriter

from test_plugin_sparql_integration import (  # noqa: E402
    _FakeConfig,
    _build_compliance_node,
    _build_maintenance_node,
    _build_manufacturing_node,
    _build_sustainment_node,
)

_DELETE_RE = re.compile(r"DELETE WHERE \{ GRAPH <([^>]*)> \{ <([^>]*)> \?mesh_p \?mesh_o \} \}")
_BUILDERS = [
    (_build_maintenance_node, "maintenance"),
    (_build_manufacturing_node, "manufacturing"),
    (_build_compliance_node, "compliance"),
    (_build_sustainment_node, "sustainment"),
]
_IDS = [n for _, n in _BUILDERS]
_ARGS = dict(graph="http://internal/X_INSTANCES", iri="http://internal/d", triples=["<a> <b> <c> ."])


def _delegate() -> Initiator:
    return Initiator(subject="test-run", kind="delegate", on_behalf_of="doc-tools-tests")


def _upsert_capturing(batch, writer=None):
    """Run a real upsert for ``batch``; return (result, the mocked httpx.post)."""
    writer = writer or JenaOntologyWriter(base_url="http://jena:3030", dataset="ds")
    with patch("iagent_mesh.writers.jena.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        result = writer.upsert(
            _delegate(), graph=batch["graph"], iri=batch["iri"], triples=batch["triples"]
        )
    return result, mock_post


# --- 1. delegate identity --------------------------------------------------

def test_service_kind_is_refused_without_a_request_and_delegate_is_admitted():
    writer = JenaOntologyWriter(base_url="http://jena:3030", dataset="ds")
    with patch("iagent_mesh.writers.jena.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        refused = writer.upsert(Initiator(subject="svc", kind="service"), **_ARGS)
        assert not refused.applied
        assert refused.outcome == "refused"
        mock_post.assert_not_called()
        ok = writer.upsert(_delegate(), **_ARGS)
    assert ok.applied
    mock_post.assert_called_once()


def test_delegate_without_on_behalf_of_cannot_be_constructed():
    # The SDK refuses a delegate that names no principal at construction, so an
    # asset that forgot on_behalf_of fails loudly before any write is attempted.
    with pytest.raises(Exception):
        Initiator(subject="run-1", kind="delegate")


# --- 2. credentials supplied by the caller ---------------------------------

def test_auth_reaches_the_wire_and_absent_auth_sends_none():
    batch = dict(_ARGS)
    authed = JenaOntologyWriter(base_url="http://jena:3030", dataset="ds", auth=("u-test", "p-test"))
    _, mock_post = _upsert_capturing(batch, authed)
    sent = mock_post.call_args.kwargs["auth"]
    assert isinstance(sent, httpx.BasicAuth), "auth= was not forwarded to httpx.post"
    assert sent._auth_header == httpx.BasicAuth("u-test", "p-test")._auth_header

    _, mock_post = _upsert_capturing(batch)
    assert mock_post.call_args.kwargs["auth"] is None


def test_userinfo_in_base_url_and_blank_credentials_are_refused():
    with pytest.raises(ValueError):
        JenaOntologyWriter(base_url="http://u:p@jena:3030", dataset="ds")
    with pytest.raises(ValueError):
        JenaOntologyWriter(base_url="http://jena:3030", dataset="ds", auth=("", "x"))
    with pytest.raises(ValueError):
        JenaOntologyWriter(base_url="http://jena:3030", dataset="ds", auth=("x", " "))


# --- 3. the per-subject replace hazard, on the captured argument ------------

@pytest.mark.parametrize("plugin_builder,name", _BUILDERS, ids=_IDS)
def test_captured_delete_subject_is_the_document_node_not_a_shared_one(plugin_builder, name):
    plugin, node = plugin_builder()
    _, batches = plugin.to_graph_queries([node], _FakeConfig(), doc_id="TEST-DOC-001", image_prefix="")
    assert batches, f"{name}: no batches"
    for i, batch in enumerate(batches):
        result, mock_post = _upsert_capturing(batch)
        assert result.applied, f"{name} #{i}: {result.outcome} {result.detail}"
        update = mock_post.call_args.kwargs["data"]["update"]
        m = _DELETE_RE.search(update)
        assert m, f"{name} #{i}: no DELETE WHERE found in the update that left httpx.post"
        deleted_graph, deleted_subject = m.group(1), m.group(2)
        # the graph is the domain INSTANCES graph, derived from the plugin label
        assert deleted_graph == f"http://internal/{plugin.domain_label}_INSTANCES"
        # the subject the DELETE removes is exactly the iri handed to upsert
        assert deleted_subject == batch["iri"]
        # ...and it is never a component / part / figure subject
        for shared in ("/components/", "/figures/", "/parts/"):
            assert shared not in deleted_subject, (
                f"{name} #{i}: DELETE subject {deleted_subject!r} is a shared-node IRI"
            )


def _two_notices_sharing_a_component():
    from doc_tools.plugins.sustainment import (
        PartImpact, SustainmentAugmentation, SustainmentNotice, SustainmentPlugin,
    )
    from doc_tools.plugins.models import BaseSection, DocumentNode

    def node_for(doc_id):
        part = PartImpact(affected_mpn="SHARED-MPN-1", replacement_mpn="REPL-9", ltb_date="2026-06-10")
        notice = SustainmentNotice(
            doc_id=doc_id, doc_type="PCN", pub_date="2026-06-10", mfr="Acme",
            categories=["EOL"], summary="s", impacted_parts=[part],
        )
        sec = BaseSection(title="t", level=1, page_start=1, content="c", node_id=f"n_{doc_id}")
        return DocumentNode(base_extraction=sec, domain_augmentation=SustainmentAugmentation(notice=notice))

    plugin = SustainmentPlugin("sustainment")
    out = []
    for doc_id in ("NOTICE-A", "NOTICE-B"):
        _, batches = plugin.to_graph_queries([node_for(doc_id)], _FakeConfig(), doc_id=doc_id, image_prefix="")
        out.extend(batches)
    return out


def test_two_notices_sharing_a_component_never_delete_each_others_triples():
    a, b = _two_notices_sharing_a_component()
    shared = "http://internal/components/SHARED-MPN-1"
    assert any(t.startswith(f"<{shared}>") for t in a["triples"]), "fixture: component not in A"
    assert any(t.startswith(f"<{shared}>") for t in b["triples"]), "fixture: component not in B"

    deletes = []
    for batch in (a, b):
        _, mock_post = _upsert_capturing(batch)
        deletes.append(_DELETE_RE.search(mock_post.call_args.kwargs["data"]["update"]).group(2))
    assert deletes[0] != deletes[1], "two notices share one DELETE subject"
    assert shared not in deletes, "a shared component IRI was the DELETE subject"

    # Neither notice DELETE subject may be a subject of the other notice triples,
    # otherwise upserting one would erase triples the other wrote.
    def subjects(batch):
        return {t.split(" ", 1)[0].strip("<>") for t in batch["triples"]}

    assert deletes[1] not in subjects(a)
    assert deletes[0] not in subjects(b)


# --- 4. the asset call site: identity, credentials, and the argument passed ---

def _drive_asset(jena, writer_cls, initiator_cls=None):
    import contextlib

    from dagster import build_asset_context

    from doc_tools.assets.semantic_assets import build_knowledge_graph
    from doc_tools.config import IngestionConfig

    config = IngestionConfig(
        graph_node_label="WorkInstruction", graph_child_label="Page",
        vector_collection_name="DocumentChunk", bucket="b",
    )
    manifest = {"doc_id": "doc-1", "text_location": "x/text.json", "metadata": {"domain_type": "maintenance"}}
    initiator_cls = initiator_cls or Initiator
    with patch("doc_tools.assets.semantic_assets.JenaOntologyWriter", writer_cls),             patch("doc_tools.assets.semantic_assets.Initiator", initiator_cls):
        with contextlib.suppress(Exception):  # the rest of the asset is heavy I/O; construction is first
            build_knowledge_graph(
                build_asset_context(), config, manifest,
                s3=MagicMock(), neo4j=MagicMock(), weaviate=MagicMock(), llm=MagicMock(), jena=jena,
            )


def test_asset_builds_writer_with_caller_supplied_auth_and_delegate_initiator(monkeypatch):
    monkeypatch.setenv("DOC_TOOLS_CLIENT_ID", "iagent-doc-tools-test")
    writer_cls = MagicMock()
    jena = MagicMock(url="http://jena:3030", dataset="ds", username="u-test", password="p-test")
    initiator_cls = MagicMock()
    _drive_asset(jena, writer_cls, initiator_cls)
    initiator_cls.assert_called_once()
    assert initiator_cls.call_args.kwargs["kind"] == "delegate"
    assert initiator_cls.call_args.kwargs["on_behalf_of"] == "iagent-doc-tools-test"
    writer_cls.assert_called_once()
    kwargs = writer_cls.call_args.kwargs
    assert kwargs["base_url"] == "http://jena:3030"  # no userinfo in the URL
    assert kwargs["auth"] == ("u-test", "p-test")


def test_asset_passes_none_auth_for_blank_credentials_and_never_binds_blank():
    writer_cls = MagicMock()
    jena = MagicMock(url="http://jena:3030", dataset="ds", username="", password="")
    _drive_asset(jena, writer_cls)
    assert writer_cls.call_args.kwargs["auth"] is None
