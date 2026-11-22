# ADR-0162 — a concept no slide teaches gets neither a proposal nor a canonical

**Status:** built
**Date:** 2026-11-09 (ruled) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/passes/concepts.py:581-584` — a code comment, which was the **only**
written statement of this ruling before this record; restated as an input filter in contract
`docs/contracts/training-workbench.md` §4.7 ("a Concept no Slide teaches gets neither a canonical
nor a proposal") and pinned by
`tests/test_concept_normalise.py::test_load_records_unions_terms_counts_edges_and_averages_unit_vectors`
(`:521` — a row with `slide: None` yields *no record at all*)
**Related:** [ADR-0161](ADR-0161-teaches-edges-are-replaced-in-one-write.md) (the prune that
creates these concepts), [ADR-0163](ADR-0163-alignment-direction-and-who-creates-a-canonical.md)
(the pass that excludes them), [ADR-0160](ADR-0160-a-concept-is-keyed-on-a-hash.md),
[`docs/arch/components/ontologies-and-alignment.md`](../arch/components/ontologies-and-alignment.md)

## Context

A `Concept` outlives its edges. Contract §4.4 is explicit: a re-ingest never `DETACH DELETE`s a
Concept, and *"a Concept that no Slide teaches any more stays as a node with no `TEACHES`;
nothing deletes it."* [ADR-0161](ADR-0161-teaches-edges-are-replaced-in-one-write.md) is the
mechanism that produces them in bulk — every re-ingest whose new answer drops a concept leaves
the node behind with nothing pointing at it.

The alignment pass ([ADR-0163](ADR-0163-alignment-direction-and-who-creates-a-canonical.md))
reads Concepts for a whole domain, not for one course. So without a rule, these untaught nodes
are *in scope*, and two things follow that are both wrong:

- **They have no vector.** A concept's vector is the mean of the L2-normalised vectors of the
  slides that teach it (`concepts.py:605-606`). No slides, no vector. A vectorless concept
  cannot be ranked by cosine, so it reaches the proposal set on a lexical signal alone and sits
  at the top of nothing in particular.
- **They have no course.** Courses are reached through the teaching slide
  (`MATCH (course)-[:HAS_CHILD]->(s)`, `concepts.py:574`). A concept with no course belongs to
  no course's per-course proposal budget, and the per-course scope rule
  ([ADR-0163](ADR-0163-alignment-direction-and-who-creates-a-canonical.md)) has nothing to match
  it against.

The concrete failure is a review queue filled with decisions nobody can make. A human opening a
proposal for a concept **no course teaches** has no slide to read, no course to place it in, and
no way to tell whether the name once meant what it looks like it means. Worse, it is
indistinguishable from a live concept: the node carries a `name`, and a reader seeing a
`CanonicalConcept` minted for it would reasonably conclude the domain teaches it.

## Decision

**A `Concept` that no `Slide` teaches is excluded from the alignment pass entirely: it gets
neither a `PROPOSED_ALIGNS_TO` nor a `CanonicalConcept`, and no record of it is loaded.**

- `load_records` drops the row before building a `ConceptRecord`: the `OPTIONAL MATCH` on the
  teaching slide yields `slide = None`, and the loop `continue`s (`concepts.py:581-584`).
- The exclusion is at **load**, not at propose time. Nothing downstream — components, the
  canonical id choice, the ranking, the orphan sweep — ever sees the concept, so no later rule
  has to remember to exclude it.
- Contract §4.7 states the input filter the same way: the pass's inputs are *"the Concepts with
  at least one `TEACHES`"*.
- "No slide teaches it" is the test, not "no course". A concept taught by a slide that hangs
  under no course still has a vector and still aligns; only the course list is empty.

## Consequences

- The node is **not** deleted, and this record does not authorise deleting it. Contract §4.4
  says nothing deletes it; a prune of untaught Concepts is a separate decision with its own
  risk (the node may carry a human's `ALIGNS_TO`), and it is not this one.
- So an untaught Concept is **inert, not absent**: it exists in Neo4j, it answers a name query,
  and any consumer that reads `Concept` without joining through `TEACHES` will see it. Only the
  alignment pass is bound by this rule.
- An untaught concept that a *later* course starts teaching re-enters the pass automatically on
  the next run, with a vector and a course. Nothing has to be undone.
- A concept that loses its last `TEACHES` loses its alignment candidacy but **keeps any
  `ALIGNS_TO` it already has**: the pass never changes a non-`auto` edge, and a pinned concept's
  stale `auto` edge is removed only when the pass has a record for it — which it no longer does.
  An auto edge on a now-untaught concept therefore persists.
- The orphan sweep is the other half of the arithmetic: a `CanonicalConcept` whose `source` is
  `concepts.normalise` is `DETACH DELETE`d when it has no `ALIGNS_TO` of any status and no
  relationship except open proposals (contract §4.7, *Orphans*). So a canonical left behind by
  concepts that have all gone untaught is collected; the concepts themselves are not.
- No measurement of how many Concepts this excludes is cited by the ruling or by the code
  comment, and none is quoted here.

## Alternatives considered

- **Propose for them anyway and let a human decide.** Rejected by the ruling. It is the
  behaviour the rule corrects: the human has no slide to read and no course to place it in, and
  the proposal cannot be answered on its merits.
- **Delete an untaught Concept.** Not taken, and contract §4.4 rules the other way — nothing
  deletes it, because the node may carry the workbench's user edges. This is the same reasoning
  that keeps [ADR-0161](ADR-0161-teaches-edges-are-replaced-in-one-write.md)'s prune on the
  relationship only.
- **Exclude at propose time rather than at load.** Not recorded as considered. The shape it
  would take is a filter in `plan_alignment` instead of in `load_records`; excluding at load is
  what makes the exclusion unconditional, since a later rule cannot forget a record that was
  never built.
- **Align them without a vector, on lexical signals only.** Not recorded as considered. The
  pass does already propose on a lexical signal with no vectors available (contract §4.7's
  "without vectors" column), so the mechanism exists — the rule is a judgement about
  reviewability, not a limitation of the scorer.
