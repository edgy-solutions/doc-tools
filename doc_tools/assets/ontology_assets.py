import os
import urllib.parse
import httpx
import rdflib
import weaviate.classes as wvc
from weaviate.util import generate_uuid5
from dagster import asset, AssetExecutionContext, MaterializeResult
from dagster_aws.s3 import S3Resource
from doc_tools.utils.dagster_resources import JenaResource, Neo4jResource
from dag_tools.components.s3_sensor.file_component import S3FileConfig
from doc_tools.partitions import ontology_partitions
from doc_tools.utils.weaviate_client import get_weaviate_client

def sync_ontology_to_weaviate(extracted_classes: list[dict], domain: str, context: AssetExecutionContext):
    """
    Takes parsed ontology classes (from rdflib/Jena) and dual-writes them to Weaviate.
    extracted_classes should be a list of dicts: {"uri": str, "label": str, "definition": str}
    """
    # 🔗 Use the Fleet-Standard Connection Strategy
    client = get_weaviate_client()
    
    try:
        # Ensure the collection exists
        if not client.collections.exists("OntologyClass"):
            context.log.info("Creating OntologyClass collection in Weaviate...")
            client.collections.create(
                name="OntologyClass",
                properties=[
                    wvc.config.Property(name="uri", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="label", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="definition", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="domain", data_type=wvc.config.DataType.TEXT),
                ],
            )
            
        collection = client.collections.get("OntologyClass")
        context.log.info(f"Syncing {len(extracted_classes)} classes to Weaviate for domain {domain}...")
        
        # Batch insert for high performance (Idempotent Upsert)
        with collection.batch.dynamic() as batch:
            for cls in extracted_classes:
                # Use the URI to generate a deterministic UUID
                deterministic_uuid = generate_uuid5(str(cls["uri"]))
                
                safe_label = str(cls["label"]) if cls.get("label") else str(cls["uri"]).split("#")[-1].split("/")[-1]
                safe_definition = str(cls["definition"]) if cls.get("definition") else "No definition provided."

                batch.add_object(
                    properties={
                        "uri": str(cls["uri"]),
                        "label": safe_label,
                        "definition": safe_definition,
                        "domain": domain.upper()
                    },
                    uuid=deterministic_uuid
                )
                
        context.log.info("Weaviate sync complete.")
        
    finally:
        # Crucial for Dagster: cleanly close the tunnel when the asset finishes
        client.close()

@asset(partitions_def=ontology_partitions)
def ingest_ontology_to_jena(context: AssetExecutionContext, config: S3FileConfig, s3: S3Resource, jena: JenaResource) -> MaterializeResult:
    """
    Detects RDF files in MinIO (via sensor partition) and pushes them to Jena Named Graphs.

    Domain resolution (in order of precedence):
      1. ``config.extra_metadata["domain"]`` — explicit override. Use this
         when the s3 path is the ontology's *source* and not its *semantic
         domain* — e.g. ``s3://ontologies/mro/mro_extension.ttl`` should
         classify under ``MAINTENANCE``, not ``MRO``. The path tells you
         where the file came from; the domain tells the resolver which
         classes to consider for which queries. Conflating the two breaks
         every case where one semantic domain has source TTLs under
         multiple s3 prefixes (the common case once multiple ontology
         stewards contribute).
      2. ``parts[0]`` (s3 path's first segment) — legacy default. Kept
         because existing sensor-fired ingestions rely on it, but should
         be considered deprecated for any new domain. Logs a warning so
         it's visible when the implicit path is in use.

    Reference: tests/routing/STEP1_2_EXECUTION_REPORT.md deviation #1 —
    the canonical pipeline ran to RUN_SUCCESS but landed classes at a
    domain the resolver couldn't see, requiring a runtime workaround.
    Explicit config is the fix.
    """
    file_url = config.file_url
    if file_url.startswith("s3://"):
        url_parts = file_url[5:].split("/", 1)
        bucket = url_parts[0]
        obj_key = url_parts[1]
    else:
        # Get the exact S3 key from the run tags injected by the sensor
        obj_key = context.run.tags.get("s3_key")
        if not obj_key:
            # Fallback to partition key replacing double underscores
            partition_key = context.partition_key
            obj_key = partition_key.replace("__", "/")

    parts = obj_key.split('/')

    if len(parts) < 2:
        raise Exception(f"Invalid ontology path: {obj_key}. Expected '{{path}}/{{filename}}'")

    filename = parts[-1]

    # Domain: explicit override > path-derived default.
    explicit_domain = (config.extra_metadata or {}).get("domain")
    if explicit_domain:
        domain = str(explicit_domain)
        context.log.info(
            f"Using explicit domain '{domain}' from config.extra_metadata "
            f"(path-derived would have been '{parts[0]}')"
        )
    else:
        domain = parts[0]
        context.log.warning(
            f"No explicit 'domain' in config.extra_metadata; falling back to "
            f"path-derived '{domain}'. Pass extra_metadata={{'domain': '<SEMANTIC_DOMAIN>'}} "
            f"to make the classification deliberate."
        )
    
    # Derive Named Graph URI
    graph_uri = f"http://internal/{domain}"
    
    s3_client = s3.get_client()
    context.log.info(f"Ingesting ontology '{filename}' for domain '{domain}' into graph <{graph_uri}>")
    
    # 1. Download from MinIO
    # We'll assume the 'ontologies' bucket as per instructions
    bucket = os.getenv("ONTOLOGY_BUCKET", "ontologies")
    try:
        response = s3_client.get_object(Bucket=bucket, Key=obj_key)
        rdf_content = response['Body'].read()
    except Exception as e:
        context.log.error(f"Failed to fetch ontology from MinIO: {e}")
        raise e

    # 2. Validate with rdflib
    g = rdflib.Graph()
    content_type = "text/turtle"
    if filename.endswith((".rdf", ".owl")):
        content_type = "application/rdf+xml"
        fmt = "xml"
    else:
        fmt = "turtle"
        
    try:
        g.parse(data=rdf_content, format=fmt)
        context.log.info(f"Successfully validated RDF content ({len(g)} triples).")
    except Exception as e:
        context.log.error(f"Syntax validation failed for {obj_key}: {e}")
        raise e

    # 3. Push to Jena using Graph Store Protocol (PUT)
    # Using PUT ensures we overwrite the previous revision of this domain's ontology
    jena_base = jena.url.rstrip('/')
    jena_ds = jena.dataset
    user = jena.username
    pw = jena.password
    
    # GSP endpoint: {host}/{dataset}/data
    target_url = f"{jena_base}/{jena_ds}/data?graph={graph_uri}"
    
    try:
        with httpx.Client(auth=(user, pw), verify=False) as client:
            resp = client.put(
                target_url,
                content=rdf_content,
                headers={"Content-Type": content_type}
            )
            resp.raise_for_status()
            context.log.info(f"Successfully pushed to Jena Named Graph: {graph_uri}")
    except Exception as e:
        context.log.error(f"Failed to push to Fuseki: {e}")
        raise e

    # 4. DUAL-WRITE: Sync to Weaviate for fast semantic search
    context.log.info("Extracting classes for Weaviate sync...")
    query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
    
    SELECT ?uri ?label ?definition
    WHERE {
        ?uri a ?type .
        FILTER(?type IN (owl:Class, rdfs:Class))
        OPTIONAL { ?uri rdfs:label ?label }
        OPTIONAL { 
            { ?uri skos:definition ?definition }
            UNION
            { ?uri rdfs:comment ?definition }
        }
    }
    """
    try:
        qres = g.query(query)
        extracted_classes = []
        for row in qres:
            extracted_classes.append({
                "uri": row.uri,
                "label": row.label,
                "definition": row.definition
            })
        
        if extracted_classes:
            sync_ontology_to_weaviate(extracted_classes, domain, context)
        else:
            context.log.warning("No classes found in ontology to sync to Weaviate.")
            
    except Exception as e:
        context.log.error(f"Weaviate Dual-Write failed: {e}")

    return MaterializeResult(
        metadata={
            "domain": domain,
            "graph_uri": graph_uri,
            "triples": len(g),
            "s3_path": f"s3://{bucket}/{obj_key}"
        }
    )


# ===========================================================================
# Option 3 fix — sync_jena_ontologies_to_neo4j
#
# Per the Session-1/Session-2 close (2026-06-12): the TTL→Neo4j leg of the
# canonical pipeline was unwired — `sync_jena_to_neo4j` depends on the XML
# extraction path (`upload_to_jena`), so TTL ingests reached Jena+Weaviate
# but never propagated to Neo4j's OntologyClass graph. On a fresh cluster
# every engine declaration referencing a canonical mesh:* / mil:* / idp:* /
# mro: class would Contract-D-reject (no OntologyClass node exists for the
# declared input_uri/output_uri).
#
# Option 3 (chosen over options 1 and 2 because it keeps TTL→Neo4j as a
# first-class observable seam — see invincible-agent state doc dated
# 2026-06-12): a NEW asset depending only on `ingest_ontology_to_jena`,
# partitioned identically, whose only job is "TTL classes reach the
# runtime graph." The XML pipeline keeps its own sync; this asset owns
# the canonical-ontology lane.
#
# Mechanics:
#   1. Derive the domain (same logic as ingest_ontology_to_jena — explicit
#      override > path-derived default).
#   2. Build the Jena Named Graph URI: `http://internal/{domain}`.
#   3. SPARQL CONSTRUCT against that graph to get the full RDF subset.
#   4. n10s.rdf.import.fetch via that CONSTRUCT URL — creates :Resource
#      nodes with the URIs preserved.
#   5. Relabel: nodes that have an rdf:type → owl:Class triple become
#      `:OntologyClass` with `domain` set; their rdfs:label becomes the
#      `label` property. This mirrors the historical shape the Phase-5
#      scripts and the mystery notebook established.
#
# Idempotency: re-running this asset on the same partition is safe — n10s
# MERGEs by URI, and the relabeling is set-not-create. Re-ingest of a TTL
# that drops a class will leave the OntologyClass node behind (orphan),
# which is the same drift signature the routing layer has standing guards
# for (`test_no_phantom_input_classes` flags any verb that points at one).
#
# Acceptance test (architect's sharp form): ingest a TTL with a class that
# has NO historical N10S artifact and NO Phase 5 Cypher provenance — a
# class that has only ever existed in a TTL — and assert it materializes
# in Neo4j at full-IRI form where the resolver looks. mil_extension.ttl
# is the natural carrier; its first ingest doubles as this asset's
# acceptance test (B1 of the docs phase).
# ===========================================================================

@asset(partitions_def=ontology_partitions, deps=[ingest_ontology_to_jena])
def sync_jena_ontologies_to_neo4j(
    context: AssetExecutionContext,
    config: S3FileConfig,
    jena: JenaResource,
    neo4j: Neo4jResource,
) -> MaterializeResult:
    """Sync TTL-ingested classes from Jena to Neo4j via n10s.

    Closes the Session-1 DAG-wiring break that made TTL→Neo4j the deploy-
    blocker (see module docstring above). Depends only on
    `ingest_ontology_to_jena` so the XML pipeline's sync stays
    independent.

    Per-partition: each TTL file gets its own materialization, scoped to
    its own Jena Named Graph and domain. Failures in one partition don't
    cascade to others.
    """
    # ----- Resolve domain (same precedence as ingest_ontology_to_jena) -----
    file_url = config.file_url
    if file_url.startswith("s3://"):
        url_parts = file_url[5:].split("/", 1)
        obj_key = url_parts[1] if len(url_parts) > 1 else ""
    else:
        obj_key = context.run.tags.get("s3_key") or ""
        if not obj_key:
            obj_key = context.partition_key.replace("__", "/")

    parts = obj_key.split("/")
    if len(parts) < 2:
        raise Exception(
            f"Invalid ontology path: {obj_key!r}. Expected '{{path}}/{{filename}}'"
        )

    explicit_domain = (config.extra_metadata or {}).get("domain")
    if explicit_domain:
        domain = str(explicit_domain)
        context.log.info(
            f"Using explicit domain '{domain}' from config.extra_metadata"
        )
    else:
        domain = parts[0]
        context.log.warning(
            f"No explicit 'domain' in config.extra_metadata; falling back to "
            f"path-derived '{domain}'. Pass extra_metadata={{'domain': "
            f"'<SEMANTIC_DOMAIN>'}} for deliberate classification — the "
            f"same lesson as ingest_ontology_to_jena."
        )

    graph_uri = f"http://internal/{domain}"
    neo4j_client = neo4j.get_client()

    # ----- Step 1: build the SPARQL CONSTRUCT fetch URL --------------------
    sparql_construct = (
        f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ "
        f"GRAPH <{graph_uri}> {{ ?s ?p ?o }} }}"
    )
    jena_base = jena.url.rstrip("/")
    jena_ds = jena.dataset
    encoded_query = urllib.parse.quote(sparql_construct)
    fetch_url = f"{jena_base}/{jena_ds}/query?query={encoded_query}"

    context.log.info(
        f"Triggering n10s fetch from Jena graph <{graph_uri}> "
        f"(domain={domain}) for partition {context.partition_key}"
    )

    # ----- Step 2: n10s import. Raises on failure (no swallow). -----------
    try:
        neo4j_client.execute_query(
            "CALL n10s.rdf.import.fetch($url, 'Turtle', "
            "{ headerParams: { Accept: 'application/x-turtle' } })",
            {"url": fetch_url},
        )
    except Exception as e:
        raise Exception(
            f"n10s.rdf.import.fetch failed for domain '{domain}' "
            f"(graph={graph_uri}): {e}. Check that "
            f"init_neo4j_n10s has been materialized (n10s config + "
            f"unique-URI constraint) and that the Jena named graph has "
            f"triples (CONSTRUCT against an empty graph imports zero "
            f"triples silently, but the call should still succeed)."
        ) from e

    # ----- Step 3: relabel owl:Class nodes as :OntologyClass --------------
    # n10s preserves rdf:type as a typed edge. We identify nodes that are
    # owl:Class instances and apply the conventional :OntologyClass label
    # plus the `domain` property the resolver filters on. Mirrors the
    # historical shape of the existing mesh#AgentTask node (verified via
    # `MATCH (c:OntologyClass {uri: '...AgentTask'}) RETURN labels(c)`).
    #
    # `handleVocabUris: 'IGNORE'` (the n10s_init config) means owl:Class
    # is imported as a :Resource node with `uri = 'http://www.w3.org/...'`,
    # and the rdf:type relationship lands as a typed relationship whose
    # type is the raw IRI string. We query for it explicitly.
    OWL_CLASS_URI = "http://www.w3.org/2002/07/owl#Class"
    RDF_TYPE_URI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

    context.log.info(
        f"Post-sync relabeling: identifying owl:Class nodes in domain "
        f"'{domain}' and tagging them as :OntologyClass"
    )

    relabel_summary = neo4j_client.execute_query(
        """
        MATCH (cls:Resource {uri: $owl_class_uri})
        MATCH (n:Resource)-[r]->(cls)
        WHERE type(r) = $rdf_type_uri OR type(r) ENDS WITH '#type'
        WITH DISTINCT n
        SET n:OntologyClass, n.domain = $domain
        WITH n
        OPTIONAL MATCH (n)-[lbl]->(lblObj)
        WHERE type(lbl) ENDS WITH '#label'
        SET n.label = coalesce(lblObj.uri, lblObj.value, n.label)
        RETURN count(DISTINCT n) AS relabeled
        """,
        {
            "owl_class_uri": OWL_CLASS_URI,
            "rdf_type_uri": RDF_TYPE_URI,
            "domain": domain.upper(),
        },
    )

    # ----- Step 4: best-effort label extraction from rdfs:label literals --
    # n10s also stores literal-valued properties on the Resource node when
    # configured. If the label property landed as `rdfs__label` or similar
    # n10s-shortened key, grab it.
    try:
        neo4j_client.execute_query(
            """
            MATCH (n:OntologyClass)
            WHERE n.domain = $domain AND n.label IS NULL
            SET n.label = coalesce(
                n.`http://www.w3.org/2000/01/rdf-schema#label`,
                n.rdfs__label,
                n.label
            )
            """,
            {"domain": domain.upper()},
        )
    except Exception as e:
        context.log.warning(
            f"Label fallback assignment failed (non-fatal): {e}"
        )

    return MaterializeResult(
        metadata={
            "domain": domain,
            "graph_uri": graph_uri,
            "fetch_url": fetch_url,
            "partition_key": context.partition_key,
            "rule": (
                "Option 3 — TTL→Neo4j is a first-class observable seam; "
                "depends only on ingest_ontology_to_jena. See "
                "invincible-agent state doc dated 2026-06-12 for the "
                "decision history."
            ),
        }
    )
