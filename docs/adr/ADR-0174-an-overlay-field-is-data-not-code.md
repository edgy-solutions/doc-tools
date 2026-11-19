# ADR-0174 — a manufacturing overlay field is data, not code

**Status:** built
**Date:** no ruling date is recorded; carried in `AGENTS.md` as standing guidance · recorded
2026-11-18
**Deciders:** `AGENTS.md` §Manufacturing Overlay 1–3, this repo's standing guidance — no
individual ruling is on record
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:92-96`; `doc_tools/plugins/manufacturing_overlay.py:1-29` — a module
docstring carrying the full rationale and the persistence-kind table
**Related:** [ADR-0177](ADR-0177-config-names-the-case.md) (the standing rule this is an
instance of), [ADR-0104](ADR-0104-a-new-domain-is-a-schema-and-a-plugin.md),
[ADR-0145](ADR-0145-domain-labels-go-on-nodes-only.md),
[ADR-0175](ADR-0175-proprietary-prompt-text-is-not-committed.md) (the same problem for prompt
*text*)

## Context

A manufacturing work instruction has an irreducible core — procedure and step identity, the
instruction text, the action verb, tooling, figure references — and then an open-ended set of
analytical flags, classifications and integration hooks layered on top. The second set is where
deployments differ, and some of those fields cannot enter this repository at all.

Before the split, adding a field meant three edits in three places: the BAML class so the model
extracts it, the plugin's `to_graph_queries` so it reaches Neo4j, and the SPARQL emitter so it
reaches Jena. A field added in two of the three is a field that extracts and does not persist,
or persists under a name nothing queries — and the failure is silent, because an absent property
looks exactly like a document that did not mention it. Worse, a proprietary field handled this
way has its name and its description sitting in the commit history for ever.

## Decision

**Adding or changing a manufacturing overlay field is a data edit, never a code edit.**

- `ManufacturingStep` is split into a public **base** (identity, text, action, tooling, figures —
  stable and committed) and a data-driven **overlay**
  (`doc_tools/plugins/manufacturing_overlay.py`).
- An `OverlayField` descriptor (`:74-95`) declares **both** halves at once: how the field is
  extracted (the BAML `description`) and how it persists — `neo4j_attr`, `related` (a typed node
  and edge off the step), `rdf_literal`, `rdf_relation`, or a combination. The kinds and the
  shapes they render are tabulated in the module docstring at `:23-27`.
- Two overlays compose at runtime (`:219-221`, `active_overlay`): `DEFAULT_OVERLAY`, twelve
  committed non-proprietary fields (`:107-171`), followed by a proprietary overlay loaded from
  the secret JSON file whose path is given by the `MANUFACTURING_OVERLAY_SPEC` environment
  variable (`:208-217`). **No value of that variable, and no proprietary field name, appears in
  this repository or in this record.**
- The BAML class is `@@dynamic`; proprietary fields are injected through `TypeBuilder` at both
  `ManufacturingPlugin` call sites (`:412-427`, `inject_proprietary_properties`) and ride the
  `extra="allow"` mirror model through to `to_graph_queries`. Document-scope fields are routed to
  `MatAugmentation` and merged across the per-chunk responses (`:429-452`,
  `extract_document_fields`).
- Unset secret means **no-op**: `load_proprietary_overlay` returns `[]` (`:208-217`), so the
  public default is the whole overlay.
- So the rule in one line, `AGENTS.md:96`: edit the overlay descriptor or the secret spec —
  **never** `to_graph_queries` and never the BAML class.
- Pinned by `tests/test_manufacturing_overlay.py` (twelve tests covering every persistence kind,
  the compose order, the scope routing and the unset case) and
  `tests/test_manufacturing_graph_golden.py` for persistence. End-to-end extraction is proved by
  `tests/test_manufacturing_extraction_ollama.py`, which skips unless `LLM_BASE_URL` is set.

## Consequences

- A field is added in one place and cannot extract-without-persisting, because the descriptor is
  the single declaration of both.
- A deployment can add **its own** fields without a code change and without a fork — which is
  the test (3) of [ADR-0177](ADR-0177-config-names-the-case.md) passing, concretely.
- Proprietary field names and descriptions never enter the tree or the history. The cost is that
  nobody reading this repository can tell what the deployed overlay actually extracts; the
  committed default is a lower bound, not the shape.
- The module is pure and deterministic apart from the one optional secret read (`:28`), so the
  rendering half can be tested without a model or a graph.
- Enum-valued proprietary fields are injected as free strings, because their allowed values live
  in the secret rather than in the tree (`:405-409`). The model therefore gets no value list for
  those fields and the graph gets no enforcement of one.
- A malformed secret spec is a startup-time failure of a `json.load`, not a validated schema
  error. No record of a decision to validate it exists.
- The overlay only covers manufacturing. The same split is not recorded as ruled for any other
  domain's augmentation class.

## Alternatives considered

- **Hard-code the fields in the BAML class and `to_graph_queries`.** This is what the split
  replaced. Rejected because it makes every field a three-place edit and makes a proprietary
  field uncommittable without a fork.
- **A fork or a patch overlay per deployment.** Not recorded as considered; it is the shape
  [ADR-0177](ADR-0177-config-names-the-case.md) test (3) exists to rule out.
- **Declare extraction and persistence separately — a BAML description in one file, a mapping in
  another.** Not recorded as considered. The docstring's reasoning at `:12-15` argues against it
  by implication: the point of the descriptor is that adding or moving a field never touches the
  writer.
