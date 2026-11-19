# ADR-0163 — alignment direction, and where a canonical concept is created

**Status:** accepted + built
**Date:** 2026-10-30 (architect; contract v5) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `docs/contracts/training-workbench.md:1` (the v5 header), §4.4 and §4.7 — a contract
that **declares itself version 5, DRAFT, 2026-10-30**; also in the pass's module docstring at `doc_tools/passes/concepts.py:12-22`
**Related:** [ADR-0162](ADR-0162-a-concept-no-slide-teaches-is-not-aligned.md) (what the pass
excludes), [ADR-0160](ADR-0160-a-concept-is-keyed-on-a-hash.md) (the key both sides MERGE on),
[ADR-0161](ADR-0161-teaches-edges-are-replaced-in-one-write.md), [ADR-0165](ADR-0165-the-contract-decides-the-concepts-rules.md), [ADR-0234](ADR-0234-the-training-workbench-seam.md)

## Context

Concept unification is a cross-lane surface: doc-tools (lane tr) writes the `Concept` nodes, and
the training-consolidation-workbench (lane wb) is the human review UI over the same Neo4j. Before
v5, **both sides wrote `CanonicalConcept`** — wb through an LLM `harmonize_concepts` asset driven
by an `unharmonized_concepts_sensor`, doc-tools through a deterministic pass. They MERGE on
different keys, wb's by `name` and doc-tools' by `id` ([ADR-0160](ADR-0160-a-concept-is-keyed-on-a-hash.md)),
so the graph grows two parallel canonical vocabularies, each invisible to the other's MERGE.

Direction was the second, quieter problem. The harmonizer wrote the edge **both ways round**,
including `(CanonicalConcept)-[:ALIGNS_TO]->(Concept)`. A reader cannot scope a query to "the
canonical a concept aligns to" when half the edges point the other way: every count and every
"is this concept aligned" check then disagrees with itself depending on the direction it assumed.
Third, review writes: if the workbench may set properties on a `Concept`, or create and delete
`ALIGNS_TO`, the pass cannot tell a human decision from its own previous output, and its safety
model — rewrite only what you own — has nothing to stand on.

## Decision

**Every alignment edge runs `(Concept) -> (CanonicalConcept)`; `CanonicalConcept` and
`ALIGNS_TO` are created by doc-tools' `concepts.normalise` and by nothing else; and the
workbench's writes in this domain are three properties on an existing proposal edge.**

- **Direction.** Every edge the pass writes *or reads* is `(Concept)-[:ALIGNS_TO]->(CanonicalConcept)`
  or `(Concept)-[:PROPOSED_ALIGNS_TO]->(CanonicalConcept)` (contract §4.7, *Direction*).
- **Creation moves out of the workbench's LLM harmonizer** into `concepts.normalise`
  (`doc_tools/passes/concepts.py`), which calls no LLM. wb's `harmonize_concepts` asset and
  `unharmonized_concepts_sensor` **must be off when this lands**, or two writers MERGE canonicals
  on different keys (contract §4.4).
- **Ownership is by `status` and `source`.** The pass may create, change and delete
  `ALIGNS_TO {status:"auto"}`, `PROPOSED_ALIGNS_TO {status:"open"}` and `CanonicalConcept` nodes
  whose `source` is `concepts.normalise` — never a non-`"auto"` `ALIGNS_TO`, nor an accepted or
  rejected proposal.
- **The workbench's only writes are `status`, `reviewed_by`, `reviewed_at`** on an existing
  `PROPOSED_ALIGNS_TO`. It never creates or deletes a `CanonicalConcept`, an `ALIGNS_TO` or a
  proposal edge, and **never sets a property on a `Concept`** (§4.4).
- **A human decision is materialised, not executed in place.** The pass writes the accepted
  proposal's `ALIGNS_TO {status:"accepted", method:"review"}` next run; the proposal edge stays
  as the record (§4.7, *Accepted proposals*).
- **The legacy reversed edge is read as a pin, never rewritten.** A
  `(CanonicalConcept)-[:ALIGNS_TO]->(Concept)` with no status is the old harmonizer's shape; the
  pass pins that concept, never writes that shape, and counts it in `legacy_reversed_edges`.

## Consequences

**Both halves of this record's status, said plainly: the contract that carries the ruling is a
DRAFT, and `concepts.normalise` is built.**

- *Built.* The pass is `doc_tools/passes/concepts.py`, declared on the `course` kind row only and
  ordered after the concept call and before `render.pages`; it runs per course at the end of an
  ingest (`doc_tools/assets/semantic_assets.py:458-483`) and has a fleet job
  (`doc_tools/concept_alignment_job.py`, `normalise_concepts_job`). Pinned in
  `tests/test_concept_normalise.py` by `::test_the_pass_is_declared_on_the_course_row_only`,
  `::test_every_written_relationship_runs_concept_to_canonical` (it greps every statement issued),
  `::test_apply_statements_guard_every_non_owned_edge`,
  `::test_an_accepted_proposal_becomes_an_aligns_to_and_the_auto_edge_goes`,
  `::test_reversed_legacy_edge_pins_the_concept_and_is_counted`.
- *Accepted, and the contract is a draft.* The read side is lane wb's and this repo cannot measure
  it, so the half that says what the workbench must stop doing is **ruled and owed, not verified
  here** ([ADR-0234](ADR-0234-the-training-workbench-seam.md)).
- **It ships switched off by default, and an unrecognised switch value writes.**
  `TRAINING_CONCEPT_ALIGNMENT` defaults to `dry` (`semantic_assets.py:464`): it plans and writes
  nothing, and stays `dry` until wb has turned its harmonizer off; moving to `on` is a values
  change made by packet (§4.7, *Switches*). But `off` → skip, `dry` → plan, `propose` → propose,
  and **anything else falls through to a writing run** (`semantic_assets.py:466-473`:
  `status = mode if mode in ("dry", "propose") else "ok"`). A typo is not inert; it is `on`.
- A failure of the per-course run **does not fail the ingest**: it is recorded as
  `concept_alignment = "failed:<ExcType>: <msg>"` (`semantic_assets.py:474-476`) and the run is
  green, so an alignment that never ran looks like one that found nothing.
- The cost of one writer is that unification is **deterministic and lexical**: no LLM, so a synonym
  with no shared token and no related term is never proposed (§10). wb's harmonizer could have
  guessed those; it also guessed wrong unauditably.
- Until that harmonizer is off, the reversed-edge pin keeps the two worlds from fighting, at the
  price that a legacy-pinned concept gets no auto edge of its own.

## Alternatives considered

- **Leave `CanonicalConcept` creation in the workbench's LLM harmonizer.** Rejected by the
  2026-10-30 ruling; §4.4 names the failure — two writers MERGE canonicals on different keys.
- **Let both write and reconcile afterwards.** No reconciliation rule exists and the ruling names
  one owner instead; not recorded as separately considered.
- **Keep the edge undirected and have readers accept either direction.** Rejected: §4.7 fixes the
  direction for reads *and* writes; the old shape survives only as a pin, because rewriting it
  would be the pass editing user data.
- **Let the workbench write the `ALIGNS_TO` when a human accepts a proposal.** Rejected: it sets
  three properties and the pass materialises the edge next run, keeping one writer for the edge.
- **Delete a rejected proposal.** Rejected: a rejected pair is never re-proposed (§4.7), so the
  edge must survive as the record of the refusal.
