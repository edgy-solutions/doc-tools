# ADR-0142 — the read side scopes to the union, in one place

**Status:** built
**Date:** no ruling date is recorded; the rule is the read-side mirror of the write-side split
in [ADR-0141](ADR-0141-reproducibility-decides-the-graph.md) · recorded 2026-11-18
**Deciders:** a standing convention recorded in `AGENTS.md`; the implementation is
invincible-agent's and no deciding person is recorded here
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:160-167` §Domain Semantic Graph — READ-SIDE MIRROR;
`doc_tools/utils/jena_client.py:110-111` (the union, stated in `UnscopedUpdateError`'s
docstring). The enforcement is **invincible-agent's** `execute_sparql` (engine-o) — cited as
that repo's code, not read for this record
**Related:** [ADR-0141](ADR-0141-reproducibility-decides-the-graph.md),
[ADR-0143](ADR-0143-the-default-graph-is-invisible.md),
`docs/arch/components/ontologies-and-alignment.md`

## Context

Splitting a domain's RDF into a vocabulary graph and an `…_INSTANCES` graph
([ADR-0141](ADR-0141-reproducibility-decides-the-graph.md)) protects the instances from the
prime. It also moves the visibility problem one graph over.

Before the split, a consumer that scoped a read to `<http://internal/{DOMAIN}>` saw everything
that domain had. After the split, the same query sees the class definitions and **none of the
extracted instances** — and it sees them with no error, no empty-result signal that looks
different from "this domain has no matching entity". That is the same failure mode as a
default-graph write ([ADR-0143](ADR-0143-the-default-graph-is-invisible.md)): data that exists,
is well-formed, and is unreachable by the only reader that matters.

The second half of the problem is where the fix goes. If every caller composes its own
two-graph union, the rule survives only in the memory of whoever writes the next reader, and the
*first* reader to forget it reintroduces the bug for its own call path alone — which is the
hardest version to find, because every other reader still works.

## Decision

**A domain-scoped read scopes to the union
`{ <http://internal/{DOMAIN}> <http://internal/{DOMAIN}_INSTANCES> }`, and that rule is derived
in exactly one place — invincible-agent's `execute_sparql`, which injects a
`VALUES ?g { …vocab… …instances… } GRAPH ?g` union.**

- The union is the *minimum* scope for a domain read. The vocabulary graph alone is wrong, and
  reading unscoped is wrong for the separate reason in
  [ADR-0143](ADR-0143-the-default-graph-is-invisible.md).
- The derivation lives in the consumer's single entry point, so **a new SPARQL reader inherits
  it for free**. That is the whole point of the rule: correctness by construction for the
  default path, rather than a convention each caller re-implements.
- **A reader that bypasses `execute_sparql` owns re-deriving the union.** Bypassing is not
  forbidden; silently inheriting half the domain is. A caller that goes around the one place
  takes on the obligation explicitly, and this record is where that obligation is written down.

**This repo holds only half of the invariant.** doc-tools is a writer here: measured at the pin
it writes both graph names (`semantic_assets.py:1395`, `:1818`;
`ontology_assets.py:1223`) and performs **no domain-scoped SPARQL read at all** — its only read
path, `JenaClient.execute_query`, is used for the per-document `urn:doc:` graph
([ADR-0140](ADR-0140-one-named-graph-per-document-replaced-whole.md)). So nothing in this tree
can satisfy or violate the read rule today. The `built` status is the index's, and it is
built **in invincible-agent**.

## Consequences

- The union rule is a **cross-repo seam**: this repo's write-side split is only safe because
  another repo's reader scopes correctly. A change to either half without the other re-hides
  instances, and no test in this tree would notice.
- doc-tools must not add a domain-scoped read without either going through the mesh consumer or
  re-deriving the union locally — and if it ever does the latter, the rule then exists in two
  places and this record needs revisiting.
- Keeping the derivation in one place means the *shape* of the split is now a published
  contract: a third graph for a domain (a future producer with a third reproducibility class)
  changes a union in a repo that is not this one.
- A reader that bypasses the one place is not an error state. It is a choice with a named
  obligation, which is better than a prohibition nobody can enforce across repos.

## Alternatives considered

- **Each caller scopes its own union.** Rejected by the ruling: the rule would live in each
  caller's memory, and one forgetful reader reintroduces the invisible-instances bug on its own
  path while every other path keeps working.
- **Undo the split so one graph per domain is correct again.** That is
  [ADR-0141](ADR-0141-reproducibility-decides-the-graph.md)'s rejected alternative, and it costs
  the instances on the next prime. The read-side union is the price paid to keep them.
- **A Jena-side union graph or inference rule, so a plain `<http://internal/{DOMAIN}>` read
  returns both.** Not recorded as considered. It would move the invariant into the store's
  configuration — out of both repos' trees, and therefore out of review.
