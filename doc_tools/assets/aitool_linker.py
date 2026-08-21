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


class MeshToolUnreachableError(RuntimeError):
    """DataHub could not be READ -- auth rejected, transport failed, or the API
    returned GraphQL errors.

    Distinct from "this URN is not a mesh tool registration", which is a
    legitimate skip. Conflating the two is what made this asset report SUCCESS
    while writing nothing: on 2026-08-21 the doc-tools pod held an invalid
    DATAHUB_TOKEN, every GMS call returned HTTP 401, `raise_for_status` raised,
    the blanket `except Exception` swallowed it, and the caller logged a
    reassuring "the next poll will retry" -- for a condition no poll can fix.

    A dead path that reports success is worse than a dead path, because the
    next operator falls back to it, watches it go green, and trusts a no-op.
    """


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
    # DataHub v1.6.0 renamed MLModel.mlModelProperties → MLModel.properties.
    # The old field name returns a ValidationError + data:null, which the
    # caller's `or {}` patterns above coerce into a "skipped" result — so the
    # symptom is "every sync fails silently / runs are red" rather than a
    # clean error. Aligns with the sensor's main search query in
    # components/aitool_sensor.py which already uses the new field name.
    query = """
    query getModelProperties($urn: String!) {
      mlModel(urn: $urn) {
        properties {
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
        body = resp.json() or {}
    except Exception as exc:
        # NOT a skip. The URN was never evaluated -- we could not read DataHub
        # at all -- so claiming "not a registration" would be a false negative
        # dressed as a routine skip.
        raise MeshToolUnreachableError(
            f"DataHub GMS unreadable while fetching {tool_urn}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    # DataHub returns HTTP 200 with `data: null` and an `errors` array
    # on schema mismatches or per-URN failures. dict.get("data", {})
    # cannot save us — its default fires only when the KEY is absent,
    # not when the value is explicitly null. Coerce with `or {}` and
    # surface the GraphQL errors so the next schema drift fails loud
    # instead of dropping into an AttributeError caught by Dagster's
    # broad except.
    if body.get("errors"):
        # Schema drift or a per-URN failure. Also NOT a skip: the question
        # "is this a mesh registration?" went unanswered, and a retry loop
        # that never surfaces the cause is how schema drift survives for
        # months. Fail loud; the message carries the GraphQL error.
        raise MeshToolUnreachableError(
            f"DataHub returned GraphQL errors for {tool_urn}: {body['errors']}"
        )
    model = (
        ((body.get("data") or {}).get("mlModel") or {}).get(
            "properties"
        )
    )
    if not model:
        return None

    cprops = model.get("customProperties") or []
    props = {
        p.get("key"): p.get("value")
        for p in cprops
        if isinstance(p, dict)
    }
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

    # Per iagent ADR-0008 follow-up: verb_anti_synonyms are NL phrases that
    # should REPEL the verb in Engine O's /search_predicates re-rank. The
    # Engine O side reads this Predicate property and applies a lexical
    # overlap penalty against the query. Critically: these must NOT be
    # included in `search_text` (the BM25-indexed blob) — that would
    # attract the wrong query, not repel it. We surface them as a separate
    # typed property on the Weaviate row.
    try:
        anti_synonyms: List[str] = json.loads(props.get("mesh_verb_anti_synonyms", "[]"))
    except json.JSONDecodeError:
        anti_synonyms = []

    # Per iagent ADR-0009: `domains` is a scope filter, not a routing key.
    # Engines self-declare the domains they serve at registration; Engine O
    # filters /find_tool matches against the caller's entitled_domains.
    # JSON-decoded back into a Neo4j list property.
    try:
        domains: List[str] = json.loads(props.get("mesh_domains", "[]"))
    except json.JSONDecodeError:
        domains = []

    # Per-provider fan-out budget declared by the engine at
    # registration. The router (Engine O) reads this and uses it
    # as the timeout for /resolve_instance calls — Engine D wants
    # 8s (DataHub GraphQL p95), Engine E wants 2s (sub-second
    # Cypher). When None, the router falls back to its global
    # floor; never set the floor below the slowest declared
    # provider. Without this property piped through, every
    # provider inherits the floor as its ceiling — exactly the
    # asymmetry that hid Engine D's 2s-strangle bug last night.
    try:
        timeout_s_raw = props.get("mesh_timeout_s")
        timeout_s = float(timeout_s_raw) if timeout_s_raw not in (None, "") else None
    except (TypeError, ValueError):
        timeout_s = None

    # ARCHITECTURAL NOTE — allowlist drift is its own bug class.
    # This function is an explicit allowlist of mesh_* properties
    # that get materialized onto the Neo4j relationship. When the
    # mesh-registrar gateway adds a new customProperty, it's
    # SILENTLY dropped here unless this dict gets an entry too.
    # mesh_provider + mesh_timeout_s were added together in the
    # Recipe v2 Gate-6 arc (2026-06-12) and the absence in the
    # allowlist nearly hid both. Future registration properties
    # need an entry here. A v0.2 cleanup should swap the allowlist
    # for a `mesh_*` prefix pass-through (whitelist by convention,
    # not enumeration) and kill this bug class entirely.
    return {
        # TWO SPECIES, ONE EDGE PROPERTY. An engine registration names its edge with
        # `mesh_verb_iri`; a presentation names it with `mesh_predicate_iri` (always
        # mesh:rendersAs, per ADR-0017). Both are "the IRI of this edge", so both land in
        # `iri`. This was a HARD KeyError for presentations -- found 2026-08-21 by the
        # break-on-purpose test, not in production, which is the point of writing it.
        "iri": props.get("mesh_verb_iri") or props.get("mesh_predicate_iri", ""),
        "synonyms": synonyms,
        "anti_synonyms": anti_synonyms,
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
        # Recipe v2 / Gate-6 additions — router uses these.
        "provider": props.get("mesh_provider", ""),
        "timeout_s": timeout_s,
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
    """Idempotent create + return handle to the Predicate collection.

    Also runs forward-compatible schema evolution: when this code adds a
    new property, the property is added to existing collections via
    config.add_property rather than requiring a wipe + rebuild. New
    properties are nullable per Weaviate's contract, so existing objects
    coexist without backfill.
    """
    if not client.collections.exists(_PREDICATE_COLLECTION):
        log.info(f"Creating {_PREDICATE_COLLECTION} collection in Weaviate...")
        client.collections.create(
            name=_PREDICATE_COLLECTION,
            # IndexPropertyLength=true is REQUIRED by Engine O's domain-scope
            # filter. /classify_predicate ORs `domains contains_any(entitled)`
            # with a `domains length == 0` clause (to keep domain-agnostic
            # predicates in scope). Weaviate rejects the length clause unless
            # the property length is indexed, raising at query time:
            #   "Property length must be indexed to be filterable! add
            #    IndexPropertyLength: true to the invertedIndexConfig"
            # When it raises, the predicate hybrid search returns empty and
            # routing silently degrades to the generalist for every caller
            # that carries entitled domains. This mirrors the seed script's
            # config so the reproducible-ingest path matches the hand-seed
            # (see the seed's IndexPropertyLength fix; the durable owner of
            # the collection is this asset per ADR-0006).
            inverted_index_config=wvc.config.Configure.inverted_index(
                index_property_length=True,
            ),
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
                # Anti-synonyms — phrases that should REPEL this verb in
                # Engine O's /search_predicates re-rank. NOT included in
                # search_text (would attract the wrong query); read by
                # Engine O as a separate field for the lexical-overlap
                # penalty. Per iagent ADR-0008 follow-up.
                wvc.config.Property(
                    name="anti_synonyms",
                    data_type=wvc.config.DataType.TEXT_ARRAY,
                ),
                wvc.config.Property(name="description", data_type=wvc.config.DataType.TEXT),
                # Provenance
                wvc.config.Property(name="tool_urn", data_type=wvc.config.DataType.TEXT),
            ],
        )
    collection = client.collections.get(_PREDICATE_COLLECTION)
    # Forward-compat: add anti_synonyms to a pre-existing collection that
    # was created before this property landed. config.add_property is a
    # no-op if the property already exists.
    try:
        existing_names = {p.name for p in collection.config.get().properties}
        if "anti_synonyms" not in existing_names:
            log.info(
                f"Adding anti_synonyms property to existing {_PREDICATE_COLLECTION} collection..."
            )
            collection.config.add_property(
                wvc.config.Property(
                    name="anti_synonyms",
                    data_type=wvc.config.DataType.TEXT_ARRAY,
                )
            )
    except Exception as exc:  # noqa: BLE001
        # Schema-evolution failure is non-fatal: Engine O's reader treats
        # missing anti_synonyms as an empty list (penalty = 0), so routing
        # degrades cleanly to the no-anti-synonym behavior.
        log.warning(
            f"Could not ensure anti_synonyms property on {_PREDICATE_COLLECTION}: {exc}. "
            "Engine O's penalty pass will no-op until the next successful schema reconcile."
        )
    return collection


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
    anti_synonyms = list(rel_props.get("anti_synonyms") or [])
    domains = list(rel_props.get("domains") or [])

    search_text = _build_predicate_search_text(
        verb_iri=verb_iri,
        verb_local=verb_local,
        synonyms=synonyms,
        description=description or "",
    )
    # Anti-synonyms intentionally NOT folded into search_text: BM25 over
    # them would ATTRACT the wrong query (the verb that should repel
    # "what tables do you have" would instead match those tokens and
    # score high). Engine O reads anti_synonyms separately and applies a
    # lexical-overlap penalty after Weaviate returns candidates.

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
            "anti_synonyms": anti_synonyms,
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
        # Reaching here now means exactly ONE thing: DataHub was read
        # successfully and this URN is not a mesh tool registration. Anything
        # that prevented us from READING raises above rather than landing here,
        # so this message can no longer describe a broken path as a stale one.
        context.log.warning(
            f"Skipping {config.tool_urn}: DataHub was reachable and this URN is "
            f"not a mesh tool registration (mesh_is_registration != 'true')."
        )
        return {"status": "skipped", "tool_urn": config.tool_urn}

    # ── TWO SPECIES SHARE THIS TABLE (2026-08-21) ─────────────────────────────────────
    # An ENGINE registration is verb-shaped: (input_uri) -[verb_iri]-> (output_uri).
    # A PRESENTATION registration is triple-shaped: (subject_uri) -[mesh:rendersAs]->
    # (object_uri). Both are edges between two OntologyClass nodes, so both materialize
    # through the same Cypher below -- only the property NAMES differ.
    #
    # Before this branch the field check demanded mesh_verb_iri / mesh_input_uri /
    # mesh_output_uri unconditionally, so EVERY presentation was rejected as "incomplete"
    # -- at ERROR level, telling the author to "re-register", A REMEDY THAT CANNOT WORK
    # because re-registering produces the same fields. The guard was correct for everything
    # it was built to carry; Presentation was never in its population.
    #
    # `mesh_tool_kind` was ALREADY on every row and already read into rel_props below. The
    # discriminator existed in the data and nothing branched on it -- declared but unwired.
    tool_kind = (props.get("mesh_tool_kind") or "").strip()
    is_presentation = tool_kind == "Presentation"

    if is_presentation:
        verb_iri = props.get("mesh_predicate_iri")
        input_uri = props.get("mesh_subject_uri")
        output_uri = props.get("mesh_object_uri")
        missing_desc = (
            f"predicate_iri={verb_iri!r}, subject_uri={input_uri!r}, "
            f"object_uri={output_uri!r}"
        )
    else:
        verb_iri = props.get("mesh_verb_iri")
        input_uri = props.get("mesh_input_uri")
        output_uri = props.get("mesh_output_uri")
        missing_desc = (
            f"verb_iri={verb_iri!r}, input_uri={input_uri!r}, output_uri={output_uri!r}"
        )

    if not (verb_iri and input_uri and output_uri):
        context.log.error(
            f"Mesh tool {config.tool_urn} (kind={tool_kind or 'AITool'}) is missing required "
            f"predicate fields ({missing_desc}). Refusing to materialize. "
            f"If the fields are present under DIFFERENT names, this linker does not yet know "
            f"that species -- re-registering will NOT help."
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

    # ADR-0019 Contract D — typed-range validation, no auto-MERGE.
    # The endpoint classes (input_uri/output_uri) MUST already exist as
    # :OntologyClass nodes from a canonical ontology load. The prior
    # MERGE form silently fabricated phantom :OntologyClass nodes when
    # the URI was misspelled or referred to a system-level concept that
    # had never been defined (the "Engine E registered mesh:GraphQuery
    # without anyone defining it" pattern). Those phantoms had no
    # subClassOf edges, no provenance, and they made the registered verb
    # silently unroutable AND polluted the noun graph.
    #
    # The MATCH below verifies pre-existence. If either endpoint class
    # isn't in the substrate, registration is rejected with a loud,
    # specific error naming the offending URI — same shape as the
    # incomplete-props rejection above. The fix path is either:
    #   - load the canonical ontology that defines the URI, then
    #     re-register the tool, OR
    #   - fix the tool's registration to point at a real existing class.
    # APOC ships with Neo4j's enterprise images and is in NEO4J_PLUGINS
    # for this cluster, so apoc.merge.relationship (which needs APOC
    # because Cypher cannot take a relationship type as a parameter)
    # remains the relationship-side primitive — only the *node*-side
    # MERGEs are now MATCHes.
    # apoc.merge.relationship's third argument is the MATCH KEY — if an
    # existing rel matches it, we update; otherwise we create. Identity
    # used to be just ``{iri: verb_iri}``, which meant N providers
    # registering the SAME predicate (e.g. Engine D and Engine E both
    # offering mesh:resolveInstance) collapsed into ONE edge with
    # last-write-wins semantics. Recipe v2 / Gate 6 needs each provider's
    # registration to live as its own edge so the discovery Cypher can
    # return multiple endpoint_urls — adding ``_tool_urn`` to the match
    # key makes the identity (verb_iri × tool_urn), one edge per
    # registration. Found 2026-06-12 when engine_e_resolve_instance
    # silently overwrote engine_d_resolve_instance's row.
    match_key = {"iri": verb_iri, "_tool_urn": rel_props.get("tool_urn", "")}
    cypher = """
    MATCH (s:OntologyClass {uri: $input_uri})
    MATCH (o:OntologyClass {uri: $output_uri})
    WITH s, o
    CALL apoc.merge.relationship(
        s,
        $verb_local,
        $match_key,
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
                match_key=match_key,
                props=rel_props,
            )
            record = result.single()
        if record is None:
            # Identify which endpoint class is missing so the operator's
            # remediation is one step, not a guess. Pure read; no writes.
            with driver.session() as session:
                missing = [
                    uri for uri in (input_uri, output_uri)
                    if not session.run(
                        "MATCH (c:OntologyClass {uri: $uri}) RETURN c LIMIT 1",
                        uri=uri,
                    ).single()
                ]
            context.log.error(
                "❌ Refusing to sync %s: registered range types not "
                "pre-existing in noun graph (ADR-0019 Contract D). "
                "Missing OntologyClass nodes: %s. Run the canonical "
                "ontology load (e.g. doc-tools' ingest_ontology_job) "
                "to define them, or fix the tool's registration to "
                "point at existing classes.",
                config.tool_urn, missing,
            )
            return {
                "status": "rejected",
                "tool_urn": config.tool_urn,
                "reason": "unresolved_range_types",
                "missing_uris": missing,
            }
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
