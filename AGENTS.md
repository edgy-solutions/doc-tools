# doc-tools Agent Guidelines

When working in `doc-tools`, AI agents should adhere to the following workflow and safety guardrails:

## Workflow Guide
1. **Understanding the Pipeline**: The pipeline reads from a `source_directory`, processes documents, and loads them into Neo4j and Weaviate.
2. **Adding Assets**: Any new step in the ingestion pipeline should be represented as a Dagster `@asset`.
3. **Configuration**: New assets requiring domain-specific knowledge MUST accept it via `IngestionConfig`.

## Safety Guardrails
- **Read-Only Source Repo**: Do NOT modify the `training-consolidation-workbench` repository. Extract and copy only.
- **Dynamic Queries**: Be extremely careful with Cypher query string formatting for dynamic labels to avoid injection vulnerability or syntax errors. Only use `config.graph_node_label`, etc.

## Extension Patterns
- To add a new document type parser, extend the existing `unstructured` based processing logic without tying it to a specific domain.
