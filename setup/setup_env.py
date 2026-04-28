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
        "CREATE INDEX hazard_index IF NOT EXISTS FOR (h:Hazard) ON (h.class);",
        "CREATE CONSTRAINT figure_id_unique IF NOT EXISTS FOR (f:Figure) REQUIRE f.id IS UNIQUE;"
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

def prime_ontologies():
    print("--- Priming Ontologies (S3-Based Ingestion) ---")
    
    # 1. UPLOAD ONTOLOGIES TO MINIO (Mediated Ingestion)
    print("--- Uploading Ontologies to MinIO for Automated Ingestion ---")
    
    # MinIO Client Init
    from minio import Minio
    s3_url = os.environ.get("S3_ENDPOINT_URL", "localhost:9000")
    if s3_url.startswith("http://"): s3_url = s3_url[len("http://"):]
    elif s3_url.startswith("https://"): s3_url = s3_url[len("https://"):]
    
    minio_client = Minio(
        s3_url,
        access_key=os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin"),
        secret_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "minioadmin"),
        secure=os.environ.get("MINIO_SECURE", "false").lower() == "true"
    )
    
    bucket = os.environ.get("ONTOLOGY_BUCKET", "ontologies")
    if not minio_client.bucket_exists(bucket):
        minio_client.make_bucket(bucket)
        print(f"Created bucket: {bucket}")

    ontologies = [
        # =================================================================
        # LAYER 1: MAINTENANCE (Engine O maps to http://internal/mro)
        # =================================================================
        # Foundation required for MRO reasoning
        {"domain": "mro", "name": "IOF_Core", "path": "https://raw.githubusercontent.com/iofoundry/ontology/master/core/Core.rdf"},
        
        # Specific MRO Ontologies
        {"domain": "mro", "name": "DINEN62264", "path": "https://raw.githubusercontent.com/hsu-aut/IndustrialStandard-ODP-DINEN62264-2/v1.4.2/DINEN62264.owl"}, 
        {"domain": "mro", "name": "IOF_MRO", "path": "https://raw.githubusercontent.com/iofoundry/ontology/master/maintenance/Maintenance.rdf"}, 
        {"domain": "mro", "name": "MIL_Unified", "path": "setup/mil_ontology.ttl"},
        {"domain": "mro", "name": "Munitions", "path": "setup/munitions_ontology.ttl"},
        
        # =================================================================
        # LAYER 2: SUSTAINMENT (Engine O maps to http://internal/sustainment)
        # =================================================================
        # Foundation required for physical logistics reasoning
        {"domain": "sustainment", "name": "IOF_Core", "path": "https://raw.githubusercontent.com/iofoundry/ontology/master/core/Core.rdf"},
        
        # Specific Logistics Ontologies
        {"domain": "sustainment", "name": "S3000L", "path": "https://www.semanticstep.org/sites/default/files/2018-01/s3kl_0.ttl"}, 
        {"domain": "sustainment", "name": "PCN_PDN_Extension", "path": "setup/sustainment_extension.ttl"}, 
        
        # =================================================================
        # LAYER 3: DATA ENGINEERING (Engine O maps to http://internal/idp)
        # =================================================================
        # Notice: NO IOF_Core here. Strictly digital/software foundation.
        {"domain": "idp", "name": "PROV-O", "path": "https://www.w3.org/ns/prov-o.ttl"}, 
    ]

    import io
    for ont in ontologies:
        print(f"Processing {ont['name']} for domain {ont['domain']}...")
        try:
            if ont["path"].startswith("http"):
                data = requests.get(ont["path"], verify=False, timeout=15).content
            else:
                with open(ont["path"], "rb") as f: data = f.read()
            
            # Use domain as directory as per requirements
            file_ext = ".rdf" if ont["path"].endswith((".rdf", ".owl")) else ".ttl"
            obj_name = f"{ont['domain']}/{ont['name']}{file_ext}"
            
            # Put to MinIO
            minio_client.put_object(
                bucket,
                obj_name,
                io.BytesIO(data),
                length=len(data),
                content_type="application/octet-stream"
            )
            print(f"  [SUCCESS] Uploaded {ont['name']} to s3://{bucket}/{obj_name}")
            
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
    prime_ontologies()

if __name__ == "__main__":
    main()
