from dagster import define_asset_job, Definitions, load_assets_from_modules

from doc_tools.assets import ingestion_assets
from doc_tools.assets import semantic_assets
from doc_tools.utils.dagster_resources import MinioResource, Neo4jResource, WeaviateResource, LLMExtractorResource
from doc_tools.sensors import document_upload_sensor

all_assets = load_assets_from_modules([ingestion_assets, semantic_assets])

process_documents_job = define_asset_job(
    name="process_documents_job",
    selection=["process_document_artifact", "build_knowledge_graph"]
)

defs = Definitions(
    assets=all_assets,
    jobs=[process_documents_job],
    sensors=[document_upload_sensor],
    resources={
        "minio": MinioResource(),
        "neo4j": Neo4jResource(),
        "weaviate": WeaviateResource(),
        "llm": LLMExtractorResource()
    },
)
