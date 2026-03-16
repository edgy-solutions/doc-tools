# doc-tools Agent Guidelines

When working in `doc-tools`, AI agents should adhere to the following workflow and safety guardrails:

## Workflow Guide
0. **Pre-flight Environment**: Ensure the environment is primed via `setup/setup_env.py` otherwise Dagster sink adapters will fail against unindexed databases. The Helm chart does this automatically.
1. **Understanding the Pipeline**: Configured sensors polling MinIO bucket/directory targets dynamically inject a `domain_type` workflow tag string. The pipeline processes documents (PDFs via `unstructured`, PPTXs via `python-pptx`), dynamically dispatches the extracted structure to the correct Plugin mapping, and orchestrates them into Neo4j, Weaviate, and Apache Jena using SPARQL.
2. **Adding Assets**: Any new step in the ingestion pipeline should be represented as a modular Dagster `@asset`.
3. **Configuration**: New assets requiring domain-specific targeting MUST accept parameters dynamically via `IngestionConfig`. Do not pollute the backend logic with specific client schemas.
4. **Environment Generation**: When adding new libraries, leverage `uv add <package>` and update `pyproject.toml`. Do not use pip.

## Safety Guardrails
- **Dynamic Queries**: Be extremely careful with Cypher query string formatting for dynamic labels to avoid injection vulnerability or syntax errors. Only use bounded f-strings against `config.graph_node_label` etc, and parameterize everything else natively.
- **Containerization**: Do not write vanilla `Dockerfiles`. This project uses CNCF Buildpacks. System-level packages belong in `Aptfile`. Start commands belong in `project.toml`.

## Extension Patterns
- **Adding a New Domain**: Do not write raw litellm or langchain logic in the assets. 
  1. Define the parsing schema in `baml_src/{domain}.baml`.
  2. Run `baml-cli generate`. This drops the compiled models directly natively into `doc_tools/baml_client` to bypass Dagster's isolated import space issues.
  3. Create `doc_tools/plugins/{domain}.py` extending `AugmentationPlugin`.
  4. Register the new plugin in the Dispatcher switch inside `doc_tools/assets/semantic_assets.py`.
- To configure external services, subclass `ConfigurableResource` inside `doc_tools/utils/dagster_resources.py`.

- **S1000D Semantic Parsing**: 
  1. Use `doc_tools.parsers.s1000d_rdf.S1000dGraphBuilder` for XML-to-RDF mapping.
  2. Maintain `lxml` for XPath speed and `rdflib` for formal graph construction.
  3. Map DMC attributes to unique URIs in the `http://edgy-solutions.com/ontology/s1000d#` namespace.

- **Hybrid Graph Synchronization**:
  1. **Jena First**: Always push raw `.ttl` to Apache Jena via `httpx` first to allow the semantic engine to perform reasoner-based inference.
  2. **Inferred Fetch**: Trigger Neo4j `n10s` (Neosemantics) using a SPARQL `CONSTRUCT` query against the Jena `/query` endpoint. This ensures the logically deduced graph (not just raw data) is synced into the Property Graph.
  3. **Idempotency**: Always wrap `n10s.graphconfig.init` in a try/except to avoid "config already exists" errors.
