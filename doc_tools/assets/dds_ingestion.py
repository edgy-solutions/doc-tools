import os
import glob
import base64
import tempfile
import subprocess
from dagster import asset, MaterializeResult, Config, get_dagster_logger
from datahub.emitter.rest_emitter import DatahubRestEmitter
from doc_tools.ingestion.idl_parser import IDLParser
from doc_tools.ingestion.datahub_emitter import DDSToDataHubEmitter
from dag_tools.utils.k8s import resolve_k8s_resource_tags

metadata_k8s_tags = resolve_k8s_resource_tags(prefix="METADATA_INGEST", default_cpu="1000m", default_mem="2Gi")

logger = get_dagster_logger()

class DDSIngestionConfig(Config):
    git_repo_url: str = os.getenv("DDS_GIT_REPO_URL", "")
    git_branch: str = os.getenv("DDS_GIT_BRANCH", "main")
    git_token: str = os.getenv("DDS_GIT_TOKEN", "")
    git_token_username: str = os.getenv("DDS_GIT_TOKEN_USERNAME", "x-access-token")
    git_ssl_verify: bool = os.getenv("DDS_GIT_SSL_VERIFY", "true").lower() == "true"
    use_pcpp: bool = os.getenv("DDS_USE_PCPP", "false").lower() == "true"
    schema_path_in_repo: str = os.getenv("DDS_SCHEMA_PATH", "schemas/dds")
    datahub_gms_url: str = os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
    datahub_token: str = os.getenv("DATAHUB_TOKEN", "")
    raw_kafka_topic: str = os.getenv("RAW_KAFKA_TOPIC", "openddil.sensor.data")

@asset(group_name="metadata_ingestion", tags=metadata_k8s_tags)
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
        idl_files = glob.glob(os.path.join(search_path, "**/*.idl"), recursive=True)
        files_scanned = len(idl_files)
        
        env_includes = os.getenv("DDS_INCLUDE_DIRS")
        if env_includes:
            include_dirs = [d.strip() for d in env_includes.replace(",", ":").split(":") if d.strip()]
            include_dirs = [d if os.path.isabs(d) else os.path.join(tmpdir, d) for d in include_dirs]
        else:
            include_dirs = []
            for root, dirs, files in os.walk(tmpdir):
                if any(f.endswith('.idl') for f in files):
                    include_dirs.append(root)
        
        if search_path not in include_dirs:
            include_dirs.insert(0, search_path)
        else:
            include_dirs.remove(search_path)
            include_dirs.insert(0, search_path)
        
        for idl_file in idl_files:
            rel_path = os.path.relpath(idl_file, search_path)
            repo_path = os.path.splitext(rel_path)[0].replace(os.sep, ".")
            
            structs = parser.parse(idl_file, include_dirs=include_dirs, use_pcpp=config.use_pcpp)
            
            for struct in structs:
                struct_name = struct["struct_name"]
                fields = struct["fields"]
                
                normalized_struct_name = struct_name.replace("::", ".")
                full_topic_name = f"{repo_name}.{repo_path}.{normalized_struct_name}"
                
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
