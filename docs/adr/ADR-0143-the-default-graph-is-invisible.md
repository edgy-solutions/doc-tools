# ADR-0143 — RDF in Jena's default graph is invisible to the mesh

**Status:** built + measured
**Date:** no ruling date is recorded; the defect and the fix are measured from the tree and from
a live-Fuseki seal · recorded 2026-11-18
**Deciders:** a property of the mesh resolver, not a choice — recorded because the *write* it
condemns succeeds silently
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:135-141` §Domain Semantic Graph 2;
`doc_tools/utils/jena_client.py:106-118` (`UnscopedUpdateError`), `:187-267`
(`update_is_graph_scoped` / `scope_update_to_graph`), `:286-325` (`execute_update` refuses);
sealed by `doc_tools_tests/test_jena_update_is_graph_scoped.py` and, against a real Fuseki,
`doc_tools_tests/test_default_graph_stays_empty.py`
**Related:** [ADR-0141](ADR-0141-reproducibility-decides-the-graph.md),
[ADR-0142](ADR-0142-the-read-side-union-lives-in-one-place.md),
[ADR-0145](ADR-0145-domain-labels-go-on-nodes-only.md)

## Context

The mesh resolver scopes **every** SPARQL read to the per-domain named graphs. A SPARQL
`INSERT DATA` with no `GRAPH` clause lands in Fuseki's default graph, which those reads never
touch. The write returns 200. The triples are in the store. Nothing can ever query them back
out.

Measured at the point the fix was written: of the four SPARQL-emitting plugins, **only
`sustainment.py` wrapped its triples in a `GRAPH <…>` clause**. The other three — compliance,
maintenance, manufacturing — emitted a bare `INSERT DATA`
(`doc_tools_tests/test_jena_update_is_graph_scoped.py:3-8`). Three domains' worth of extraction
output was being written successfully into a graph no reader scopes to.

This is the same class of failure as reading only the vocabulary graph
([ADR-0142](ADR-0142-the-read-side-union-lives-in-one-place.md)) — well-formed data, no error,
unreachable — and it is why both halves are recorded separately. Here the data never becomes
visible at all; there it stops being visible when the split happens.

## Decision

**A SPARQL Update that would land in Jena's default graph is refused, not sent — and the
scoping decision lives in the single writer rather than in each plugin.**

- A plugin's `to_graph_queries()` SPARQL must target the domain's instance graph,
  `GRAPH <http://internal/{DOMAIN}_INSTANCES>` (`AGENTS.md:146-148`), per
  [ADR-0141](ADR-0141-reproducibility-decides-the-graph.md).
- `JenaClient.execute_update` is where that is enforced, with three outcomes
  (`doc_tools/utils/jena_client.py:286-325`): an already-scoped body passes through unchanged;
  an unscoped body with a `graph_uri` is wrapped by `scope_update_to_graph`; a body that cannot
  be scoped safely — no `INSERT DATA`, unbalanced braces, an unsafe graph URI, or no
  `graph_uri` at all — raises `UnscopedUpdateError` **before any HTTP call is made**.
- The refusal message names the fix (`:318-324`): pass
  `graph_uri=f'http://internal/{domain_label}_INSTANCES'`, or scope the query yourself.
- Scoping is textual, and deliberately careful about it: `_ordinary_mask`
  (`:125-184`) classifies every character as ordinary syntax or as part of a string literal, an
  angle-bracket IRI or a `#` comment, so the word `GRAPH` inside a literal cannot be mistaken
  for a clause.

## Consequences

- A plugin can no longer write invisibly, even by accident — **the failure moved from silent to
  loud**, which is the whole value. A plugin that emits an unscopable body now fails its run
  instead of reporting success on triples nobody will read.
- The per-plugin seals assert the **outcome** (exactly one `GRAPH` clause naming the correct
  `…_INSTANCES` graph, braces balanced), not which side did the scoping, so a plugin later fixed
  to self-scope does not break the seal.
- The measurement is a real one, and it costs something to keep: the outcome seal
  `test_default_graph_stays_empty.py` needs a live Fuseki. It is guarded by `REQUIRE_JENA` —
  unset, a workstation without Fuseki skips legitimately; set, as CI sets it, a missing Fuseki
  is a **failure, not a skip**. That guard exists because a grey check that reads as a pass is a
  check that gates nothing, a trap this lane has already had to close once elsewhere.
- Nothing stops a *future* reader from querying the default graph deliberately. The rule is
  about where writes land, and it holds only while the resolver's scoping holds
  ([ADR-0142](ADR-0142-the-read-side-union-lives-in-one-place.md)).

## Alternatives considered

- **Fix the three plugins to emit their own `GRAPH` clause.** Rejected in favour of moving the
  decision into the single writer: four plugins self-scoping is four places to get it wrong, and
  a fifth plugin would start wrong by default. The seal was written so that self-scoping remains
  *allowed* — a scoped body passes through untouched — just not required.
- **Default the graph silently when the caller gives no `graph_uri`.** Rejected by the
  implementation: with no `graph_uri` the writer cannot know the domain, and guessing one would
  write a domain's instances into another domain's graph — a worse, quieter error than the one
  being fixed. It raises instead.
- **Let the default-graph write happen and fix the read side to include the default graph.**
  Not recorded as considered. It would make every domain read see every other domain's
  unscoped triples, destroying the domain scoping the resolver exists to provide.
