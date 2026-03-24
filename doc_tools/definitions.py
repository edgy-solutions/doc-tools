from dagster import Definitions, load_assets_from_modules, AssetSelection, define_asset_job, EnvVar
from dag_tools import S3SensorComponent, S3ToFileComponent

from doc_tools.assets import ingestion_assets, semantic_assets, xml_ingestion, ontology_assets
from doc_tools.utils.dagster_resources import MinioResource, Neo4jResource, WeaviateResource, LLMExtractorResource, JenaResource
import os

# 1. Instantiate Ingestion Components (declarative replaces config.yaml)
pdf_ingest = S3ToFileComponent(
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

# 2. Instantiate Sensors (decoupled from assets)
pdf_sensor = S3SensorComponent(
    bucket="processing-artifacts",
    prefix="manufacturing/IID/",
    partition_name="pdf_files",
    target_job=pdf_ingest.job_name,
    target_op=pdf_ingest.op_name,
    filter_patterns=["archive/", "metadata.json"]
)

# Added value: migrated the recently added ontology sensor to the new component model
ontology_sensor = S3SensorComponent(
    bucket=os.getenv("ONTOLOGY_BUCKET", "ontologies"),
    prefix="",
    partition_name="ontology_files",
    target_job="ingest_ontology_job",
    target_op="ingest_ontology_to_jena",
    filter_patterns=[]
)

# 3. Assets & Jobs
# We exclude ingestion_assets.process_document_artifact to avoid name collision with the component's asset
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
    tags=k8s_tags
)

defs = Definitions(
    assets=pdf_ingest.assets + all_assets,
    jobs=[pdf_ingest.job, xml_graph_sync_job, ingest_ontology_job],
    sensors=[pdf_sensor.sensor, ontology_sensor.sensor],
    resources={
        "minio": MinioResource(
            endpoint_url=EnvVar("S3_ENDPOINT_URL"),
            access_key=EnvVar("AWS_ACCESS_KEY_ID"),
            secret_key=EnvVar("AWS_SECRET_ACCESS_KEY"),
            secure=os.getenv("MINIO_SECURE", "false").lower() == "true"
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
            username=EnvVar("JENA_USERNAME"),
            password=EnvVar("JENA_PASSWORD")
        )
    },
)
