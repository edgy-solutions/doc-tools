import os
import requests
from dagster import asset, AssetExecutionContext, Config
from pydantic import Field
from doc_tools.assets.semantic_linker import propose_datahub_term, DATAHUB_GMS_URL, DATAHUB_TOKEN

class GlobalIngestionConfig(Config):
    search_limit: int = Field(default=1000, description="Max number of datasets to scan in DataHub")

@asset
def ingest_global_semantic_links(context: AssetExecutionContext, config: GlobalIngestionConfig) -> dict:
    """
    Polls DataHub for all Dataset entities that possess an 'ontology_uri' Custom Property.
    Proposes Glossary Terms for those datasets using the Phase 7 Short Name standard.
    This enables 'Late Binding' AI routing for any asset tagged by dag-tools CI/CD.
    """
    context.log.info("Polling DataHub for datasets with 'ontology_uri' custom property...")
    
    # GraphQL query to find datasets with customProperties
    # We fetch the urn and the customProperties aspect
    query = """
    query searchDatasetsWithOntology($input: SearchInput!) {
      search(input: $input) {
        searchResults {
          entity {
            urn
            ... on Dataset {
              customProperties {
                key
                value
              }
            }
          }
        }
      }
    }
    """
    
    # We search for datasets. Filtering for specific custom properties in the search query 
    # can be platform-dependent (Elasticsearch vs. others), so we'll fetch recently 
    # modified datasets and filter in Python for maximum reliability across environments.
    variables = {
        "input": {
            "type": "DATASET",
            "query": "*",
            "start": 0,
            "count": config.search_limit
        }
    }
    
    headers = {
        "Authorization": f"Bearer {DATAHUB_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        resp = requests.post(DATAHUB_GMS_URL, json={"query": query, "variables": variables}, headers=headers)
        resp.raise_for_status()
        search_results = resp.json().get("data", {}).get("search", {}).get("searchResults", [])
    except Exception as e:
        context.log.error(f"Failed to poll DataHub search: {e}")
        raise e

    stats = {"scanned": 0, "found_tags": 0, "linked": 0}

    for result in search_results:
        entity = result.get("entity", {})
        urn = entity.get("urn")
        custom_props = entity.get("customProperties", [])
        
        stats["scanned"] += 1
        
        # Look for the ontology_uri key
        ontology_uri = None
        for prop in custom_props:
            if prop["key"] == "ontology_uri":
                ontology_uri = prop["value"]
                break
        
        if ontology_uri:
            stats["found_tags"] += 1
            context.log.info(f"📍 Found Semantic Tag on {urn} -> {ontology_uri}")
            
            reasoning = "Propagated from 'ontology_uri' custom property pushed by dag-tools."
            try:
                # Use our standardized linker to propose the term
                propose_datahub_term(urn, ontology_uri, reasoning)
                stats["linked"] += 1
            except Exception as e:
                context.log.error(f"Failed to propose term for {urn}: {e}")

    return stats
