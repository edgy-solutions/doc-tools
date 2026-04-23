import os
import boto3
from dagster import asset, Config, MaterializeResult
from doc_tools.parsers.s1000d_rdf import S1000dGraphBuilder
from doc_tools.parsers.dita_rdf import DitaGraphBuilder
from doc_tools.parsers.iads_rdf import IadsGraphBuilder
from doc_tools.parsers.mil_std_40051_rdf import MilStd40051GraphBuilder

class XmlIngestConfig(Config):
    s3_bucket: str
    s3_key: str

from dagster_aws.s3 import S3Resource

@asset
def extract_rdf_from_xml(context, config: XmlIngestConfig, s3: S3Resource) -> dict:
    """
    Universal XML to RDF extractor. Routes to specific parsers based on the 
    S3 directory prefix and processes files entirely in-memory.
    """
    s3_client = s3.get_client()

    context.log.info(f"Fetching XML from s3://{config.s3_bucket}/{config.s3_key} into memory...")
    
    response = None
    try:
        response = s3_client.get_object(Bucket=config.s3_bucket, Key=config.s3_key)
        xml_bytes = response['Body'].read()
    except Exception as e:
        context.log.error(f"Failed to fetch file from S3: {e}")
        raise e
    finally:
        if response:
            try:
                response['Body'].close()
            except Exception:
                pass

    # Routing Logic: Use the root directory name from the s3_key
    doc_type = config.s3_key.split('/')[0].lower()
    
    PARSERS = {
        's1000d': S1000dGraphBuilder,
        'iads': IadsGraphBuilder,
        'dita': DitaGraphBuilder,
        '40051': MilStd40051GraphBuilder
    }

    if doc_type not in PARSERS:
        context.log.error(f"No parser registered for directory type: {doc_type}")
        raise ValueError(f"Unsupported doc_type: {doc_type}")

    context.log.info(f"Routing to {PARSERS[doc_type].__name__} for doc_type: {doc_type}")
    
    # Derive doc_id from s3_key (e.g., "s1000d/manual_v2.xml" -> "manual_v2")
    import os
    filename = os.path.basename(config.s3_key)
    doc_id = os.path.splitext(filename)[0]
    base_dir = os.path.dirname(config.s3_key) or "unknown"
    base_name = filename.replace('.', '_')
    image_prefix = f"s3://{config.s3_bucket}/{base_dir}/generated/{base_name}/images/"
    
    builder = PARSERS[doc_type](bucket=config.s3_bucket, doc_id=doc_id, image_prefix=image_prefix)
    
    # Parse the in-memory bytes and capture the root URI
    root_uri = builder.parse_data_module(xml_bytes)
    
    # Return the serialized RDF string directly for in-memory passing (K8s safe)
    rdf_string = builder.serialize(format="turtle")
    context.log.info(f"RDF serialized to string successfully. Root URI: {root_uri}")

    
    return {
        "rdf_string": rdf_string,
        "root_uri": root_uri,
        "s3_key": config.s3_key
    }
