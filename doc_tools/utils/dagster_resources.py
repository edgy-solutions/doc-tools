import os
from dagster import ConfigurableResource

# We will need some stubs for the resources that the assets depend on.
# For doc-tools, we can use these simple wrappers around the clients.

from pydantic import Field

class Neo4jResource(ConfigurableResource):
    uri: str 
    username: str 
    password: str 

    def get_client(self):
        # In a real system, this would return a driver or a wrapper
        from .neo4j_client import Neo4jClient
        return Neo4jClient(uri=self.uri, user=self.username, password=self.password)

class WeaviateResource(ConfigurableResource):
    http_host: str = Field(description="The HTTP REST endpoint for Weaviate (e.g., weaviate:8080)")
    grpc_host: str = Field(description="The high-speed gRPC endpoint for Weaviate (e.g., weaviate-grpc:50051)")

    def get_client(self):
        from .weaviate_client import get_weaviate_client
        return get_weaviate_client(http_host=self.http_host, grpc_host=self.grpc_host)

class LLMExtractorResource(ConfigurableResource):
    langfuse_public_key: str = Field(description="Public key for Langfuse tracing")
    langfuse_secret_key: str = Field(description="Secret key for Langfuse tracing")
    langfuse_host: str = Field(description="Langfuse API host (e.g., https://cloud.langfuse.com)")

    def get_client(self):
        # This provides a centralized way to access Langfuse config if needed
        return {
            "public_key": self.langfuse_public_key,
            "secret_key": self.langfuse_secret_key,
            "host": self.langfuse_host
        }

class JenaResource(ConfigurableResource):
    url: str 
    dataset: str
    username: str 
    password: str 

    def get_client(self):
        from .jena_client import JenaClient
        return JenaClient(url=self.url, dataset=self.dataset, username=self.username, password=self.password)

