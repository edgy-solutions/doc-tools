import os
import glob
import re
import tempfile
import subprocess
from dagster import asset, MaterializeResult, Config
from datahub.emitter.rest_emitter import DatahubRestEmitter
from doc_tools.ingestion.idl_parser import IDLParser
from doc_tools.ingestion.datahub_emitter import DDSToDataHubEmitter

class DDSIngestionConfig(Config):
    git_repo_url: str = os.getenv("DDS_GIT_REPO_URL", "")
    git_branch: str = os.getenv("DDS_GIT_BRANCH", "main")
    git_token: str = os.getenv("DDS_GIT_TOKEN", "")
    git_ssl_verify: bool = os.getenv("DDS_GIT_SSL_VERIFY", "true").lower() == "true"
    use_pcpp: bool = os.getenv("DDS_USE_PCPP", "false").lower() == "true"
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
        repo_name = clone_url.split("/")[-1].replace(".git", "")
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
        
        env_includes = os.getenv("DDS_INCLUDE_DIRS")
        if env_includes:
            include_dirs = [d.strip() for d in env_includes.replace(",", ":").split(":") if d.strip()]
            include_dirs = [os.path.join(tmpdir, d) if not os.path.isabs(d) else d for d in include_dirs]
        else:
            include_dirs = []
            for root, dirs, files in os.walk(tmpdir):
                if any(f.endswith('.idl') for f in files):
                    include_dirs.append(root)
        
        for idl_file in idl_files:
            rel_path = os.path.relpath(idl_file, tmpdir)
            repo_path = os.path.splitext(rel_path)[0].replace("/", ".")
            
            structs = parser.parse(idl_file, include_dirs=include_dirs, use_pcpp=config.use_pcpp)
            
            for struct in structs:
                struct_name = struct["struct_name"]
                fields = struct["fields"]
                
                full_topic_name = f"{repo_name}.{repo_path}.{struct_name}"
                
                # 1. Emit DDS Schema
                emitter.emit_dds_schema(topic_name=full_topic_name, parsed_fields=fields)
                total_structs += 1
                
                # 2. Emit Kafka Lineage
                emitter.emit_kafka_lineage(dds_topic_name=full_topic_name, kafka_topic_name=config.raw_kafka_topic)
                total_lineage_edges += 1
                
    return MaterializeResult(
        asset_key="ingest_dds_idl_schemas",
        metadata={
            "run_info": "Ingested DDS IDL schemas and mapped lineage to Kafka",
            "total_structs_ingested": total_structs,
            "total_lineage_edges_created": total_lineage_edges,
            "files_scanned": files_scanned
        }
    )
