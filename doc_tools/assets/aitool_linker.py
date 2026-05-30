"""AITool binding plane — propose / sync side.

Mirror of ``semantic_linker`` for AITool registrations rather than Datasets.
Per ADR-0004 (predicate-graph routing) and ADR-0006 (DataHub inbox, Neo4j
substrate), a mesh tool registers itself to DataHub as an ``mlModel`` entity
with ``customProperties.mesh_is_registration = "true"`` plus a full
SPO-shaped payload (verb IRI, input/output URIs, synonyms, endpoint URL,
OpenAPI schema, etc.). This module:

1. Reads that custom-property payload from DataHub at run time
2. Materializes a typed predicate edge in Neo4j:

       (s:OntologyClass {uri: input_uri})
           -[v:`<verb_local>` {iri, synonyms, endpoint_url, ...}]->
       (o:OntologyClass {uri: output_uri})

   The relationship *type* is the verb's local name (e.g.
   ``applyDiagnostics`` from ``mro:applyDiagnostics``); the full
   namespaced IRI is preserved as a relationship property. APOC's
   ``apoc.merge.relationship`` lets us parameterize the type.

Per ADR-0006: code-controlled mesh tool registrations auto-approve.
There is no HITL queue for the AITool side (unlike legacy DB tables which
need human classification). The asset is fired by ``AIToolSensorComponent``
whenever DataHub gains or updates a tagged ``mlModel`` entity.
"""

import json
import os
from typing import Any, Dict, List, Optional

import requests
from dagster import Config, asset, AssetExecutionContext

from doc_tools.utils.dagster_resources import Neo4jResource

# Use the same DataHub configuration as semantic_linker for consistency.
DATAHUB_GMS_URL = os.getenv("DATAHUB_GMS_URL", "http://datahub-gms:8080/api/graphql")
DATAHUB_TOKEN = os.getenv("DATAHUB_TOKEN", "")


def get_verb_local_name(verb_iri: str) -> str:
    """Extract the relationship type from a namespaced verb IRI.

    ``mesh:applyDiagnostics`` -> ``applyDiagnostics``
    ``mro:detectVibrationAnomalies`` -> ``detectVibrationAnomalies``

    Neo4j relationship types can't contain colons; the full IRI is stored
    as a relationship property so callers can still query by namespaced
    identity.
    """
    return verb_iri.split(":")[-1] if ":" in verb_iri else verb_iri


def _fetch_tool_properties(tool_urn: str) -> Optional[Dict[str, str]]:
    """Read the mesh tool's customProperties bag from DataHub GMS.

    Returns ``None`` if the entity is missing, the request fails, or the
    entity isn't marked as a mesh tool registration (``mesh_is_registration``
    must be ``"true"``).
    """
    query = """
    query getModelProperties($urn: String!) {
      mlModel(urn: $urn) {
        mlModelProperties {
          customProperties {
            key
            value
          }
        }
      }
    }
    """
    headers = {"Authorization": f"Bearer {DATAHUB_TOKEN}", "Content-Type": "application/json"}
    try:
        resp = requests.post(
            DATAHUB_GMS_URL,
            json={"query": query, "variables": {"urn": tool_urn}},
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
    except Exception:
        return None

    model = (
        resp.json().get("data", {}).get("mlModel") or {}
    ).get("mlModelProperties")
    if not model:
        return None

    props = {p["key"]: p["value"] for p in model.get("customProperties", [])}
    if props.get("mesh_is_registration") != "true":
        return None
    return props


def _build_relationship_properties(props: Dict[str, str]) -> Dict[str, Any]:
    """Translate DataHub's flat string customProperties into typed Neo4j
    relationship properties.

    DataHub requires custom-property values to be strings; the SDK
    JSON-encodes lists and bools (``"true"`` / ``"false"``). We restore the
    native types here so downstream Cypher / Engine O sees real arrays and
    booleans on the relationship.
    """
    try:
        synonyms: List[str] = json.loads(props.get("mesh_verb_synonyms", "[]"))
    except json.JSONDecodeError:
        synonyms = []

    # Per iagent ADR-0009: `domains` is a scope filter, not a routing key.
    # Engines self-declare the domains they serve at registration; Engine O
    # filters /find_tool matches against the caller's entitled_domains.
    # JSON-decoded back into a Neo4j list property.
    try:
        domains: List[str] = json.loads(props.get("mesh_domains", "[]"))
    except json.JSONDecodeError:
        domains = []

    return {
        "iri": props["mesh_verb_iri"],
        "synonyms": synonyms,
        "endpoint_url": props.get("mesh_endpoint_url", ""),
        "openapi_schema": props.get("mesh_openapi_schema", ""),
        "owner_persona": props.get("mesh_owner_persona", ""),
        "domains": domains,
        "cost_class": props.get("mesh_cost_class", "fast"),
        "requires_human_approval": props.get("mesh_requires_human_approval", "false") == "true",
        "namespace_authority": props.get("mesh_namespace_authority", "domain"),
        "tool_urn": props.get("_tool_urn", ""),
        "tool_kind": props.get("mesh_tool_kind", "AITool"),
        "version": props.get("mesh_tool_version", "0.0.0"),
        "sdk_version": props.get("mesh_sdk_version", ""),
    }


class AIToolSyncConfig(Config):
    """Configured by the sensor when a tool registration changes."""
    tool_urn: str


@asset
def sync_aitool_predicate_to_neo4j(
    context: AssetExecutionContext,
    config: AIToolSyncConfig,
    neo4j: Neo4jResource,
) -> dict:
    """Materialize an AITool registration as a typed predicate edge in Neo4j.

    Reads the tool's customProperties from DataHub at run time (rather than
    trusting the sensor's run config) so the materialized graph always
    reflects the current DataHub state -- this matches the Dataset side's
    Phase 7 standard where the full URI is fetched from the term at sync
    time, not from the proposal payload.
    """
    props = _fetch_tool_properties(config.tool_urn)
    if not props:
        context.log.warning(
            f"Skipping {config.tool_urn}: not a mesh tool registration or not "
            f"reachable in DataHub. The sensor may have fired stale; the next "
            f"poll will retry."
        )
        return {"status": "skipped", "tool_urn": config.tool_urn}

    verb_iri = props.get("mesh_verb_iri")
    input_uri = props.get("mesh_input_uri")
    output_uri = props.get("mesh_output_uri")
    if not (verb_iri and input_uri and output_uri):
        context.log.error(
            f"Mesh tool {config.tool_urn} is missing required predicate fields "
            f"(verb_iri={verb_iri!r}, input_uri={input_uri!r}, output_uri={output_uri!r}). "
            f"Refusing to materialize; tool author must re-register."
        )
        return {"status": "rejected", "tool_urn": config.tool_urn, "reason": "incomplete"}

    # Tag the tool URN onto the relationship so operators can trace edges back
    # to their DataHub entries (and the reconciliation asset of ADR-0006 can
    # detect orphans).
    props_with_urn = dict(props)
    props_with_urn["_tool_urn"] = config.tool_urn
    rel_props = _build_relationship_properties(props_with_urn)

    verb_local = get_verb_local_name(verb_iri)

    # APOC's apoc.merge.relationship parameterizes the relationship type --
    # essential because Cypher itself can't take a relationship type as a
    # parameter. APOC ships with Neo4j's enterprise images and is already
    # in NEO4J_PLUGINS for this cluster.
    cypher = """
    MERGE (s:OntologyClass {uri: $input_uri})
    MERGE (o:OntologyClass {uri: $output_uri})
    WITH s, o
    CALL apoc.merge.relationship(
        s,
        $verb_local,
        {iri: $verb_iri},
        $props,
        o,
        $props
    ) YIELD rel
    RETURN type(rel) AS rel_type, rel.iri AS iri
    """

    try:
        driver = neo4j.get_driver()
        with driver.session() as session:
            result = session.run(
                cypher,
                input_uri=input_uri,
                output_uri=output_uri,
                verb_local=verb_local,
                verb_iri=verb_iri,
                props=rel_props,
            )
            record = result.single()
        context.log.info(
            f"✅ Synced predicate edge: ({input_uri}) -[{verb_local}]-> ({output_uri}) "
            f"for {config.tool_urn}"
        )
        return {
            "status": "synced",
            "tool_urn": config.tool_urn,
            "verb_iri": verb_iri,
            "input_uri": input_uri,
            "output_uri": output_uri,
            "rel_type": record["rel_type"] if record else verb_local,
        }
    except Exception as e:
        context.log.error(f"❌ Failed to sync {config.tool_urn} to Neo4j: {e}")
        raise
