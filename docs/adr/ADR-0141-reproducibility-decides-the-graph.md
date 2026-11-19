# ADR-0141 — producers with different reproducibility must not share a graph

**Status:** built + measured
**Date:** 2026-10-16 (the instance-graph write on the XML path ruled); the collision the
invariant cures predates it · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris (ruling of 2026-10-16, recorded in the asset);
the invariant itself was forced by a collision in a running system, not chosen on taste
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:135-158` §Domain Semantic Graph — THE INVARIANT;
`doc_tools/assets/semantic_assets.py:1753-1766` (the ruling, in the asset),
`:1818` and `:1395` (the two writers choosing `…_INSTANCES`),
`doc_tools/plugins/sustainment.py:2726-2732`
**Related:** [ADR-0140](ADR-0140-one-named-graph-per-document-replaced-whole.md),
[ADR-0142](ADR-0142-the-read-side-union-lives-in-one-place.md) (the read-side half this split
makes necessary), [ADR-0143](ADR-0143-the-default-graph-is-invisible.md),
[ADR-0144](ADR-0144-the-vocabulary-path-appends.md),
[ADR-0146](ADR-0146-the-supersede-key-is-the-slug.md)

## Context

Two different producers write RDF for the same semantic domain:

1. **Vocabulary** — the class-definition TTLs, ingested by `ingest_ontology_to_jena`. These are
   **manifest-reproducible**: the manifest lists them, and the platform's prime can rebuild them
   from source at any time. Because it can, it does: the prime is **DROP-first** on every
   re-ingest (`clear_ontology_graphs`, in invincible-agent).
2. **Runtime instances** — a plugin's `to_graph_queries()` SPARQL, and the XML path's second
   write. These are the output of an extraction run over a document that arrived once. They are
   **not reproducible**: nothing can regenerate them from a manifest.

Put both in `<http://internal/{DOMAIN}>` and the first prime after an extraction deletes the
extraction. The ruling is not hypothetical, which is why it is `measured`: **the collision
actually happened.** The prime meant to land `pcn_extension` for the dogfood would have
destroyed the extracted parts first (`AGENTS.md:154-155`). A reproducible producer's clean-slate
behaviour is correct for it and fatal for its graph-mate.

The danger is also quiet. A DROP-first prime leaves a well-formed, readable vocabulary graph
behind. Nothing errors. The instances are simply gone, and the next reader concludes the
extraction never ran.

## Decision

**Reproducibility, not domain, decides the graph: a manifest-reproducible producer and a
non-reproducible one may never write to the same named graph.**

- Vocabulary goes to `<http://internal/{DOMAIN}>` (`doc_tools/assets/ontology_assets.py:1223`).
  The prime drops it, which is correct for data the manifest can rebuild.
- Runtime instances go to `<http://internal/{DOMAIN}_INSTANCES>`, a separate graph the prime
  never touches. Two writers do this at the pin: the plugin dispatch
  (`semantic_assets.py:1395`) and the XML path's second write (`:1818`, chosen from the
  document's resolved domain).
- **It is enforced on both ends, not by convention.** The writer side cannot opt out — the
  graph name is computed by the asset, and `JenaClient.execute_update` refuses an unscoped
  update outright ([ADR-0143](ADR-0143-the-default-graph-is-invisible.md)). The clearer side
  drops **manifest-listed graphs only**, so an `…_INSTANCES` graph is outside its reach even if
  a writer got it wrong. Either end alone would leave the invariant one mistake from a wipe.
- A document whose domain cannot be resolved **raises** rather than defaulting
  (`:1808-1817`): a tolerated skip here is a document whose instances silently never land.

## Consequences

- A domain's triples now live in **two** graphs, so every domain-scoped read must scope to the
  union or the instances are invisible again — one graph over from the bug the GRAPH clause
  fixed. That obligation is [ADR-0142](ADR-0142-the-read-side-union-lives-in-one-place.md), and
  it is the direct cost of this split.
- The prime keeps its clean-slate property, which is what makes the vocabulary reproducible at
  all. Nothing had to be weakened to protect the instances.
- The rule generalises past the two producers that exist: any new writer must declare which
  side of the reproducibility line it is on *before* it picks a graph name. "Which domain is
  this?" is the wrong first question.
- Instance data is now the only RDF in this system with no rebuild path. It is protected from
  the prime, and that means a genuinely bad instance write has to be superseded deliberately
  ([ADR-0146](ADR-0146-the-supersede-key-is-the-slug.md)) rather than cleared by a re-prime.

## Alternatives considered

- **One graph per domain, with the prime clearing selectively.** This is the shape the collision
  came from. Rejected: it makes the clearer responsible for knowing every writer's provenance,
  and a clearer that must enumerate exceptions is one commit away from wiping the data again.
  The split moves the decision to the write, where the producer already knows the answer.
- **Make instances reproducible — keep the source documents and re-extract on every prime.**
  Not recorded as considered. It would mean a prime re-runs extraction over the whole corpus
  (LLM calls, per-document), which is the opposite of what a prime is for.
- **Convention only: document the rule and trust writers.** Explicitly rejected by the ruling —
  `AGENTS.md:157-158` says the rule is enforced on both ends "not by convention alone". The
  collision happened under a convention.
