"""Tests for the legacy-table semantic binding (doc_tools/assets/semantic_linker).

Covers the confidence-tiered classification routing, DataHub term proposal, and
the Neo4j approval sync. All external boundaries (Engine O HTTP, DataHub emitter,
DataHub GMS, Neo4j) are mocked.
"""
from unittest.mock import MagicMock, patch

from dagster import build_asset_context

from doc_tools.assets.semantic_linker import (
    get_short_name,
    propose_datahub_term,
    apply_semantic_tags,
    sync_approved_tags_to_neo4j,
    ApprovedTagConfig,
)


def test_get_short_name():
    assert get_short_name("http://onto/example/Pump") == "Pump"
    assert get_short_name("http://onto/example#Valve") == "Valve"


def _resp(payload):
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = payload
    return r


@patch("doc_tools.assets.semantic_linker.propose_datahub_term")
@patch("doc_tools.assets.semantic_linker.requests.post")
def test_apply_semantic_tags_routes_by_confidence(mock_post, mock_propose):
    confidences = {"schema.high": 0.9, "schema.mid": 0.6, "schema.low": 0.2}

    def post_side_effect(url, json=None, timeout=None, **kw):
        name = json["table_name"]
        c = confidences[name]
        return _resp({
            "resolved_uri": f"http://onto/{name}" if c >= 0.5 else None,
            "confidence_score": c,
            "reasoning": "r",
        })

    mock_post.side_effect = post_side_effect

    stats = apply_semantic_tags(
        build_asset_context(),
        extract_sqlserver_metadata={"schema.high": {"description": "d", "domain": "X"}},
        extract_oracle_metadata={"schema.mid": {"description": "d"}},
        parse_design_metadata={"schema.low": {"description": "d"}},
    )

    assert stats == {"processed": 3, "tagged": 1, "human_review": 1}
    # auto-tag (>=0.85) and human-review (>=0.5) both propose; reject (<0.5) does not
    assert mock_propose.call_count == 2


def test_apply_semantic_tags_empty_short_circuits():
    stats = apply_semantic_tags(
        build_asset_context(),
        extract_sqlserver_metadata={},
        extract_oracle_metadata={},
        parse_design_metadata={},
    )
    assert stats == {"processed": 0, "tagged": 0, "human_review": 0}


@patch("doc_tools.assets.semantic_linker.requests.post")
@patch("doc_tools.assets.semantic_linker.DatahubRestEmitter")
def test_propose_datahub_term_emits_and_posts(mock_emitter_cls, mock_post):
    mock_post.return_value = _resp({"ok": True})
    out = propose_datahub_term("urn:li:dataset:x", "http://onto/Pump", "reason")
    mock_emitter_cls.return_value.emit.assert_called_once()   # ensures GlossaryTerm metadata
    assert mock_post.called                                   # proposal submitted
    assert out == {"ok": True}


def _neo4j_with_session():
    neo4j = MagicMock()
    session = MagicMock()
    neo4j.get_driver.return_value.session.return_value.__enter__.return_value = session
    return neo4j, session


@patch("doc_tools.assets.semantic_linker.requests.post")
def test_sync_approved_tags_uses_ontology_uri_from_datahub(mock_post):
    mock_post.return_value = _resp({"data": {"glossaryTerm": {"glossaryTermInfo": {
        "customProperties": [{"key": "ontology_uri", "value": "http://onto/Pump"}]
    }}}})
    neo4j, session = _neo4j_with_session()
    cfg = ApprovedTagConfig(dataset_urn="urn:li:dataset:x", term_urn="urn:li:glossaryTerm:Pump")

    out = sync_approved_tags_to_neo4j(build_asset_context(), config=cfg, neo4j=neo4j)

    assert out["status"] == "success" and out["ontology_uri"] == "http://onto/Pump"
    kw = session.run.call_args.kwargs
    assert kw["ontology_uri"] == "http://onto/Pump"
    assert kw["dataset_urn"] == "urn:li:dataset:x"


@patch("doc_tools.assets.semantic_linker.requests.post")
def test_sync_approved_tags_falls_back_to_urn_when_no_property(mock_post):
    mock_post.return_value = _resp({"data": {"glossaryTerm": {"glossaryTermInfo": {
        "customProperties": []
    }}}})
    neo4j, _ = _neo4j_with_session()
    cfg = ApprovedTagConfig(dataset_urn="urn:li:dataset:y", term_urn="urn:li:glossaryTerm:Valve")

    out = sync_approved_tags_to_neo4j(build_asset_context(), config=cfg, neo4j=neo4j)
    assert out["ontology_uri"] == "Valve"  # parsed from the term URN
