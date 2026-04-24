import os
import glob
from dagster import asset, AssetMaterialization, Config
from datahub.emitter.rest_emitter import DatahubRestEmitter
from doc_tools.ingestion.json_schema_parser import JSONSchemaParser
from doc_tools.ingestion.datahub_emitter import DDSToDataHubEmitter

class RabbitMQIngestionConfig(Config):
    schema_directory: str = "./rabbitmq_schemas"
    datahub_gms_url: str = "http://localhost:8080"
    datahub_token: str = ""
    raw_kafka_topic: str = "openddil.sensor.data"

@asset(group_name="metadata_ingestion")
def ingest_rabbitmq_schemas(config: RabbitMQIngestionConfig):
    """
    Scans a local directory for .json schema files, parses them, and ingests them into DataHub
    as a custom RabbitMQ platform dataset, while emitting lineage from the corresponding Kafka topics.
    """
    parser = JSONSchemaParser()
    emitter_client = DatahubRestEmitter(
        gms_server=config.datahub_gms_url, 
        token=config.datahub_token if config.datahub_token else None
    )
    emitter = DDSToDataHubEmitter(emitter_client)
    
    schema_files = glob.glob(os.path.join(config.schema_directory, "**/*.json"), recursive=True)
    
    total_schemas = 0
    total_lineage_edges = 0
    
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
            "files_scanned": len(schema_files)
        }
    )
