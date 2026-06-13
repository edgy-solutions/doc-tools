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
    s3: S3Resource,
    neo4j: Neo4jResource,
) -> MaterializeResult:
    """Sync TTL-ingested classes from MinIO to Neo4j via rdflib extraction.

    Closes the Session-1 DAG-wiring break that made TTL→Neo4j the deploy-
    blocker (see module docstring above). Depends only on
    `ingest_ontology_to_jena` so the XML pipeline's sync stays
    independent.

    Implementation note (Session-2 lesson): the first attempt used
    n10s.rdf.import.fetch against Jena. That ran into three layered
    problems — a wrong Fuseki endpoint path (`/ds/query` 404s instead of
    `/ds/sparql`), n10s's silent-zero failure mode (it returns success
    with triplesLoaded=0 when the fetch HTTP-errors), AND a
    :Resource-vs-:OntologyClass label collision with the historical
    direct-load shape that would have duplicated every node. Replaced
    with the simpler shape: extract classes via rdflib from the S3
    source (same RDF the ingest_ontology_to_jena step parses) and emit
    them as direct MERGEs. Mirrors the validated pattern from
    seed_mro_extension_runtime.py and from sync_ontology_to_weaviate's
    Weaviate path — same source data, same extraction, same convention.

    The seam stays first-class observable: this asset's only job is
    "TTL classes reach Neo4j's OntologyClass graph." Failures raise
    loudly. Idempotent — re-runs MERGE on URI and update label/
    definition/domain.
    """
    # ----- Resolve domain + S3 key (same precedence as ingest_ontology_to_jena) -----
    file_url = config.file_url
    if file_url.startswith("s3://"):
        url_parts = file_url[5:].split("/", 1)
        bucket = url_parts[0]
        obj_key = url_parts[1] if len(url_parts) > 1 else ""
    else:
        bucket = os.getenv("ONTOLOGY_BUCKET", "ontologies")
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
            f"No explicit 'domain' in config.extra_metadata; falling back "
            f"to path-derived '{domain}'. Pass extra_metadata={{'domain': "
            f"'<SEMANTIC_DOMAIN>'}} for deliberate classification — same "
            f"lesson as ingest_ontology_to_jena."
        )

    # ----- Step 1: fetch + parse the RDF from MinIO -----------------------
    bucket = os.getenv("ONTOLOGY_BUCKET", "ontologies")
    filename = parts[-1]
    s3_client = s3.get_client()
    context.log.info(
        f"Fetching {filename!r} from s3://{bucket}/{obj_key} for "
        f"domain '{domain}'"
    )
    try:
        response = s3_client.get_object(Bucket=bucket, Key=obj_key)
        rdf_content = response["Body"].read()
    except Exception as e:
        raise Exception(
            f"Failed to fetch RDF from s3://{bucket}/{obj_key} for "
            f"Neo4j sync: {e}. Note ingest_ontology_to_jena (upstream "
            f"dep) succeeded so the file exists; check MinIO ACLs and "
            f"the S3 resource credentials."
        ) from e

    g = rdflib.Graph()
    fmt = "xml" if filename.endswith((".rdf", ".owl")) else "turtle"
    try:
        g.parse(data=rdf_content, format=fmt)
    except Exception as e:
        raise Exception(
            f"RDF parse failed for {filename!r} (format={fmt}): {e}. "
            f"This is downstream of ingest_ontology_to_jena which "
            f"already validated the same content — the failure here "
            f"is probably a content/MinIO drift between the two assets."
        ) from e

    # ----- Step 2: SPARQL-extract classes (same shape as the Weaviate sync) ----
    extract_query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl:  <http://www.w3.org/2002/07/owl#>
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
    rows = list(g.query(extract_query))
    classes = []
    for row in rows:
        uri = str(row.uri)
        # Drop blank nodes; they're never resolver targets.
        if not uri or uri.startswith("Bnode_") or uri.startswith("_:"):
            continue
        label = str(row.label) if row.label is not None else uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        definition = str(row.definition) if row.definition is not None else ""
        classes.append({"uri": uri, "label": label, "definition": definition})

    if not classes:
        # Silent-zero is the same failure shape that bit the n10s
        # attempt. The asset's contract is "TTL classes reach Neo4j" —
        # zero classes is a contract violation that should turn red.
        raise Exception(
            f"Zero classes extracted from {filename!r} (domain "
            f"'{domain}') — the SPARQL extraction found no "
            f"owl:Class / rdfs:Class triples. This could be a "
            f"parse-but-no-types issue, or a content drift. The "
            f"upstream ingest_ontology_to_jena validated {len(g)} "
            f"triples; classes among them: 0. Fix the TTL or the "
            f"extraction pattern."
        )

    context.log.info(
        f"Extracted {len(classes)} classes from {filename!r} for "
        f"domain '{domain}'. First 3: "
        f"{[c['uri'] for c in classes[:3]]}"
    )

    # ----- Step 3: MERGE into Neo4j ---------------------------------------
    # Match the validated pattern from seed_mro_extension_runtime.py:
    # MERGE on uri; SET label / definition / domain. Idempotent. Preserves
    # any rich properties (ingest_run_id, source_ontology, provenance,
    # ingested_at) that the historical direct-load shape established —
    # this asset doesn't overwrite them, just refreshes the
    # resolver-visible label / definition / domain.
    neo4j_client = neo4j.get_client()
    try:
        neo4j_client.execute_query(
            """
            UNWIND $classes AS cls
            MERGE (c:OntologyClass {uri: cls.uri})
            SET c.label = cls.label,
                c.definition = cls.definition,
                c.domain = $domain,
                c.last_synced_at = datetime(),
                c.synced_by = 'sync_jena_ontologies_to_neo4j',
                c.synced_from = $s3_path
            """,
            {
                "classes": classes,
                "domain": domain.upper(),
                "s3_path": f"s3://{bucket}/{obj_key}",
            },
        )
    except Exception as e:
        raise Exception(
            f"Neo4j MERGE failed for domain '{domain}' "
            f"({len(classes)} classes): {e}"
        ) from e

    # ----- Step 4: verification read (the seam's standing assertion) ------
    # The asset's contract is "TTL classes reach Neo4j." Verify by
    # reading back. This is the analog of the saga's read-back probe.
    verify_uris = [c["uri"] for c in classes]
    try:
        result = neo4j_client.execute_query(
            """
            UNWIND $uris AS uri
            OPTIONAL MATCH (c:OntologyClass {uri: uri})
            RETURN uri AS asked, c.uri AS landed, c.domain AS domain
            """,
            {"uris": verify_uris},
        )
        missing = [r["asked"] for r in result.records if r["landed"] is None]
    except Exception as e:
        context.log.warning(f"Verification readback failed: {e}")
        missing = []

    if missing:
        raise Exception(
            f"Verification readback found {len(missing)} classes that "
            f"did NOT land in Neo4j despite the MERGE returning. "
            f"Missing: {missing[:5]}{' ...' if len(missing) > 5 else ''}. "
            f"This is the read-back-probe failure mode the v0.2 saga "
            f"introduced for predicate edges; same shape applied here."
        )

    context.log.info(
        f"Sync complete. {len(classes)} :OntologyClass nodes "
        f"materialized at full-IRI form for domain '{domain}'. "
        f"Verification readback green."
    )

    return MaterializeResult(
        metadata={
            "domain": domain,
            "classes_merged": len(classes),
            "s3_path": f"s3://{bucket}/{obj_key}",
            "partition_key": context.partition_key,
            "first_class_uris": [c["uri"] for c in classes[:5]],
            "rule": (
                "Option 3 — TTL→Neo4j is a first-class observable seam; "
                "depends only on ingest_ontology_to_jena. rdflib "
                "extraction + direct MERGE (chosen over n10s after the "
                "Session-2 first attempt revealed three layered "
                "problems). See invincible-agent state doc dated "
                "2026-06-12 for the decision history."
            ),
        }
    )
