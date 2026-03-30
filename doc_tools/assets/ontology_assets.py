import os
import httpx
import rdflib
from dagster import asset, AssetExecutionContext, MaterializeResult, DynamicPartitionsDefinition
from doc_tools.utils.dagster_resources import MinioResource, JenaResource

ontology_partitions = DynamicPartitionsDefinition(name="ontology_files")

@asset(partitions_def=ontology_partitions)
def ingest_ontology_to_jena(context: AssetExecutionContext, minio: MinioResource, jena: JenaResource) -> MaterializeResult:
    """
    Detects RDF files in MinIO (via sensor partition) and pushes them to Jena Named Graphs.
    s3://ontologies/{domain}/{file} -> http://internal/{domain}
    """
    # The partition key is the full object path: {domain}/{filename}
    partition_key = context.partition_key
    parts = partition_key.split('/')
    
    if len(parts) < 2:
        raise Exception(f"Invalid ontology path: {partition_key}. Expected '{{domain}}/{{filename}}'")
    
    domain = parts[0]
    filename = parts[1]
    
    # Derive Named Graph URI
    graph_uri = f"http://internal/{domain}"
    
    minio_client = minio.get_client()
    context.log.info(f"Ingesting ontology '{filename}' for domain '{domain}' into graph <{graph_uri}>")
    
    # 1. Download from MinIO
    # We'll assume the 'ontologies' bucket as per instructions
    bucket = os.getenv("ONTOLOGY_BUCKET", "ontologies")
    try:
        response = minio_client.get_object(bucket, partition_key)
        rdf_content = response.read()
        response.close()
        response.release_conn()
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
        context.log.error(f"Syntax validation failed for {partition_key}: {e}")
        raise e

    # 3. Push to Jena using Graph Store Protocol (PUT)
    # Using PUT ensures we overwrite the previous revision of this domain's ontology
    jena_url = os.getenv("JENA_GSP_ENDPOINT", "http://fuseki:3030/ds/data")
    user = os.getenv("JENA_USERNAME", "admin")
    pw = os.getenv("JENA_PASSWORD", "password")
    
    target_url = f"{jena_url}?graph={graph_uri}"
    
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

    return MaterializeResult(
        metadata={
            "domain": domain,
            "graph_uri": graph_uri,
            "triples": len(g),
            "s3_path": f"s3://{bucket}/{partition_key}"
        }
    )
