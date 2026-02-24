import os
import weaviate

class WeaviateClient:
    def __init__(self, url=None):
        self.url = url or os.getenv("WEAVIATE_URL", "http://localhost:8081")
        
        self.client = weaviate.Client(
            url=self.url,
            # Auth can be added here if needed
        )

    def ensure_class(self, class_schema):
        class_name = class_schema["class"]
        if not self.client.schema.exists(class_name):
            self.client.schema.create_class(class_schema)
            print(f"Created Weaviate class: {class_name}")

    def add_object(self, data_object, class_name, uuid=None):
        return self.client.data_object.create(
            data_object=data_object,
            class_name=class_name,
            uuid=uuid
        )
