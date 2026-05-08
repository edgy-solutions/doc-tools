import os
import httpx
import rdflib
import weaviate.classes as wvc
from weaviate.util import generate_uuid5
from dagster import asset, AssetExecutionContext, MaterializeResult
from dagster_aws.s3 import S3Resource
from doc_tools.utils.dagster_resources import JenaResource
from dag_tools.components.s3_sensor.file_component import S3FileConfig
from doc_tools.partitions import ontology_partitions
from doc_tools.utils.weaviate_client import get_weaviate_client

def sync_ontology_to_weaviate(extracted_classes: list[dict], domain: str, context: AssetExecutionContext):
    """
    Takes parsed ontology classes (from rdflib/Jena) and dual-writes them to Weaviate.
    extracted_classes should be a list of dicts: {"uri": str, "label": str, "definition": str}
    """
    # 🔗 Use the Fleet-Standard Connection Strategy
    client = get_weaviate_client()
    
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
        context.log.info(f"Syncing {len(extracted_classes)} classes to Weaviate for domain {domain}...")
        
        # Batch insert for high performance (Idempotent Upsert)
        with collection.batch.dynamic() as batch:
            for cls in extracted_classes:
                # Use the URI to generate a deterministic UUID
                deterministic_uuid = generate_uuid5(str(cls["uri"]))
                
                safe_label = str(cls["label"]) if cls.get("label") else str(cls["uri"]).split("#")[-1].split("/")[-1]
                safe_definition = str(cls["definition"]) if cls.get("definition") else "No definition provided."

                batch.add_object(
                    properties={
                        "uri": str(cls["uri"]),
                        "label": safe_label,
                        "definition": safe_definition,
                        "domain": domain.upper()
                    },
                    uuid=deterministic_uuid
                )
                
        context.log.info("Weaviate sync complete.")
        
    finally:
        # Crucial for Dagster: cleanly close the tunnel when the asset finishes
        client.close()

@asset(partitions_def=ontology_partitions)
def ingest_ontology_to_jena(context: AssetExecutionContext, config: S3FileConfig, s3: S3Resource, jena: JenaResource) -> MaterializeResult:
    """
    Detects RDF files in MinIO (via sensor partition) and pushes them to Jena Named Graphs.
    s3://ontologies/{domain}/{file} -> http://internal/{domain}
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
        raise Exception(f"Invalid ontology path: {obj_key}. Expected '{domain}/{filename}'")
    
    domain = parts[0]
    filename = parts[-1]
    
    # Derive Named Graph URI
    graph_uri = f"http://internal/{domain}"
    
    s3_client = s3.get_client()
    context.log.info(f"Ingesting ontology '{filename}' for domain '{domain}' into graph <{graph_uri}>")
    
    # 1. Download from MinIO
    # We'll assume the 'ontologies' bucket as per instructions
    bucket = os.getenv("ONTOLOGY_BUCKET", "ontologies")
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

    # 3. Push to Jena using Graph Store Protocol (PUT)
    # Using PUT ensures we overwrite the previous revision of this domain's ontology
    jena_base = jena.url.rstrip('/')
    jena_ds = jena.dataset
    user = jena.username
    pw = jena.password
    
    # GSP endpoint: {host}/{dataset}/data
    target_url = f"{jena_base}/{jena_ds}/data?graph={graph_uri}"
    
    try:
        with httpx.Client(auth=(user, pw), verify=False) as client:
            resp = client.put(
                target_url,
                content=rdf_content,
                headers={"Content-Type": content_type}
            )
            resp.raise_for_status()
            context.log.info(f"Successfully pushed to Jena Named Graph: {graph_uri}")
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
