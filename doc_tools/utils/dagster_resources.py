import os
from dagster import ConfigurableResource

# We will need some stubs for the resources that the assets depend on.
# For doc-tools, we can use these simple wrappers around the clients.

class MinioResource(ConfigurableResource):
    def get_client(self):
        from minio import Minio
        
        ep = os.getenv("S3_ENDPOINT_URL", "localhost:9000")
        secure = False
        if ep.startswith("http://"):
            ep = ep[len("http://"):]
        elif ep.startswith("https://"):
            ep = ep[len("https://"):]
            secure = True
            
        if "/" in ep:
            ep = ep.split("/")[0]

        # Return a simple minio client or mock for now as configuration wasn't fully specified
        return Minio(
            endpoint=ep,
            access_key=os.getenv("AWS_ACCESS_KEY_ID", "minioadmin"),
            secret_key=os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin"),
            secure=secure
        )
    
    @property
    def endpoint(self):
        return os.getenv("S3_ENDPOINT_URL", "localhost:9000")

class Neo4jResource(ConfigurableResource):
    def get_client(self):
        from .neo4j_client import Neo4jClient
        return Neo4jClient()

class WeaviateResource(ConfigurableResource):
    def get_client(self):
        from .weaviate_client import WeaviateClient
        return WeaviateClient()

class LLMExtractorResource(ConfigurableResource):
    def get_client(self):
        # A mock for the LLMExtractor for now as its source was complex BAML usage.
        class StubExtractor:
            def extract_outline(self, text):
                class Outline:
                    sections = []
                return Outline()
            def extract_concepts(self, text):
                class Content:
                    concepts = []
                return Content()
        return StubExtractor()

class JenaResource(ConfigurableResource):
    def get_client(self):
        from .jena_client import JenaClient
        return JenaClient()

