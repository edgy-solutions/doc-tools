from dagster import define_asset_job, Definitions, load_assets_from_modules

from doc_tools.assets import ingestion_assets
from doc_tools.assets import semantic_assets
from doc_tools.utils.dagster_resources import MinioResource, Neo4jResource, WeaviateResource, LLMExtractorResource, JenaResource
from doc_tools.sensors import build_document_sensor
import yaml
import os

default_config = {}
config_paths = ["/app/config/config.yaml", "config.yaml"]
for path in config_paths:
    if os.path.exists(path):
        with open(path, "r") as f:
            default_config = yaml.safe_load(f)
        break

SENSOR_CONFIGS = default_config.get("sensors", [])
sensors = [build_document_sensor(c["bucket"], c["directory"], c.get("config", {})) for c in SENSOR_CONFIGS]

all_assets = load_assets_from_modules([ingestion_assets, semantic_assets])

# Fallback config for manual UI executions (e.g. defaulting to training)
fallback_config = {}
for c in SENSOR_CONFIGS:
    if c["directory"] == "training":
        fallback_config = c.get("config", {})
        break

process_documents_job = define_asset_job(
    name="process_documents_job",
    selection=["process_document_artifact", "build_knowledge_graph"],
    config=fallback_config
)

defs = Definitions(
    assets=all_assets,
    jobs=[process_documents_job],
    sensors=sensors,
    resources={
        "minio": MinioResource(),
        "neo4j": Neo4jResource(),
        "weaviate": WeaviateResource(),
        "llm": LLMExtractorResource(),
        "jena": JenaResource()
    },
)
