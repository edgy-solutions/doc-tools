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


# Meta-ontology IRI prefixes — vocabularies that describe ONTOLOGIES,
# not DOMAIN CONCEPTS. Their terms should never appear in the
# OntologyClass corpus (Engine O's /resolve candidate pool). They got
# in because the SPARQL extract patterns match `owl:Class` and
# `rdfs:Class` and meta-ontologies declare their own meta-concepts as
# `owl:Class` (e.g. prov:Bundle, prov:Usage).
#
# The 2026-06-27 PROV-contamination finding banked at
# [[ontology-class-pool-prov-contamination]] documented the
# consequence: 31 PROV-O classes sat in the Weaviate OntologyClass
# collection tagged domain=DATA_ENGINEERING with rich definitions,
# competing with weakly-defined domain classes. Every routed-path
# query in the 2026-06-27 session reproducibly returned prov#*
# (Bundle, Usage, PrimarySource) and fell back to Engine A. The
# specialist routing path was effectively never exercised.
#
# Path A fix per [[failure-mode-pluralism-in-fixes]]: filter at
# ingest time so meta-ontology terms never enter the corpus. Same
# shape as [[mesh-thing-retired]]. Paired cleanup deletes the
# existing 31 polluted entries (separate operation; this filter
# prevents the next ingest from re-polluting).
_META_ONTOLOGY_IRI_PREFIXES: tuple[str, ...] = (
    "http://www.w3.org/ns/prov#",          # PROV-O
    "http://www.w3.org/2000/01/rdf-schema#",  # RDFS
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",  # RDF
    "http://www.w3.org/2002/07/owl#",      # OWL
    "http://www.w3.org/2004/02/skos/core#",  # SKOS
    "http://purl.org/dc/terms/",           # Dublin Core terms
    "http://purl.org/dc/elements/1.1/",    # Dublin Core elements
    "http://xmlns.com/foaf/0.1/",          # FOAF
    "http://www.w3.org/ns/dcat#",          # DCAT (data catalog vocabulary)
    "http://www.w3.org/2006/vcard/ns#",    # vCard
)


def _is_meta_ontology_iri(uri: str) -> bool:
    """Return True iff `uri` belongs to a meta-ontology that should
    NOT enter the OntologyClass corpus. Used by both the Weaviate
    and Neo4j sync paths to filter the SPARQL extraction's output
    before write.

    Defensive at the read-side too (Engine O could add a parallel
    filter), but the WRITE-side is where the fix belongs per
    [[writer-canonical-form-class]]: don't put pollution into the
    store you'd otherwise have to filter at every reader.
    """
    return any(uri.startswith(p) for p in _META_ONTOLOGY_IRI_PREFIXES)


def sync_ontology_to_weaviate(extracted_classes: list[dict], domain: str, context: AssetExecutionContext):
    """
    Takes parsed ontology classes (from rdflib/Jena) and dual-writes them to Weaviate.
    extracted_classes should be a list of dicts: {"uri": str, "label": str, "definition": str}
    """
    # 🔗 Use the Fleet-Standard Connection Strategy
    client = get_weaviate_client()

    # Meta-ontology filter — see _META_ONTOLOGY_IRI_PREFIXES docstring.
    # Filter BEFORE batch open so we don't pay batch-init cost for
    # entries we'd skip anyway, and so the log line below is honest
    # about how many classes are actually written.
    filtered_meta: list[dict] = []
    domain_classes: list[dict] = []
    for cls in extracted_classes:
        uri = str(cls.get("uri", ""))
        if _is_meta_ontology_iri(uri):
            filtered_meta.append(cls)
        else:
            domain_classes.append(cls)
    if filtered_meta:
        context.log.info(
            f"Filtered {len(filtered_meta)} meta-ontology classes from "
            f"Weaviate sync (e.g. {filtered_meta[0].get('uri','<?>')}). "
            f"See [[ontology-class-pool-prov-contamination]] for the "
            f"2026-06-27 finding this filter closes."
        )

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
        context.log.info(
            f"Syncing {len(domain_classes)} domain classes to Weaviate "
            f"for domain {domain} ({len(filtered_meta)} meta-ontology "
            f"classes filtered)..."
        )

        # Batch insert for high performance (Idempotent Upsert).
        # Computes the vector via doc_tools.utils.embed.embed_document()
        # (LiteLLM /embeddings, default nomic-embed-text, search_document:
        # prefix) and passes it to batch.add_object(vector=...) so Engine O's
        # hybrid search (which calls embed_query for the search_query:-prefixed
        # query vector) can score document/query similarity correctly. The
        # embedded text is "<label> — <definition>" — labels alone are
        # often too short to embed informatively. See doc_tools/utils/embed.py
        # for the rationale: code owns the embedding-model contract AND the
        # task-prefix discipline.
        from doc_tools.utils.embed import embed_document

        def _humanize_label(label: str) -> str:
            """Split underscore/camelCase compounds into words — for the
            EMBEDDING text only (the stored label is unchanged). A
            definition-less class's name is its ENTIRE semantic signal,
            and 'SomeCompoundClassName_specifiedProperty' embeds poorly
            against the natural-language queries Engine O's hybrid
            search receives."""
            import re
            words = re.sub(r"[_\-]+", " ", label)
            words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", words)
            words = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", words)
            return re.sub(r"\s+", " ", words).strip()

        with collection.batch.dynamic() as batch:
            for cls in domain_classes:
                # Use the URI to generate a deterministic UUID
                deterministic_uuid = generate_uuid5(str(cls["uri"]))

                safe_label = str(cls["label"]) if cls.get("label") else str(cls["uri"]).split("#")[-1].split("/")[-1]
                # NO FILLER, deliberately. The old default ('No definition
                # provided.') was both EMBEDDED and STORED: hundreds of
                # definition-less classes shared the same suffix, so their
                # vectors clustered on the filler instead of their names,
                # and the stored filler leaked verbatim into Engine O's
                # candidate prompts (token noise on every /resolve).
                # Absent stays absent: empty string in the row, label-only
                # in the vector.
                safe_definition = str(cls["definition"]) if cls.get("definition") else ""

                # Embed "<humanized label> — <definition>" for richer
                # signal than label alone; definition-less classes embed
                # the humanized label by itself. Best-effort: on gateway
                # failure, write without a vector so ingestion still
                # completes (BM25 still works; backfill can populate
                # later).
                embed_input = (
                    f"{_humanize_label(safe_label)} — {safe_definition}"
                    if safe_definition
                    else _humanize_label(safe_label)
                )
                try:
                    cls_vector = embed_document(embed_input)
                except Exception as e:
                    context.log.warning(
                        f"embed_document failed for {cls.get('uri','<?>')}; "
                        f"writing without vector (BM25-only until backfill): {e}"
                    )
                    cls_vector = None

                add_kwargs: dict = {
                    "properties": {
                        "uri": str(cls["uri"]),
                        "label": safe_label,
                        "definition": safe_definition,
                        "domain": domain.upper()
                    },
                    "uuid": deterministic_uuid,
                }
                if cls_vector is not None:
                    add_kwargs["vector"] = cls_vector

                batch.add_object(**add_kwargs)
                
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

    # Domain resolution (2026-06-16: explicit-per-file mechanism — see
    # standing memory feedback_path_vs_semantic_domain + STATE_GATEWAY_V02.md
    # "explicit-per-file domain fix"). The resolver queries with SEMANTIC
    # domain names (MAINTENANCE / SUSTAINMENT / DATA_ENGINEERING / MESH /
    # MANUFACTURING) and the s3 PATH is the source axis, not the semantic
    # axis. Path-derivation works correct-by-accident when the path's
    # first segment happens to match the semantic domain (mro/, idp/,
    # sustainment/, mesh/) and silently produces wrong-domain entries
    # when it doesn't (mil/, future Munitions). Removing the silent
    # fallback is the durability fix.
    #
    # Priority order:
    #   1. config.extra_metadata['domain'] — explicit dagster config
    #      (used by prime_databases.py's trigger_ingest_jobs)
    #   2. S3 object metadata 'x-amz-meta-domain' — set by
    #      prime_databases.py's upload_canonical_ttls; auto-fixes
    #      the sensor-fired path that doesn't pass dagster config
    #   3. ERROR — path-derivation as a SILENT fallback is removed;
    #      a future ingestion path that doesn't declare a domain
    #      should fail loud, not silently land at a path-derived
    #      value that will produce confidently-wrong routing.
    #
    # The error path's message names the fix path explicitly so the
    # remediation is obvious from the log.
    s3_client = s3.get_client()
    bucket = os.getenv("ONTOLOGY_BUCKET", "ontologies")

    explicit_domain = (config.extra_metadata or {}).get("domain")
    s3_metadata_domain = None
    domain_source = None

    if explicit_domain:
        domain = str(explicit_domain)
        domain_source = "config.extra_metadata"
    else:
        # Probe S3 object metadata for x-amz-meta-domain (priority 2).
        try:
            head = s3_client.head_object(Bucket=bucket, Key=obj_key)
            s3_metadata_domain = (head.get("Metadata") or {}).get("domain")
        except Exception as e:
            context.log.warning(f"head_object failed (continuing): {e}")
            s3_metadata_domain = None

        if s3_metadata_domain:
            domain = str(s3_metadata_domain)
            domain_source = "s3_object_metadata.x-amz-meta-domain"
        else:
            raise Exception(
                f"Domain not declared for ontology {obj_key!r}. "
                f"Path-derivation as a silent fallback was removed 2026-06-16 "
                f"after producing confidently-wrong routing for the mil/ path "
                f"(mil:* classes are SEMANTIC maintenance, but path-derived "
                f"'MIL' was invisible to MAINTENANCE-domain resolver queries). "
                f"Declare domain via ONE OF: "
                f"(1) config.extra_metadata={{'domain': '<SEMANTIC_DOMAIN>'}} "
                f"in dagster runConfigData (the prime_databases.py path), OR "
                f"(2) S3 object metadata 'x-amz-meta-domain' on the object "
                f"(the sensor-fired path; prime_databases.py:339-343 sets "
                f"this automatically on every upload). The path's first "
                f"segment is {parts[0]!r}, which the legacy fallback would "
                f"have used — confirm that's the intended SEMANTIC domain "
                f"before declaring it."
            )

    context.log.info(
        f"Using domain {domain!r} from {domain_source} for ontology {filename!r}"
    )

    # Derive Named Graph URI
    graph_uri = f"http://internal/{domain}"

    context.log.info(f"Ingesting ontology '{filename}' for domain '{domain}' into graph <{graph_uri}>")

    # 1. Download from MinIO
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

    # 3. Push to Jena using Graph Store Protocol (POST = MERGE/append, NOT PUT).
    # This asset is partitioned PER FILE, and MANY files map to ONE semantic domain
    # (e.g. MAINTENANCE = IOF_Core + IOF_MRO + DINEN62264 + mro/maintenance/mil
    # extensions). PUT REPLACES the whole named graph, so N files PUT to
    # http://internal/{domain} collapsed to whichever file landed LAST — silently
    # (found 2026-07-22: MAINTENANCE held only mil_extension's 10 classes, IOF core
    # destroyed). POST merges each file's triples into the domain graph so they
    # accumulate. Idempotency across re-runs is guaranteed by the reproducible
    # orchestrator clearing each domain graph ONCE before the per-file ingests
    # (invincible-agent setup/prime_databases.py `clear_ontology_graphs`), so
    # append-only never doubles blank-node structures on a re-prime.
    jena_base = jena.url.rstrip('/')
    jena_ds = jena.dataset
    user = jena.username
    pw = jena.password

    # GSP endpoint: {host}/{dataset}/data
    target_url = f"{jena_base}/{jena_ds}/data?graph={graph_uri}"

    try:
        with httpx.Client(auth=(user, pw), verify=False) as client:
            resp = client.post(
                target_url,
                content=rdf_content,
                headers={"Content-Type": content_type}
            )
            resp.raise_for_status()
            context.log.info(f"Successfully MERGED into Jena Named Graph: {graph_uri} (POST/append)")
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
#   6. subClassOf edges: MERGE (child)-[:subClassOf]->(parent) for every
#      named->named rdfs:subClassOf whose parent is a synced (non-meta)
#      class. THIS is what makes phase5_catalog_verb_migration.py's
#      docstring claim ("subClassOf edges land at TTL ingest via the
#      Jena→Neo4j step") TRUE — before, only NODES were synced and the
#      edges were hand-MERGEd by that one-off, so a fresh cluster's class
#      set was flat and find_compatible_verbs' subClassOf* walk never
#      formed. Source-authority per ADR-0006: the ingest owns node AND
#      hierarchy, so no hand-run is needed and none can silently revert.
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
    """Sync TTL-ingested classes AND their subClassOf hierarchy from MinIO
    to Neo4j via rdflib extraction.

    Closes the Session-1 DAG-wiring break that made TTL→Neo4j the deploy-
    blocker (see module docstring above). Depends only on
    `ingest_ontology_to_jena` so the XML pipeline's sync stays
    independent.

    Materializes BOTH the OntologyClass nodes AND their named-to-named
    `subClassOf` edges (Step 2.5 / Step 3.5). The edges were previously
    orphaned to the one-off `scripts/phase5_catalog_verb_migration.py`,
    whose docstring claimed they land here — a claim this asset now makes
    true. Without them a fresh cluster's classes are a flat set and the
    routing compat-walk (`find_compatible_verbs`, subClassOf*) never forms.

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

    # ----- Domain resolution (2026-06-16: explicit-per-file, no silent fallback).
    # Same precedence as ingest_ontology_to_jena:
    #   1. config.extra_metadata['domain']
    #   2. S3 object metadata 'x-amz-meta-domain'
    #   3. ERROR (path-derivation as silent fallback removed)
    # See ingest_ontology_to_jena's identical block for the trace.
    s3_client = s3.get_client()
    bucket_default = os.getenv("ONTOLOGY_BUCKET", "ontologies")

    explicit_domain = (config.extra_metadata or {}).get("domain")
    domain_source = None
    if explicit_domain:
        domain = str(explicit_domain)
        domain_source = "config.extra_metadata"
    else:
        try:
            head = s3_client.head_object(Bucket=bucket_default, Key=obj_key)
            s3_metadata_domain = (head.get("Metadata") or {}).get("domain")
        except Exception as e:
            context.log.warning(f"head_object failed (continuing): {e}")
            s3_metadata_domain = None

        if s3_metadata_domain:
            domain = str(s3_metadata_domain)
            domain_source = "s3_object_metadata.x-amz-meta-domain"
        else:
            raise Exception(
                f"Domain not declared for ontology {obj_key!r}. "
                f"Path-derivation as a silent fallback was removed 2026-06-16. "
                f"Declare domain via config.extra_metadata={{'domain':'<SEMANTIC>'}} "
                f"or via S3 object metadata x-amz-meta-domain. Path's first "
                f"segment {parts[0]!r} — confirm it's the intended SEMANTIC "
                f"domain before declaring it."
            )

    context.log.info(
        f"Using domain {domain!r} from {domain_source}"
    )

    # ----- Step 1: fetch + parse the RDF from MinIO -----------------------
    bucket = bucket_default
    filename = parts[-1]
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
    #
    # Blank-node owl:Class entries are EXCLUDED at the SPARQL layer via
    # !isBlank(?uri). Imported ontologies (PROV-O, IOF_Core, S3000L,
    # DINEN62264, etc.) declare many anonymous owl:Class restrictions
    # (rdfs:subClassOf of a unionOf / intersectionOf / Restriction expression,
    # which rdflib materializes as a fresh blank node with type owl:Class).
    # These have no human label, no semantic content, and no role as resolver
    # targets — they're RDF authoring artifacts, not concepts.
    #
    # PRE-FIX bug history (2026-06-15): this filter was Python-side and
    # checked `uri.startswith("Bnode_")` / `"_:"` which **never match**
    # rdflib's `BNode.__str__` output (`N[a-f0-9]{32}`). The filter has been
    # a no-op since Session 2's keystone — every ontology re-ingest leaked
    # ~441 blank-node :OntologyClass nodes (substrate count grew 1,191
    # blank-node phantoms across two writers, this pipeline contributing
    # 441). Surfaced by the mesh:Thing investigation's pre-flight provenance
    # grouping. Inert in routing (no verbs route through them, no LLM picks
    # them — labels are the hex IDs themselves) but cosmetic debt that ships
    # to every fresh bootstrap.
    #
    # Defense-in-depth: SPARQL filter is primary; Python isinstance check is
    # secondary belt-and-braces in case a future rdflib version changes
    # SPARQL evaluation. Either alone would close the leak; both together
    # surface the regression at two layers.
    extract_query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl:  <http://www.w3.org/2002/07/owl#>
    PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

    SELECT ?uri ?label ?definition
    WHERE {
        ?uri a ?type .
        FILTER(?type IN (owl:Class, rdfs:Class))
        FILTER(!isBlank(?uri))
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
    # Diagnostics to distinguish "extraction found nothing" from
    # "extraction found N but every one was filtered out" — the two
    # produce identical empty `classes` lists but have very different
    # meanings. Without this split, a legitimately-filtered
    # meta-ontology TTL (PROV-O, RDFS, OWL, SKOS...) raises the same
    # exception as a broken extraction pattern. 2026-07-01 fix.
    seen_non_blank_uris = 0
    filtered_meta = 0
    for row in rows:
        # Defense-in-depth: rdflib's BNode subclasses URIRef; isinstance
        # check fires even if SPARQL didn't filter (e.g., future rdflib
        # behavior change). The string check is kept for legacy outputs.
        if isinstance(row.uri, rdflib.term.BNode):
            continue
        uri = str(row.uri)
        if not uri or uri.startswith("Bnode_") or uri.startswith("_:"):
            continue
        seen_non_blank_uris += 1
        # Meta-ontology filter — see _META_ONTOLOGY_IRI_PREFIXES /
        # _is_meta_ontology_iri at module top. Mirrors the Weaviate-side
        # filter in sync_ontology_to_weaviate so BOTH stores stay
        # canonical-clean of provenance/RDFS/OWL/SKOS/DC/etc. terms.
        # See [[ontology-class-pool-prov-contamination]].
        if _is_meta_ontology_iri(uri):
            filtered_meta += 1
            continue
        label = str(row.label) if row.label is not None else uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        definition = str(row.definition) if row.definition is not None else ""
        classes.append({"uri": uri, "label": label, "definition": definition})

    if not classes:
        # Distinguish "content drift / broken extraction" (real error)
        # from "correctly filtered meta-ontology TTL" (deliberate no-op).
        # The 2026-06 [[ontology-class-pool-prov-contamination]] fix
        # added the meta-ontology filter, but this zero-check treated
        # "all filtered" the same as "nothing found" — which broke
        # substrate init any time PROV-O.ttl (or any other meta-only
        # TTL) was in the seed set. Now:
        #   - filtered_meta > 0 AND seen_non_blank_uris == filtered_meta
        #     → the TTL is entirely meta-ontology content that the
        #       corpus discipline says should NOT be in Neo4j. Log
        #       loudly and return an empty class list so the caller
        #       can decide what to do (skip vs error). Neo4j write
        #       becomes a no-op.
        #   - otherwise → real content drift or extraction bug. Raise.
        if filtered_meta > 0 and seen_non_blank_uris == filtered_meta:
            context.log.warning(
                f"Ontology {filename!r} (domain '{domain}') contained "
                f"{filtered_meta} classes but ALL were filtered as "
                f"meta-ontology terms per _META_ONTOLOGY_IRI_PREFIXES. "
                f"Skipping Neo4j write — this TTL should not be in the "
                f"seed set (its terms are corpus-noise per "
                f"[[ontology-class-pool-prov-contamination]]). Consider "
                f"removing it from the ontology upload manifest."
            )
            return MaterializeResult(
                metadata={
                    "classes_written": 0,
                    "domain": domain,
                    "filename": filename,
                    "skipped_reason": "all_meta_ontology_filtered",
                    "filtered_meta_count": filtered_meta,
                }
            )
        # Real zero-extraction failure — TTL parsed but no
        # owl:Class/rdfs:Class triples were found at all.
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

    # ----- Step 2.5: extract subClassOf edges (the routing hierarchy) -----
    # WHY THIS IS HERE NOW. find_compatible_verbs walks
    # (subject)-[:subClassOf*]->(ancestor) in Neo4j to reach a verb typed
    # against an ANCESTOR class (e.g. idp:Dashboard -> idp:Dataset, where the
    # catalog verbs live). This asset previously MERGEd class NODES but NOT
    # these edges, so a fresh cluster had a FLAT class set: the compat-walk
    # never formed and catalog routing silently fell to the generalist. The
    # edges had to be hand-MERGEd by
    # scripts/phase5_catalog_verb_migration.py — whose docstring FALSELY
    # claimed they "land at TTL ingest via the Jena->Neo4j step." This step
    # makes that claim TRUE (source-authority, ADR-0006): the ingest that
    # owns the nodes now owns their hierarchy too, so no fresh cluster needs
    # a hand-run and none can silently revert on the next ingest.
    #
    # Named->named only — blank-node restriction/union superclasses are RDF
    # authoring artifacts, not routing ancestors (same !isBlank discipline
    # as the class extraction above).
    subclass_edges = [
        {"child": str(child), "parent": str(parent)}
        for child, _p, parent in g.triples((None, rdflib.RDFS.subClassOf, None))
        if not isinstance(child, rdflib.term.BNode)
        and not isinstance(parent, rdflib.term.BNode)
    ]
    context.log.info(
        f"Extracted {len(subclass_edges)} named subClassOf edge(s) "
        f"from {filename!r}"
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

    # ----- Step 3.5: MERGE subClassOf edges -------------------------------
    # MATCH both endpoints (NOT merge the parent). The parent must ALREADY
    # be a synced OntologyClass node — this is deliberate: it stops
    # meta-ontology parents that the class extraction filters OUT
    # (prov:Entity, iof:*) from being fabricated as bare nodes here, so the
    # idp:Dataset->prov:Entity root stays correctly ABSENT (the meta-filter
    # discipline holds on the edge side too). Intra-TTL edges (e.g.
    # idp:Dashboard->idp:Dataset, both synced this run) always form;
    # cross-TTL edges form on the run after the parent's partition has
    # synced. Idempotent MERGE — re-runs converge, never duplicate.
    edges_written = 0
    if subclass_edges:
        try:
            neo4j_client.execute_query(
                """
                UNWIND $edges AS e
                MATCH (c:OntologyClass {uri: e.child})
                MATCH (p:OntologyClass {uri: e.parent})
                MERGE (c)-[:subClassOf]->(p)
                """,
                {"edges": subclass_edges},
            )
            edges_written = len(subclass_edges)
        except Exception as e:
            raise Exception(
                f"Neo4j subClassOf MERGE failed for domain '{domain}' "
                f"({len(subclass_edges)} edges): {e}"
            ) from e
        context.log.info(
            f"MERGE'd subClassOf edges (idempotent); {edges_written} "
            f"candidate edge(s) — those whose parent is a synced non-meta "
            f"class landed, meta/cross-partition parents skipped by design."
        )

    # ----- Step 4: verification read (the seam's standing assertion) ------
    # The asset's contract is "TTL classes reach Neo4j." Verify by
    # reading back. This is the analog of the saga's read-back probe.
    #
    # neo4j_client.execute_query (utils/neo4j_client.py) returns a plain
    # list[dict] — NOT a neo4j.Result with a `.records` attribute. The
    # previous code assumed .records and silently swallowed the
    # AttributeError, then logged "readback green" regardless. That made
    # verification a no-op and hid real "merged but absent" cases.
    verify_uris = [c["uri"] for c in classes]
    readback_ok = False
    try:
        result = neo4j_client.execute_query(
            """
            UNWIND $uris AS uri
            OPTIONAL MATCH (c:OntologyClass {uri: uri})
            RETURN uri AS asked, c.uri AS landed, c.domain AS domain
            """,
            {"uris": verify_uris},
        )
        missing = [r["asked"] for r in result if r["landed"] is None]
        readback_ok = True
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

    verify_msg = (
        "Verification readback green."
        if readback_ok
        else "Verification readback was skipped due to a prior error; "
             "see WARNING above."
    )
    context.log.info(
        f"Sync complete. {len(classes)} :OntologyClass nodes "
        f"materialized at full-IRI form for domain '{domain}'. "
        f"{verify_msg}"
    )

    return MaterializeResult(
        metadata={
            "domain": domain,
            "classes_merged": len(classes),
            "subclassof_edges_merged": edges_written,
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
