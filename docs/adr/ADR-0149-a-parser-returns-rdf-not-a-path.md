# ADR-0149 — a parser returns serialized RDF, never a file path

**Status:** built
**Date:** no ruling date is recorded; carried as standing guidance in `AGENTS.md` · recorded
2026-11-18
**Deciders:** a property of the deployment — isolated Dagster K8s pods — recorded as a
requirement in `AGENTS.md`; no individual is named
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:112` (§Multi-Standard Semantic Parsing 4, "High-Performance Passing") and
`AGENTS.md:133` (§Hybrid Graph Synchronization 6, "In-Memory Triples"); implemented at
`doc_tools/parsers/s1000d_rdf.py:181`, `:732-734`, `:737-747` and
`doc_tools/assets/xml_ingestion.py:297-299`, `:343-349`
**Related:** [ADR-0148](ADR-0148-one-mil-namespace-across-parsers.md) (what the triples are
written in), [ADR-0100](ADR-0100-doc-tools-is-a-code-location-not-a-service.md) (why this repo
runs as pods and nothing else), [ADR-0146](ADR-0146-the-supersede-key-is-the-slug.md) (the other
value this asset's return dict carries)

## Context

Each ingestion step in this repo is a separate Dagster asset, and in production each materialises
in **its own Kubernetes pod** with its own ephemeral filesystem. An asset that returns
`/tmp/doc.ttl` returns a string that is perfectly valid, perfectly readable locally — and
meaningless in the pod that consumes it. The consumer opens the path, finds nothing there, and
fails on a missing file several steps away from the asset that actually made the mistake.

The failure mode is specifically a *locally green* one. On a developer workstation all assets
run in one process against one filesystem, so a path hand-off works, the suite passes, and the
break appears only once the graph is split across pods. That is the shape of bug this decision
exists to make impossible rather than to catch.

A related constraint sits on the same wire: the text chunks indexed to Weaviate are walked from
**the same in-memory `rdflib.Graph` the parser just built** (`xml_ingestion.py:300-310`), so the
XML is parsed exactly once and nothing is re-read from disk.

## Decision

**A parser returns the serialized RDF as a string, and assets pass Turtle text and root URIs
between each other in memory. The local filesystem is not a channel between assets.**

- `S1000dGraphBuilder.parse_data_module(xml_content: bytes) -> str` takes bytes and returns the
  root URI (`s1000d_rdf.py:181`); `serialize(format="turtle") -> str` returns the graph as text
  (`:732-734`); the module-level convenience `data_module_graph(raw_bytes, doc_id) -> str`
  returns the serialization directly (`:737-747`). No method in the builder takes or returns a
  path.
- `extract_rdf_from_xml` serializes in the producing pod — *"Return the serialized RDF string
  directly for in-memory passing (K8s safe)"* (`xml_ingestion.py:297-299`) — and returns it as
  `rdf_string` inside a plain dict alongside `root_uri`, `s3_key`, `chunks`, `domain`,
  `content_kind` and `doc_id` (`:343-349`).
- The consumers take the string as a string: `doc_tools/assets/semantic_assets.py:1738` encodes
  it to UTF-8 for the Jena write, and `:1823` re-parses it with `rdflib` for the Neo4j side.
  Neither touches a path.
- Documents themselves still come from object storage, which is the opposite of a local path: it
  is reachable from any pod.

Pinned by `tests/test_parsers_rdf.py:224-228`, which asserts the serialization
`isinstance(ttl, str)` and that it contains the expected namespace and class.

## Consequences

- An asset graph can be split across pods, re-ordered, or retried on a different node without
  touching the parsers. Nothing depends on two steps sharing a disk.
- **The whole graph is held in memory twice at the hand-off** — once as the `rdflib.Graph` and
  once as the serialized string — and the string travels through Dagster's I/O manager. For a
  large data module that is the price of this decision, and it is paid on every XML ingest. The
  alternative's cost (a hand-off that works locally and fails in production) is not a price, it
  is a defect.
- The in-memory graph is reused for chunking, so the XML is parsed once per ingest rather than
  once per consumer.
- A new parser must follow the same return shape. There is no type or base class that forces it,
  so the convention rests on this record, the guidance in `AGENTS.md`, and review.

## Alternatives considered

No alternative is recorded. The obvious one — write the Turtle to object storage and pass its
key, which *would* survive a pod boundary — is **not** recorded as considered, and would trade
the memory cost for a storage write, a lifecycle question and a second place a document's
triples exist. The guidance states the in-memory rule as a requirement, with the K8s pod
isolation as its stated reason, and names no option it was chosen over.
