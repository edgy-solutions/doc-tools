from dagster import Config

class ProcessConfig(Config):
    bucket: str = "processing-artifacts"

class IngestionConfig(Config):
    graph_node_label: str  # e.g., "Course" or "FinancialReport"
    graph_child_label: str # e.g., "Slide" or "Page"
    vector_collection_name: str # e.g., "TrainingDocs" or "LegalContracts"
    bucket: str = "processing-artifacts"
