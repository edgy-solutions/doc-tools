import os
import glob
import base64
import tempfile
import subprocess
from dagster import asset, MaterializeResult, Config, get_dagster_logger
from datahub.emitter.rest_emitter import DatahubRestEmitter
from doc_tools.ingestion.json_schema_parser import JSONSchemaParser
from doc_tools.ingestion.datahub_emitter import DDSToDataHubEmitter
from dag_tools.utils.k8s import resolve_k8s_resource_tags

metadata_k8s_tags = resolve_k8s_resource_tags(prefix="METADATA_INGEST", default_cpu="1000m", default_mem="2Gi")

logger = get_dagster_logger()

class RabbitMQIngestionConfig(Config):
    git_repo_url: str = os.getenv("RABBITMQ_GIT_REPO_URL", "")
    git_branch: str = os.getenv("RABBITMQ_GIT_BRANCH", "main")
    git_token: str = os.getenv("RABBITMQ_GIT_TOKEN", "")
    git_token_username: str = os.getenv("RABBITMQ_GIT_TOKEN_USERNAME", "x-access-token")
    git_ssl_verify: bool = os.getenv("RABBITMQ_GIT_SSL_VERIFY", "true").lower() == "true"
    schema_path_in_repo: str = os.getenv("RABBITMQ_SCHEMA_PATH", "schemas/rabbitmq")
    datahub_gms_url: str = os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
    datahub_token: str = os.getenv("DATAHUB_TOKEN", "")
    raw_kafka_topic: str = os.getenv("RAW_KAFKA_TOPIC", "openddil.sensor.data")

@asset(group_name="metadata_ingestion", tags=metadata_k8s_tags)
def ingest_rabbitmq_schemas(config: RabbitMQIngestionConfig):
    """
    Clones a Git repository, scans a directory for .json schema files, parses them, and ingests them into DataHub
    as a custom RabbitMQ platform dataset, while emitting lineage from the corresponding Kafka topics.
    """
    parser = JSONSchemaParser()
    emitter_client = DatahubRestEmitter(
        gms_server=config.datahub_gms_url, 
        token=config.datahub_token if config.datahub_token else None
    )
    emitter = DDSToDataHubEmitter(emitter_client)
    
    total_schemas = 0
    total_lineage_edges = 0
    files_scanned = 0
    
    with tempfile.TemporaryDirectory() as tmpdir:
        clone_url = config.git_repo_url
        repo_name = clone_url.split("/")[-1].replace(".git", "")
            
        git_cmd = ["git"]
        if config.git_token:
            userpass = f"{config.git_token_username}:{config.git_token}"
            auth = base64.b64encode(userpass.encode()).decode()
            git_cmd.extend(["-c", f"http.extraHeader=Authorization: Basic {auth}"])
        if not config.git_ssl_verify:
            git_cmd.extend(["-c", "http.sslVerify=false"])
        git_cmd.extend(["clone", "-b", config.git_branch, "--single-branch", clone_url, tmpdir])
            
        try:
            subprocess.run(
                git_cmd,
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"git clone failed: {e.stderr}")
            raise RuntimeError("git clone failed (see logs)") from None
        
        search_path = os.path.join(tmpdir, config.schema_path_in_repo)
        schema_files = glob.glob(os.path.join(search_path, "**/*.json"), recursive=True)
        files_scanned = len(schema_files)
        
        for schema_file in schema_files:
            rel_path = os.path.relpath(schema_file, search_path)
            repo_path = os.path.splitext(rel_path)[0].replace(os.sep, ".")
            
            schemas = parser.parse(schema_file)
            
            for schema in schemas:
                struct_name = schema["struct_name"]
                fields = schema["fields"]
                
                full_topic_name = f"{repo_name}.{repo_path}.{struct_name}"
                
                # 1. Emit RabbitMQ Schema
                emitter.emit_rabbitmq_schema(topic_name=full_topic_name, parsed_fields=fields)
                total_schemas += 1
                
                # 2. Emit Kafka Lineage (Kafka -> RabbitMQ)
                emitter.emit_rabbitmq_lineage(
                    kafka_topic_name=config.raw_kafka_topic,
                    rabbitmq_topic_name=full_topic_name
                )
                total_lineage_edges += 1
                
    return MaterializeResult(
        asset_key="ingest_rabbitmq_schemas",
        metadata={
            "run_info": "Ingested RabbitMQ JSON schemas and mapped lineage from Kafka",
            "total_schemas_ingested": total_schemas,
            "total_lineage_edges_created": total_lineage_edges,
            "files_scanned": files_scanned
        }
    )
