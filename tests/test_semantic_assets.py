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
    _extraction_payload,
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


def _n10s_session(resource_count: int):
    """A neo4j session double whose `MATCH (r:Resource) RETURN count(r)` answers
    with a real integer.

    Idempotency is decided by a PRECONDITION CHECK, not by catching the re-init
    error — n10s wraps that failure in a ClientError whose `str()` hides the
    "non-empty" substring, so two successive string-match attempts both missed
    (see the comment in semantic_assets.init_neo4j_n10s). A bare MagicMock
    session returns a MagicMock for the count, which the `> 0` comparison cannot
    order; the mock has to model the query the code actually asks.
    """
    session = MagicMock()

    def run(query, *a, **k):
        if "count(r)" in query:
            return MagicMock(single=lambda: {"c": resource_count})
        return MagicMock()

    session.run.side_effect = run
    return session


def _driver_for(session):
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    return driver


@patch("doc_tools.assets.semantic_assets.GraphDatabase.driver")
def test_init_neo4j_n10s_runs_config_and_constraint(mock_driver):
    """EMPTY graph: no :Resource nodes yet, so n10s has never been initialized
    here and init must run."""
    session = _n10s_session(resource_count=0)
    driver = _driver_for(session)
    mock_driver.return_value = driver
    neo4j = MagicMock(uri="bolt://x", username="u", password="p")

    init_neo4j_n10s(build_asset_context(), neo4j=neo4j)

    ran = [c.args[0] for c in session.run.call_args_list]
    assert any("n10s.graphconfig.init" in q for q in ran)
    assert any("CONSTRAINT" in q for q in ran)
    driver.close.assert_called_once()


@patch("doc_tools.assets.semantic_assets.GraphDatabase.driver")
def test_init_neo4j_n10s_skips_init_when_the_graph_is_already_populated(mock_driver):
    """POPULATED graph: init is SKIPPED rather than attempted-and-swallowed.

    This test was `..._tolerates_already_exists` and asserted the old shape — let
    graphconfig.init raise, catch it by message. That is the behaviour the
    precondition check replaced, because the message never matched: the asset
    now never calls init on a populated graph at all. Asserting init is NOT
    called is the whole point; a test that only checked the constraint would
    still pass if the check silently regressed to attempt-and-catch.
    """
    session = _n10s_session(resource_count=1234)
    mock_driver.return_value = _driver_for(session)

    init_neo4j_n10s(build_asset_context(), neo4j=MagicMock(uri="bolt://x", username="u", password="p"))

    ran = [c.args[0] for c in session.run.call_args_list]
    assert not any("graphconfig.init" in q for q in ran), (
        "init was attempted on a populated graph — n10s rejects that, and the "
        "rejection is the error the string-matching approach could not catch"
    )
    assert any("CONSTRAINT" in q for q in ran), (
        "the constraint is created on BOTH paths — it is IF NOT EXISTS and is "
        "what the n10s import relies on"
    )


def test_sync_jena_to_neo4j_wipes_fetches_and_labels():
    jena = _jena_resource()
    jclient = MagicMock()
    jclient.execute_query.return_value = {
        "results": {"bindings": [{"s": {"value": "mil#a"}}, {"s": {"value": "mil#b"}}]}
    }
    jena.get_client.return_value = jclient

    neo4j = MagicMock()
    nclient = MagicMock()
    # n10s.rdf.import.fetch must answer with a real row. The asset RAISES on an
    # empty result rather than logging and continuing — an import that loaded
    # nothing is the endpoint-404 / named-graph-missing failure it must be able
    # to report honestly, so "no rows" is an outcome the mock has to opt out of
    # deliberately (see test_sync_raises_when_the_n10s_fetch_reports_nothing).
    nclient.execute_query.return_value = [
        {"triplesLoaded": 42, "terminationStatus": "OK", "extraInfo": ""}
    ]
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


# --------------------------------------------------------------------------- #
# extraction.json payload — the structured LLM output written to S3 (option A).
# --------------------------------------------------------------------------- #
def test_extraction_payload_serializes_augmentations_and_skips_none():
    from doc_tools.plugins.manufacturing import (
        ManufacturingStep, StrategicAssessment, MatAugmentation,
    )
    from doc_tools.plugins.models import BaseSection, DocumentNode

    step = ManufacturingStep(
        procedure_id="0010", step_id="1", instruction_text="Apply sealant.",
        action_verb="Apply", tooling=["Wrench"], consumables=[], is_value_added=True,
        is_safety_critical=False, process_category="Transformation", justification="x",
    )
    aug = MatAugmentation(
        steps=[step], assessment=StrategicAssessment(proprietary_score=0.5, outsourceable=False)
    )
    sec = BaseSection(title="t", level=0, page_start=0, content="", node_id="d1")
    nodes = [
        DocumentNode(base_extraction=sec, domain_augmentation=aug),
        DocumentNode(base_extraction=sec, domain_augmentation=None),  # no-op augment -> skipped
    ]

    payload = _extraction_payload(nodes, "inbound/22", "manufacturing")

    assert payload["doc_id"] == "inbound/22"
    assert payload["domain_type"] == "manufacturing"
    assert len(payload["augmentations"]) == 1  # the None node is skipped
    a = payload["augmentations"][0]
    assert a["steps"][0]["action_verb"] == "Apply"
    assert a["steps"][0]["tooling"] == ["Wrench"]
    assert a["assessment"]["proprietary_score"] == 0.5


# ---------------------------------------------------------------------------
# The n10s fetch must be able to FAIL
# ---------------------------------------------------------------------------
# This step used to swallow a failed import and report success, so a WP that
# synced zero triples looked identical to one that synced cleanly — the shape
# that cost hours of debugging an endpoint-404. Both pins below exist so that
# honesty cannot regress quietly.

def _jena_with_subjects():
    jena = _jena_resource()
    jclient = MagicMock()
    jclient.execute_query.return_value = {
        "results": {"bindings": [{"s": {"value": "mil#a"}}]}
    }
    jena.get_client.return_value = jclient
    return jena


def _sync(nclient):
    neo4j = MagicMock()
    neo4j.get_client.return_value = nclient
    return sync_jena_to_neo4j(
        build_asset_context(),
        upload_to_jena={"root_uri": "mil#a", "s3_key": "s1000d/m.xml"},
        jena=_jena_with_subjects(),
        neo4j=neo4j,
    )


def test_sync_raises_when_the_n10s_fetch_reports_nothing():
    """No rows means the procedure never executed — n10s missing, or the fetch
    URL 404ing. Silent success there leaves Neo4j empty while the asset is
    green."""
    import pytest
    nclient = MagicMock()
    nclient.execute_query.return_value = []
    with pytest.raises(RuntimeError, match="no rows"):
        _sync(nclient)


def test_sync_raises_when_n10s_terminates_non_OK():
    import pytest
    nclient = MagicMock()
    nclient.execute_query.return_value = [
        {"triplesLoaded": 0, "terminationStatus": "KO", "extraInfo": "Could not fetch"}
    ]
    with pytest.raises(RuntimeError, match="terminationStatus"):
        _sync(nclient)
