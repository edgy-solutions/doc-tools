"""Tests for the AITool binding plane (ADR-0004 Step B).

Covers the deterministic logic in ``aitool_linker``:

- ``get_verb_local_name`` URI-to-relationship-type extraction
- ``_build_relationship_properties`` type-restoration from DataHub's
  flat-string customProperties (booleans + JSON-encoded arrays)
- The sync asset's end-to-end flow with mocked DataHub fetch + Neo4j driver

We don't exercise the live DataHub GraphQL or a real Neo4j here — those
are covered by integration tests against the dev cluster. Unit tests just
need to pin down the contract so refactors can't silently break it.
"""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from doc_tools.assets import aitool_linker
from doc_tools.assets.aitool_linker import (
    _build_relationship_properties,
    get_verb_local_name,
    sync_aitool_predicate_to_neo4j,
    AIToolSyncConfig,
)


# ---------------------------------------------------------------------------
# get_verb_local_name
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "iri,expected",
    [
        ("mesh:applyDiagnostics", "applyDiagnostics"),
        ("mro:detectVibrationAnomalies", "detectVibrationAnomalies"),
        ("logistics:analyzeFacilityInventory", "analyzeFacilityInventory"),
        ("compliance:auditProcedure", "auditProcedure"),
        # Defensive: even an un-namespaced string returns itself unchanged
        ("plainVerb", "plainVerb"),
    ],
)
def test_get_verb_local_name(iri, expected):
    assert get_verb_local_name(iri) == expected


# ---------------------------------------------------------------------------
# _build_relationship_properties
# ---------------------------------------------------------------------------
def test_build_relationship_properties_restores_types():
    """DataHub stores everything as a string; we restore arrays and booleans."""
    flat = {
        "mesh_is_registration":         "true",
        "mesh_tool_kind":               "AITool",
        "mesh_verb_iri":                "mro:applyDiagnostics",
        "mesh_verb_synonyms":           json.dumps(["diagnose", "troubleshoot"]),
        "mesh_input_uri":               "mro:Symptom",
        "mesh_output_uri":              "mro:FaultReport",
        "mesh_owner_persona":           "MECHANIC",
        "mesh_cost_class":              "medium",
        "mesh_requires_human_approval": "true",
        "mesh_namespace_authority":     "domain",
        "mesh_endpoint_url":            "http://engine-a.mesh.svc:8081/execute",
        "mesh_openapi_schema":          "{\"openapi\":\"3.0.0\"}",
        "mesh_sdk_version":             "0.1.0",
        "mesh_tool_version":            "1.2.3",
        "_tool_urn":                    "urn:li:mlModel:(urn:li:dataPlatform:mesh,foo,PROD)",
    }
    props = _build_relationship_properties(flat)

    assert props["iri"] == "mro:applyDiagnostics"
    assert props["synonyms"] == ["diagnose", "troubleshoot"]  # restored to list
    assert props["endpoint_url"] == "http://engine-a.mesh.svc:8081/execute"
    assert props["owner_persona"] == "MECHANIC"
    assert props["cost_class"] == "medium"
    assert props["requires_human_approval"] is True  # restored to bool
    assert props["namespace_authority"] == "domain"
    assert props["tool_urn"] == "urn:li:mlModel:(urn:li:dataPlatform:mesh,foo,PROD)"
    assert props["tool_kind"] == "AITool"
    assert props["version"] == "1.2.3"
    assert props["sdk_version"] == "0.1.0"


def test_build_relationship_properties_defaults():
    """Missing optional fields get sensible defaults; missing required IRI raises."""
    minimal = {"mesh_verb_iri": "mesh:foo"}
    props = _build_relationship_properties(minimal)
    assert props["iri"] == "mesh:foo"
    assert props["synonyms"] == []
    assert props["endpoint_url"] == ""
    assert props["owner_persona"] == ""
    assert props["cost_class"] == "fast"  # SDK default
    assert props["requires_human_approval"] is False
    assert props["namespace_authority"] == "domain"


def test_build_relationship_properties_malformed_synonyms_json():
    """Bad JSON in synonyms gracefully falls back to an empty list."""
    flat = {"mesh_verb_iri": "mesh:foo", "mesh_verb_synonyms": "[not valid json"}
    props = _build_relationship_properties(flat)
    assert props["synonyms"] == []


def test_requires_human_approval_only_true_when_string_is_true():
    """Anything other than the exact string ``"true"`` is False."""
    assert _build_relationship_properties(
        {"mesh_verb_iri": "x:y", "mesh_requires_human_approval": "true"}
    )["requires_human_approval"] is True

    for falsy in ["false", "FALSE", "0", "", "yes", "no", "True"]:
        assert _build_relationship_properties(
            {"mesh_verb_iri": "x:y", "mesh_requires_human_approval": falsy}
        )["requires_human_approval"] is False, f"failed for {falsy!r}"


# ---------------------------------------------------------------------------
# sync_aitool_predicate_to_neo4j — end-to-end with mocks
# ---------------------------------------------------------------------------
class _FakeSession:
    """Records the Cypher + params passed through; returns a fixed record."""

    def __init__(self):
        self.executed = None

    @contextmanager
    def __enter__cm(self):
        yield self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, cypher, **params):
        self.executed = (cypher, params)
        result = MagicMock()
        result.single.return_value = {
            "rel_type": params.get("verb_local"),
            "iri": params.get("verb_iri"),
        }
        return result


class _FakeDriver:
    def __init__(self):
        self.session_obj = _FakeSession()

    def session(self):
        return self.session_obj


class _FakeNeo4jResource:
    def __init__(self):
        self.driver = _FakeDriver()

    def get_driver(self):
        return self.driver


def _ctx():
    """Build a minimal AssetExecutionContext stand-in."""
    ctx = MagicMock()
    ctx.log = MagicMock()
    return ctx


def test_sync_emits_apoc_merge_with_verb_local_name(monkeypatch):
    """Happy path: DataHub returns a full tool payload; the sync emits a
    Cypher MERGE that uses APOC's parameterized relationship type."""
    full_props = {
        "mesh_is_registration":         "true",
        "mesh_tool_kind":               "AITool",
        "mesh_verb_iri":                "mro:applyDiagnostics",
        "mesh_verb_synonyms":           json.dumps(["diagnose"]),
        "mesh_input_uri":               "mro:Symptom",
        "mesh_output_uri":              "mro:FaultReport",
        "mesh_owner_persona":           "MECHANIC",
        "mesh_cost_class":              "medium",
        "mesh_requires_human_approval": "false",
        "mesh_namespace_authority":     "domain",
        "mesh_endpoint_url":            "http://engine-a.mesh.svc:8081/execute",
        "mesh_openapi_schema":          "{}",
        "mesh_sdk_version":             "0.1.0",
        "mesh_tool_version":            "0.1.0",
    }
    monkeypatch.setattr(aitool_linker, "_fetch_tool_properties", lambda urn: full_props)

    neo4j = _FakeNeo4jResource()
    result = sync_aitool_predicate_to_neo4j(
        _ctx(),
        config=AIToolSyncConfig(tool_urn="urn:li:mlModel:(urn:li:dataPlatform:mesh,foo,PROD)"),
        neo4j=neo4j,
    )

    assert result["status"] == "synced"
    assert result["verb_iri"] == "mro:applyDiagnostics"
    assert result["input_uri"] == "mro:Symptom"
    assert result["output_uri"] == "mro:FaultReport"

    cypher, params = neo4j.driver.session_obj.executed
    assert "apoc.merge.relationship" in cypher
    assert params["verb_local"] == "applyDiagnostics"
    assert params["verb_iri"] == "mro:applyDiagnostics"
    assert params["input_uri"] == "mro:Symptom"
    assert params["output_uri"] == "mro:FaultReport"
    assert params["props"]["synonyms"] == ["diagnose"]
    assert params["props"]["requires_human_approval"] is False


def test_sync_skips_when_datahub_returns_nothing(monkeypatch):
    """If the tool URN can't be fetched (deleted, unreachable, wrong type),
    skip cleanly rather than crashing."""
    monkeypatch.setattr(aitool_linker, "_fetch_tool_properties", lambda urn: None)

    neo4j = _FakeNeo4jResource()
    result = sync_aitool_predicate_to_neo4j(
        _ctx(),
        config=AIToolSyncConfig(tool_urn="urn:li:mlModel:(urn:li:dataPlatform:mesh,gone,PROD)"),
        neo4j=neo4j,
    )

    assert result["status"] == "skipped"
    assert neo4j.driver.session_obj.executed is None


def test_sync_rejects_incomplete_payload(monkeypatch):
    """If the SDK somehow produces a registration with missing verb/IO URIs,
    refuse to write a malformed edge."""
    incomplete = {
        "mesh_is_registration": "true",
        "mesh_verb_iri": "mro:foo",
        "mesh_input_uri": "",
        "mesh_output_uri": "",
    }
    monkeypatch.setattr(aitool_linker, "_fetch_tool_properties", lambda urn: incomplete)

    neo4j = _FakeNeo4jResource()
    result = sync_aitool_predicate_to_neo4j(
        _ctx(),
        config=AIToolSyncConfig(tool_urn="urn:li:mlModel:(urn:li:dataPlatform:mesh,bad,PROD)"),
        neo4j=neo4j,
    )

    assert result["status"] == "rejected"
    assert result["reason"] == "incomplete"
    assert neo4j.driver.session_obj.executed is None


def test_sync_propagates_neo4j_errors(monkeypatch):
    """Per ADR-0006, the runtime Neo4j side is authoritative for routing.
    If we can't write the edge, the asset must FAIL loudly so Dagster
    surfaces it -- we do NOT swallow errors here."""
    monkeypatch.setattr(
        aitool_linker, "_fetch_tool_properties", lambda urn: {
            "mesh_is_registration": "true",
            "mesh_verb_iri": "mesh:foo",
            "mesh_input_uri": "mesh:A",
            "mesh_output_uri": "mesh:B",
        }
    )

    class _BrokenNeo4j:
        def get_driver(self):
            broken = MagicMock()
            broken.session.side_effect = RuntimeError("neo4j unreachable")
            return broken

    with pytest.raises(RuntimeError, match="neo4j unreachable"):
        sync_aitool_predicate_to_neo4j(
            _ctx(),
            config=AIToolSyncConfig(tool_urn="urn:li:mlModel:(urn:li:dataPlatform:mesh,x,PROD)"),
            neo4j=_BrokenNeo4j(),
        )
