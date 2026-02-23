# Generative AI Document Ingestion Tools (`doc-tools`)

A domain-agnostic, configurable document data ingestion pipeline built with [Dagster](https://dagster.io). This repository provides a robust and reliable system for processing various document types (PDFs, presentations, words, etc.) and converting them into structured knowledge representations suitable for Generative AI applications like RAG (Retrieval-Augmented Generation).

## 🚀 Key Features

1. **Robust Document Parsing:** Extracts rich text, metadata, and embedded images from generic document formats using the high-resolution power of the `unstructured` library.
2. **Semantic Layout Detection:** Automatically identifies page layouts, reading orders, and structural semantic elements during processing via heuristic visual analysis.
3. **Graph Knowledge Representation:** Maps processed documents into a highly-linked **Neo4j** Knowledge Graph for traversing document relationships, concepts, and metadata.
4. **Vector Embeddings for RAG:** Embeds text chunks directly into **Weaviate** for immediate semantic search availability.
5. **Configurability:** Fully configurable domains! Easily override GraphQL / Graph target labels and Vector DB collections via Dagster run configs.

---

## 🏗️ Project Structure
- `baml_src/`: LLM prompt definitions mapped to structural schemas. Compiles via `baml-py` into Pydantic models.
- `charts/doc-tools/`: The Helm Chart for deploying the application to Kubernetes, fully supporting ConfigMaps and Secrets.
- `doc_tools/`: The main Dagster application codebase.
  - `doc_tools/assets/`: The Dagster data assets forming the core ingestion and semantic pipelines.
  - `doc_tools/plugins/`: Contains the **Domain-Agnostic Plugin Architecture**. Base structural nodes are passed here where domain logic (Training/MAT) invokes BAML schemas and returns Cypher/SPARQL queries.
  - `doc_tools/utils/`: Extracted domain implementations for text extraction, layout detection, Neo4j mapping, and Weaviate connections.
  - `doc_tools/definitions.py`: The entrypoint for Dagster orchestration that binds dependencies, resources, and configurations.
- `pyproject.toml`: The root Python project configuration and exact dependencies managed via [uv](https://docs.astral.sh/uv/).

---

## 🛠️ Setup Instructions

1. **Clone the repository:**
   ```bash
   git clone <your-repo-url>
   cd doc-tools
   ```

2. **Setup and Install via `uv`:**
   Use the ultrafast Python package manager `uv` to automatically wire the virtual environment and sync the specific subdependencies seamlessly.
   ```bash
   uv sync
   ```
   *(Note: You may need system-level tools like Tesseract-OCR and poppler installed depending on your OS for Unstructured logic to work out of the box).*

3. **Compile BAML Schemas:**
   If you modify the LLM prompts or schemas in `baml_src/`, you must recompile the Python clients.
   ```bash
   uv run baml-cli generate
   ```

---

## 💻 Development & Execution

To spin up the Dagster webserver, view the pipeline UI, or execute the underlying pipeline from your local desktop:

**Start Dagster Webserver:**
```bash
uv run dagster dev
```

### Running the Generalized Pipeline

The pipeline heavily employs `dagster.Config` via `IngestionConfig` to dynamically bind your document run to specific graph labels and vector databases index names to avoid domain lock-in. 

You can execute a pipeline run immediately using the local configuration via the Dagster Webserver by selecting `process_documents_job`.

Here is a look at what the sample execution YAML configuration (`doc_tools/example_run_config.yaml`) looks like for customizing domain labels:
```yaml
ops:
  build_knowledge_graph:
    config:
      source_directory: "/data/inputs"
      graph_node_label: "Course"
      graph_child_label: "Slide"
      vector_collection_name: "TrainingCourse"
```

To invoke that pipeline immediately from the CLI over a specific document dynamically:
```bash
uv run dagster job execute -m doc_tools.definitions -j process_documents_job -c doc_tools/example_run_config.yaml --tags '{"dagster/partition": "doc_id/file.pdf"}'
```

---

## 🌩️ Deployment via Helm

A packaged Helm chart `/charts/doc-tools` is dynamically wired to receive credentials, mount configurations, and pull the latest GHCR Cloud Native Buildpack containers dynamically.

To configure and deploy to your cluster:
1. Copy or modify `charts/doc-tools/values.yaml` to specify your `secrets` (MinIO, Neo4j, Weaviate credentials) and your Dagster run properties.
2. Template or deploy:
```bash
helm template doc-tools ./charts/doc-tools
# OR 
helm install doc-tools ./charts/doc-tools
```
