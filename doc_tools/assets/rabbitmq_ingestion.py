import os
import glob
import tempfile
import subprocess
from dagster import asset, AssetMaterialization, Config
from datahub.emitter.rest_emitter import DatahubRestEmitter
from doc_tools.ingestion.json_schema_parser import JSONSchemaParser
from doc_tools.ingestion.datahub_emitter import DDSToDataHubEmitter

class RabbitMQIngestionConfig(Config):
    git_repo_url: str = os.getenv("RABBITMQ_GIT_REPO_URL", "")
    git_branch: str = os.getenv("RABBITMQ_GIT_BRANCH", "main")
    git_token: str = os.getenv("RABBITMQ_GIT_TOKEN", "")
    git_ssl_verify: bool = os.getenv("RABBITMQ_GIT_SSL_VERIFY", "true").lower() == "true"
    schema_path_in_repo: str = os.getenv("RABBITMQ_SCHEMA_PATH", "schemas/rabbitmq")
    datahub_gms_url: str = os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
    datahub_token: str = os.getenv("DATAHUB_TOKEN", "")
    raw_kafka_topic: str = os.getenv("RAW_KAFKA_TOPIC", "openddil.sensor.data")

@asset(group_name="metadata_ingestion")
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
        if config.git_token and clone_url.startswith("https://"):
            clone_url = clone_url.replace("https://", f"https://{config.git_token}@")
            
        git_cmd = ["git"]
        if not config.git_ssl_verify:
            git_cmd.extend(["-c", "http.sslVerify=false"])
        git_cmd.extend(["clone", "-b", config.git_branch, "--single-branch", clone_url, tmpdir])
            
        subprocess.run(
            git_cmd,
            check=True,
            capture_output=True
        )
        
        search_path = os.path.join(tmpdir, config.schema_path_in_repo)
        schema_files = glob.glob(os.path.join(search_path, "**/*.json"), recursive=True)
        files_scanned = len(schema_files)
        
        for schema_file in schema_files:
            schemas = parser.parse(schema_file)
            
            for schema in schemas:
                struct_name = schema["struct_name"]
                fields = schema["fields"]
                
                # 1. Emit RabbitMQ Schema
                emitter.emit_rabbitmq_schema(topic_name=struct_name, parsed_fields=fields)
                total_schemas += 1
                
                # 2. Emit Kafka Lineage (Kafka -> RabbitMQ)
                emitter.emit_rabbitmq_lineage(
                    kafka_topic_name=config.raw_kafka_topic,
                    rabbitmq_topic_name=struct_name
                )
                total_lineage_edges += 1
                
    yield AssetMaterialization(
        asset_key="ingest_rabbitmq_schemas",
        description="Ingested RabbitMQ JSON schemas and mapped lineage from Kafka",
        metadata={
            "total_schemas_ingested": total_schemas,
            "total_lineage_edges_created": total_lineage_edges,
            "files_scanned": files_scanned
        }
    )
