import os
from dagster import sensor, RunRequest, SensorEvaluationContext, DefaultSensorStatus

# Check env var for default sensor status. Off by default to prevent unwanted runs.
_sensor_default_enabled = os.getenv("DAGSTER_SENSOR_DEFAULT_ENABLED", "false").lower() == "true"
_sensor_status = DefaultSensorStatus.RUNNING if _sensor_default_enabled else DefaultSensorStatus.STOPPED

def get_minio_client():
    from minio import Minio
    return Minio(
        endpoint=os.getenv("MINIO_ENDPOINT", "localhost:9000"),
        access_key=os.getenv("MINIO_ROOT_USER", "minioadmin"),
        secret_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin"),
        secure=False
    )

@sensor(job_name="process_documents_job", default_status=_sensor_status)
def document_upload_sensor(context: SensorEvaluationContext):
    """
    Monitors MinIO 'processing-artifacts' bucket for new document artifacts.
    Expected structure: {doc_id}/{filename}
    Ignores: 'generated/' directory and metadata.json.
    """
    from doc_tools.assets.ingestion_assets import BUCKET_NAME, document_files_partition
    
    client = get_minio_client()
    
    # Ensure bucket exists
    if not client.bucket_exists(BUCKET_NAME):
        client.make_bucket(BUCKET_NAME)
    
    # List all objects in bucket
    objects = client.list_objects(BUCKET_NAME, recursive=True)
    
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
            
        # Parse doc_id and filename: expecting {doc_id}/{filename}
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
        
        for key in new_partition_keys:
            yield RunRequest(
                run_key=key,
                partition_key=key
            )
            new_cursor = key
            
    context.update_cursor(new_cursor)
