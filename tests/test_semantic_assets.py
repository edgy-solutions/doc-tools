"""Tests for the Jena<->Neo4j sync pipeline in doc_tools/assets/semantic_assets.

Covers upload_to_jena (PUT to a Named Graph), init_neo4j_n10s (n10s config +
constraint, incl. the already-exists path), sync_jena_to_neo4j (deep-wipe +
n10s fetch + domain labeling), and the _apply_post_sync_domain_labels helper.
httpx / neo4j driver / Jena+Neo4j clients are mocked. The heavy
build_knowledge_graph orchestration is intentionally left to integration tests.
"""
from unittest.mock import MagicMock, patch

from dagster import build_asset_context

from doc_tools.assets.semantic_assets import (
    upload_to_jena,
    init_neo4j_n10s,
    sync_jena_to_neo4j,
    _apply_post_sync_domain_labels,
    _ensure_weaviate_collection,
    _index_chunk,
)


def _jena_resource():
    j = MagicMock()
    j.url = "http://jena:3030/"
    j.dataset = "ds"
    j.username = "u"
    j.password = "p"
    return j


@patch("doc_tools.assets.semantic_assets.httpx.Client")
def test_upload_to_jena_puts_to_named_graph(mock_client_cls):
    client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = client
    client.put.return_value = MagicMock(raise_for_status=lambda: None)

    payload = {"s3_key": "s1000d/m.xml", "rdf_string": "@prefix x: <y> .", "root_uri": "mil#x"}
    out = upload_to_jena(build_asset_context(), extract_rdf_from_xml=payload, jena=_jena_resource())

    assert out == payload  # metadata passes through downstream
    url = client.put.call_args.args[0]
    assert url.startswith("http://jena:3030/ds/data?graph=")
    assert "urn%3Adoc%3As1000d" in url               # urn:doc: quoted into the graph param
    assert client.put.call_args.kwargs["content"] == b"@prefix x: <y> ."


@patch("doc_tools.assets.semantic_assets.GraphDatabase.driver")
def test_init_neo4j_n10s_runs_config_and_constraint(mock_driver):
    session = MagicMock()
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    mock_driver.return_value = driver
    neo4j = MagicMock(uri="bolt://x", username="u", password="p")

    init_neo4j_n10s(build_asset_context(), neo4j=neo4j)

    ran = [c.args[0] for c in session.run.call_args_list]
    assert any("n10s.graphconfig.init" in q for q in ran)
    assert any("CONSTRAINT" in q for q in ran)
    driver.close.assert_called_once()


@patch("doc_tools.assets.semantic_assets.GraphDatabase.driver")
def test_init_neo4j_n10s_tolerates_already_exists(mock_driver):
    session = MagicMock()

    def run_side(query, *a, **k):
        if "graphconfig.init" in query:
            raise Exception("Config already exists")
        return MagicMock()

    session.run.side_effect = run_side
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    mock_driver.return_value = driver

    # should swallow the "already exists" error and still create the constraint
    init_neo4j_n10s(build_asset_context(), neo4j=MagicMock(uri="bolt://x", username="u", password="p"))
    assert any("CONSTRAINT" in c.args[0] for c in session.run.call_args_list)


def test_sync_jena_to_neo4j_wipes_fetches_and_labels():
    jena = _jena_resource()
    jclient = MagicMock()
    jclient.execute_query.return_value = {
        "results": {"bindings": [{"s": {"value": "mil#a"}}, {"s": {"value": "mil#b"}}]}
    }
    jena.get_client.return_value = jclient

    neo4j = MagicMock()
    nclient = MagicMock()
    neo4j.get_client.return_value = nclient

    payload = {"root_uri": "mil#a", "s3_key": "s1000d/m.xml"}
    sync_jena_to_neo4j(build_asset_context(), upload_to_jena=payload, jena=jena, neo4j=neo4j)

    queries = [c.args[0] for c in nclient.execute_query.call_args_list]
    assert any("DETACH DELETE" in q for q in queries)               # deep wipe
    assert any("n10s.rdf.import.fetch" in q for q in queries)       # n10s fetch
    assert any("SET n:MAINTENANCE" in q for q in queries)           # post-sync labeling


def test_apply_post_sync_domain_labels_sets_label():
    nclient = MagicMock()
    _apply_post_sync_domain_labels(nclient, ["mil#a", "mil#b"], "MAINTENANCE", build_asset_context())
    q, params = nclient.execute_query.call_args.args
    assert "SET n:MAINTENANCE" in q
    assert params["uri_list"] == ["mil#a", "mil#b"]


def test_apply_post_sync_domain_labels_empty_is_noop():
    nclient = MagicMock()
    _apply_post_sync_domain_labels(nclient, [], "X", build_asset_context())
    nclient.execute_query.assert_not_called()


# --------------------------------------------------------------------------- #
# Weaviate v4 chunk indexing (regression guard for the stale-API bug:
# build_knowledge_graph used to call ensure_class/add_object, which don't exist
# on the v4 WeaviateClient). Constructing wvc.config.Property in the helper also
# exercises the real Weaviate v4 API, catching signature drift.
# --------------------------------------------------------------------------- #
def test_ensure_weaviate_collection_creates_when_missing():
    client = MagicMock()
    client.collections.exists.return_value = False
    _ensure_weaviate_collection(client, "Chunks")
    client.collections.create.assert_called_once()
    assert client.collections.create.call_args.kwargs["name"] == "Chunks"


def test_ensure_weaviate_collection_skips_when_present():
    client = MagicMock()
    client.collections.exists.return_value = True
    _ensure_weaviate_collection(client, "Chunks")
    client.collections.create.assert_not_called()


def test_index_chunk_inserts_via_v4_data_insert():
    client = MagicMock()
    props = {"text": "hi", "doc_id": "d", "chunk_id": "d_p1", "domain": "MANUFACTURING"}
    _index_chunk(client, "Chunks", props)
    client.collections.get.assert_called_once_with("Chunks")
    client.collections.get.return_value.data.insert.assert_called_once_with(properties=props)
