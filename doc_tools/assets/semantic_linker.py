import os
import requests
from dagster import asset, AssetExecutionContext, Config
from typing import Dict, Any
from doc_tools.utils.dagster_resources import Neo4jResource

# Engine O Endpoint
ONTOLOGY_SVC_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://ontology-agent-svc.default.svc.cluster.local:8084")
DATAHUB_GMS_URL = os.getenv("DATAHUB_GMS_URL", "http://datahub-gms:8080/api/graphql")
DATAHUB_TOKEN = os.getenv("DATAHUB_TOKEN", "")

def propose_datahub_term(dataset_urn: str, term_urn: str, reason: str):
    """Submits a Proposed Glossary Term to DataHub for HITL review."""
    query = """
    mutation proposeTerms($input: ProposeTermsInput!) {
      proposeTerms(input: $input)
    }
    """
    variables = {
        "input": {
            "resourceUrn": dataset_urn,
            "proposals": [{"urn": term_urn}]
        }
    }
    headers = {
        "Authorization": f"Bearer {DATAHUB_TOKEN}",
        "Content-Type": "application/json"
    }
    resp = requests.post(DATAHUB_GMS_URL, json={"query": query, "variables": variables}, headers=headers)
    resp.raise_for_status()
    return resp.json()

@asset
def apply_semantic_tags(
    context: AssetExecutionContext,
    extract_sqlserver_metadata: dict,
    extract_oracle_metadata: dict,
    parse_design_metadata: dict
) -> dict:
    """
    Consumes extracted metadata, classifies via Engine O, and pushes to DataHub.
    """
    all_metadata = {}
    all_metadata.update(extract_sqlserver_metadata or {})
    all_metadata.update(extract_oracle_metadata or {})
    all_metadata.update(parse_design_metadata or {})
    
    if not all_metadata:
        context.log.info("No metadata found to classify.")
        return {"processed": 0, "tagged": 0, "human_review": 0}

    stats = {"processed": 0, "tagged": 0, "human_review": 0}
    
    for table_name, meta in all_metadata.items():
        stats["processed"] += 1
        domain = meta.get("domain", "DATA_ENGINEERING")
        
        dossier = {
            "table_name": table_name,
            "columns_schema": meta.get("columns", "Unknown"),
            "dba_comments": meta.get("description", "None"),
            "orm_class_name": meta.get("orm_class", "None"),
            "sample_data": meta.get("sample", "None"),
            "domain": domain
        }
        
        try:
            resp = requests.post(f"{ONTOLOGY_SVC_URL}/classify_legacy_table", json=dossier, timeout=30)
            resp.raise_for_status()
            classification = resp.json()
            
            resolved_uri = classification.get("resolved_uri")
            confidence = classification.get("confidence_score", 0.0)
            reasoning = classification.get("reasoning", "")
            
            if resolved_uri and confidence >= 0.85:
                context.log.info(f"✅ AUTO-TAGGING: {table_name} -> {resolved_uri}")
                dataset_urn = f"urn:li:dataset:(urn:li:dataPlatform:legacy,{table_name},PROD)"
                term_urn = f"urn:li:glossaryTerm:{resolved_uri}"
                propose_datahub_term(dataset_urn, term_urn, reasoning) # Even auto-tags go through propose for safety/audit
                stats["tagged"] += 1
            elif resolved_uri and confidence >= 0.50:
                context.log.warning(f"⚠️ HUMAN REVIEW: {table_name} -> {resolved_uri}")
                dataset_urn = f"urn:li:dataset:(urn:li:dataPlatform:legacy,{table_name},PROD)"
                term_urn = f"urn:li:glossaryTerm:{resolved_uri}"
                propose_datahub_term(dataset_urn, term_urn, reasoning)
                stats["human_review"] += 1
            else:
                context.log.error(f"❌ REJECTED: {table_name} is unrecognizable. Skipping.")
                
        except Exception as e:
            context.log.error(f"Failed to classify {table_name}: {e}")
            
    return stats

# --- NEW ASSET FOR NEO4J SYNC ---
class ApprovedTagConfig(Config):
    dataset_urn: str
    term_urn: str

@asset
def sync_approved_tags_to_neo4j(
    context: AssetExecutionContext, 
    config: ApprovedTagConfig, 
    neo4j: Neo4jResource
):
    """
    Consumes approved tag payloads from the DataHub sensor and draws 
    the semantic [:HAS_DATA] link in the Neo4j Knowledge Graph.
    """
    context.log.info(f"Syncing DataHub approval to Neo4j: {config.dataset_urn} -> {config.term_urn}")
    
    # 1. Clean the DataHub Glossary Term URN to get the pure IOF Ontology URI
    # Example term_urn: "urn:li:glossaryTerm:http://spec.industrialontologies.org/ontology/construct/Pump"
    ontology_uri = config.term_urn.replace("urn:li:glossaryTerm:", "")
    
    # 2. Define the Cypher Query
    # MERGE creates the node/edge if it doesn't exist, or matches it if it does.
    cypher_query = """
    // Ensure the Ontology Class proxy node exists
    MERGE (o:OntologyClass {uri: $ontology_uri})
    
    // Ensure the DataHub Dataset proxy node exists
    MERGE (d:DataAsset {urn: $dataset_urn})
    
    // Draw the Bidirectional Semantic Link
    MERGE (o)-[:HAS_DATA]->(d)
    """
    
    # 3. Execute against the Graph Database
    try:
        driver = neo4j.get_driver()
        with driver.session() as session:
            session.run(
                cypher_query, 
                ontology_uri=ontology_uri, 
                dataset_urn=config.dataset_urn
            )
        context.log.info(f"✅ Successfully linked {ontology_uri} to {config.dataset_urn} in Neo4j.")
        
        return {
            "status": "success", 
            "ontology_uri": ontology_uri, 
            "dataset_urn": config.dataset_urn
        }
        
    except Exception as e:
        context.log.error(f"❌ Failed to sync to Neo4j: {e}")
        raise e
