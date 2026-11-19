# ADR-0150 — a glossary-term URN uses the short name; the ontology URI is a property

**Status:** built
**Date:** no ruling date is recorded; carried as standing guidance in `AGENTS.md`
(§Semantic Binding Plane, "Phase 7 URN Standard") · recorded 2026-11-18
**Deciders:** the repo's standing guidance in `AGENTS.md`; no individual is named
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:170-171` (§Semantic Binding Plane 1–2) and `AGENTS.md:174` (5, "Neo4j
Sync"); implemented at `doc_tools/assets/semantic_linker.py:37-39` (`get_short_name`),
`:46-63` (the URN and the `customProperties` aspect) and `:196-228` (the runtime read)
**Related:** [ADR-0151](ADR-0151-semantic-tags-are-late-bound-through-hitl.md) (the flow this
URN travels on), [ADR-0147](ADR-0147-mesh-is-the-canonical-prefix.md) (the other
identifier-spelling convention)

## Context

A semantic tag binds a DataHub `Dataset` to an ontology class. The ontology's identifier is a
full URI (`http://…/ontology/maintenance#MaintenanceWorkOrder`); DataHub's identifier is a URN
(`urn:li:glossaryTerm:…`). Something has to decide which of the two the URN carries.

Putting the full URI in the URN is the tempting choice, because it needs no second lookup. It is
also the one that breaks: a URN is a flat, delimited string, and a URI inside it brings `:`,
`/` and `#` into a field those characters already structure. The term then renders in the
DataHub UI as a wall of URI, and a human approving a proposal is reading machine identity
instead of a term name.

Dropping the URI entirely is worse. The short name alone is **not** an identity: two ontologies
can both define `WorkOrder`, and the Neo4j write needs the full class URI to `MERGE` the right
`OntologyClass` node. Lose the URI and the graph binds a dataset to a name, not a class.

## Decision

**A glossary term's URN is `urn:li:glossaryTerm:<short name>`. The full ontology URI is stored
on the term entity under `customProperties.ontology_uri`, and every consumer reads it back from
there at runtime.**

- `get_short_name(uri)` takes the last path segment and then the last fragment
  (`semantic_linker.py:37-39`); the URN is built from it (`:46-47`).
- `propose_datahub_term` upserts a `glossaryTermInfo` aspect carrying
  `customProperties={"ontology_uri": ontology_uri}` before proposing the term, so the URI exists
  on the entity from the moment the term does (`:49-63`).
- `sync_approved_tags_to_neo4j` queries DataHub GMS for the term's `customProperties` and takes
  `ontology_uri` from there (`:196-224`) rather than reconstructing it from the URN, and that URI
  is what the `MERGE (o:OntologyClass {uri: $ontology_uri})` uses (`:237`).

Pinned by `tests/test_semantic_linker.py:21` (`get_short_name`), `:75` (the emit-and-propose
path) and `:91` (the sync reads the URI from DataHub).

## Consequences

- The DataHub UI shows a readable term, and the ontology URI is still authoritative — but it is
  authoritative **in one place only**, the term's custom properties. A term created by any other
  route without that property is a term this repo cannot bind.
- **There is a fallback, and it is lossy.** When no `ontology_uri` is found, the sync logs a
  warning and strips the URN prefix instead (`:225-228`), which yields the *short name* where a
  URI is expected, and writes it as an `OntologyClass.uri`. That is pinned deliberately by
  `tests/test_semantic_linker.py:107` — so the behaviour is intended, not accidental — but the
  node it produces is keyed on something that is not a URI and will not join to the ontology.
  A reader seeing a bare `WorkOrder` as a `uri` in Neo4j is looking at this path, not at a bad
  ontology.
- Every consumer pays one DataHub read per sync to recover the URI. That is the stated cost of
  late binding ([ADR-0151](ADR-0151-semantic-tags-are-late-bound-through-hitl.md)) and the reason
  the guidance says the URI must be fetched *at runtime* rather than cached at proposal time.
- Short names collide by construction. Two ontology classes with the same local name map to one
  URN, and nothing here detects that; the second proposal upserts the first's `ontology_uri`.
  No measurement of whether this has happened exists, so it is named here and not quantified.

## Alternatives considered

No alternative is recorded as considered. The two shapes the decision rules out are visible in
the rule itself — the full URI as the URN, and the short name with no URI anywhere — and the
guidance states the standard as a `MUST` rather than as a selection. The URN-parsing fallback in
the code is an error path, not a recorded alternative.
