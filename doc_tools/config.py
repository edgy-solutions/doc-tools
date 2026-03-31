from dagster import Config

class ProcessConfig(Config):
    bucket: str = "processing-artifacts"

class IngestionConfig(Config):
    graph_node_label: str = "Document"
    graph_child_label: str = "Chunk"
    vector_collection_name: str = "DocumentChunk"
    procedure_id_format: str = r"^\d{4}$"
    step_id_format: str = r"^\d+(?:\.\d+)*$"
    valid_personnel_roles: str = ""
    valid_hazard_classes: str = ""
    valid_process_categories: str = ""
    bucket: str = "processing-artifacts"
