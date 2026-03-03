import json
import os
from typing import Any, Dict
from dagster import asset, AssetExecutionContext
from doc_tools.config import IngestionConfig
from doc_tools.assets.ingestion_assets import document_files_partition
from doc_tools.utils.dagster_resources import MinioResource, Neo4jResource, WeaviateResource, LLMExtractorResource, JenaResource
from doc_tools.plugins import BaseSection, DocumentNode
from doc_tools.plugins.training import TrainingPlugin
from doc_tools.plugins.manufacturing import ManufacturingPlugin

@asset(partitions_def=document_files_partition)
def build_knowledge_graph(
    context: AssetExecutionContext,
    config: IngestionConfig,
    process_document_artifact: Dict[str, Any],
    minio: MinioResource,
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
    
    # Configuration Labels
    node_label = config.graph_node_label
    child_label = config.graph_child_label
    collection_name = config.vector_collection_name
    
    context.log.info(f"Building Graph for doc: {doc_id} using labels '{node_label}' and '{child_label}'")
    
    minio_client = minio.get_client()
    neo4j_client = neo4j.get_client()
    weaviate_client = weaviate.get_client()
    llm_client = llm.get_client()
    jena_client = jena.get_client()
    
    # 2. Load Text Data
    import tempfile
    text_elements = []
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            minio_client.fget_object(config.bucket, text_location, tmp.name)
            with open(tmp.name, 'r', encoding='utf-8') as f:
                text_elements = json.load(f)
    except Exception as e:
        context.log.warning(f"Could not load text data from Minio: {e}. Using mock elements.")
        text_elements = [{"type": "Text", "text": "Mock extracted text", "metadata": {"page_number": 1}}]
            
    # --- PASS 1: CREATE NODES ---
    
    context.log.info(f"Creating Parent '{node_label}' Node...")
    try:
        metadata = manifest.get("metadata", {})
        title = manifest.get("filename", doc_id)
        
        # Using configured labels in Cypher queries requires f-strings or manual substitution
        # as Neo4j drivers cannot parameterize labels.
        neo4j_client.execute_query(
            f"""
            MERGE (n:{node_label} {{id: $id}}) 
            SET n.title = $title
            """,
            {
                "id": doc_id, 
                "title": title
            }
        )
    except Exception as e:
        context.log.error(f"Parent Node creation failed: {e}")

    # Process Pages/Chunks (Content Extraction)
    from collections import defaultdict
    from doc_tools.utils.layout_detector import detect_layout
    
    pages = defaultdict(list)
    page_elements = defaultdict(list)
    
    current_chunk_page = 1
    current_chunk_size = 0
    CHUNK_LIMIT = 1500
    
    for el in text_elements:
        metadata = el.get("metadata", {})
        text = el.get("text", "")
        
        type_ = el.get("type", "Text")
        formatted_text = f"[{type_}] {text}"
        
        if "page_number" in metadata:
            page_num = metadata["page_number"]
            pages[page_num].append(formatted_text)
            page_elements[page_num].append(el)
        else:
            pages[current_chunk_page].append(formatted_text)
            page_elements[current_chunk_page].append(el)
            
            current_chunk_size += len(text)
            if current_chunk_size > CHUNK_LIMIT:
                current_chunk_page += 1
                current_chunk_size = 0
        
    # Initialize appropriate Plugin based on run tags
    try:
        domain_type = context.run_tags.get("domain_type")
    except AttributeError:
        try:
             domain_type = context.run.tags.get("domain_type")
        except AttributeError:
             domain_type = manifest.get("metadata", {}).get("project", "Training")
             
    if domain_type == "manufacturing":
        plugin = ManufacturingPlugin()
    elif domain_type == "compliance":
        try:
            from doc_tools.plugins.compliance import CompliancePlugin
            plugin = CompliancePlugin()
        except ImportError:
            context.log.warning("CompliancePlugin not found, falling back to TrainingPlugin")
            plugin = TrainingPlugin()
    else:
        plugin = TrainingPlugin()
        
    context.log.info(f"Initialized {type(plugin).__name__} for domain: {domain_type}")

    # Ensure Weaviate Class exists with dynamic collection name
    try:
        weaviate_client.ensure_class({
            "class": collection_name,
            "vectorizer": "text2vec-transformers",
            "moduleConfig": {
                "text2vec-transformers": {
                    "vectorizeClassName": False
                }
            },
            "properties": [
                {"name": "text", "dataType": ["text"], "moduleConfig": {"text2vec-transformers": {"skip": False, "vectorizePropertyName": False}}},
                {"name": "doc_id", "dataType": ["string"], "moduleConfig": {"text2vec-transformers": {"skip": True}}},
                {"name": "chunk_id", "dataType": ["string"], "moduleConfig": {"text2vec-transformers": {"skip": True}}},
            ]
        })
    except Exception as e:
        context.log.error(f"Weaviate Class creation failed: {e}")

    # Reconstruct full text for optional Global Plugin Pass
    full_text_parts = []
    current_page = -1
    for el in text_elements:
        text = el.get("text", "")
        if not text:
            continue
        page_num = el.get("metadata", {}).get("page_number")
        if page_num is not None and page_num != current_page:
            full_text_parts.append(f"\n--- Page {page_num} ---\n")
            current_page = page_num
        type_ = el.get("type", "Text")
        full_text_parts.append(f"[{type_}] {text}")
        
    full_text = "\n".join(full_text_parts)

    # Allow plugins an optional full-document processing pass (e.g. Outlines)
    document_nodes = []
    try:
        context.log.info(f"Executing global full-text pass for {type(plugin).__name__}...")
        global_nodes = plugin.process_fulltext(full_text, doc_id, manifest.get("metadata", {}))
        if global_nodes:
            document_nodes.extend(global_nodes)
    except Exception as e:
        context.log.error(f"Global plugin extraction failed: {e}")

    # Process each page/chunk through the Plugin architecture
    for page_num, texts in pages.items():
        chunk_text = "\n".join(texts)
        if not chunk_text.strip():
            continue
            
        chunk_id = f"{doc_id}_p{page_num}"
        elements = page_elements.get(page_num, [])
        layout_style = detect_layout(elements)
        
        filename = manifest.get("filename", "")
        file_ext = os.path.splitext(filename)[1].upper().replace('.', '') if filename else "Unknown"
        asset_type = file_ext
        
        # 1. Instantiate Base Section
        section = BaseSection(
            title=f"Page {page_num}",
            level=1,
            page_start=page_num,
            content=chunk_text,
            node_id=chunk_id
        )
        
        # 2. Augment via Domain Plugin
        try:
            node = plugin.augment(section)
            document_nodes.append(node)
        except Exception as e:
            context.log.error(f"Plugin augmentation failed for chunk {chunk_id}: {e}")

        # Baseline Child Node still maintained for full structural map
        try:
            neo4j_client.execute_query(
                f"""
                MATCH (parent:{node_label} {{id: $parent_id}})
                MERGE (child:{child_label} {{id: $id}})
                SET child.number = $page_num, 
                    child.text = $text,
                    child.asset_type = $asset_type,
                    child.layout_style = $layout_style,
                    child.elements = $elements_json
                MERGE (parent)-[:HAS_CHILD]->(child)
                """,
                {"parent_id": doc_id, "id": chunk_id, "page_num": page_num, "text": chunk_text[:500], "asset_type": asset_type, "layout_style": layout_style, "elements_json": json.dumps(elements)}
            )
        except Exception as e:
            context.log.error(f"Neo4j baseline chunk creation failed: {e}")

    # 3. Graph Sink: Convert Augmented Nodes to Cypher/SPARQL
    context.log.info(f"Generating domain graph queries from {len(document_nodes)} augmented nodes...")
    cypher_queries, sparql_queries = plugin.to_graph_queries(document_nodes, config)
    
    # Execute Cypher
    for idx, c_query in enumerate(cypher_queries):
        try:
            neo4j_client.execute_query(c_query["query"], c_query.get("params", {}))
        except Exception as e:
            context.log.error(f"Failed executing domain cypher query {idx}: {e}")
            
    # Execute SPARQL sink update
    if sparql_queries:
        context.log.info(f"SPARQL Queries to emit to Jena: {len(sparql_queries)}")
        for idx, s_query in enumerate(sparql_queries):
            try:
                jena_client.execute_update(s_query)
            except Exception as e:
                context.log.error(f"Failed executing domain SPARQL query {idx}: {e}")

        # Vector Indexing
        try:
            weaviate_client.add_object(
                data_object={
                    "text": chunk_text,
                    "doc_id": doc_id,
                    "chunk_id": chunk_id
                },
                class_name=collection_name
            )
        except Exception as e:
            context.log.error(f"Vector indexing failed for chunk {chunk_id}: {e}")

    # --- PASS 2: LINK & ROLL-UP (Domain-Specific) ---
    try:
        context.log.info(f"Executing Pass 2 Roll-up for {type(plugin).__name__}...")
        plugin.execute_pass2_rollup(neo4j_client, doc_id, config)
    except Exception as e:
        context.log.error(f"Pass 2 Roll-up failed: {e}")

    try:
        neo4j_client.close()
    except Exception:
        pass
        
    return {"doc_id": doc_id, "status": "processed", "node_label": node_label, "collection": collection_name}
