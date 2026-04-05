from dagster import Definitions, load_assets_from_modules, AssetSelection, define_asset_job, EnvVar
from dagster_aws.s3 import S3Resource, s3_pickle_io_manager
from dag_tools import S3SensorComponent
from doc_tools.components.document_parser import DocumentParserComponent
from doc_tools.components.sqlserver_extractor import SqlServerExtractorComponent
from doc_tools.components.oracle_extractor import OracleExtractorComponent
from doc_tools.components.design_parser import DesignParserComponent
from doc_tools.components.datahub_sensor import DataHubSensorComponent
from doc_tools.assets import semantic_assets, xml_ingestion, ontology_assets, semantic_linker
from doc_tools.utils.dagster_resources import Neo4jResource, WeaviateResource, LLMExtractorResource, JenaResource
from doc_tools.partitions import ontology_partitions, design_files_partition
import os

# 1. Instantiate the Custom Parser Component
document_parser = DocumentParserComponent(
    name="process_document_artifact",
    partition_name="pdf_files",
    config={
        "graph_node_label": "WorkInstruction",
        "graph_child_label": "Page",
        "vector_collection_name": "DocumentChunk",
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

design_sensor = S3SensorComponent(
    bucket=os.getenv("DESIGN_BUCKET", "design-artifacts"),
    prefix="",
    partition_name="design_files",
    target_job="parse_design_metadata_job",
    target_op="parse_design_metadata",
    filter_patterns=[],
    s3_resource={
        "endpoint_url": EnvVar("S3_ENDPOINT_URL"),
        "aws_access_key_id": EnvVar("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": EnvVar("AWS_SECRET_ACCESS_KEY"),
        "use_ssl": os.getenv("MINIO_SECURE", "false").lower() == "true",
        "verify": False
    }
)
design_sensor_defs = design_sensor.build_defs(None)

design_parser = DesignParserComponent(
    name="parse_design_metadata"
)
design_parser_defs = design_parser.build_defs(None)

datahub_sensor = DataHubSensorComponent(
    name="datahub_approval_sensor",
    datahub_gms_url=os.getenv("DATAHUB_GMS_URL", "http://datahub-gms:8080/api/graphql"),
    datahub_token=os.getenv("DATAHUB_TOKEN", "")
)
datahub_sensor_defs = datahub_sensor.build_defs(None)

# 3. Assets & Jobs
all_assets = load_assets_from_modules([semantic_assets, xml_ingestion, ontology_assets, semantic_linker])

sqlserver_extractor = SqlServerExtractorComponent(
    name="extract_sqlserver_metadata",
    domain="DATA_ENGINEERING",
    host=os.getenv("SQLSERVER_HOST", "localhost"),
    port=int(os.getenv("SQLSERVER_PORT", "1433")),
    database=os.getenv("SQLSERVER_DATABASE", "master"),
    username=os.getenv("SQLSERVER_USERNAME", "sa"),
    password=os.getenv("SQLSERVER_PASSWORD", "password"),
    driver=os.getenv("SQLSERVER_DRIVER", "ODBC Driver 18 for SQL Server"),
    trust_server_certificate=os.getenv("SQLSERVER_TRUST_CERT", "true").lower() == "true"
)
sqlserver_extractor_defs = sqlserver_extractor.build_defs(None)

oracle_extractor = OracleExtractorComponent(
    name="extract_oracle_metadata",
    domain="DATA_ENGINEERING",
    host=os.getenv("ORACLE_HOST", "localhost"),
    port=int(os.getenv("ORACLE_PORT", "1521")),
    service_name=os.getenv("ORACLE_SERVICE_NAME", "ORCL"),
    username=os.getenv("ORACLE_USERNAME", "system"),
    password=os.getenv("ORACLE_PASSWORD", "password")
)
oracle_extractor_defs = oracle_extractor.build_defs(None)

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

design_metadata_job = define_asset_job(
    name="parse_design_metadata_job",
    selection=["parse_design_metadata"],
    partitions_def=design_files_partition,
    tags=k8s_tags
)

s3_io_manager = s3_pickle_io_manager.configured({
    "s3_bucket": os.getenv("DAGSTER_STORAGE_BUCKET", "processing-artifacts"),
    "s3_prefix": "dagster-artifacts"
})

defs = Definitions(
    assets=list(document_parser_defs.assets) + list(sqlserver_extractor_defs.assets) + list(oracle_extractor_defs.assets) + list(design_parser_defs.assets) + list(datahub_sensor_defs.assets) + all_assets,
    jobs=list(document_parser_defs.jobs) + list(datahub_sensor_defs.jobs) + [xml_graph_sync_job, ingest_ontology_job, design_metadata_job],
    sensors=list(pdf_sensor_defs.sensors) + list(ontology_sensor_defs.sensors) + list(design_sensor_defs.sensors) + list(datahub_sensor_defs.sensors),
    resources={
        "io_manager": s3_io_manager,
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
        **design_sensor_defs.resources,
    },
)
