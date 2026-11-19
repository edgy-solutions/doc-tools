# ADR-0140 — a document is isolated in its own named graph, replaced whole

**Status:** built
**Date:** no ruling date is recorded; the convention predates the census and is measured from
the tree at the pin · recorded 2026-11-18
**Deciders:** a standing write convention of this repo, recorded in `AGENTS.md`; no deciding
person is recorded
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:127-134` §Hybrid Graph Synchronization & Revisioning 1–6;
`doc_tools/assets/semantic_assets.py:1733-1750` (the `urn:doc:` PUT in `upload_to_jena`),
`:1960-2009` (the Neo4j wipe and the scoped `CONSTRUCT` in `sync_jena_to_neo4j`)
**Related:** [ADR-0141](ADR-0141-reproducibility-decides-the-graph.md) (the *other* graph the
same asset writes, where PUT is forbidden),
[ADR-0146](ADR-0146-the-supersede-key-is-the-slug.md),
[ADR-0149](ADR-0149-a-parser-returns-rdf-not-a-path.md),
`docs/arch/components/ontologies-and-alignment.md`

## Context

A document is re-dropped. The second drop of the same document carries *different bytes* — a
revised module, a corrected figure reference, fewer steps than before. Without an isolation
rule, the second ingest's triples are added beside the first's: the reasoning engine then holds
two revisions of one document at once, no reader can tell which is current, and the difference
between "this document says X" and "this document used to say X" is lost for good.

The same failure has a second half in Neo4j. The sync imports from Jena through `n10s`; if the
previous revision's nodes are still there, the import merges onto them and the stale nodes
survive. This repo has already had exactly that: the wipe step used to swallow the SPARQL
exception and fall back to a one-element URI list, so a previous revision's triples stayed in
Neo4j across re-ingests **and the step still reported success**
(`doc_tools/assets/semantic_assets.py:1967-1973`).

## Decision

**Every document gets its own Jena named graph, named from its identifier, and a re-ingest
replaces that graph whole rather than adding to it.**

- The graph name is `urn:doc:{s3_key}` — the document's own identifier, URL-quoted into the
  Graph Store Protocol request (`:1733-1734`).
- The write is `httpx.put` to `{jena}/{dataset}/data?graph=…` (`:1743`). PUT, not POST: the
  Graph Store Protocol replaces the named graph's contents, so the old revision is gone rather
  than merged with.
- Before the Neo4j import, every subject in that named graph is fetched from Jena
  (`SELECT DISTINCT ?s WHERE { GRAPH <urn:doc:…> { ?s ?p ?o } }`, `:1960`) and each is
  `DETACH DELETE`d (`:1998`). A query failure **raises**; a zero-subject result raises too,
  because the upload ran immediately before and an empty graph means the write did not land.
- The fetch back into Neo4j is a `CONSTRUCT` scoped to that one graph (`:2009`), so a sync pulls
  one document and never the store.
- After the import, the domain label is applied to the imported `:Resource` nodes
  (`_apply_post_sync_domain_labels`, `:2074`), per
  [ADR-0145](ADR-0145-domain-labels-go-on-nodes-only.md).

**This rule governs the per-document graph only.** The domain graphs are a different write with
a different rule, and PUT is wrong there — see
[ADR-0141](ADR-0141-reproducibility-decides-the-graph.md) and
[ADR-0144](ADR-0144-the-vocabulary-path-appends.md).

## Consequences

- A document's revision history is **not** kept in Jena. Whole-graph replacement buys "the graph
  holds the current state" and costs the ability to ask what the previous revision said. Nothing
  in this repo reads a previous revision, so the cost is unrealised — but it is a cost.
- Per-document isolation means a document can be re-driven, or deleted, without touching a
  sibling. That is what makes the Neo4j wipe safe to scope by subject here, and it is the
  opposite of the shared-subject situation on the domain-instance side
  ([ADR-0146](ADR-0146-the-supersede-key-is-the-slug.md)).
- Both the wipe and the n10s fetch fail loudly rather than degrading. A run that cannot clear the
  old revision fails instead of reporting success on a half-replaced graph.
- One divergence, recorded rather than repaired: `AGENTS.md` 3 states the wipe as
  `MATCH (n:Resource {uri: $uri}) DETACH DELETE n` **on the root node URI**, while the code
  deletes *every* subject the named graph holds. The code is the broader behaviour and is
  deliberate (it is the fix for the silent-degrade bug above); the `AGENTS.md` wording lags it.
  This row belongs in `DEBT.md` as a doc-wording correction, not as a behaviour dispute.

## Alternatives considered

- **One graph for everything, triples added per ingest.** This is what the rule exists to
  prevent, and its failure is recorded above: two revisions coexisting with no way to tell them
  apart. Not recorded as *considered* — it is the state the convention replaced.
- **POST/append into the per-document graph, with a scoped DELETE first.** This is what the
  domain-instance write does, for reasons specific to a *shared* graph
  ([ADR-0146](ADR-0146-the-supersede-key-is-the-slug.md)). It is not recorded as considered for
  the per-document graph, and it would buy nothing there: the graph has exactly one document's
  triples, so replacing it whole and deleting its subjects are the same act.
