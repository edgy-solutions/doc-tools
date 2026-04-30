import os
import glob
import re
import tempfile
import subprocess
from dagster import asset, AssetMaterialization, Config
from datahub.emitter.rest_emitter import DatahubRestEmitter
from doc_tools.ingestion.idl_parser import IDLParser
from doc_tools.ingestion.datahub_emitter import DDSToDataHubEmitter

class DDSIngestionConfig(Config):
    git_repo_url: str = os.getenv("DDS_GIT_REPO_URL", "")
    git_branch: str = os.getenv("DDS_GIT_BRANCH", "main")
    git_token: str = os.getenv("DDS_GIT_TOKEN", "")
    git_ssl_verify: bool = os.getenv("DDS_GIT_SSL_VERIFY", "true").lower() == "true"
    schema_path_in_repo: str = os.getenv("DDS_SCHEMA_PATH", "schemas/dds")
    datahub_gms_url: str = os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
    datahub_token: str = os.getenv("DATAHUB_TOKEN", "")
    raw_kafka_topic: str = os.getenv("RAW_KAFKA_TOPIC", "openddil.sensor.data")

@asset(group_name="metadata_ingestion")
def ingest_dds_idl_schemas(config: DDSIngestionConfig):
    """
    Clones a Git repository, scans a directory for .idl files, parses them, and ingests them into DataHub
    as a custom DDS platform dataset, while emitting lineage to corresponding Kafka topics.
    """
    parser = IDLParser()
    emitter_client = DatahubRestEmitter(
        gms_server=config.datahub_gms_url, 
        token=config.datahub_token if config.datahub_token else None
    )
    emitter = DDSToDataHubEmitter(emitter_client)
    
    total_structs = 0
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
        idl_files = glob.glob(os.path.join(search_path, "**/*.idl"), recursive=True)
        files_scanned = len(idl_files)
        
        for idl_file in idl_files:
            structs = parser.parse(idl_file, include_dirs=[tmpdir])
            
            for struct in structs:
                struct_name = struct["struct_name"]
                fields = struct["fields"]
                
                # 1. Emit DDS Schema
                emitter.emit_dds_schema(topic_name=struct_name, parsed_fields=fields)
                total_structs += 1
                
                # 2. Emit Kafka Lineage
                emitter.emit_kafka_lineage(dds_topic_name=struct_name, kafka_topic_name=config.raw_kafka_topic)
                total_lineage_edges += 1
                
    yield AssetMaterialization(
        asset_key="ingest_dds_idl_schemas",
        description="Ingested DDS IDL schemas and mapped lineage to Kafka",
        metadata={
            "total_structs_ingested": total_structs,
            "total_lineage_edges_created": total_lineage_edges,
            "files_scanned": files_scanned
        }
    )
