import os
import time
import requests
from neo4j import GraphDatabase
import weaviate

def parse_env():
    """Simple parser for local .env if python-dotenv is not installed"""
    env_vars = {}
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip().strip("'").strip('"')
    
    # Merge with actual environment so os.environ overrides .env
    for k, v in env_vars.items():
        if k not in os.environ:
            os.environ[k] = v

def prime_neo4j():
    print("--- Priming Neo4j (Constraints & Indexes) ---")
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "password")
    
    cypher_commands = [
        "CREATE CONSTRAINT part_id_unique IF NOT EXISTS FOR (p:Part) REQUIRE p.id IS UNIQUE;",
        "CREATE CONSTRAINT proc_id_unique IF NOT EXISTS FOR (p:Procedure) REQUIRE p.id IS UNIQUE;",
        "CREATE CONSTRAINT step_id_unique IF NOT EXISTS FOR (s:ManufacturingStep) REQUIRE s.id IS UNIQUE;",
        "CREATE INDEX hazard_index IF NOT EXISTS FOR (h:Hazard) ON (h.class);"
    ]
    
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            for cmd in cypher_commands:
                session.run(cmd)
                print(f"Executed: {cmd.split()[1]} {cmd.split()[2]}")
        driver.close()
        print("Neo4j successfully primed.")
    except Exception as e:
        print(f"Failed to prime Neo4j: {e}")

def prime_weaviate():
    print("--- Priming Weaviate (Schema & Vectorizer) ---")
    url = os.environ.get("WEAVIATE_URL", "http://localhost:8080")
    api_key = os.environ.get("WEAVIATE_API_KEY", "")
    
    auth_config = None
    if api_key:
        auth_config = weaviate.AuthApiKey(api_key=api_key)
        
    try:
        client = weaviate.Client(url=url, auth_client_secret=auth_config)
        
        class_name = "DocumentChunk"
        if not client.schema.exists(class_name):
            schema = {
                "class": class_name,
                "description": "A chunk of text extracted from a parsed industrial document.",
                "vectorizer": "text2vec-transformers",
                "properties": [
                    {
                        "name": "raw_text",
                        "dataType": ["text"],
                        "description": "The raw chunked text content"
                    },
                    {
                        "name": "document_title",
                        "dataType": ["text"]
                    },
                    {
                        "name": "page_number",
                        "dataType": ["int"]
                    },
                    {
                        "name": "domain_type",
                        "dataType": ["text"],
                        "description": "Domain routing tag, e.g., 'manufacturing' or 'compliance'"
                    }
                ]
            }
            client.schema.create_class(schema)
            print(f"Created Weaviate schema for class: {class_name}")
        else:
            print(f"Weaviate schema {class_name} already exists.")
            
    except Exception as e:
        print(f"Failed to prime Weaviate: {e}")

def prime_jena():
    print("--- Priming Apache Jena (Ontologies) ---")
    # Base endpoint, e.g. http://localhost:3030/ds
    import urllib.parse
    raw_url = os.environ.get("JENA_URL", "http://localhost:3030/ds/update")
    # To load data via Graph Store HTTP protocol, we usually submit to /data
    base_endpoint = raw_url.replace("/update", "/data")
    
    user = os.environ.get("JENA_USERNAME", "admin")
    password = os.environ.get("JENA_PASSWORD", "password")
    
    # 1. Download IOF Base Ontology (Placeholder URL mapping to external IOF core)
    iof_core = "https://raw.githubusercontent.com/iofoundry/ontology/master/core/Core.rdf"
    dinen = "https://raw.githubusercontent.com/hsu-aut/IndustrialStandard-ODP-DINEN62264-2/v1.4.2/DINEN62264.owl"
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    munitions_path = os.path.join(current_dir, "munitions_ontology.ttl")
    
    ontologies = [
        {"name": "IOF_Core", "source": "url", "path": iof_core},
        {"name": "DINEN62264", "source": "url", "path": dinen},
        {"name": "Munitions_Custom", "source": "file", "path": munitions_path}
    ]
    
    for ont in ontologies:
        print(f"Loading {ont['name']} into Jena...")
        turtle_data = None
        
        try:
            if ont["source"] == "url":
                resp = requests.get(ont["path"], timeout=10)
                if resp.status_code == 200:
                    turtle_data = resp.text
                else:
                    print(f"Failed to download {ont['path']} (HTTP {resp.status_code})")
                    continue
            else:
                if os.path.exists(ont["path"]):
                    with open(ont["path"], "r") as f:
                        turtle_data = f.read()
                else:
                    print(f"File not found: {ont['path']}")
                    continue
            
            # Post to Jena
            auth = (user, password) if user else None
            
            # Determine content type based on extension
            if ont["path"].endswith(".rdf") or ont["path"].endswith(".owl"):
                content_type = "application/rdf+xml"
            else:
                content_type = "text/turtle"
                
            headers = {"Content-Type": content_type}
            
            # We use 'default' graph
            post_resp = requests.post(f"{base_endpoint}?default", data=turtle_data.encode('utf-8'), headers=headers, auth=auth)
            
            if post_resp.status_code in [200, 201, 204]:
                print(f"Successfully loaded {ont['name']} into Jena.")
            else:
                print(f"Failed to load {ont['name']} into Jena. Status code: {post_resp.status_code}. Response: {post_resp.text}")
                
        except Exception as e:
            print(f"Error loading {ont['name']}: {e}")

def main():
    print("=== Starting Virigin Environment Pre-Flight Checklist ===")
    parse_env()
    
    # Add brief sleep to allow services to start if running simultaneously in a pod
    time.sleep(2)
    
    prime_neo4j()
    prime_weaviate()
    prime_jena()
    
    print("=== Pre-Flight Complete ===")

if __name__ == "__main__":
    main()
