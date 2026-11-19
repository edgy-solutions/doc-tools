# ADR-0153 — every legacy extractor emits one uniform contract

**Status:** built
**Date:** no ruling date is recorded; carried as standing guidance in `AGENTS.md`
(§Legacy Schema & Design Metadata Extraction) · recorded 2026-11-18
**Deciders:** the repo's standing guidance in `AGENTS.md`; no individual is named
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:121` (§Legacy Schema 1, "Uniform Output Contract") and `AGENTS.md:125`
(5, "Adding a New DB Dialect"); implemented at
`doc_tools/components/oracle_extractor.py:37-63`,
`doc_tools/components/sqlserver_extractor.py:38-68`,
`doc_tools/components/design_parser.py:58-93` and
`doc_tools/assets/semantic_linker.py:85-102`
**Related:** [ADR-0151](ADR-0151-semantic-tags-are-late-bound-through-hitl.md) (what happens to
these dossiers once merged), [ADR-0102](ADR-0102-assets-and-declarative-components.md) (each
extractor is a declarative component),
[ADR-0112](ADR-0112-a-kind-may-declare-no-domain.md) (the domain question elsewhere in the repo)

## Context

Four legacy sources feed the semantic binding plane, and no two look alike: Oracle
(`ALL_TAB_COMMENTS` through `oracledb`), SQL Server (`MS_Description` extended properties
through SQLAlchemy/`pyodbc`), .NET EDMX conceptual models (`EntityType` /
`NavigationProperty` / `Documentation`), and modelling-tool JSON exports (`tables[]` with
`name` / `description` / `relations`).

Each one's natural output shape is its own. If each asset returned that shape, the merge
downstream would need a branch per dialect, and the classifier's input would differ by source —
so the same table described identically in two tools could classify differently, and a new
dialect would mean editing the consumer as well as adding a producer. The consumer is also the
place where the credential and the ontology POST live, so every dialect addition would touch the
one asset with the most to break.

There is a second failure the contract forecloses. The ontology classifier needs a `domain` to
scope its answer. An extractor that omits it hands the classifier a table with no scope, which
is not an error — it is a worse classification, silently.

## Decision

**Every legacy extractor emits exactly `{"schema.table_name": {"description": …, "domain": …}}`,
always injects a `domain` tag (default `DATA_ENGINEERING`), and converges in
`apply_semantic_tags`. A new dialect adds a component; it may not bypass the consumer.**

- `OracleExtractorComponent` documents the shape in its asset docstring and builds it row by row
  (`oracle_extractor.py:37-38`, `:57-60`, `:63`), tagging with its component-level `domain` field
  (`:13`, `:24`).
- `SqlServerExtractorComponent` emits the identical shape (`sqlserver_extractor.py:42`,
  `:62-68`).
- `DesignParserComponent` emits it from both of its file formats — the JSON branch
  (`design_parser.py:58-62`) and the EDMX branch (`:89-93`) — each marked
  *"STRICT DOMAIN INJECTION"*, with the domain inferred from the S3 key prefix.
- `apply_semantic_tags` takes the three asset outputs as plain dicts and flat-merges them
  (`semantic_linker.py:85-98`), then treats every entry the same way: one dossier, one POST to
  the ontology service's `/classify_legacy_table`, one proposal route
  ([ADR-0151](ADR-0151-semantic-tags-are-late-bound-through-hitl.md)).
- Adding a dialect is a component subclassing `Component, Resolvable, Model`, registered in
  `doc_tools/definitions.py` (instantiate, `build_defs`, add to the asset list) — and
  `AGENTS.md:125` ends with *"Do not bypass `apply_semantic_tags`"*.

Pinned by `tests/test_oracle_extractor.py:26` (the asset's emitted mapping),
`tests/test_design_parser.py:46`, `:59`, `:71` (both formats and the unsupported-extension case)
and `tests/test_semantic_linker.py:37-61`, which feeds the consumer three single-entry dicts
from three different sources and asserts one set of counts.

## Consequences

- One classification path, one credential check, one place where a dossier is built. A new
  dialect is additive, and the consumer does not grow a branch per source.
- **The merge is `dict.update`, so the key space is shared and collisions are silent.** Two
  dialects that both name a table `dbo.Orders` resolve to one entry — the last writer wins, in
  the fixed order sqlserver → oracle → design (`semantic_linker.py:95-98`). The contract's
  flatness is what makes the merge trivial and is also what makes the collision invisible; no
  measurement of whether this has occurred exists.
- **The contract is a convention the consumer tolerates deviations from, not a validated
  schema.** The dossier is built entirely with `.get` defaults (`semantic_linker.py:138-147`), so
  a missing `description` classifies as the string `"None"`, a missing `domain` becomes
  `DATA_ENGINEERING` downstream as well as upstream, and any extra key is dropped unread. Nothing
  raises on a non-conforming entry.
- Two deviations already exist and are invisible for that reason. `DesignParserComponent` emits a
  **third** key, `relationships` (`design_parser.py:60`, `:91`), which the dossier never reads;
  and it keys on the bare table or entity name, **not** the `schema.table_name` the contract
  names (`:58`, `:89`), because an EDMX entity and a modelling-tool export have no schema
  segment. The uniform half is `description` and `domain`; the key shape is uniform for the two
  database dialects only.
- The `description` is whatever the source held, and each branch invents a different filler when
  it held nothing: `'No description'` for a JSON export without one (`design_parser.py:59`) and
  `f"Entity Model: {name}"` for an EDMX entity with no `Documentation` node (`:86`). Both reach
  the classifier as though they were descriptions, and nothing marks such an entry as
  evidence-free.
- Of the three extractor components, two are pinned by their own tests (Oracle, Design);
  `SqlServerExtractorComponent` is exercised only through the consumer's fixtures, so a drift in
  its emitted shape would be caught later and less directly than the others'.

## Alternatives considered

No alternative is recorded. The obvious one — a per-dialect shape with an adapter layer in front
of `apply_semantic_tags` — is **not** recorded as considered; the guidance states the uniform
contract as a `MUST` and states the no-bypass rule as a prohibition, neither as a choice between
options.
