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
from dagster import build_asset_context

from doc_tools.assets import aitool_linker
from doc_tools.assets.aitool_linker import (
    _build_relationship_properties,
    _build_predicate_search_text,
    _humanize_verb_local,
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
        "mesh_domains":                 json.dumps(["MAINTENANCE", "MANUFACTURING"]),
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
    # Per iagent ADR-0009: domains projected from mesh_domains as a real list
    assert props["domains"] == ["MAINTENANCE", "MANUFACTURING"]
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
    # Per iagent ADR-0009: missing mesh_domains defaults to an empty list
    # (domain-agnostic) — matches the SDK-side default.
    assert props["domains"] == []
    assert props["cost_class"] == "fast"  # SDK default
    assert props["requires_human_approval"] is False
    assert props["namespace_authority"] == "domain"


def test_malformed_domains_json_falls_back_to_empty():
    """Bad JSON in mesh_domains is treated as empty, never raised."""
    flat = {"mesh_verb_iri": "mesh:foo", "mesh_domains": "[not valid json"}
    props = _build_relationship_properties(flat)
    assert props["domains"] == []


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
# Predicate-vector-store helpers (iagent ADR-0009 Step F'.6)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "verb_local,expected",
    [
        ("queryKnowledgeGraph", "query knowledge graph"),
        ("applyDiagnostics",     "apply diagnostics"),
        ("analyzeDataset",       "analyze dataset"),
        ("retrieveKnowledge",    "retrieve knowledge"),
        # Already lowercased — no extra spaces inserted
        ("diagnose",             "diagnose"),
        # ALLCAPS acronym held together (no space inside)
        ("URLValidator",         "urlvalidator"),
        # Empty input is safe
        ("",                     ""),
    ],
)
def test_humanize_verb_local(verb_local, expected):
    """The verb's natural-language form is what Weaviate vectorizes; this
    function has to turn camelCase identifiers into something an embedding
    model can interpret as English without an LLM round-trip."""
    assert _humanize_verb_local(verb_local) == expected


def test_build_predicate_search_text_combines_all_signals():
    """The search blob includes the humanized verb, the synonym list, AND
    the description so BM25 and the vector embedding both have signal."""
    text = _build_predicate_search_text(
        verb_iri="mesh:queryKnowledgeGraph",
        verb_local="queryKnowledgeGraph",
        synonyms=["query graph", "cypher query", "graph lookup"],
        description="Runs a smolagents CodeAgent over Neo4j with mem0 memory.",
    )
    assert "query knowledge graph" in text
    assert "query graph" in text
    assert "cypher query" in text
    assert "smolagents" in text


def test_build_predicate_search_text_omits_empty_synonyms_and_description():
    """Missing synonyms / description don't leave dangling separators."""
    text = _build_predicate_search_text(
        verb_iri="mesh:diagnose",
        verb_local="diagnose",
        synonyms=[],
        description="",
    )
    # Just the humanized verb, no trailing ". " or ", "
    assert text == "diagnose"


def test_build_predicate_search_text_skips_blank_synonym_entries():
    text = _build_predicate_search_text(
        verb_iri="mesh:diagnose",
        verb_local="diagnose",
        synonyms=["", "diagnose vibration", None or ""],  # nosec - explicit blanks
        description="",
    )
    # Empty entries dropped from the joined synonym blob
    assert "diagnose vibration" in text
    assert ", ," not in text


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
    """Build a real AssetExecutionContext for direct asset invocation.

    ``sync_aitool_predicate_to_neo4j`` is an ``@asset``; newer Dagster rejects a
    direct-invocation context that isn't a ``BaseDirectExecutionContext``, so a
    bare ``MagicMock()`` no longer works. ``build_asset_context()`` is the
    matching helper for an asset (vs. ``build_op_context`` for an ``@op``).
    """
    return build_asset_context()


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
    # No live services in this unit test: Neo4j is faked via _FakeNeo4jResource
    # and DataHub via the patch above. The happy path also mirrors the predicate
    # to Weaviate (ADR-0009 Step F'.6) as a best-effort side effect; stub it so
    # the test doesn't attempt a real connection to http://weaviate:8080.
    monkeypatch.setattr(aitool_linker, "sync_predicate_to_weaviate", lambda **kwargs: None)

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


# ---------------------------------------------------------------------------
# Two species share this table: engine verbs and presentation triples
# ---------------------------------------------------------------------------
#
# Measured 2026-08-21 against a live cluster: DataHub held 11 presentation
# registrations and Weaviate's Predicate collection held ZERO rendersAs rows.
# The field check demanded mesh_verb_iri / mesh_input_uri / mesh_output_uri
# unconditionally, so every presentation was rejected as "incomplete" -- at
# ERROR level, instructing the author to "re-register", A REMEDY THAT CANNOT
# WORK because re-registering produces the same fields.
#
# `mesh_tool_kind` was already on every row and already read into rel_props.
# The discriminator existed in the data and nothing branched on it.

_PRESENTATION_PROPS = {
    "mesh_is_registration": "true",
    "mesh_tool_kind": "Presentation",
    "mesh_subject_uri": "http://invincible-agent/mesh#DatasetAnalysisReport",
    "mesh_predicate_iri": "mesh:rendersAs",
    "mesh_object_uri": "http://invincible-agent/mesh#ChartWidget",
    "mesh_archetype": "CHART_WIDGET",
    "mesh_expected_fields": '["dataset_id", "metrics", "viz_type"]',
}


def _run_linker(monkeypatch, props):
    """Drive the asset with DataHub stubbed and Neo4j/Weaviate mocked."""
    monkeypatch.setattr(aitool_linker, "_fetch_tool_properties", lambda urn: props)
    monkeypatch.setattr(aitool_linker, "sync_predicate_to_weaviate",
                        lambda *a, **k: None)

    captured = {}

    class _Session:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def run(self, cypher, **params):
            captured.update(params)
            r = MagicMock()
            r.single.return_value = {"rel_type": params.get("verb_local"),
                                     "iri": params.get("verb_iri")}
            return r

    class _Driver:
        def session(self): return _Session()

    neo4j = MagicMock()
    neo4j.get_driver.return_value = _Driver()

    cfg = aitool_linker.AIToolSyncConfig(tool_urn="urn:li:mlModel:(x,presentation_probe,PROD)")
    out = aitool_linker.sync_aitool_predicate_to_neo4j(
        build_asset_context(), cfg, neo4j)
    return out, captured


def test_a_PRESENTATION_registration_materializes(monkeypatch):
    """The break-on-purpose: this exact payload was REJECTED before the tool_kind branch."""
    out, captured = _run_linker(monkeypatch, dict(_PRESENTATION_PROPS))
    assert out["status"] != "rejected", f"presentation rejected: {out}"
    # subject -> predicate -> object maps onto the existing input -> verb -> output slots,
    # because a Predicate row IS a triple and so is a presentation.
    assert captured["input_uri"] == _PRESENTATION_PROPS["mesh_subject_uri"]
    assert captured["output_uri"] == _PRESENTATION_PROPS["mesh_object_uri"]
    assert captured["verb_local"] == "rendersAs"


def test_a_presentation_MISSING_its_own_fields_is_still_rejected(monkeypatch):
    """The branch must not become a bypass. A Presentation lacking subject/object is as
    unmaterializable as a verb lacking input/output."""
    props = dict(_PRESENTATION_PROPS)
    del props["mesh_object_uri"]
    out, _ = _run_linker(monkeypatch, props)
    assert out["status"] == "rejected" and out["reason"] == "incomplete"


def test_ENGINE_registrations_are_UNCHANGED_by_the_branch(monkeypatch):
    """The verb path is the population the guard was built for. It must be untouched."""
    props = {
        "mesh_is_registration": "true",
        "mesh_tool_kind": "Engine",
        "mesh_verb_iri": "mesh:lookupOwnership",
        "mesh_input_uri": "http://invincible-agent/idp#Dataset",
        "mesh_output_uri": "http://invincible-agent/mesh#OwnershipFact",
    }
    out, captured = _run_linker(monkeypatch, props)
    assert out["status"] != "rejected"
    assert captured["input_uri"] == props["mesh_input_uri"]
    assert captured["verb_local"] == "lookupOwnership"


def test_a_row_with_NO_tool_kind_takes_the_verb_path(monkeypatch):
    """Absent kind defaults to the verb species, matching the pre-existing default
    (`props.get("mesh_tool_kind", "AITool")`). A missing discriminator must not silently
    change which fields are required."""
    props = {
        "mesh_is_registration": "true",
        "mesh_verb_iri": "mesh:describeAsset",
        "mesh_input_uri": "http://invincible-agent/idp#Dataset",
        "mesh_output_uri": "http://invincible-agent/mesh#AssetProfile",
    }
    out, _ = _run_linker(monkeypatch, props)
    assert out["status"] != "rejected"


# ═══════════════════════════════════════════════════════════════════════════════
# UNREACHABLE IS NOT A SKIP (2026-08-21)
#
# The doc-tools pod held an invalid DATAHUB_TOKEN. Every GMS call returned HTTP
# 401. `raise_for_status()` raised, a blanket `except Exception` swallowed it,
# `_fetch_tool_properties` returned None, and the asset logged "not a mesh tool
# registration or not reachable ... the next poll will retry" and returned
# {"status": "skipped"} -- so the Dagster run reported SUCCESS.
#
# A manual materialization of one presentation URN went green while writing
# nothing. That is the expensive shape: a dead path dressed as a working
# fallback, which the next operator falls back TO, watches succeed, and trusts.
#
# The two conditions are now distinct:
#   * DataHub unreadable (auth/transport/GraphQL errors) -> RAISE. The question
#     went unanswered; no poll can fix a bad credential.
#   * DataHub read fine, URN simply isn't a registration -> skip, as before.
# ═══════════════════════════════════════════════════════════════════════════════

class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


def test_a_401_raises_instead_of_reporting_a_skip(monkeypatch):
    """THE REGRESSION. An auth failure must not be indistinguishable from
    'this URN is not a registration'."""
    monkeypatch.setattr(
        aitool_linker.requests, "post",
        lambda *a, **k: _Resp(status=401),
    )
    with pytest.raises(aitool_linker.MeshToolUnreachableError) as exc:
        aitool_linker._fetch_tool_properties("urn:li:mlModel:(x,y,PROD)")
    assert "unreadable" in str(exc.value).lower()


def test_transport_failure_raises(monkeypatch):
    """A connection error is also an unanswered question, not a negative answer."""
    def _boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(aitool_linker.requests, "post", _boom)
    with pytest.raises(aitool_linker.MeshToolUnreachableError):
        aitool_linker._fetch_tool_properties("urn:li:mlModel:(x,y,PROD)")


def test_graphql_errors_raise(monkeypatch):
    """Schema drift returns HTTP 200 with data:null and an errors array. Silently
    retrying that is how drift survives for months."""
    monkeypatch.setattr(
        aitool_linker.requests, "post",
        lambda *a, **k: _Resp(body={"data": None, "errors": [{"message": "no field"}]}),
    )
    with pytest.raises(aitool_linker.MeshToolUnreachableError):
        aitool_linker._fetch_tool_properties("urn:li:mlModel:(x,y,PROD)")


def test_a_genuine_non_registration_still_skips(monkeypatch):
    """THE POSITIVE CONTROL. If everything raised, the asset could never skip a
    legitimately unrelated URN -- and a seal that only raises is not a seal."""
    monkeypatch.setattr(
        aitool_linker.requests, "post",
        lambda *a, **k: _Resp(body={"data": {"mlModel": {"properties": {
            "description": "a dataset, not a mesh tool",
            "customProperties": [{"key": "mesh_is_registration", "value": "false"}],
        }}}}),
    )
    assert aitool_linker._fetch_tool_properties("urn:li:mlModel:(x,y,PROD)") is None


def test_a_real_registration_still_returns_props(monkeypatch):
    """The happy path must survive the change."""
    monkeypatch.setattr(
        aitool_linker.requests, "post",
        lambda *a, **k: _Resp(body={"data": {"mlModel": {"properties": {
            "description": "renders ownership facts",
            "customProperties": [
                {"key": "mesh_is_registration", "value": "true"},
                {"key": "mesh_tool_kind", "value": "Presentation"},
            ],
        }}}}),
    )
    props = aitool_linker._fetch_tool_properties("urn:li:mlModel:(x,y,PROD)")
    assert props["mesh_tool_kind"] == "Presentation"
    assert props["_mesh_description"] == "renders ownership facts"


# ---------------------------------------------------------------------------
# mesh_slots — the verb's parameter declarations (iagent slot pipeline)
# ---------------------------------------------------------------------------
# Requested in docs/mesh-slots-projection-request.md. The producer emits the key
# today and it was being SILENTLY dropped, which is the bug class the allowlist's
# own architectural note already names.


def test_mesh_slots_projects_as_a_json_string():
    """Present and intact, verbatim.

    The shape here is the CORRECTED one: `window` is `list[str]`, not `str`. The original
    request document showed `str`, and that was not a typo in the document — it was what
    the producer emitted, because its derivation unwrapped `Optional[list[str]]` twice and
    reported the element type. Fixed upstream; the shape is pinned here so this repo's
    expectation cannot quietly drift back."""
    declarations = (
        '[{"name": "group_by", "kind": "spoken-optional", "type": "enum", '
        '"required": false, "values": ["org", "initiative"], "default": "org"}, '
        '{"name": "window", "kind": "spoken-optional", "type": "list[str]", "required": false}, '
        '{"name": "baseline_state", "kind": "handle", "type": "PlanState", "required": true}]'
    )
    props = _build_relationship_properties(
        {"mesh_verb_iri": "mesh:foo", "mesh_slots": declarations}
    )
    assert props["slots"] == declarations, "the declarations must survive byte for byte"

    # ...and the string is real JSON the consumer can decode, with the kinds intact —
    # asserting on the string alone would pass for a string that says anything at all.
    decoded = json.loads(props["slots"])
    assert [d["name"] for d in decoded] == ["group_by", "window", "baseline_state"]
    assert decoded[2]["kind"] == "handle"


def test_mesh_slots_is_a_STRING_because_neo4j_cannot_hold_a_list_of_maps():
    """THE CONSTRAINT THAT SHAPED THIS FIELD, pinned so it survives a tidy-up.

    `slots` is a list of MAPS. Neo4j property values may only be primitives or arrays of
    primitives, so decoding this the way `domains` is decoded makes the relationship write
    fail with `Neo.ClientError.Statement.TypeError`. Measured against the sandbox Neo4j in a
    rolled-back transaction before this field was written.

    The inconsistency with `domains` is therefore deliberate, and it looks exactly like a
    bug to a reader who does not know the constraint — which is why it is asserted rather
    than only commented."""
    props = _build_relationship_properties(
        {"mesh_verb_iri": "mesh:foo", "mesh_slots": '[{"name": "group_by"}]'}
    )
    assert isinstance(props["slots"], str), (
        "slots was decoded into a list — the Neo4j write will now fail for every verb "
        "that declares a slot. See the comment in _build_relationship_properties."
    )
    # The sibling that IS a list, so this test cannot pass by everything being a string.
    domains = _build_relationship_properties(
        {"mesh_verb_iri": "mesh:foo", "mesh_domains": '["PORTFOLIO_PLANNING"]'}
    )
    assert isinstance(domains["domains"], list)


def test_missing_mesh_slots_defaults_to_an_empty_list():
    """Absent means `[]` means today's behaviour — the same contract `mesh_domains` has.

    The iagent side fails CLOSED on empty declarations (every spoken slot refused), so this
    default is what keeps the whole slot pipeline dark until a producer actually declares."""
    props = _build_relationship_properties({"mesh_verb_iri": "mesh:foo"})
    assert props["slots"] == "[]"
    assert json.loads(props["slots"]) == []


def test_malformed_mesh_slots_json_falls_back_to_empty():
    """Never raised, per the idiom. Validated-but-not-decoded: this function checks the JSON
    parses precisely so a consumer's own `json.loads` cannot be handed garbage that this
    function chose to pass along."""
    props = _build_relationship_properties(
        {"mesh_verb_iri": "mesh:foo", "mesh_slots": "[not valid json"}
    )
    assert props["slots"] == "[]"


def test_a_key_outside_the_allowlist_DOES_NOT_PROJECT():
    """THE NEGATIVE, and the reason this file gained tests at all.

    The discard is currently INCIDENTAL — it falls out of the return value being a literal
    dict, and nothing states it is intended. That is exactly what let `mesh_slots` be
    dropped without a signal for as long as it was: the producer emitted it, the projection
    ignored it, and no error was raised at any layer.

    Pinning the discard as a DECISION means the next producer that invents a key learns it
    from a red test instead of rediscovering the silence. The allowlist's own architectural
    note calls this out as its own bug class, and names mesh_provider + mesh_timeout_s as
    the pair it nearly hid once already."""
    props = _build_relationship_properties(
        {"mesh_verb_iri": "mesh:foo", "mesh_not_a_real_key": "x"}
    )
    assert "mesh_not_a_real_key" not in props
    assert "not_a_real_key" not in props
    assert "x" not in props.values(), "the value leaked in under some other name"

    # Non-vacuity: a key that IS on the allowlist projects, so the assertions above are
    # detecting the allowlist rather than an empty return.
    assert _build_relationship_properties(
        {"mesh_verb_iri": "mesh:foo", "mesh_provider": "engine_d"}
    )["provider"] == "engine_d"


# ---------------------------------------------------------------------------
# The retirement, asserted rather than narrated
# ---------------------------------------------------------------------------

_RETIREMENT = (
    "ADR-0006 §Addendum retired this path on 2026-06-13. "
    "`agent_fleet/mesh_registrar` (invincible-agent) is the SOLE WRITER of AITool "
    "predicate edges to the live graph; this module exists only for one-off manual "
    "re-syncs through the Dagster launchpad. Re-wiring it into automatic registration "
    "gives the substrate TWO writers with different property sets — which is the "
    "allowlist-drift bug class the retirement was performed to end."
)


def test_the_aitool_sensor_STAYS_RETIRED():
    """Fails if anyone wires this path back into automatic registration.

    Read from the source with AST rather than by importing `definitions` — that import
    pulls the whole Dagster + torch dependency chain, and a test that cannot run is not a
    guard. What is asserted is narrow and exact: no name mentioning `aitool` may appear in
    the arguments of the `Definitions(...)` call.

    WHY A TEST AND NOT THE COMMENT THAT IS ALREADY THERE. The retirement WAS documented —
    in an ADR addendum, and in a comment at the `Definitions(...)` call, one file over from
    the projection everyone reads. Two agents in two days traced a property into
    `aitool_linker.py`, found a plausible working projection, and built against it; the
    second filed a cross-repo request calling it "the single gate" on a feature it could
    not gate. Prose one file over is prose nobody reads. A test fails in the reader's face.
    """
    import ast
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1] / "doc_tools" / "definitions.py")
    tree = ast.parse(src.read_text(encoding="utf-8"))

    call = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "Definitions"),
        None,
    )
    assert call is not None, "the Definitions(...) call moved — this guard points at nothing"

    mentioned = {
        n.id for n in ast.walk(call) if isinstance(n, ast.Name)
    } | {
        n.attr for n in ast.walk(call) if isinstance(n, ast.Attribute)
    }
    offenders = sorted(m for m in mentioned if "aitool" in m.lower())
    assert not offenders, f"{offenders} wired back into Definitions(). {_RETIREMENT}"

    # Non-vacuity: the call really does reference the sensors that ARE live, so an empty
    # `mentioned` set cannot make this pass silently.
    assert any("sensor" in m.lower() for m in mentioned), (
        "no sensor names found in Definitions(...) — the AST walk is not seeing the "
        "arguments, so the assertion above proved nothing"
    )


def test_the_module_says_it_is_retired_where_a_reader_LANDS():
    """The banner is load-bearing, not decoration.

    An agent tracing "where does this property get written" opens this module, not
    `definitions.py` and not the ADR. The retirement has to be legible from the first
    screen or it is not legible at all — which is exactly how it was missed twice."""
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1]
           / "doc_tools" / "assets" / "aitool_linker.py").read_text(encoding="utf-8")
    head = src[:2500]
    assert "RETIRED" in head, "the retirement banner left the top of the module"
    assert "mesh_registrar" in head, "the banner no longer names the live writer"
    assert "ADR-0006" in head, "the banner no longer cites the ruling that retired this"

    fn = src[src.index("def _build_relationship_properties"):][:1400]
    assert "RETIRED" in fn, (
        "the projection function no longer says it is retired — a reader who jumps "
        "straight to it (which is what a search for the property does) sees nothing"
    )
