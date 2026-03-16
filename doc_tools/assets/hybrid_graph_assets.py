import os
import httpx
from dagster import asset, MaterializeResult, AssetCheckResult, MetadataValue
from neo4j import GraphDatabase

from doc_tools.parsers.s1000d_rdf import S1000dGraphBuilder

@asset
def parse_s1000d_module(context) -> str:
    """
    Parses S1000D XML modules and generates a raw Turtle file.
    Returns the file path to the generated .ttl file.
    """
    builder = S1000dGraphBuilder()
    
    # In a real scenario, this would pull from MinIO or a local directory
    # For this example, we'll assume a local path or a specific test file
    xml_path = os.environ.get("S1000D_INPUT_PATH", "data/s1000d_sample.xml")
    output_path = "output/s1000d_raw.ttl"
    
    os.makedirs("output", exist_ok=True)
    
    if os.path.exists(xml_path):
        with open(xml_path, "rb") as f:
            dmc_uri = builder.parse_data_module(f.read())
            context.log.info(f"Parsed DM: {dmc_uri}")
    else:
        context.log.warning(f"S1000D input file {xml_path} not found. Generating empty graph.")
        
    with open(output_path, "w") as f:
        f.write(builder.serialize(format="turtle"))
        
    return output_path

@asset
def upload_to_jena(context, parse_s1000d_module: str) -> MaterializeResult:
    """
    Uploads a raw S1000D Turtle file to the Apache Jena Fuseki data endpoint.
    """
    s1000d_raw_path = parse_s1000d_module
    # Read JENA_URL from environment; default to a common local Fuseki path
    # e.g., http://localhost:3030/ds/data
    jena_url = os.environ.get("JENA_URL", "http://localhost:3030/ds/data")
    user = os.environ.get("JENA_USERNAME", "admin")
    pw = os.environ.get("JENA_PASSWORD", "password")
    
    context.log.info(f"Uploading {s1000d_raw_path} to Jena at {jena_url}...")
    
    with open(s1000d_raw_path, "rb") as f:
        data = f.read()
        
    try:
        with httpx.Client(auth=(user, pw), verify=False) as client:
            response = client.post(
                jena_url,
                content=data,
                headers={"Content-Type": "text/turtle; charset=utf-8"}
            )
            response.raise_for_status()
            
        return MaterializeResult(
            metadata={
                "status": "success",
                "bytes_uploaded": len(data),
                "endpoint": jena_url
            }
        )
    except Exception as e:
        context.log.error(f"Failed to upload to Jena: {e}")
        raise e

@asset(deps=[upload_to_jena])
def init_neo4j_n10s(context) -> MaterializeResult:
    """
    Idempotently initializes the Neosemantics (n10s) plugin configuration in Neo4j.
    """
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USERNAME", "neo4j")
    pw = os.environ.get("NEO4J_PASSWORD", "password")
    
    driver = GraphDatabase.driver(uri, auth=(user, pw))
    
    with driver.session() as session:
        # 1. Initialize Graph Config if not already present
        # handleVocabUris: 'IGNORE' simplifies the graph by stripping namespaces from labels/properties
        try:
            session.run("CALL n10s.graphconfig.init({handleVocabUris: 'IGNORE'})")
            context.log.info("Initialized n10s graph config.")
        except Exception as e:
            if "already exists" in str(e).lower():
                context.log.info("n10s graph config already exists. Skipping.")
            else:
                raise e
        
        # 2. Ensure Uniqueness Constraint on URIs (Critical for n10s performance)
        session.run("CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS FOR (r:Resource) REQUIRE r.uri IS UNIQUE")
        context.log.info("Ensured n10s_unique_uri constraint.")
        
    driver.close()
    return MaterializeResult(metadata={"n10s_status": "ready"})

@asset(deps=[init_neo4j_n10s])
def sync_jena_to_neo4j(context) -> MaterializeResult:
    """
    Triggers Neo4j to fetch the RDF graph from Jena and import it into the property graph model.
    """
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USERNAME", "neo4j")
    pw = os.environ.get("NEO4J_PASSWORD", "password")
    
    # Point to the SPARQL query endpoint to get the INFERRED graph
    # e.g., http://localhost:3030/ds/query
    jena_query_url = os.environ.get("JENA_QUERY_URL", "http://localhost:3030/ds/query")
    
    # A standard SPARQL CONSTRUCT query to pull the entire inferred graph
    sparql_query = "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"
    
    # URL-encode the query so n10s can fetch it via HTTP GET
    import urllib.parse
    encoded_query = urllib.parse.quote(sparql_query)
    fetch_url = f"{jena_query_url}?query={encoded_query}"
    
    driver = GraphDatabase.driver(uri, auth=(user, pw))
    
    with driver.session() as session:
        # Execute the n10s fetch from the inferred SPARQL endpoint
        context.log.info(f"Triggering Neo4j n10s fetch from inferred SPARQL endpoint at {jena_query_url}...")
        result = session.run(
            "CALL n10s.rdf.import.fetch($url, 'Turtle')",
            url=fetch_url
        )
        
        summary = result.single()
        triples_imported = summary["triplesLoaded"] if summary else 0
        
    driver.close()
    
    return MaterializeResult(
        metadata={
            "triples_imported": triples_imported,
            "source_jena_query_url": jena_query_url,
            "query": sparql_query
        }
    )
