# ADR-0145 — domain labels go on nodes, never on relationships

**Status:** accepted + built
**Date:** no ruling date is recorded; carried as a standing write convention in `AGENTS.md` ·
recorded 2026-11-18
**Deciders:** a standing convention of this repo, recorded in `AGENTS.md` §Figure/Image Nodes;
no deciding person is recorded
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:103-107` §Figure/Image Nodes 2;
`doc_tools/plugins/maintenance.py:289-296`, `doc_tools/plugins/manufacturing.py:394-401`,
`doc_tools/plugins/training.py:524-532` (the figure writes),
`doc_tools/assets/semantic_assets.py:2074-2090` (`_apply_post_sync_domain_labels`)
**Related:** [ADR-0140](ADR-0140-one-named-graph-per-document-replaced-whole.md) (where the
label is applied after the Neo4j import),
[ADR-0141](ADR-0141-reproducibility-decides-the-graph.md) (domain segregation in Jena, which is
by graph rather than by label)

## Context

Domain segregation in Neo4j is done with labels: downstream agents filter by `:MAINTENANCE`,
`:SUSTAINMENT` and so on, and a node without its domain label is invisible to them. So every
write that mints a node has to carry the label, and the figure write is the one that mints nodes
shared across documents (`Figure` nodes, keyed `fig_<ref>`).

The question this record settles is what happens on the **edge**. A writer that is thinking in
terms of "everything in this domain is tagged" naturally reaches for the same treatment on the
relationship — and in Neo4j a relationship has exactly one *type*, not a set of labels, so the
only way to express it is to fold the domain into the type name:
`[:REFERENCES_FIGURE_MAINTENANCE]`. One writer doing that forks the edge vocabulary per domain:
a traversal written as `[:REFERENCES_FIGURE]` silently matches nothing for that domain, and the
reader sees a figureless document rather than an error.

Measured at the pin, no plugin does this. The convention is what keeps it that way, and before
this record it existed only as the last sentence of one `AGENTS.md` bullet.

## Decision

**A domain label goes on the node. A relationship never carries one — not as a label, and not
folded into its type name.**

- The figure write is `MERGE (f:Figure:{domain_label} {id: "fig_" + fig_ref})` and the edge
  beside it is the bare `MERGE (ms)-[:REFERENCES_FIGURE]->(f)`
  (`doc_tools/plugins/maintenance.py:293-295`; the same pair in
  `manufacturing.py:398-400` and `training.py:530-532`).
- The label is interpolated from the plugin's own `domain_label`, so a plugin cannot label a
  node with another domain's label by accident.
- On the XML path the label is applied **after** the n10s import, to the imported `:Resource`
  nodes (`_apply_post_sync_domain_labels`, `semantic_assets.py:2074-2090`) — the same rule
  reached by a different route, because those nodes are minted by n10s rather than by a plugin's
  Cypher.
- **Relationship types stay domain-free**, so one traversal reads every domain. Edge semantics
  are the edge's; domain membership is the endpoints'.

## Consequences

- A traversal is written once. `[:REFERENCES_FIGURE]` matches in every domain, and a query that
  wants one domain filters on the node label it is already matching.
- Domain filtering and edge traversal stay separable: adding a domain adds a label, not an edge
  type, so no existing query has to learn a new type name.
- The rule is **not** enforced by a check. No test at the pin asserts that a relationship type
  carries no domain, and nothing in the write path would refuse one — the status is
  `accepted + built` because the ruling is in force and the code at the pin obeys it, not
  because a seal holds it. A plugin added tomorrow could violate it and pass.
- The same segregation question has a different answer in Jena, where it is settled by **graph**
  rather than by label ([ADR-0141](ADR-0141-reproducibility-decides-the-graph.md)). A reader
  moving between the two stores should not expect the mechanism to carry over.

## Alternatives considered

No alternative is recorded. The obvious one — encoding the domain in the relationship type,
since a Neo4j relationship cannot hold a second label — is **not** recorded as considered; the
convention states the outcome without arguing it. Its cost is the forked-traversal failure
described in `## Context`, which is this record's reconstruction of the reason and not a quoted
ruling.
