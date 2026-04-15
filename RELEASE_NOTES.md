# 🚀 Release Notes: doc-tools v0.1.0 (Generative Ingestion Genesis)

Welcome to the **Generative Ingestion Genesis** release of `doc-tools`! This inaugural release establishes a robust, domain-agnostic, and highly configurable document ingestion pipeline built on Dagster. It sets the foundation for processing complex document formats into structured, AI-ready knowledge representations.

## 🎉 Key Features & Architectural Milestones

### The "Holy Trinity" of Data Segregation
We have implemented strict isolation mechanisms across our three primary data layers to prevent cross-domain data leakage:
* **Neo4j (Graph Knowledge):** Every node is now automatically tagged with its uppercase domain label (e.g., `:MANUFACTURING`, `:COMPLIANCE`, `:TRAINING`). This guarantees secure, domain-specific graph traversals.
* **Weaviate (Vector Retrieval):** All text chunks now include a `domain` metadata property, ensuring downstream RAG agents only retrieve context relevant to their specific domain.
* **Apache Jena (Deep Reasoning):** Strict isolation is maintained via Named Graphs, separating document instances (`urn:doc:{s3_key}`) from domain ontologies (`http://internal/{domain}`).

### Unified Military Graph (MIL Ontology)
For aerospace and defense applications, `doc-tools` now acts as a Semantic Translator. We've introduced specialized parsers that map diverse structural elements into a single, unified MIL Ontology:
* Support for **S1000D**, **DITA**, **IADS**, and **MIL-STD-40051** XML standards.
* **First-Class Entity Extraction:** Tooling information and entities are now extracted as first-class nodes in Neo4j and correctly linked to their respective procedures and steps.

### Declarative Component Architecture
The core orchestration layer has been completely refactored to utilize a modular, declarative component architecture powered by `dag-tools`.
* Replaced legacy `config.yaml` files with typed, Python-native `IngestionConfig` objects.
* Introduced `S3SensorComponent` and `S3ToFileComponent` for zero-config, rapid fanning-out of pipelines across new domains.
* Refactored Design Metadata, Oracle, and SQL Server extraction logic to match the new declarative component pattern.

### DataHub Human-in-the-Loop (HITL) Integration
* Successfully implemented the DataHub HITL loop and Neo4j Sync Sensor.
* Semantic tags and glossary terms approved in DataHub are now automatically synced and linked within the Neo4j Knowledge Graph.

### Kubernetes & Cloud-Native Optimizations
* **In-Memory Artifact Passing:** Transitioned to `s3_pickle_io_manager` for intermediate artifacts. Dagster now serializes `process_document_artifact` outputs directly to MinIO, allowing seamless loading into downstream assets across different Kubernetes pods.
* Standardized Apache Jena environment variables for easier configuration and deployment.

## 🐛 Bug Fixes & Stability Improvements
* Fixed Dagster invariant violations and duplicate asset/sensor key errors caused by component module scoping.
* Upgraded to the latest `dag-tools` package to resolve S3SensorComponent naming collisions.
* Resolved `NameError` in the `build_knowledge_graph` asset.
* Fixed the `DagsterInvalidConfigError` by making `IngestionConfig` optional with safe defaults.
* Identified and fixed the 404 HeadObject error during S3 ingestion.
* Resolved the JenaClient initialization error.
* Regenerated BAML clients to ensure alignment with the latest schemas.
* Fully tested and validated compatibility with Python 3.12.
