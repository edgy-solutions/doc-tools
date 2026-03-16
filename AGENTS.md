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

- **Multi-Standard Semantic Parsing**: 
  1. Use `doc_tools.parsers` for standard-specific logic (`S1000dGraphBuilder`, `DitaGraphBuilder`, `IadsGraphBuilder`, `MilStd40051GraphBuilder`).
  2. Maintain a unified `MIL` namespace: `http://edgy-solutions.com/ontology/mil#`.
  3. Implement extraction logic in `doc_tools/assets/xml_ingestion.py` using the directory routing pattern.
  4. **High-Performance Passing**: Always return the serialized RDF string (as a string, not a file path) to ensure compatibility with isolated Dagster K8s pods.

- **Hybrid Graph Synchronization & Revisioning**:
  1. **Named Graphs**: Every document MUST be isolated in its own Jena Named Graph using its identifier (e.g., `urn:doc:{s3_key}`).
  2. **Jena PUT First**: Use `httpx.put` to push Turtle data to the Named Graph. This ensures the old revision is completely replaced in the reasoning engine.
  3. **Neo4j Wipe**: Before importing the new revision, execute `MATCH (n:Resource {uri: $uri}) DETACH DELETE n` on the root node URI to clear the old graph structure.
  4. **Targeted Fetch**: Use a SPARQL `CONSTRUCT` query restricted to the document's `GRAPH <uri>` to fetch and sync only the latest version through `n10s`.
  5. **In-Memory Triples**: Pass raw Turtle data and root URIs between assets as dictionaries; do not use the local filesystem.
