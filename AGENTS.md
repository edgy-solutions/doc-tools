# doc-tools Agent Guidelines

When working in `doc-tools`, AI agents should adhere to the following workflow and safety guardrails:

## Workflow Guide
0. **Pre-flight Environment**: Ensure the environment is primed via `setup/setup_env.py` otherwise Dagster sink adapters will fail against unindexed databases. The Helm chart does this automatically.
1. **Understanding the Pipeline**: Configured sensors polling MinIO bucket/directory targets dynamically inject a `domain_type` workflow tag string. The pipeline processes documents (PDFs via `unstructured`, PPTXs via `python-pptx`), dynamically dispatches the extracted structure to the correct Plugin mapping, and orchestrates them into Neo4j, Weaviate, and Apache Jena using SPARQL.
2. **Adding Assets**: Any new step in the ingestion pipeline should be represented as a modular Dagster `@asset`.
3. **Configuration**: Use **Declarative Components** (`S3ToFileComponent`, `S3SensorComponent`) in `doc_tools/definitions.py` to instantiate jobs and sensors. These components encapsulate `IngestionConfig` (labels, collections) and replace the legacy `config.yaml`. Do not pollute the backend logic with specific client schemas.
4. **Environment Generation**: When adding new libraries, leverage `uv add <package>` and update `pyproject.toml`. Do not use pip.

## Safety Guardrails
- **Dynamic Queries**: Be extremely careful with Cypher query string formatting for dynamic labels to avoid injection vulnerability or syntax errors. Only use bounded f-strings against `config.graph_node_label` etc, and parameterize everything else natively.
- **Containerization**: This project uses standard **Dockerfiles** managed in `.github/workflows/build-container.yml`. System-level packages belong in the `apt-get install` block within the Dockerfile generator step.

## Extension Patterns
- **Adding a New Domain**: Do not write raw litellm or langchain logic in the assets. 
  1. Define the parsing schema in `baml_src/{domain}.baml`.
  2. **BAML Prompt Layout**: Always follow the optimal layout to mitigate recency bias:
     - Role/Task Definition
     - `### DOCUMENT TEXT ###` (The content)
     - `### INSTRUCTIONS ###` (Dynamic `system_instructions`)
     - `### OUTPUT FORMAT ###` (`{{ ctx.output_format }}`)
  3. Run `baml-cli generate`. This drops the compiled models directly natively into `doc_tools/baml_client`.
  4. Create `doc_tools/plugins/{domain}.py` extending `AugmentationPlugin`.
  5. Register the new plugin in the Dispatcher switch inside `doc_tools/assets/semantic_assets.py`.
  6. **Existing Domains**: `manufacturing.py` (MANUFACTURING), `maintenance.py` (MAINTENANCE), `training.py` (TRAINING - uses full document context), `compliance.py` (COMPLIANCE), `sustainment.py` (SUSTAINMENT - uses full document context for PCN/PDN aggregation).
- To configure external services, subclass `ConfigurableResource` inside `doc_tools/utils/dagster_resources.py`.

- **Dynamic Prompt Management (Langfuse & GitOps)**:
  1. All prompts should be decoupled from BAML code.
  2. Create a ground-truth Markdown file in `prompts/{prompt_name}.md`.
  3. Use the `Langfuse` SDK in the plugin's `__init__` and `execute_global_pass` to fetch prompts dynamically via the `production` label.
  4. Integrate `scripts/check_drift.py` into CI/CD to ensure local Markdown files match Langfuse versions tagged as `ready-for-prod`.

- **Table Processing**:
  1. Documents with tabular data should use `doc_tools.utils.formatters.convert_element_to_markdown` during the global pass.
  2. This converts `unstructured` HTML tables into Markdown grids to improve LLM extraction accuracy for dense data mapping (e.g., part-to-replacement).

- **Figure/Image Nodes**:
  1. All BAML schemas should include `figure_references string[]` to extract explicit figure IDs.
  2. Plugin `to_graph_queries()` must emit `MERGE (f:Figure:{domain_label})` with `[:REFERENCES_FIGURE]` edges. Domain labels go on nodes only, NEVER on relationships.
  3. XML parsers extract `mil:Figure` triples using `mil:hasFigure` predicate.

- **Multi-Standard Semantic Parsing**: 
  1. Use `doc_tools.parsers` for standard-specific logic (`S1000dGraphBuilder`, `DitaGraphBuilder`, `IadsGraphBuilder`, `MilStd40051GraphBuilder`).
  2. Maintain a unified `MIL` namespace: `http://edgy-solutions.com/ontology/mil#`.
  3. Implement extraction logic in `doc_tools/assets/xml_ingestion.py` using the directory routing pattern.
  4. **High-Performance Passing**: Always return the serialized RDF string (as a string, not a file path) to ensure compatibility with isolated Dagster K8s pods.

- **DataHub Schema Ingestion & Lineage**:
  1. DataHub schema ingestion assets (`ingest_dds_idl_schemas` and `ingest_rabbitmq_schemas`) are designed for ephemeral Kubernetes pods.
  2. They use Python's `tempfile` and `subprocess` to dynamically clone Git repositories (supporting authentication tokens) at runtime.
  3. The schemas are parsed from the temporary directory and emitted to DataHub, with the cloned repository wiped automatically after execution.

- **Hybrid Graph Synchronization & Revisioning**:
  1. **Named Graphs**: Every document MUST be isolated in its own Jena Named Graph using its identifier (e.g., `urn:doc:{s3_key}`).
  2. **Jena PUT First**: Use `httpx.put` to push Turtle data to the Named Graph. This ensures the old revision is completely replaced in the reasoning engine.
  3. **Neo4j Wipe**: Before importing the new revision, execute `MATCH (n:Resource {uri: $uri}) DETACH DELETE n` on the root node URI to clear the old graph structure.
  4. **Targeted Fetch**: Use a SPARQL `CONSTRUCT` query restricted to the document's `GRAPH <uri>` to fetch and sync only the latest version through `n10s`.
  5. **Post-Sync Domain Labeling**: After n10s import, apply `:MAINTENANCE` label to all imported Resource nodes via `_apply_post_sync_domain_labels()`. This ensures XML tech manuals are visible to downstream agents that filter by Neo4j domain labels.
  6. **In-Memory Triples**: Pass raw Turtle data and root URIs between assets as dictionaries; do not use the local filesystem.

- **Semantic Binding Plane (Late Binding & URN Standardization)**:
  1. **Phase 7 URN Standard**: Glossary Term URNs MUST use the Short Name (e.g., `urn:li:glossaryTerm:MaintenanceWorkOrder`).
  2. **URI Storage**: The full Ontology URI MUST be stored in the `customProperties` aspect of the `GlossaryTerm` entity under the key `ontology_uri`.
  3. **DataHub Polling (Late Binding)**: Do NOT parse local dbt or metadata files for semantic tags. Use `doc_tools.assets.global_semantic_ingestion` to poll DataHub GMS for any `Dataset` possessing the `ontology_uri` custom property.
  4. **HITL Workflow**: All semantic linkings must go through the `propose_datahub_term` flow for human-in-the-loop approval before being synced to the Neo4j Knowledge Graph via the `datahub_approval_sensor`.
  5. **Neo4j Sync**: The `sync_approved_tags_to_neo4j` asset must fetch the full `ontology_uri` from the DataHub entity's `customProperties` at runtime to ensure graph accuracy.
