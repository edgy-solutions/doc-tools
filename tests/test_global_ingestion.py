"""Tests for the DataHub-polling backfill assets.

- ingest_global_semantic_links: finds Datasets carrying an ontology_uri custom
  property and proposes glossary terms.
- ingest_global_aitool_registrations: finds mlModels marked as mesh tool
  registrations.

DataHub HTTP + the term proposer are mocked.
"""
from unittest.mock import MagicMock, patch

from dagster import build_asset_context


def _resp(payload):
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = payload
    return r


@patch("doc_tools.assets.global_semantic_ingestion.propose_datahub_term")
@patch("doc_tools.assets.global_semantic_ingestion.requests.post")
def test_ingest_global_semantic_links(mock_post, mock_propose):
    from doc_tools.assets.global_semantic_ingestion import (
        ingest_global_semantic_links, GlobalIngestionConfig,
    )
    mock_post.return_value = _resp({"data": {"search": {"searchResults": [
        {"entity": {"urn": "urn:li:dataset:a",
                    "customProperties": [{"key": "ontology_uri", "value": "http://onto/Pump"}]}},
        {"entity": {"urn": "urn:li:dataset:b",
                    "customProperties": [{"key": "other", "value": "x"}]}},
    ]}}})

    stats = ingest_global_semantic_links(build_asset_context(), config=GlobalIngestionConfig(search_limit=10))

    assert stats == {"scanned": 2, "found_tags": 1, "linked": 1}
    mock_propose.assert_called_once()
    args = mock_propose.call_args.args
    assert args[0] == "urn:li:dataset:a" and args[1] == "http://onto/Pump"


@patch("doc_tools.assets.global_aitool_ingestion.requests.post")
def test_ingest_global_aitool_registrations_filters_by_marker(mock_post):
    from doc_tools.assets.global_aitool_ingestion import (
        ingest_global_aitool_registrations, GlobalAIToolIngestionConfig,
    )
    mock_post.return_value = _resp({"data": {"search": {"searchResults": [
        {"entity": {"urn": "urn:li:mlModel:tool",
                    "properties": {"customProperties": [{"key": "mesh_is_registration", "value": "true"}]}}},
        {"entity": {"urn": "urn:li:mlModel:realmodel",
                    "properties": {"customProperties": [{"key": "mesh_is_registration", "value": "false"}]}}},
        {"entity": {"urn": "urn:li:mlModel:nondisc", "properties": {"customProperties": []}}},
    ]}}})

    out = ingest_global_aitool_registrations(build_asset_context(),
                                             config=GlobalAIToolIngestionConfig(search_limit=10))

    assert out["scanned"] == 1
    assert out["tool_urns"] == ["urn:li:mlModel:tool"]
