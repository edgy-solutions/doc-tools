# ADR-0148 — one `MIL` namespace across every standard parser

**Status:** built
**Date:** no ruling date is recorded; carried as standing guidance in `AGENTS.md` · recorded
2026-11-18
**Deciders:** the repo's standing guidance in `AGENTS.md` §Extension Patterns; no individual is
named
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:110` (§Multi-Standard Semantic Parsing 2) and `AGENTS.md:106`
(§Figure/Image Nodes 3); implemented in `doc_tools/parsers/s1000d_rdf.py:74`,
`doc_tools/parsers/dita_rdf.py:17`, `doc_tools/parsers/iads_rdf.py:17`,
`doc_tools/parsers/mil_std_40051_rdf.py:30`, `doc_tools/parsers/mil_info_code_map.py:49`,
`doc_tools/utils/xml_chunks.py:53-56`
**Related:** [ADR-0149](ADR-0149-a-parser-returns-rdf-not-a-path.md) (what a parser hands back),
[ADR-0145](ADR-0145-domain-labels-go-on-nodes-only.md) (the other half of §Figure/Image Nodes),
[ADR-0147](ADR-0147-mesh-is-the-canonical-prefix.md) (the mesh-side namespace constant)

## Context

Four standard-specific graph builders exist — `S1000dGraphBuilder`, `DitaGraphBuilder`,
`IadsGraphBuilder`, `MilStd40051GraphBuilder` — and each one turns a different XML dialect into
RDF about the same kind of thing: a technical data module, its procedural steps, its parts and
its figures.

If each parser minted its own namespace, the triples would be *correct per parser* and
**unjoinable across parsers**. A consumer asking "which data modules reference this figure"
would have to know which dialect each document arrived as, and a SPARQL query written against
S1000D output would return nothing for a DITA document carrying the same facts. Nothing fails
loudly in that situation: each document's graph is internally consistent, and the join just
comes back empty.

The traversal consumers are concrete. `doc_tools/utils/xml_chunks.py` walks `mil:hasFigure`
from the root to each `Figure` URI to build chunk text (`:170`, `:195`), and
`doc_tools/utils/content_kind.py:351` declares a kind's `target_ontology_class` as
`http://edgy-solutions.com/ontology/mil#DataModule`. Both are written against one namespace,
not four.

## Decision

**Every standard parser writes into the single `MIL` namespace
`http://edgy-solutions.com/ontology/mil#`, and a figure is attached as `mil:Figure` through the
`mil:hasFigure` predicate.**

- Each builder binds the namespace on construction — `self.MIL = Namespace(…)` — and derives its
  predicates from it, including `self.HAS_FIGURE = self.MIL.hasFigure`
  (`s1000d_rdf.py:86`, `dita_rdf.py:28`, `iads_rdf.py:29`).
- `MilStd40051GraphBuilder` writes the edge directly, at
  `mil_std_40051_rdf.py:256` and `:304`.
- Readers bind the same string: `xml_chunks.py:53-56` (`_MIL_NS`, `_MIL_HAS_FIGURE`) and
  `mil_info_code_map.py:49` (`MIL_NS`).
- The class vocabulary that these triples are supposed to satisfy is the `mil` TBox, which is
  Lane 1's to declare; this repo's obligation is to emit into that namespace and nothing else.

Pinned by `tests/test_parsers_rdf.py`, which declares `MIL` once (`:25`) and asserts the figure
edge across dialects — `:96` for S1000D and `:860`, `:893`, `:928` for MIL-STD-40051 — so a
parser that drifted to its own namespace fails. `tests/test_xml_chunk_identity.py:42` pins the
reader's side of the same predicate.

## Consequences

- One query shape works across all four dialects, and a new parser inherits the join for free by
  binding the same namespace.
- **The namespace literal is repeated at seven sites** (five parsers/maps and two readers) with
  no shared constant. The tests pin the value from the outside, which is what makes `built`
  honest here, but a sixth parser added without a test would carry a typo'd namespace into a
  graph that reads as empty rather than as broken. Collapsing the seven literals into one
  constant is a cleanup this record does not make and does not authorise.
- A term this repo emits may be undeclared in the `mil` TBox. That is a separate, known gap and
  is not a namespace question: the namespace is right whether or not the class exists.

## Alternatives considered

No alternative is recorded. The obvious one — a namespace per standard (`s1000d:`, `dita:`,
`iads:`), with an alignment layer mapping them onto one another — is **not** recorded as
considered anywhere in the tree, and the guidance states the unified namespace as a
requirement rather than as a choice between options.
