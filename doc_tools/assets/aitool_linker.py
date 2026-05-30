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
from typing import Any, Dict, List, Optional, Tuple

import requests
import weaviate.classes as wvc
from weaviate.util import generate_uuid5
from dagster import Config, asset, AssetExecutionContext

from doc_tools.utils.dagster_resources import Neo4jResource
from doc_tools.utils.weaviate_client import get_weaviate_client

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

    The mlModel's top-level ``description`` is folded into the returned dict
    under the synthetic key ``_mesh_description`` so the Weaviate sync (per
    iagent ADR-0009 Step F'.6) has the natural-language text it needs for
    semantic verb matching, without forcing a second GraphQL round trip.
    """
    query = """
    query getModelProperties($urn: String!) {
      mlModel(urn: $urn) {
        mlModelProperties {
          description
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
    # Stash the top-level description for the Weaviate sync.
    if model.get("description"):
        props["_mesh_description"] = model["description"]
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


# ---------------------------------------------------------------------------
# Weaviate `Predicate` collection sync (iagent ADR-0009 Step F'.6)
# ---------------------------------------------------------------------------
#
# Engine O's /search_predicates does verb-level routing — given an NL query,
# pick the registered predicate that best matches. Cypher exact-match on
# r.synonyms is brittle (tense / phrasing / plural variations all miss), so
# we mirror the OntologyClass / Weaviate pattern for predicates: doc-tools
# writes each registered predicate to a `Predicate` collection here; Engine
# O runs hybrid search (BM25 + vector) against it at routing time.
#
# Schema design: one Predicate object per (verb_iri, input_uri) pair. The
# vectorized text combines the human-readable verb tokens + synonyms +
# description so semantic similarity catches phrasings the synonym list
# missed.

_PREDICATE_COLLECTION = "Predicate"


def _humanize_verb_local(verb_local: str) -> str:
    """Turn ``queryKnowledgeGraph`` into ``query knowledge graph`` so the
    embedding sees the verb as natural language instead of camelCase glue.
    Cheap and deterministic — no LLM needed."""
    out = []
    for i, ch in enumerate(verb_local):
        if i > 0 and ch.isupper() and not verb_local[i - 1].isupper():
            out.append(" ")
        out.append(ch.lower())
    return "".join(out).strip()


def _build_predicate_search_text(
    verb_iri: str,
    verb_local: str,
    synonyms: List[str],
    description: str,
) -> str:
    """Compose the natural-language blob that Weaviate vectorizes.

    The blob is concatenated in priority order: the verb's human-readable
    form (so the embedding picks up the verb itself), the synonym list
    (operator-curated NL phrasings), and the description (free-form
    explanation). All three contribute to BM25 ranking; the combined text
    drives the vector embedding.
    """
    parts: List[str] = [_humanize_verb_local(verb_local)]
    if synonyms:
        parts.append(", ".join(s for s in synonyms if s))
    if description:
        parts.append(description)
    return ". ".join(p for p in parts if p)


def _ensure_predicate_collection(client, log) -> Any:
    """Idempotent create + return handle to the Predicate collection."""
    if not client.collections.exists(_PREDICATE_COLLECTION):
        log.info(f"Creating {_PREDICATE_COLLECTION} collection in Weaviate...")
        client.collections.create(
            name=_PREDICATE_COLLECTION,
            properties=[
                # Identity / routing
                wvc.config.Property(name="verb_iri", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="verb_local", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="input_uri", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="output_uri", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="endpoint_url", data_type=wvc.config.DataType.TEXT),
                # Persona / scope
                wvc.config.Property(name="owner_persona", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(
                    name="domains",
                    data_type=wvc.config.DataType.TEXT_ARRAY,
                ),
                # Policy
                wvc.config.Property(name="cost_class", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="requires_human_approval", data_type=wvc.config.DataType.BOOL),
                # NL text (the field Engine O runs hybrid search over)
                wvc.config.Property(name="search_text", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(
                    name="synonyms",
                    data_type=wvc.config.DataType.TEXT_ARRAY,
                ),
                wvc.config.Property(name="description", data_type=wvc.config.DataType.TEXT),
                # Provenance
                wvc.config.Property(name="tool_urn", data_type=wvc.config.DataType.TEXT),
            ],
        )
    return client.collections.get(_PREDICATE_COLLECTION)


def sync_predicate_to_weaviate(
    rel_props: Dict[str, Any],
    description: str,
    tool_urn: str,
    context: AssetExecutionContext,
) -> None:
    """Mirror a Neo4j predicate edge to the Weaviate Predicate collection.

    Idempotent: the Weaviate UUID is deterministic from (verb_iri, input_uri),
    so re-syncs upsert the same row. A Weaviate failure is logged and
    swallowed — Neo4j remains the system of record, but Engine O's
    /search_predicates needs the Weaviate row to route. A missed sync
    means this predicate is unroutable until the next successful sync;
    the sensor's retry policy is what closes that window.
    """
    verb_iri = rel_props["iri"]
    verb_local = get_verb_local_name(verb_iri)
    input_uri = rel_props.get("_input_uri") or rel_props.get("input_uri", "")
    output_uri = rel_props.get("_output_uri") or rel_props.get("output_uri", "")
    synonyms = list(rel_props.get("synonyms") or [])
    domains = list(rel_props.get("domains") or [])

    search_text = _build_predicate_search_text(
        verb_iri=verb_iri,
        verb_local=verb_local,
        synonyms=synonyms,
        description=description or "",
    )

    client = get_weaviate_client()
    try:
        collection = _ensure_predicate_collection(client, context.log)

        deterministic_uuid = generate_uuid5(f"{verb_iri}|{input_uri}")
        properties = {
            "verb_iri": verb_iri,
            "verb_local": verb_local,
            "input_uri": input_uri,
            "output_uri": output_uri,
            "endpoint_url": rel_props.get("endpoint_url", ""),
            "owner_persona": rel_props.get("owner_persona", ""),
            "domains": domains,
            "cost_class": rel_props.get("cost_class", "fast"),
            "requires_human_approval": bool(rel_props.get("requires_human_approval", False)),
            "search_text": search_text,
            "synonyms": synonyms,
            "description": description or "",
            "tool_urn": tool_urn,
        }

        # Upsert: replace_properties handles the create-or-update path
        # without needing a separate exists() round-trip.
        if collection.data.exists(uuid=deterministic_uuid):
            collection.data.replace(uuid=deterministic_uuid, properties=properties)
        else:
            collection.data.insert(uuid=deterministic_uuid, properties=properties)

        context.log.info(
            f"✅ Mirrored predicate to Weaviate: {verb_iri} (uuid={deterministic_uuid})"
        )
    except Exception as exc:  # noqa: BLE001
        # Per ADR-0009 Step F'.6: Weaviate is a routing accelerator, not the
        # source of truth. A missed sync degrades verb matching to Cypher
        # exact-match (the current behavior) — it does not break routing.
        context.log.warning(
            f"⚠️ Failed to mirror predicate {verb_iri} to Weaviate: {exc}. "
            f"Neo4j edge is authoritative; Engine O will fall back to Cypher "
            f"exact-match until the next successful sync."
        )
    finally:
        try:
            client.close()
        except Exception:
            pass


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

    # Stash the input/output URIs on rel_props so the Weaviate sync below
    # has them in one place. These don't end up on the Neo4j relationship
    # (the endpoint nodes carry them) — purely a local pass-through.
    rel_props["_input_uri"] = input_uri
    rel_props["_output_uri"] = output_uri

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
    except Exception as e:
        context.log.error(f"❌ Failed to sync {config.tool_urn} to Neo4j: {e}")
        raise

    # Mirror the predicate to Weaviate (iagent ADR-0009 Step F'.6). Done
    # *after* the Neo4j MERGE because Neo4j is the system of record; if
    # this Weaviate write fails, the function still returns success — verb
    # matching just degrades to Cypher exact-match until the next sync.
    sync_predicate_to_weaviate(
        rel_props=rel_props,
        description=props.get("_mesh_description", ""),
        tool_urn=config.tool_urn,
        context=context,
    )

    return {
        "status": "synced",
        "tool_urn": config.tool_urn,
        "verb_iri": verb_iri,
        "input_uri": input_uri,
        "output_uri": output_uri,
        "rel_type": record["rel_type"] if record else verb_local,
    }
