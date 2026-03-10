from dagster import Config

class ProcessConfig(Config):
    bucket: str = "processing-artifacts"

class IngestionConfig(Config):
    graph_node_label: str  # e.g., "Course" or "FinancialReport"
    graph_child_label: str # e.g., "Slide" or "Page"
    vector_collection_name: str # e.g., "TrainingDocs" or "LegalContracts"
    procedure_id_format: str = "PROC-01"
    step_id_format: str = "1.2.3"
    valid_personnel_roles: str = "QC Inspector, Journeyman, Safety Officer"
    valid_hazard_classes: str = "1.1D, 1.3C, Hazmat 3, Biohazard"
    valid_process_categories: str = "Transformation, Inspection, Movement, Rework, Critical Safety Hold"
    bucket: str = "processing-artifacts"
