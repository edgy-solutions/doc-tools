import os
from dagster import ConfigurableResource

# We will need some stubs for the resources that the assets depend on.
# For doc-tools, we can use these simple wrappers around the clients.

class MinioResource(ConfigurableResource):
    endpoint_url: str
    access_key: str
    secret_key: str
    secure: bool

    def get_client(self):
        from minio import Minio
        
        ep = self.endpoint_url
        if ep.startswith("http://"):
            ep = ep[len("http://"):]
        elif ep.startswith("https://"):
            ep = ep[len("https://"):]
            
        if "/" in ep:
            ep = ep.split("/")[0]

        return Minio(
            endpoint=ep,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=self.secure
        )
    
    @property
    def endpoint(self):
        return self.endpoint_url

class Neo4jResource(ConfigurableResource):
    uri: str 
    username: str 
    password: str 

    def get_client(self):
        # In a real system, this would return a driver or a wrapper
        from .neo4j_client import Neo4jClient
        return Neo4jClient(uri=self.uri, user=self.username, password=self.password)

class WeaviateResource(ConfigurableResource):
    url: str 

    def get_client(self):
        from .weaviate_client import WeaviateClient
        return WeaviateClient(url=self.url)

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
    url: str 
    username: str 
    password: str 

    def get_client(self):
        from .jena_client import JenaClient
        return JenaClient(base_url=self.url, username=self.username, password=self.password)

