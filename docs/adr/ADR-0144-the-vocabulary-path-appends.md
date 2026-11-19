# ADR-0144 — the vocabulary path appends; only the instance path replaces

**Status:** built
**Date:** 2026-07-22 (the collapse found; the fix is commit `71a66f9`) · recorded 2026-11-18
**Deciders:** a property of the Graph Store Protocol against a many-files-one-domain asset, not
a style choice; no deciding person is recorded
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:142-145` §Domain Semantic Graph 1 (`71a66f9`);
`doc_tools/assets/ontology_assets.py:1257-1297` — a code comment carrying the measurement, which
was the only statement of *why* beyond the one-line note in `AGENTS.md`
**Related:** [ADR-0140](ADR-0140-one-named-graph-per-document-replaced-whole.md) (the PUT rule
this one is **not**), [ADR-0141](ADR-0141-reproducibility-decides-the-graph.md),
[ADR-0146](ADR-0146-the-supersede-key-is-the-slug.md),
`docs/arch/components/ontologies-and-alignment.md`

## Context

`ingest_ontology_to_jena` is partitioned **per file**, and **many files map to one semantic
domain**: one domain's vocabulary is assembled from several source TTLs contributed under
different prefixes by different stewards. The domain graph is `<http://internal/{DOMAIN}>` —
one graph, N partitions writing into it.

The per-document rule one section earlier in `AGENTS.md` says *PUT first*
([ADR-0140](ADR-0140-one-named-graph-per-document-replaced-whole.md)), and PUT under the Graph
Store Protocol **replaces the whole named graph**. Applied here, each partition's PUT wiped the
partitions that had already landed, and the domain graph ended up holding whichever file
finished last.

That is not hypothetical. Found 2026-07-22: one domain's graph held only its extension file's
ten classes, and the core ontology that should have been beside them was destroyed
(`doc_tools/assets/ontology_assets.py:1261-1263`, the collapse named at `:1262`). Silently —
every partition reported success, because each PUT *did* succeed.

The trap is that the two rules look like one rule. A reader who has internalised "Jena PUT
first" from the revisioning section applies it to the vocabulary path and reintroduces the
collapse.

## Decision

**The domain vocabulary path uses POST/append. PUT-replace belongs to the per-document graph
only.**

- The write is `client.post` to the Graph Store Protocol endpoint
  `{jena}/{dataset}/data?graph=<http://internal/{DOMAIN}>`
  (`doc_tools/assets/ontology_assets.py:1274`, `:1291-1297`). POST merges the file's triples
  into the graph, so N partitions accumulate instead of overwriting.
- **Idempotency across re-runs is not the writer's job.** It comes from the orchestrator
  clearing each domain graph **once** before the per-file ingests (invincible-agent's prime,
  `clear_ontology_graphs`), so append-only never doubles blank-node structures on a re-prime.
  That clear-once discipline is the same mechanism [ADR-0141](ADR-0141-reproducibility-decides-the-graph.md)
  constrains to manifest-listed graphs.
- **No auto-retry on this POST.** A `ReadTimeout` is ambiguous — the server may have applied the
  merge — so a blind retry could double the graph, and doubling is exactly what the clear-once
  discipline exists to prevent. A failed partition is re-driven by a re-prime
  (clear, then a single append), not by re-POSTing (`:1283-1288`).
- The HTTP timeout is 120s read/write with a short connect (`:1289`), because the large
  ontologies' merge into TDB2 exceeds httpx's 5s default when the prime launches every partition
  at once — a spurious partition failure that succeeded on a quieter re-run.

## Consequences

- A domain's vocabulary can be contributed by any number of files under any number of prefixes,
  which is the point: the path an ontology arrives under is the *source* axis, not the semantic
  one, a distinction the asset's own domain-resolution docstring (`:1112-1133`) makes
  explicitly.
- Correctness now depends on a step **in another repo**: if the prime stops clearing a domain
  graph exactly once before the ingests, append-only starts accumulating duplicates. The writer
  cannot detect this, and no test in this tree would.
- A partition failure is not locally recoverable. "Re-run the failed partition" is the wrong
  instinct here and the comment says so; the recovery unit is the whole domain.
- Two write disciplines now coexist in one repo for one store, distinguished only by which graph
  is being written. That is a standing hazard, and it is why this record and
  [ADR-0140](ADR-0140-one-named-graph-per-document-replaced-whole.md) cite each other.

## Alternatives considered

- **Keep PUT and merge the files before writing** — one partition per domain that reads every
  TTL and PUTs the union. Not recorded as considered. It would undo the per-file partitioning
  (and its per-file retry and provenance) to buy a replace semantics nothing needs, since the
  prime already clears the graph.
- **POST with an auto-retry on timeout.** Explicitly rejected in the code comment: a POST that
  may have been applied cannot be safely retried, and the failure mode of guessing wrong is a
  doubled graph with duplicated blank-node structures.
- **PUT per file into per-file graphs, unioned at read time.** Not recorded as considered. It
  would add a graph per source TTL to a read-side union that is already a cross-repo
  obligation ([ADR-0142](ADR-0142-the-read-side-union-lives-in-one-place.md)).
