import os
import boto3
from dagster import asset, Config, MaterializeResult
from doc_tools.parsers.s1000d_rdf import S1000dGraphBuilder

# Placeholder for other parsers
class IadsGraphBuilder:
    def __init__(self):
        self.graph = []
    def parse_data_module(self, data):
        return "mock:iads:uri"
    def serialize(self, format="turtle"):
        return "# Mock IADS Turtle Output"

class XmlIngestConfig(Config):
    s3_bucket: str
    s3_key: str

from doc_tools.utils.dagster_resources import MinioResource

@asset
def extract_rdf_from_xml(context, config: XmlIngestConfig, minio: MinioResource) -> str:
    """
    Universal XML to RDF extractor. Routes to specific parsers based on the 
    S3 directory prefix and processes files entirely in-memory.
    """
    s3_client = minio.get_client()

    context.log.info(f"Fetching XML from s3://{config.s3_bucket}/{config.s3_key} into memory...")
    
    response = None
    try:
        # MinioResource returns the client directly, so we use it as is
        response = s3_client.get_object(config.s3_bucket, config.s3_key)
        xml_bytes = response.read()
    except Exception as e:
        context.log.error(f"Failed to fetch file from MinIO: {e}")
        raise e
    finally:
        if response:
            try:
                response.close()
                response.release_conn() # Crucial for K8s connection pooling
            except Exception:
                pass

    # Routing Logic: Use the root directory name from the s3_key
    doc_type = config.s3_key.split('/')[0].lower()
    
    PARSERS = {
        's1000d': S1000dGraphBuilder,
        'iads': IadsGraphBuilder
    }

    if doc_type not in PARSERS:
        context.log.error(f"No parser registered for directory type: {doc_type}")
        raise ValueError(f"Unsupported doc_type: {doc_type}")

    context.log.info(f"Routing to {PARSERS[doc_type].__name__} for doc_type: {doc_type}")
    builder = PARSERS[doc_type]()
    
    # Parse the in-memory bytes
    builder.parse_data_module(xml_bytes)
    
    # Return the serialized RDF string directly for in-memory passing (K8s safe)
    rdf_string = builder.serialize(format="turtle")
    context.log.info("RDF serialized to string successfully.")
    
    return rdf_string
