# ADR-0212 — dynamic Cypher is bounded to a label name; every value is a parameter

**Status:** accepted
**Date:** not recorded; in force as a standing guardrail · recorded 2026-11-18
**Deciders:** not recorded; stated in `AGENTS.md` §Safety Guardrails (`AGENTS.md:60`)
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:61` — a one-line guardrail, which was the **only** written statement of
this ruling; its one enforcement is the docstring and assertions at
`tests/test_provenance_invariant.py:96-107`
**Related:** [ADR-0104](ADR-0104-a-new-domain-is-a-schema-and-a-plugin.md) (where a domain label
comes from), [ADR-0121](ADR-0121-a-null-domain-type-is-not-a-defect.md)

## Context

Neo4j parameterises values but **not labels**. `MERGE (n:$label {id: $id})` is not valid Cypher,
so a pipeline that writes `Document`/`Chunk` nodes for one ingestion and domain-suffixed nodes
for another has no choice but to build part of the query as a string. Every plugin in this repo
does: measured at the pin there are **8** f-string interpolations of
`config.graph_node_label`, **13** of `config.graph_child_label` and **44** of
`self.domain_label`, across five plugin modules.

String-built Cypher is the standard injection shape, and it is also the standard *syntax-error*
shape — a label with a space in it fails at the server with a message that points at the
generated text rather than at the code that generated it. The rule exists to keep the
string-built part as small as it can be and to make the rest unable to carry anything.

## Decision

**Only bounded f-strings, against `config.graph_node_label` and its siblings; everything else is
parameterised natively** (`AGENTS.md:61`).

- The interpolated name must come from a declared configuration field or a module constant. The
  label fields are defaults on `IngestionConfig` — `graph_node_label: str = "Document"`,
  `graph_child_label: str = "Chunk"` (`doc_tools/config.py:7-8`).
- Each write site **binds the label to a local name once** and interpolates that, rather than
  reaching into config inside each query string: `node_label = config.graph_node_label` /
  `child_label = config.graph_child_label`
  (`doc_tools/assets/semantic_assets.py:513-514`). `doc_tools/plugins/document.py:160-161` does
  the same with a `getattr` default, so a config object missing the field still produces
  `Document`/`Chunk` rather than `None` in the query text.
- **Every value is a `$`-parameter.** Ids, titles, dates, text — all of it, including values that
  look safe.
- The invariant is asserted, for the one fragment that has a test:
  `test_the_fragment_parameterises_every_value` checks that the generated Cypher contains **no
  quote character at all**, on the reasoning that a literal value could not be written without
  one, and that each field appears as `$`-parameter
  (`tests/test_provenance_invariant.py:96-107`).

## Consequences

- The quote-character assertion is the useful trick to copy: it is a one-line, whole-fragment
  check that needs no parser and cannot be satisfied by a query that inlines a value.
- It covers **one** fragment. The 65 label interpolations counted above have no equivalent test;
  the rule holds there by review only.
- **Where the rule as written and the tree disagree — a row for [DEBT.md](DEBT.md).** The
  guardrail names `config.graph_node_label` ("etc"). The widest interpolated name is not a
  config field at all: `self.domain_label` is a property derived at runtime from the plugin's
  `domain_type` — `self.domain_type.upper().replace(" ", "_").replace("-", "_")`
  (`doc_tools/plugins/base.py:175-180`) — and `domain_type` arrives as a workflow tag in run
  config, not as a defaulted field. The transformation normalises case and separators; it is not
  an allow-list, so a braces-or-backtick-bearing `domain_type` would reach the query text. No
  reading of the tree shows that happening, and it is 44 of the 65 sites. The rule should either
  name `domain_label` as in scope and require a validating sanitiser, or the sanitiser should
  reject anything outside `[A-Z0-9_]`.
- A label that changes shape changes the graph silently: nothing in the tree compares the label
  a query writes against the label a later query reads, so a divergence shows up as an empty
  result rather than as an error.

## Alternatives considered

- **`apoc.merge.node(labels, props)` to pass labels as data.** Not recorded as considered. It
  would remove the string building entirely, at the cost of depending on APOC being installed in
  every target Neo4j.
- **One fixed label set for all domains, with the domain as a property.** Not recorded as
  considered here; the domain label is part of the graph contract
  ([ADR-0104](ADR-0104-a-new-domain-is-a-schema-and-a-plugin.md)), and queries filter on it.
- **Ban dynamic Cypher outright.** Not available: Neo4j cannot parameterise a label, which is
  the constraint the rule is written around.
