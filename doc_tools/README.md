# doc-tools

A domain-agnostic document data ingestion pipeline built with [Dagster](https://dagster.io).

## Overview
This repository provides a generalized pipeline for:
1. Extracting text, metadata, and images from generic documents (PDF, PPTX, DOCX, etc.) using `unstructured`.
2. Automatically detecting page layouts and semantic structure.
3. Loading the structured representation into a Neo4j Knowledge Graph.
4. Vectorizing the document content into Weaviate for semantic search.

## Setup

1. Create a Python virtual environment and activate it:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. Install the necessary dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Development

To spin up the Dagster webserver and view the pipeline UI:

```bash
cd doc_tools
dagster dev
```

## Running the Pipeline

The pipeline uses `dagster.Config` (`IngestionConfig`) to dynamically configure the graph labels and vector collection names.

You can execute a pipeline run via the Dagster UI using a run configuration or from the CLI.

Example configuration (`example_run_config.yaml`):
```yaml
ops:
  build_knowledge_graph:
    config:
      source_directory: "/data/inputs"
      graph_node_label: "Course"
      graph_child_label: "Slide"
      vector_collection_name: "TrainingCourse"
```

To run from the CLI using the example config on a dynamically added partition name:
```bash
# Note: First add the partition key or use Dagster Webserver to launch run
dagster job execute -m doc_tools.definitions -j process_documents_job -c example_run_config.yaml --tags '{"dagster/partition": "doc_id/filename.pdf"}'
```
