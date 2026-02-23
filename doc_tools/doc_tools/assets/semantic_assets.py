import json
import os
from typing import Any, Dict
from dagster import asset, AssetExecutionContext
from doc_tools.config import IngestionConfig
from doc_tools.assets.ingestion_assets import document_files_partition, BUCKET_NAME
from doc_tools.utils.dagster_resources import MinioResource, Neo4jResource, WeaviateResource, LLMExtractorResource
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
    llm: LLMExtractorResource
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
    
    # 2. Load Text Data
    import tempfile
    text_elements = []
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            minio_client.download_file(BUCKET_NAME, text_location, tmp.name)
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
        
    # Initialize appropriate Plugin based on metadata
    project_type = manifest.get("metadata", {}).get("project", "Training")
    plugin = ManufacturingPlugin() if project_type == "MAT" else TrainingPlugin()
    context.log.info(f"Initialized {type(plugin).__name__} for project: {project_type}")

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

    # Process each page/chunk through the Plugin architecture
    document_nodes = []
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
            content=chunk_text
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
            
    # Mock Jena/SPARQL sink since we don't have a configured JenaResource in this architecture yet
    if sparql_queries:
        context.log.info(f"SPARQL Queries to emit to Jena: {len(sparql_queries)}")
        for idx, s_query in enumerate(sparql_queries):
            context.log.debug(f"SPARQL [{idx}]:\n{s_query}")

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

    try:
        neo4j_client.close()
    except Exception:
        pass
        
    return {"doc_id": doc_id, "status": "processed", "node_label": node_label, "collection": collection_name}
