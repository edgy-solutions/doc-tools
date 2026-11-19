# ADR-0161 — stale `TEACHES` edges are replaced, in one write

**Status:** built
**Date:** 2026-10-30 (architect's ruling) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris — the ruling is quoted at the deletion
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/plugins/training.py:501-510` — a code comment, which was the **only**
written statement of this ruling's *reasoning* before this record; the rule itself is contract
`docs/contracts/training-workbench.md` §4.4 rule 4; the prune is `training.py:511-522`, pinned by
`tests/test_training_section_concepts.py::test_prune_follows_each_slides_merges_and_keeps_exactly_the_new_ids`,
`::test_a_slide_with_no_concepts_still_gets_a_prune_with_empty_keep` and
`::test_prune_deletes_the_edge_only`
**Related:** [ADR-0160](ADR-0160-a-concept-is-keyed-on-a-hash.md) (the key the prune matches on),
[ADR-0164](ADR-0164-one-concept-call-per-section-group.md) (the other subtree a re-ingest
replaces), [ADR-0163](ADR-0163-alignment-direction-and-who-creates-a-canonical.md) (the
workbench edges the prune must not touch), [ADR-0234](ADR-0234-the-training-workbench-seam.md),
[`docs/arch/components/ontologies-and-alignment.md`](../arch/components/ontologies-and-alignment.md)

## Context

The concept write is a `MERGE`: `MERGE (s)-[t:TEACHES]->(c)` per concept the model named for
this slide (`training.py:485`), and **a `MERGE` only ever adds.** So a re-augmented slide kept
every edge from the earlier run. Re-ingest a course after a prompt change, a model change or a
fix to the concept pass, and the slide ends up teaching the union of every concept any run has
ever named for it — the new answer *plus* the old one. Nothing fails, nothing is logged, and the
graph looks richer than before.

That union is then load-bearing. `TEACHES` is the alignment pass's only input filter
([ADR-0162](ADR-0162-a-concept-no-slide-teaches-is-not-aligned.md)), its `related_terms` feed
the lexical signals, and `teach_count` is the tie-break that picks a canonical's display name
([ADR-0163](ADR-0163-alignment-direction-and-who-creates-a-canonical.md)). A stale edge
therefore does not merely sit there: it votes.

The repair that suggests itself — `DETACH DELETE` the Concept and rebuild — is the dangerous
one. A `Concept` is **shared across slides and courses** and may carry the workbench's user
edges. Deleting the node would silently drop a human decision.

## Decision

**A re-augmented Slide's `TEACHES` edges are replaced, not merged: the new edges are MERGEd,
then every `TEACHES` from that Slide to a Concept the new answer does not name is deleted — in
the same write, and in that order.**

- The architect's ruling, quoted at the deletion: *"yes, replace stale concept links on
  re-ingest"*.
- `keep_ids` is the de-duplicated list of `concept_node_id(domain, name)` for this slide's
  concepts (`training.py:511-513`), so two spellings that normalize alike appear once: the prune
  matches on the [ADR-0160](ADR-0160-a-concept-is-keyed-on-a-hash.md) key, never on a name.
- The prune deletes **the relationship only**: `DELETE t`, never `DETACH DELETE`, never the
  Concept (`training.py:514-518`). The node stays because it may carry workbench edges.
- It runs **after** this slide's MERGEs, as its own transaction (each entry of `cypher_queries`
  is one). The order is deliberate: if a MERGE failed, the old edge stays rather than being lost
  with nothing to replace it.
- **An empty `keep` is the model's answer, not missing data.** A slide whose new answer names no
  concept loses all its `TEACHES`; a failed section call fails the run
  ([ADR-0164](ADR-0164-one-concept-call-per-section-group.md)), so an empty list can only mean
  "this slide teaches nothing".
- Scope is one slide: the prune is anchored on the slide the MERGEs just wrote.

## Consequences

- The `TEACHES` set a reader sees is the **latest run's**, which is what makes a re-ingest a fix
  rather than an accumulation. This is the part a reimplementation loses: a MERGE-only path
  looks correct, passes every "the edge exists" test, and keeps every stale edge.
- **`ALIAS_OF` is pruned on a different scope, and the asymmetry is real.** At the pin the
  candidate `ALIAS_OF` edges get their own prune (`training.py:559-571`), but it is keyed on
  `{course_id: $course_id}` — and `course_id` is set `ON CREATE` (`:554`), so an alias edge
  belongs to the **first course that asserted it** and only that course's re-ingest can remove
  it. A `TEACHES` edge is replaced per slide by whichever run touches the slide; an `ALIAS_OF`
  edge only by one particular course. So re-ingesting course B does not clear an alias first
  asserted by course A, and an edge written before `course_id` existed matches no prune at all.
  The alias set is no longer the union of every run, but it is not the latest run's either.
- `docs/arch/components/ontologies-and-alignment.md` claim 16 **contradicts the code at this
  pin** on two points: it says the plugin deletes stale `TEACHES` *before* writing (the code
  prunes after, deliberately), and it says `ALIAS_OF` is not replaced at all (a course-scoped
  prune exists, pinned by
  `tests/test_training_section_concepts.py::test_alias_prune_follows_every_alias_merge_and_keeps_exactly_the_pairs`).
  The ruling and the code agree; the architecture record is stale, and that row belongs in
  [DEBT.md](DEBT.md).
- A prune per slide means a re-ingest issues roughly twice as many graph statements as a
  MERGE-only path. That cost is small beside the concept calls.
- A Concept that no slide teaches any more **stays as a node with no `TEACHES`**; nothing
  deletes it (contract §4.4). What happens to it next is
  [ADR-0162](ADR-0162-a-concept-no-slide-teaches-is-not-aligned.md).

## Alternatives considered

- **Keep merging and accept the union.** Rejected by the ruling. It is the behaviour that was
  there, and it made every re-ingest additive.
- **`DETACH DELETE` the Concept and rebuild.** Rejected, and the comment says why: the Concept is
  shared and may carry the workbench's `ALIGNS_TO`. Contract §4.4 rule 4 states the general
  form — a re-ingest MERGEs and never `DETACH DELETE`s a Course, Slide or Concept.
- **Prune before the MERGEs, or in one transaction with them.** Rejected: the comment makes the
  ordering a safety property. A prune that runs first, or a single transaction that fails
  mid-way, can leave the slide with neither the old edges nor the new.
- **Treat an empty answer as "no data, keep what is there".** Rejected: an empty list *is* the
  model's answer, because a failed call fails the run instead of returning nothing.
- No alternative is recorded for the `ALIAS_OF` scoping asymmetry above. The obvious one —
  pruning `ALIAS_OF` per re-ingesting course regardless of which course first asserted the
  edge — is **not** recorded as considered.
