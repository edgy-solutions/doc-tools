# doc-tools Agent Guidelines

When working in `doc-tools`, AI agents should adhere to the following workflow and safety guardrails:

## Workflow Guide
1. **Understanding the Pipeline**: The pipeline polls MinIO via `document_upload_sensor`, processes documents (PDFs via `unstructured`, PPTXs via `python-pptx`), and orchestrates them into Neo4j and Weaviate.
2. **Adding Assets**: Any new step in the ingestion pipeline should be represented as a modular Dagster `@asset`.
3. **Configuration**: New assets requiring domain-specific targeting MUST accept parameters dynamically via `IngestionConfig`. Do not pollute the backend logic with specific client schemas.
4. **Environment Generation**: When adding new libraries, leverage `uv add <package>` and update `pyproject.toml`. Do not use pip.

## Safety Guardrails
- **Dynamic Queries**: Be extremely careful with Cypher query string formatting for dynamic labels to avoid injection vulnerability or syntax errors. Only use bounded f-strings against `config.graph_node_label` etc, and parameterize everything else natively.
- **Containerization**: Do not write vanilla `Dockerfiles`. This project uses CNCF Buildpacks. System-level packages belong in `Aptfile`. Start commands belong in `project.toml`.

## Extension Patterns
- To add a new document type parser, extend the existing logic in `doc_tools/assets/ingestion_assets.py` without tying it to a specific format domain.
- To configure external services, subclass `ConfigurableResource` inside `doc_tools/utils/dagster_resources.py`.
