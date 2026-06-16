import os
import json
import httpx
import urllib.parse
from typing import Any, Dict
from dagster import asset, AssetExecutionContext, MaterializeResult, AutomationCondition
from neo4j import GraphDatabase
from doc_tools.config import IngestionConfig
from dagster_aws.s3 import S3Resource
from doc_tools.partitions import pdf_files_partition
from doc_tools.utils.dagster_resources import Neo4jResource, WeaviateResource, LLMExtractorResource, JenaResource
from doc_tools.plugins import BaseSection, DocumentNode
from doc_tools.plugins.training import TrainingPlugin
from doc_tools.plugins.manufacturing import ManufacturingPlugin
from doc_tools.plugins.sustainment import SustainmentPlugin
import weaviate.classes as wvc


def _ensure_weaviate_collection(client, name: str) -> None:
    """Idempotently create the chunk collection using the Weaviate v4 API
    (mirrors ontology_assets). The deployed cluster supplies the default
    vectorizer, so no vectorizer_config is set here."""
    if not client.collections.exists(name):
        client.collections.create(
            name=name,
            properties=[
                wvc.config.Property(name="text", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="doc_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="chunk_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="domain", data_type=wvc.config.DataType.TEXT),
            ],
        )


def _index_chunk(client, name: str, properties: dict) -> None:
    """Insert one chunk object using the Weaviate v4 API."""
    client.collections.get(name).data.insert(properties=properties)


def _extraction_payload(document_nodes, doc_id: str, domain_type: str) -> dict:
    """Serialize the structured LLM extraction for persistence to S3.

    to_graph_queries only writes Neo4j/Jena; this captures the raw extracted
    records (each node's Pydantic ``domain_augmentation`` -> dict) so the output
    is retrievable / auditable / reprocessable. Domain-generic: works for any
    plugin whose augmentation is a Pydantic model. Nodes without an augmentation
    (e.g. per-chunk no-op augment) are skipped.
    """
    augmentations = [
        n.domain_augmentation.model_dump()
        for n in document_nodes
        if n.domain_augmentation is not None and hasattr(n.domain_augmentation, "model_dump")
    ]
    return {"doc_id": doc_id, "domain_type": domain_type, "augmentations": augmentations}


@asset(
    partitions_def=pdf_files_partition,
    automation_condition=AutomationCondition.on_missing() | AutomationCondition.any_deps_updated()
)
def build_knowledge_graph(
    context: AssetExecutionContext,
    config: IngestionConfig,
    process_document_artifact: Dict[str, Any],
    s3: S3Resource,
    neo4j: Neo4jResource,
    weaviate: WeaviateResource,
    llm: LLMExtractorResource,
    jena: JenaResource
):
    """
    Ingests documents into Neo4j using generic labels provided via Configuration.
    Vectorizes document chunks into a Weaviate collection provided via Configuration.
    """
    manifest = process_document_artifact
    doc_id = manifest["doc_id"]
    text_location = manifest["text_location"]
    
    # Map Configuration Variables to Local Context
    node_label = config.graph_node_label
    child_label = config.graph_child_label
    collection_name = config.vector_collection_name
    
    context.log.info(f"Building Graph for doc: {doc_id} using labels '{node_label}' and '{child_label}'")
    
    # Domain Label for Neo4j Segregation
    metadata = manifest.get("metadata", {})
    domain_type = metadata.get("domain_type")
    if not domain_type:
        try:
            domain_type = context.run.tags.get("domain_type")
        except AttributeError:
            domain_type = metadata.get("project", "Training")
    
    domain_label = domain_type.upper().replace(" ", "_").replace("-", "_")
    
    s3_client = s3.get_client()
    neo4j_client = neo4j.get_client()
    weaviate_client = weaviate.get_client()
    llm_client = llm.get_client()
    jena_client = jena.get_client()
    
    # 2. Load Text Data
    import tempfile
    text_elements = []
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            s3_client.download_file(Bucket=config.bucket, Key=text_location, Filename=tmp.name)
            with open(tmp.name, 'r', encoding='utf-8') as f:
                text_elements = json.load(f)
    except Exception as e:
        context.log.warning(f"Could not load text data from Minio: {e}. Using mock elements.")
        text_elements = [{"type": "Text", "text": "Mock extracted text", "metadata": {"page_number": 1}}]
            
    # --- PASS 1: CREATE NODES ---
    
    # Create Parent Node
    try:
        title = manifest.get("filename", doc_id)
        neo4j_client.execute_query(
            f"MERGE (n:{node_label}:{domain_label} {{id: $id}}) SET n.title = $title",
            {"id": doc_id, "title": title}
        )
    except Exception as e:
        context.log.error(f"Parent Node creation failed: {e}")

    # Process Pages/Chunks (Content Extraction)
    from collections import defaultdict
    from doc_tools.utils.layout_detector import detect_layout
    
    pages = defaultdict(list)
    page_elements = defaultdict(list)
    
    for el in text_elements:
        p_metadata = el.get("metadata", {})
        text = el.get("text", "")
        type_ = el.get("type", "Text")
        formatted_text = f"[{type_}] {text}"
        page_num = p_metadata.get("page_number", 1)
        pages[page_num].append(formatted_text)
        page_elements[page_num].append(el)
            
    # Initialize appropriate Plugin
    if domain_type == "manufacturing":
        plugin = ManufacturingPlugin(domain_type)
    elif domain_type == "maintenance":
        from doc_tools.plugins.maintenance import MaintenancePlugin
        plugin = MaintenancePlugin(domain_type)
    elif domain_type == "compliance":
        try:
            from doc_tools.plugins.compliance import CompliancePlugin
            plugin = CompliancePlugin(domain_type)
        except ImportError:
            context.log.warning("CompliancePlugin not found, falling back to TrainingPlugin")
            plugin = TrainingPlugin(domain_type)
    elif domain_type == "sustainment":
        plugin = SustainmentPlugin(domain_type)
    else:
        plugin = TrainingPlugin(domain_type)
        
    context.log.info(f"Initialized {type(plugin).__name__} for domain: {domain_type}")

    # Ensure Weaviate Collection (v4 API)
    try:
        _ensure_weaviate_collection(weaviate_client, collection_name)
    except Exception as e:
        context.log.error(f"Weaviate Class creation failed: {e}")

    # Reconstruct full text for Global Plugin Pass
    full_text_parts = []
    current_page = -1
    for el in text_elements:
        text = el.get("text", "")
        if not text: continue
        page_num = el.get("metadata", {}).get("page_number")
        if page_num is not None and page_num != current_page:
            full_text_parts.append(f"\n--- Page {page_num} ---\n")
            current_page = page_num
        full_text_parts.append(f"[{el.get('type', 'Text')}] {text}")
    full_text = "\n".join(full_text_parts)

    document_nodes = []
    try:
        context.log.info(f"Executing global full-text pass for {type(plugin).__name__}...")
        global_nodes = plugin.process_fulltext(full_text, doc_id, metadata, elements=text_elements)
        if global_nodes:
            document_nodes.extend(global_nodes)
    except Exception as e:
        context.log.error(f"Global plugin extraction failed: {e}")

    # Process each page/chunk
    for page_num, texts in pages.items():
        chunk_text = "\n".join(texts)
        if not chunk_text.strip(): continue
            
        chunk_id = f"{doc_id}_p{page_num}"
        elements = page_elements.get(page_num, [])
        layout_style = detect_layout(elements)
        
        filename = manifest.get("filename", "")
        file_ext = os.path.splitext(filename)[1].upper().replace('.', '') if filename else "Unknown"
        
        # 1. Instantiate Base Section
        section = BaseSection(title=f"Page {page_num}", level=1, page_start=page_num, content=chunk_text, node_id=chunk_id)
        
        # 2. Augment via Domain Plugin
        try:
            node = plugin.augment(section, config)
            document_nodes.append(node)
        except Exception as e:
            context.log.error(f"Plugin augmentation failed for chunk {chunk_id}: {e}")

        # Neo4j baseline chunk creation
        try:
            neo4j_client.execute_query(
                f"""
                MATCH (parent:{node_label}:{domain_label} {{id: $parent_id}})
                MERGE (child:{child_label}:{domain_label} {{id: $id}})
                SET child.number = $page_num, child.text = $text, child.asset_type = $asset_type,
                    child.layout_style = $layout_style, child.elements = $elements_json
                MERGE (parent)-[:HAS_CHILD]->(child)
                """,
                {"parent_id": doc_id, "id": chunk_id, "page_num": page_num, "text": chunk_text[:500], "asset_type": file_ext, "layout_style": layout_style, "elements_json": json.dumps(elements)}
            )
        except Exception as e:
            context.log.error(f"Neo4j baseline chunk creation failed: {e}")

        # Vector Indexing (Per Chunk, v4 API)
        try:
            _index_chunk(weaviate_client, collection_name, {
                "text": chunk_text, "doc_id": doc_id, "chunk_id": chunk_id, "domain": domain_label,
            })
        except Exception as e:
            context.log.error(f"Vector indexing failed for chunk {chunk_id}: {e}")

    # Derive image_prefix from text_location
    # e.g. text_location: "manufacturing/IID/generated/test_pdf/text.json"
    # base_dir: "manufacturing/IID/generated/test_pdf"
    base_dir = os.path.dirname(text_location)
    image_prefix = f"s3://{config.bucket}/{base_dir}/images/"

    # Persist the structured LLM extraction to S3 (next to text.json) so it can be
    # retrieved/audited/reprocessed — the graph sink below only writes Neo4j + Jena.
    try:
        payload = _extraction_payload(document_nodes, doc_id, domain_type)
        extraction_key = f"{base_dir}/extraction.json"
        s3_client.put_object(
            Bucket=config.bucket,
            Key=extraction_key,
            Body=json.dumps(payload, indent=2, default=str).encode("utf-8"),
            ContentType="application/json",
        )
        context.log.info(
            f"Wrote extraction to s3://{config.bucket}/{extraction_key} "
            f"({len(payload['augmentations'])} augmentation(s))"
        )
    except Exception as e:
        context.log.error(f"Failed to write extraction.json: {e}")

    # 3. Graph Sink: Convert Augmented Nodes to Cypher/SPARQL
    context.log.info(f"Generating domain graph queries from {len(document_nodes)} augmented nodes...")
    cypher_queries, sparql_queries = plugin.to_graph_queries(document_nodes, config, doc_id=doc_id, image_prefix=image_prefix)
    
    for idx, c_query in enumerate(cypher_queries):
        try:
            neo4j_client.execute_query(c_query["query"], c_query.get("params", {}))
        except Exception as e:
            context.log.error(f"Failed executing domain cypher query {idx}: {e}")
            
    if sparql_queries:
        context.log.info(f"SPARQL Queries to emit to Jena: {len(sparql_queries)}")
        for idx, s_query in enumerate(sparql_queries):
            try:
                jena_client.execute_update(s_query)
            except Exception as e:
                context.log.error(f"Failed executing domain SPARQL query {idx}: {e}")

    # --- PASS 2: LINK & ROLL-UP ---
    try:
        context.log.info(f"Executing Pass 2 Roll-up for {type(plugin).__name__}...")
        plugin.execute_pass2_rollup(neo4j_client, doc_id, config)
    except Exception as e:
        context.log.error(f"Pass 2 Roll-up failed: {e}")

    try:
        neo4j_client.close()
    except Exception:
        pass
    # The Weaviate v4 client holds gRPC/HTTP connections that must be closed
    # explicitly, or it leaks (ResourceWarning Con004) across runs.
    try:
        weaviate_client.close()
    except Exception:
        pass

    return {"doc_id": doc_id, "status": "processed", "node_label": node_label, "collection": collection_name}

@asset
def upload_to_jena(context: AssetExecutionContext, extract_rdf_from_xml: dict, jena: JenaResource) -> dict:
    """
    Uploads the generic RDF Turtle string to a specific Named Graph in Apache Jena.
    Uses PUT to ensure idempotency (overwrites previous revisions of this file).
    """
    jena_url = f"{jena.url.rstrip('/')}/{jena.dataset}/data"
    user = jena.username
    pw = jena.password
    
    s3_key = extract_rdf_from_xml["s3_key"]
    # Construct Named Graph URI from S3 key
    graph_uri = urllib.parse.quote(f"urn:doc:{s3_key}")
    target_url = f"{jena_url}?graph={graph_uri}"
    
    context.log.info(f"Uploading RDF for {s3_key} to Jena Named Graph: {graph_uri}")
    
    data = extract_rdf_from_xml["rdf_string"].encode('utf-8')
        
    try:
        with httpx.Client(auth=(user, pw), verify=False) as client:
            # Using PUT to completely overwrite the Named Graph for this document
            response = client.put(
                target_url,
                content=data,
                headers={"Content-Type": "text/turtle; charset=utf-8"}
            )
            response.raise_for_status()
            
        return extract_rdf_from_xml # Pass metadata downstream
    except Exception as e:
        context.log.error(f"Failed to upload to Jena: {e}")
        raise e

@asset(deps=[upload_to_jena])
def init_neo4j_n10s(context: AssetExecutionContext, neo4j: Neo4jResource) -> MaterializeResult:
    """
    Idempotently initializes Neosemantics (n10s) config in Neo4j.
    """
    uri = neo4j.uri
    user = neo4j.username
    pw = neo4j.password
    
    driver = GraphDatabase.driver(uri, auth=(user, pw))
    
    with driver.session() as session:
        try:
            session.run("CALL n10s.graphconfig.init({handleVocabUris: 'IGNORE'})")
            context.log.info("Initialized n10s graph config.")
        except Exception as e:
            if "already exists" in str(e).lower():
                context.log.info("n10s graph config already exists.")
            else:
                raise e
        
        session.run("CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS FOR (r:Resource) REQUIRE r.uri IS UNIQUE")
        
    driver.close()
    return MaterializeResult(metadata={"n10s_status": "ready"})

@asset(deps=[init_neo4j_n10s])
def sync_jena_to_neo4j(context: AssetExecutionContext, upload_to_jena: dict, jena: JenaResource, neo4j: Neo4jResource) -> MaterializeResult:
    """
    Deletes the previous revision in Neo4j (deep wipe) and fetches the fresh isolated graph from Jena.
    """
    neo4j_client = neo4j.get_client()
    jena_client = jena.get_client()
    
    root_uri = upload_to_jena["root_uri"]
    s3_key = upload_to_jena["s3_key"]
    
    # Construct Named Graph URI from S3 key
    graph_uri = f"urn:doc:{s3_key}"
    
    # 1. Fetch ALL subject URIs from this document's Named Graph in Jena
    # This allows us to perform a clean 'deep delete' in Neo4j
    context.log.info(f"Fetching subjects from Jena Named Graph: {graph_uri}")
    subjects_query = f"""
    SELECT DISTINCT ?s WHERE {{
      GRAPH <{graph_uri}> {{
        ?s ?p ?o
      }}
    }}
    """
    try:
        jena_results = jena_client.execute_query(subjects_query)
        uri_list = [row["s"]["value"] for row in jena_results["results"]["bindings"]]
        context.log.info(f"Found {len(uri_list)} unique URIs to wipe from Neo4j.")
    except Exception as e:
        context.log.error(f"Failed to fetch subjects from Jena: {e}")
        uri_list = [root_uri] # Fallback to just the root if query fails
        
    # 2. Deep Wipe in Neo4j
    if uri_list:
        context.log.info(f"Wiping {len(uri_list)} Nodes from Neo4j (Deep Detach/Delete)...")
        try:
            # We don't need the domain label for deletion because the URI is unique across the DB
            neo4j_client.execute_query(
                "UNWIND $uri_list AS deleted_uri MATCH (n {uri: deleted_uri}) DETACH DELETE n",
                {"uri_list": uri_list}
            )
        except Exception as e:
            context.log.error(f"Deep wipe failed: {e}")

    # 3. Trigger Neo4j n10s fetch for ONLY this document
    # Scoped CONSTRUCT ensures we only pull the current revision's graph
    context.log.info(f"Triggering Neo4j n10s fetch from Jena Named Graph for: {s3_key}")
    
    # n10s fetch requires a URL that returns RDF. We point it back to our Jena query endpoint.
    sparql_construct = f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }}"
    
    # Construct the fetch URL (Fuseki /{dataset}/query endpoint with ?query=...)
    jena_base = jena.url.rstrip('/')
    jena_ds = jena.dataset
    encoded_query = urllib.parse.quote(sparql_construct)
    fetch_url = f"{jena_base}/{jena_ds}/query?query={encoded_query}"
    
    try:
        # Pass headers to ensure we get Turtle back for n10s
        result = neo4j_client.execute_query(
            "CALL n10s.rdf.import.fetch($url, 'Turtle', { headerParams: { Accept: 'application/x-turtle' } })",
            {"url": fetch_url}
        )
        # result is now a record/summary
        triples_imported = 0 # In a real driver we'd parse the result summary
    except Exception as e:
        context.log.error(f"n10s fetch failed: {e}")
        triples_imported = 0

    # 4. Post-Sync: Apply MAINTENANCE domain label to all imported nodes
    # XML tech manuals (S1000D, IADS, DITA, 40051) are maintenance/MRO content
    _apply_post_sync_domain_labels(neo4j_client, uri_list, "MAINTENANCE", context)

        
    return MaterializeResult(
        metadata={
            "triples_to_sync": len(uri_list),
            "root_uri": root_uri,
            "s3_key": s3_key,
            "jena_named_graph": graph_uri
        }
    )


def _apply_post_sync_domain_labels(neo4j_client, uri_list, domain_label: str, context):
    """
    After n10s imports RDF nodes as :Resource nodes, apply the domain segregation
    label so downstream agents can filter by domain in Cypher.
    """
    if not uri_list:
        return
    
    context.log.info(f"Applying :{domain_label} label to {len(uri_list)} imported Resource nodes...")
    try:
        neo4j_client.execute_query(
            f"UNWIND $uri_list AS u MATCH (n:Resource {{uri: u}}) SET n:{domain_label}",
            {"uri_list": uri_list}
        )
        context.log.info(f"Successfully applied :{domain_label} to all synced nodes.")
    except Exception as e:
        context.log.error(f"Failed to apply domain labels: {e}")
