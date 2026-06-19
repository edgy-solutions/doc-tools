from dagster import Definitions, load_assets_from_modules, AssetSelection, define_asset_job, EnvVar
from dagster_aws.s3 import S3Resource, s3_pickle_io_manager
from dag_tools import S3SensorComponent
from doc_tools.components.document_parser import DocumentParserComponent
from doc_tools.components.sqlserver_extractor import SqlServerExtractorComponent
from doc_tools.components.oracle_extractor import OracleExtractorComponent
from doc_tools.components.design_parser import DesignParserComponent
from doc_tools.components.datahub_sensor import DataHubSensorComponent
from doc_tools.components.aitool_sensor import AIToolSensorComponent
from doc_tools.assets import semantic_assets, xml_ingestion, ontology_assets, semantic_linker, dds_ingestion, rabbitmq_ingestion, global_semantic_ingestion, aitool_linker, global_aitool_ingestion
from doc_tools.utils.dagster_resources import Neo4jResource, WeaviateResource, LLMExtractorResource, JenaResource
from doc_tools.partitions import ontology_partitions, design_files_partition
import os
from dag_tools.utils.k8s import resolve_k8s_resource_tags

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
_document_parser_defs = document_parser.build_defs(None)

# 2. Instantiate Sensors (decoupled from assets)
pdf_sensor = S3SensorComponent(
    bucket="processing-artifacts",
    prefix="manufacturing/inbound/",
    partition_name="pdf_files",
    target_job=f"{document_parser.name}_job",
    target_op=document_parser.name,
    filter_patterns=["archive/", "metadata.json", "generated/"],
    s3_resource={
        "endpoint_url": EnvVar("S3_ENDPOINT_URL"),
        "aws_access_key_id": EnvVar("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": EnvVar("AWS_SECRET_ACCESS_KEY"),
        "use_ssl": os.getenv("MINIO_SECURE", "false").lower() == "true",
        "verify": False
    }
)
_pdf_sensor_defs = pdf_sensor.build_defs(None)

sustainment_sensor = S3SensorComponent(
    name="sustainment_sensor",
    bucket="processing-artifacts",
    prefix="sustainment/inbound/",
    partition_name="pdf_files",
    target_job=f"{document_parser.name}_job",
    target_op=document_parser.name,
    filter_patterns=["archive/", "metadata.json", "generated/"],
    s3_resource={
        "endpoint_url": EnvVar("S3_ENDPOINT_URL"),
        "aws_access_key_id": EnvVar("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": EnvVar("AWS_SECRET_ACCESS_KEY"),
        "use_ssl": os.getenv("MINIO_SECURE", "false").lower() == "true",
        "verify": False
    }
)
_sustainment_sensor_defs = sustainment_sensor.build_defs(None)

ontology_sensor = S3SensorComponent(
    name="ontology_sensor",
    bucket=os.getenv("ONTOLOGY_BUCKET", "ontologies"),
    prefix="",
    partition_name="ontology_files",
    target_job="ingest_ontology_job",
    target_op="ingest_ontology_to_jena",
    # ingest_ontology_job's selection includes BOTH ops, and both require
    # the same S3FileConfig (file_url). Without listing the second op
    # here the sensor-triggered run fails config validation with
    # "Missing required config entry sync_jena_ontologies_to_neo4j at
    # path root:ops". prime_databases.py's --trigger-ingest provides
    # both ops' config explicitly via GraphQL; this aligns the sensor
    # path with that. See dag-tools S3SensorComponent additional_target_ops.
    additional_target_ops=["sync_jena_ontologies_to_neo4j"],
    filter_patterns=[],
    s3_resource={
        "endpoint_url": EnvVar("S3_ENDPOINT_URL"),
        "aws_access_key_id": EnvVar("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": EnvVar("AWS_SECRET_ACCESS_KEY"),
        "use_ssl": os.getenv("MINIO_SECURE", "false").lower() == "true",
        "verify": False
    }
)
_ontology_sensor_defs = ontology_sensor.build_defs(None)

design_sensor = S3SensorComponent(
    name="design_sensor",
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
_design_sensor_defs = design_sensor.build_defs(None)

design_parser = DesignParserComponent(
    name="parse_design_metadata"
)
_design_parser_defs = design_parser.build_defs(None)

datahub_sensor = DataHubSensorComponent(
    name="datahub_approval_sensor",
    datahub_gms_url=os.getenv("DATAHUB_GMS_URL", "http://datahub-gms:8080/api/graphql"),
    datahub_token=os.getenv("DATAHUB_TOKEN", "")
)
_datahub_sensor_defs = datahub_sensor.build_defs(None)

# AITool binding plane — RETIRED 2026-06-13 per ADR-0006 §Addendum.
#
# Gateway v0.2 (agent_fleet/mesh_registrar) is now sole writer of AITool
# predicate edges into Neo4j + Weaviate. The sensor's role was to poll
# DataHub for mesh_is_registration=true MCPs and materialize them; v0.2
# does that synchronously in the request path with bounded forward-retry
# + saga compensation, eliminating the sync-gap window the sensor's
# run-key dedup + allowlist drift bug classes lived in.
#
# Why DEACTIVATED, not deleted:
#   - The component, asset (sync_aitool_predicate_to_neo4j), and helper
#     functions in doc_tools/assets/aitool_linker.py stay in the
#     codebase so a one-off manual re-sync of a specific tool_urn is
#     still possible via Dagster's launchpad (the asset takes a
#     tool_urn config and is idempotent). It just isn't triggered by
#     a sensor anymore.
#   - Rollback is a one-line revert: re-add the sensor block to
#     Definitions() below if v0.2 needs to be turned off in an
#     emergency. Until that happens, AITool MCPs in DataHub are
#     audit-trail records, not materialization triggers.
#   - The Dataset sync sensor (datahub_sensor) is UNCHANGED — it
#     operates on glossary terms / Dataset HAS_DATA edges, which v0.2
#     explicitly does not touch (ADR-0006 §Addendum §Scope guardrails).
#
# A short-window race during cutover is the only failure mode this
# transition introduces — see ADR-0006 §Addendum §Cutover. The mitigation
# in that section is: the conjunctive-read invariant makes any
# half-written state unrouted, so even if the sensor fires once during
# the rollout window with allowlist-drift'd properties, the resulting
# edge is unrouted until v0.2 re-registers it cleanly.
#
# aitool_sensor = AIToolSensorComponent(
#     name="aitool_registration_sensor",
#     datahub_gms_url=os.getenv("DATAHUB_GMS_URL", "http://datahub-gms:8080/api/graphql"),
#     datahub_token=os.getenv("DATAHUB_TOKEN", "")
# )
# _aitool_sensor_defs = aitool_sensor.build_defs(None)

# 3. Assets & Jobs
all_assets = load_assets_from_modules([semantic_assets, xml_ingestion, ontology_assets, semantic_linker, dds_ingestion, rabbitmq_ingestion, global_semantic_ingestion, aitool_linker, global_aitool_ingestion])

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
_sqlserver_extractor_defs = sqlserver_extractor.build_defs(None)

oracle_extractor = OracleExtractorComponent(
    name="extract_oracle_metadata",
    domain="DATA_ENGINEERING",
    host=os.getenv("ORACLE_HOST", "localhost"),
    port=int(os.getenv("ORACLE_PORT", "1521")),
    service_name=os.getenv("ORACLE_SERVICE_NAME", "ORCL"),
    username=os.getenv("ORACLE_USERNAME", "system"),
    password=os.getenv("ORACLE_PASSWORD", "password")
)
_oracle_extractor_defs = oracle_extractor.build_defs(None)

# 3. Dynamic K8s Resource Management
# Resolve tags using different prefixes for resource control
xml_k8s_tags = resolve_k8s_resource_tags(prefix="XML_INGEST", default_cpu="2000m", default_mem="6Gi")
ontology_k8s_tags = resolve_k8s_resource_tags(prefix="ONTOLOGY_INGEST", default_cpu="1000m", default_mem="2Gi")
design_k8s_tags = resolve_k8s_resource_tags(prefix="DESIGN_PARSER", default_cpu="1000m", default_mem="2Gi")

xml_graph_sync_job = define_asset_job(
    name="xml_graph_sync_job",
    selection=["extract_rdf_from_xml", "upload_to_jena", "init_neo4j_n10s", "sync_jena_to_neo4j"],
    tags=xml_k8s_tags
)

ingest_ontology_job = define_asset_job(
    name="ingest_ontology_job",
    # Option 3 fix (2026-06-12): include sync_jena_ontologies_to_neo4j so
    # TTL ingests propagate to Neo4j's OntologyClass graph in the same
    # job. Without this, the Session-1 DAG-wiring break stays open and
    # canonical classes never reach the runtime graph the resolver reads.
    selection=["ingest_ontology_to_jena", "sync_jena_ontologies_to_neo4j"],
    tags=ontology_k8s_tags
)

design_metadata_job = define_asset_job(
    name="parse_design_metadata_job",
    selection=["parse_design_metadata"],
    tags=design_k8s_tags
)

s3_io_manager = s3_pickle_io_manager.configured({
    "s3_bucket": os.getenv("DAGSTER_STORAGE_BUCKET", "processing-artifacts"),
    "s3_prefix": "dagster-artifacts"
})

defs = Definitions(
    # AITool sensor RETIRED 2026-06-13 per ADR-0006 §Addendum — the
    # gateway v0.2 saga is now sole writer of AITool predicate edges.
    # The aitool_linker module (with sync_aitool_predicate_to_neo4j)
    # is loaded via all_assets so the asset is still callable for
    # one-off manual syncs through the Dagster launchpad. The SENSOR
    # is what's gone — no automatic polling of DataHub for mlModel MCPs.
    assets=list(_document_parser_defs.assets) + list(_sqlserver_extractor_defs.assets) + list(_oracle_extractor_defs.assets) + list(_design_parser_defs.assets) + list(_datahub_sensor_defs.assets) + all_assets,
    jobs=list(_document_parser_defs.jobs) + list(_datahub_sensor_defs.jobs) + [xml_graph_sync_job, ingest_ontology_job, design_metadata_job],
    sensors=list(_pdf_sensor_defs.sensors) + list(_sustainment_sensor_defs.sensors) + list(_ontology_sensor_defs.sensors) + list(_design_sensor_defs.sensors) + list(_datahub_sensor_defs.sensors),
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
            http_host=EnvVar("WEAVIATE_HTTP_HOST"),
            grpc_host=EnvVar("WEAVIATE_GRPC_HOST")
        ),
        "llm": LLMExtractorResource(
            langfuse_public_key=EnvVar("LANGFUSE_PUBLIC_KEY"),
            langfuse_secret_key=EnvVar("LANGFUSE_SECRET_KEY"),
            langfuse_host=EnvVar("LANGFUSE_HOST")
        ),
        "jena": JenaResource(
            url=EnvVar("JENA_URL"),
            dataset=EnvVar("JENA_DS"),
            username=EnvVar("JENA_USERNAME"),
            password=EnvVar("JENA_PASSWORD")
        ),
        **_pdf_sensor_defs.resources,
        **_sustainment_sensor_defs.resources,
        **_ontology_sensor_defs.resources,
        **_design_sensor_defs.resources,
    },
)

del _document_parser_defs
del _pdf_sensor_defs
del _sustainment_sensor_defs
del _ontology_sensor_defs
del _design_sensor_defs
del _design_parser_defs
del _datahub_sensor_defs
# del _aitool_sensor_defs  # RETIRED 2026-06-13 — gateway v0.2 is sole writer; see ADR-0006 §Addendum
del _sqlserver_extractor_defs
del _oracle_extractor_defs
