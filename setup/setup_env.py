import os
import time
import argparse
import requests
import urllib3
from urllib.parse import urlparse
from neo4j import GraphDatabase
import weaviate

proxy_int = None

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    
    for k, v in env_vars.items():
        if k not in os.environ:
            os.environ[k] = v

def get_base_url(url):
    """Safely extracts just the scheme and host:port from a full URL."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"

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

def prime_jena():
    print("--- Priming Apache Jena (Auto-Provisioning) ---")
    
    # Configuration with safe base URL parsing
    raw_host = os.environ.get("JENA_URL", "http://localhost:3030")
    host = get_base_url(raw_host)
    ds_name = os.environ.get("JENA_DS", "ds")
    user = os.environ.get("JENA_USERNAME", "admin")
    pw = os.environ.get("JENA_PASSWORD", "password")
    auth = (user, pw)
    
    # 1. ENSURE DATASET EXISTS
    print(f"Checking for dataset /{ds_name} at {host}...")
    try:
        check = requests.get(f"{host}/$/datasets/{ds_name}", auth=auth, proxies=proxy_int, verify=False)
        if check.status_code == 404:
            print(f"  [!] Dataset /{ds_name} not found. Creating it now...")
            # Create a persistent TDB2 dataset
            create_params = {'dbName': ds_name, 'dbType': 'tdb2'}
            create_res = requests.post(f"{host}/$/datasets", data=create_params, auth=auth, proxies=proxy_int, verify=False)
            if create_res.status_code in [200, 201]:
                print(f"  [SUCCESS] Dataset /{ds_name} created.")
            else:
                print(f"  [ERROR] Could not create dataset: {create_res.status_code} {create_res.text}")
                return
        else:
            print(f"  [OK] Dataset /{ds_name} exists.")
    except Exception as e:
        print(f"  [ERROR] Connection failed: {e}")
        return

    # 2. LOAD ONTOLOGIES
    ontologies = [
        # --- LAYER A: The Foundation ---
        {"name": "IOF_Core", "path": "https://raw.githubusercontent.com/iofoundry/ontology/master/core/Core.rdf"},
        
        # --- LAYER B: The Domains (Manufacturing & Sustainment) ---
        {"name": "DINEN62264", "path": "https://raw.githubusercontent.com/hsu-aut/IndustrialStandard-ODP-DINEN62264-2/v1.4.2/DINEN62264.owl"}, 
        {"name": "IOF_MRO", "path": "https://raw.githubusercontent.com/iofoundry/ontology/master/maintenance/MaintenanceReferenceOntology.rdf"}, 
        
        # --- LAYER C: The Logistics Standards (S-Series) ---
        {"name": "S3000L", "path": "https://www.semanticstep.org/sites/default/files/2018-01/s3kl_0.ttl"}, 
        
        # --- LAYER D: Our Custom App Logic (Local Files in /setup) ---
        {"name": "MIL_Unified", "path": "setup/mil_ontology.ttl"},
        {"name": "Munitions", "path": "setup/munitions_ontology.ttl"}
    ]

    for ont in ontologies:
        print(f"Loading {ont['name']}...")
        try:
            if ont["path"].startswith("http"):
                data = requests.get(ont["path"], verify=False, timeout=15).text
            else:
                with open(ont["path"], "r") as f: data = f.read()
            
            # Content Type Logic
            c_type = "application/rdf+xml" if ont["path"].endswith((".rdf", ".owl")) else "text/turtle"
            
            # Upload using Graph Store Protocol
            res = requests.post(
                f"{host}/{ds_name}/data?default",
                data=data.encode('utf-8'),
                headers={"Content-Type": f"{c_type}; charset=utf-8"},
                auth=auth,
                verify=False
            )
            
            if res.status_code in [200, 201, 204]:
                print(f"  [SUCCESS] Loaded {ont['name']}.")
            else:
                print(f"  [FAILED] {ont['name']} Status: {res.status_code}")
        except Exception as e:
            print(f"  [ERROR] {ont['name']}: {e}")

def wipe_databases(wipe_neo4j_weaviate=True, wipe_jena=False):
    print("=== DANGER: Wiping Databases ===")
    
    if wipe_neo4j_weaviate:
        # 1. Neo4j Wipe
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USERNAME", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "password")
        try:
            driver = GraphDatabase.driver(uri, auth=(user, password))
            with driver.session() as session:
                session.run("MATCH (n) DETACH DELETE n")
            driver.close()
            print("[SUCCESS] Neo4j graph cleared.")
        except Exception as e:
            print(f"[ERROR] Failed to clear Neo4j: {e}")

        # 2. Weaviate Wipe
        weaviate_url = os.environ.get("WEAVIATE_URL", "http://localhost:8080")
        try:
            client = weaviate.Client(weaviate_url)
            client.schema.delete_all()
            print("[SUCCESS] Weaviate schemas and vectors cleared.")
        except Exception as e:
            print(f"[ERROR] Failed to clear Weaviate: {e}")

    if wipe_jena:
        # 3. Jena Wipe 
        raw_host = os.environ.get("JENA_URL", "http://localhost:3030")
        host = get_base_url(raw_host)
        ds_name = os.environ.get("JENA_DS", "ds")
        user = os.environ.get("JENA_USERNAME", "admin")
        pw = os.environ.get("JENA_PASSWORD", "password")
        
        try:
            update_query = "CLEAR ALL"
            res = requests.post(
                f"{host}/{ds_name}/update",
                data={"update": update_query},
                auth=(user, pw),
                verify=False
            )
            
            if res.status_code in [200, 204]:
                print(f"[SUCCESS] Jena dataset /{ds_name} contents cleared.")
            else:
                print(f"[ERROR] Failed to clear Jena contents: {res.status_code} {res.text}")
        except Exception as e:
            print(f"[ERROR] Failed to connect to Jena to clear data: {e}")

def main():
    parser = argparse.ArgumentParser(description="Document Tools Environment Setup")
    parser.add_argument("--wipe", action="store_true", help="Clear data from Neo4j and Weaviate (document extraction targets).")
    parser.add_argument("--wipe-jena", action="store_true", help="Clear semantic ontology data from Apache Jena.")
    args = parser.parse_args()

    parse_env()
    
    if args.wipe or args.wipe_jena:
        wipe_databases(wipe_neo4j_weaviate=args.wipe, wipe_jena=args.wipe_jena)
        return

    print("=== Starting Virgin Environment Pre-Flight Checklist ===")
    time.sleep(2)
    
    prime_neo4j()
    prime_jena()

if __name__ == "__main__":
    main()
