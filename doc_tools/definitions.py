from dagster import Definitions, load_assets_from_modules, AssetSelection, define_asset_job, EnvVar
from dagster_aws.s3 import S3Resource
from dag_tools import S3SensorComponent
from doc_tools.components.document_parser import DocumentParserComponent
from doc_tools.assets import semantic_assets, xml_ingestion, ontology_assets
from doc_tools.utils.dagster_resources import Neo4jResource, WeaviateResource, LLMExtractorResource, JenaResource
from doc_tools.partitions import ontology_partitions
import os

# 1. Instantiate the Custom Parser Component
document_parser = DocumentParserComponent(
    name="process_document_artifact",
    partition_name="pdf_files",
    config={
        "graph_node_label": "WorkInstruction",
        "graph_child_label": "Page",
        "vector_collection_name": "ManufacturingDocumentChunk",
        "procedure_id_format": r"^\d{4}$",
        "step_id_format": r"^\d+(?:\.\d+)*$",
        "valid_personnel_roles": "QC Inspector, Journeyman, Safety Officer",
        "valid_hazard_classes": "1.1D, 1.3C, Hazmat 3, Biohazard",
        "valid_process_categories": "Transformation, Inspection, Movement, Rework, Critical Safety Hold",
        "bucket": "processing-artifacts"
    }
)
document_parser_defs = document_parser.build_defs(None)

# 2. Instantiate Sensors (decoupled from assets)
pdf_sensor = S3SensorComponent(
    bucket="processing-artifacts",
    prefix="manufacturing/IID/",
    partition_name="pdf_files",
    target_job=f"{document_parser.name}_job",
    target_op=document_parser.name,
    filter_patterns=["archive/", "metadata.json"],
    s3_resource={
        "endpoint_url": EnvVar("S3_ENDPOINT_URL"),
        "aws_access_key_id": EnvVar("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": EnvVar("AWS_SECRET_ACCESS_KEY"),
        "use_ssl": os.getenv("MINIO_SECURE", "false").lower() == "true",
        "verify": False
    }
)
pdf_sensor_defs = pdf_sensor.build_defs(None)

ontology_sensor = S3SensorComponent(
    bucket=os.getenv("ONTOLOGY_BUCKET", "ontologies"),
    prefix="",
    partition_name="ontology_files",
    target_job="ingest_ontology_job",
    target_op="ingest_ontology_to_jena",
    filter_patterns=[],
    s3_resource={
        "endpoint_url": EnvVar("S3_ENDPOINT_URL"),
        "aws_access_key_id": EnvVar("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": EnvVar("AWS_SECRET_ACCESS_KEY"),
        "use_ssl": os.getenv("MINIO_SECURE", "false").lower() == "true",
        "verify": False
    }
)
ontology_sensor_defs = ontology_sensor.build_defs(None)

# 3. Assets & Jobs
all_assets = load_assets_from_modules([semantic_assets, xml_ingestion, ontology_assets])

k8s_tags = {
    "dagster-k8s/config": {
        "container_config": {
            "resources": {
                "requests": {"cpu": "2000m", "memory": "6Gi"},
                "limits": {"cpu": "4000m", "memory": "12Gi"}
            }
        }
    }
}

xml_graph_sync_job = define_asset_job(
    name="xml_graph_sync_job",
    selection=["extract_rdf_from_xml", "upload_to_jena", "init_neo4j_n10s", "sync_jena_to_neo4j"],
    tags=k8s_tags
)

ingest_ontology_job = define_asset_job(
    name="ingest_ontology_job",
    selection=["ingest_ontology_to_jena"],
    partitions_def=ontology_partitions,
    tags=k8s_tags
)

defs = Definitions(
    assets=list(document_parser_defs.assets) + all_assets,
    jobs=list(document_parser_defs.jobs) + [xml_graph_sync_job, ingest_ontology_job],
    sensors=list(pdf_sensor_defs.sensors) + list(ontology_sensor_defs.sensors),
    resources={
        "s3": S3Resource(
            endpoint_url=EnvVar("S3_ENDPOINT_URL"),
            aws_access_key_id=EnvVar("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=EnvVar("AWS_SECRET_ACCESS_KEY"),
        ),
        "neo4j": Neo4jResource(
            uri=EnvVar("NEO4J_URI"),
            username=EnvVar("NEO4J_USERNAME"),
            password=EnvVar("NEO4J_PASSWORD")
        ),
        "weaviate": WeaviateResource(
            url=EnvVar("WEAVIATE_URL")
        ),
        "llm": LLMExtractorResource(),
        "jena": JenaResource(
            url=EnvVar("JENA_URL"),
            dataset=EnvVar("JENA_DS"),
            username=EnvVar("JENA_USERNAME"),
            password=EnvVar("JENA_PASSWORD")
        ),
        **pdf_sensor_defs.resources,
        **ontology_sensor_defs.resources,
    },
)
