import os
from dagster import sensor, RunRequest, SensorEvaluationContext, DefaultSensorStatus

# Check env var for default sensor status. Off by default to prevent unwanted runs.
_sensor_default_enabled = os.getenv("DAGSTER_SENSOR_DEFAULT_ENABLED", "false").lower() == "true"
_sensor_status = DefaultSensorStatus.RUNNING if _sensor_default_enabled else DefaultSensorStatus.STOPPED

def get_minio_client():
    from minio import Minio
    
    # The Minio python client requires the endpoint WITHOUT http:// or https://
    endpoint_url = os.getenv("S3_ENDPOINT_URL", "localhost:9000")
    if endpoint_url.startswith("http://"):
        endpoint_url = endpoint_url[len("http://"):]
    elif endpoint_url.startswith("https://"):
        endpoint_url = endpoint_url[len("https://"):]
        
    return Minio(
        endpoint=endpoint_url,
        access_key=os.getenv("AWS_ACCESS_KEY_ID", "minioadmin"),
        secret_key=os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin"),
        secure=os.getenv("MINIO_SECURE", "false").lower() == "true"
    )

def build_document_sensor(bucket_name: str, directory: str, run_config: dict = None):
    domain_type = directory.strip('/')
    sensor_name = f"{domain_type}_document_sensor"
    
    if run_config is None:
        run_config = {}
            
    @sensor(name=sensor_name, job_name="process_documents_job", default_status=_sensor_status)
    def _document_sensor(context: SensorEvaluationContext):
        """
        Monitors MinIO bucket/directory for new document artifacts.
        Expected structure: {directory}/{doc_id}/{filename} or {doc_id}/{filename} if matching filtering.
        """
        from doc_tools.assets.ingestion_assets import document_files_partition
        
        client = get_minio_client()
        
        # Ensure bucket exists
        if not client.bucket_exists(bucket_name):
            client.make_bucket(bucket_name)
        
        # List all objects in bucket
        try:
            objects = client.list_objects(bucket_name, prefix=f"{directory}/", recursive=True)
        except Exception:
            objects = []
            
        last_processed_object = context.cursor or ""
        new_cursor = last_processed_object
        
        # Gather valid objects
        valid_objects = []
        for obj in objects:
            if obj.is_dir: continue
            obj_name = obj.object_name
            
            # Skip generated artifacts and metadata to avoid double triggering
            if "/generated/" in obj_name or obj_name.endswith("/metadata.json"):
                continue
                
            parts = obj_name.split('/')
            if len(parts) >= 2:
                valid_objects.append(obj_name)
        
        # Sort to process chronologically/lexicographically and allow robust pagination against cursor
        valid_objects.sort()
        
        new_partition_keys = []
        for obj_name in valid_objects:
            if obj_name <= last_processed_object:
                continue
                
            new_partition_keys.append(obj_name)
            
            # Limit batch size to 5 to avoid timeouts in single tick
            if len(new_partition_keys) >= 5:
                break
                
        if new_partition_keys:
            # Register new partitions to Dagster state
            context.instance.add_dynamic_partitions(document_files_partition.name, new_partition_keys)
            
            # Inject bucket config into the job payloads dynamically
            import copy
            sensor_run_config = copy.deepcopy(run_config)
            if "ops" not in sensor_run_config:
                sensor_run_config["ops"] = {}
            for op in ["process_document_artifact", "build_knowledge_graph"]:
                if op not in sensor_run_config["ops"]:
                    sensor_run_config["ops"][op] = {}
                if "config" not in sensor_run_config["ops"][op]:
                    sensor_run_config["ops"][op]["config"] = {}
                sensor_run_config["ops"][op]["config"]["bucket"] = bucket_name
                
            for key in new_partition_keys:
                yield RunRequest(
                    run_key=key,
                    partition_key=key,
                    run_config=sensor_run_config,
                    tags={"domain_type": domain_type}
                )
                new_cursor = key
                
        context.update_cursor(new_cursor)
        
    return _document_sensor

