# ADR-0146 — the instance-graph supersede key is the slug

**Status:** built
**Date:** 2026-10-17 (architect ruling 2 of that date) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris — ruling 2 of 2026-10-17
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/assets/xml_ingestion.py:351-370` — a code comment, which was the **only**
written statement of this ruling before this record; the implementing comment and code are
`doc_tools/assets/semantic_assets.py:1760-1802` and `:1834-1866`. Sealed by
`tests/test_xml_instance_graph_write.py`
**Related:** [ADR-0141](ADR-0141-reproducibility-decides-the-graph.md) (which graph this write
targets), [ADR-0140](ADR-0140-one-named-graph-per-document-replaced-whole.md) (where PUT *is*
right), [ADR-0144](ADR-0144-the-vocabulary-path-appends.md)

## Context

The XML path's second write puts a module's content triples into the shared
`<http://internal/{DOMAIN}_INSTANCES>` graph ([ADR-0141](ADR-0141-reproducibility-decides-the-graph.md)).
Shared means PUT is out: a whole-graph replace would clobber every sibling module of the domain.
So a re-drop has to supersede *just this module's* subjects — and the question is what key
selects them.

A bare additive `INSERT DATA` is not good enough, and the reason is measured rather than
asserted. Across ten drops of the S1000D fixture set there are six distinct modules, four of
them dropped twice, and **two of those pairs disagree on content** (19 triples against 14, and
14 against 9). Under a pure insert the graph accumulates both versions of each and no reader can
tell which is current (`doc_tools/assets/semantic_assets.py:1760-1769`).

The key is the **slug**, and the reason is structural, not a style preference: the builder mints
**dependent subjects that carry the slug and not the module IRI** — `step-<slug>-N-M`,
`proclist-<slug>-N`, and the `part-`/`tool-`/`fig-`/`item-`/`interval-`/`faultcode-` families
(`doc_tools/assets/xml_ingestion.py:354-358`). Key the supersede on anything narrower and a
re-drop **with fewer steps leaves those subjects orphaned for ever**: the module's own node
updates, and `step-<slug>-9` from the previous revision stays in the graph with nothing pointing
at it and no later drop able to name it.

Two near-candidates are both wrong. **`root_uri` alone** does not reach the dependent subjects:
they do not contain the module IRI. **`doc_id`** is not the slug — the slug is `_fragment(doc_id)`
(`doc_tools/parsers/s1000d_rdf.py:41`, exposed as the builder's `doc_slug` property at `:107`),
and a `doc_id` holding any character outside `[A-Za-z0-9_.-]` appears in the subjects
**sanitized**, so a filter written against the raw `doc_id` matches nothing and the write
silently stays additive.

## Decision

**The instance-graph write supersedes by the slug: a scoped DELETE keyed on the module's root
URI *or* the hyphen-delimited slug, followed by the INSERT, in one request.**

- The filter is `?s = <root_uri> || CONTAINS(STR(?s), "-<slug>-")`
  (`doc_tools/assets/semantic_assets.py:1859-1864`). **Both legs are required**: the root URI's
  local name and the slug differ in case, in a leading prefix and in a trailing segment, so the
  module's own subject does not match the slug test.
- The slug is **taken from the builder** (`doc_slug`, carried on the asset's output at
  `xml_ingestion.py:370`), never re-derived at the writer. Same canonicalizer on both sides, or
  the two never meet.
- **DELETE and INSERT go in one request**, separated by `;` (`:1865`). A SPARQL Update request is
  one Fuseki transaction, so the supersede is atomic; as two calls, a committed DELETE before a
  failing INSERT would leave the module with **no** triples.
- **Never PUT**, for the shared-graph reason above (`:1770-1772`).
- The scope was **measured before the DELETE was written** (`:1778-1796`): over 6 modules and 36
  subjects, every subject is either the root URI or contains `-<slug>-` — 0 of 36 uncovered,
  across 9 subject shapes; 0 shared subjects and 0 shared triples between modules, so the blast
  radius on a sibling is 0; and a `dmRef` target is never a subject (it is minted in object
  position only, `doc_tools/parsers/s1000d_rdf.py:263-271`), so the DELETE takes nothing another
  module owns. The slug is hyphen-delimited in the filter, so it cannot match a longer one.
- **No slug means no supersede.** A parser that does not scope its subjects per document
  (`iads`/`dita`/`40051`) stays **additive and warns loudly** (`:1867-1877`): deleting by its
  unscoped subjects would take a sibling *document's* triples. Unreachable at the pin — only the
  S1000D data-module kind is routed — and it must not arm silently if one is wired up.
- An unsafe `root_uri` or `doc_slug` is **refused**, not sent (`:1838-1855`): an over-broad
  DELETE against a shared graph is not recoverable.

## Consequences

- The instance graph holds the **current** state of each module, and "idempotent" means that
  rather than the weaker "re-running the same bytes adds nothing".
- A re-drop with fewer steps leaves no orphans, which is sealed directly
  (`test_redrop_with_fewer_steps_leaves_no_orphan`), as are the sibling blast radius
  (`test_supersede_leaves_a_sibling_module_untouched`), the single-request atomicity and the
  absence of slug-prefix collisions among the fixtures.
- This is the **opposite** of the PCN side, where component IRIs are shared across notices and
  delete-by-subject is destructive. What makes it safe here is the measured 0 shared subjects.
- The correctness of the DELETE depends on the builder's subject-minting staying slug-scoped. A
  new dependent-subject family that omits the slug would be missed by the supersede and would
  accumulate — and nothing outside the builder would say so.
- Three parsers remain additive by design, with a log warning as the only signal, so routing one
  of them is a decision about this record rather than a configuration detail.

## Alternatives considered

- **Bare additive `INSERT DATA`.** Rejected on the measurement above: two of the re-dropped
  pairs disagree on content, so the graph would hold both revisions with no way to tell which is
  current.
- **PUT the whole instance graph.** Rejected: the graph is shared by every module of the domain,
  so a replace clobbers the siblings.
- **Key the supersede on `root_uri` alone, or on `doc_id`.** Both rejected in the ruling, and
  for different reasons — `root_uri` misses the dependent subjects; `doc_id` is not the string
  that appears in them, so it matches nothing and degrades to additive without an error.
- **Two requests, DELETE then INSERT.** Rejected: a committed DELETE followed by a failed INSERT
  leaves the module with no triples at all.
