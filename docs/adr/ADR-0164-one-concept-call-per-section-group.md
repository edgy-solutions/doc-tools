# ADR-0164 — concepts are extracted one call per section group

**Status:** built
**Date:** no ruling date is recorded; carried by the contract as v3 §4.5 and v4 §4.6 · recorded 2026-11-18
**Deciders:** lane tr, in the contract it owns — `docs/contracts/training-workbench.md` §11 ("the owning lane edits this file"). The census names no individual ruling for this row.
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `docs/contracts/training-workbench.md` §4.6 (grouping) and §4.4 rule 4 (the Section subtree);
implemented in `doc_tools/utils/concept_groups.py` (module docstring `:1-15` carries the cost argument) and `doc_tools/plugins/training.py:396-425`
**Related:** [ADR-0161](ADR-0161-teaches-edges-are-replaced-in-one-write.md) (the other subtree a re-ingest replaces), [ADR-0160](ADR-0160-a-concept-is-keyed-on-a-hash.md), [ADR-0165](ADR-0165-the-contract-decides-the-concepts-rules.md),
[ADR-0234](ADR-0234-the-training-workbench-seam.md), [`docs/arch/components/extraction-pipeline.md`](../arch/components/extraction-pipeline.md)

## Context

Concept extraction used to be one LLM call per slide, and a course ingest is a serial run of those calls, so
the ingest's wall clock is **that serial sum**. The cost argument is recorded in `concept_groups.py:10-12`: a
deck whose outline is one section per slide *"would otherwise make one call per slide, which is today's cost."*

Per-slide calls also throw away the thing that makes a concept name good. A slide read alone gives the model
no idea what the surrounding section is about, so the same idea comes back under a different name on
consecutive slides, and the alignment pass ([ADR-0163](ADR-0163-alignment-direction-and-who-creates-a-canonical.md)) is left to repair drift that need not have happened.

The second half of this record is a different failure. Sections are **positional**: `Section.id` is
`{parent.id}_s{i}`, `i` 0-based within the parent (contract §3). A re-ingest that MERGEs sections therefore
does not update an outline — it *overlays* a second one. A course that had four sections and now has three
keeps `_s3` from the previous run, pointing at slides the new outline assigns elsewhere, with no way to tell
a stale section from a current one.

## Decision

**Concepts, `TEACHES` `related_terms`, figure references and Section notes come from one
`ExtractSectionConcepts` call per group of at most 8 slides, aligned to the outline — and a re-ingest
replaces the Section subtree whole, in one statement.**

The grouping (contract §4.6, planned by `doc_tools/utils/concept_groups.py`):

- A slide belongs to the **deepest** outline section whose page range holds it; of two at one depth, the
  later start. Slides outside every section are unsectioned.
- Consecutive slides of one section form a **run**. A run longer than `MAX_SLIDES` (8,
  `concept_groups.py:21`) splits into near-equal pieces — 20 slides give 7, 7, 6.
- Runs are packed, in page order, into calls of at most 8 slides **without splitting a run**, so a section is
  split only when it alone exceeds 8. Short sections share a call, each under its own `=== Section: <title> ===` marker; a nested child splits its parent's run, so a parent can appear twice.
- **The reply stays per slide**: one entry per `=== Slide N ===` marker, plus one note per section marker.
  `TEACHES` therefore stays slide-level even though the call is not.
- `TRAINING_CONCEPT_CONCURRENCY` (default 1, minimum 1) is the number of calls in flight; results are
  assembled in **call order** whatever the completion order.
- **One retry**, then: a raise fails every slide of the call; a reply missing a slide fails that slide alone
  and the run ends `failed:concept_parse` while the other slides' writes still happen. Extra reply entries
  are ignored, the first wins for a duplicate, and a salience outside `[0, 1]` is clamped rather than fatal.
- **Section notes are best effort and never a failure.** They pair with the call's section markers by
  position when the counts match, else by title (case and whitespace folded); unpaired notes are dropped, and a section split across calls merges its notes in page order.

The Section subtree (contract §4.4 rule 4, `training.py:396-425`):

- **One statement, one transaction**: delete this Course's old `Section:{label}` nodes — those reached by
  `HAS_SECTION*` from the Course, plus any orphan whose `id` starts with `{Course.id}_s` — set
  `Course.outline_source`, then write the new rows and their `HAS_SECTION` edges. It names **only** `Section:{label}` as a delete target, and the same run rewrites `HAS_SECTION`, Section → Slide and `COVERS`.
- **If the build fails, the old Sections stay and the run fails.** No partial outline.

## Consequences

- A deck's ingest cost drops from one call per slide to one call per 8-slide group, and a deck whose outline
  is one section per slide is the worst case the cap is sized for: 160 one-slide sections make 20 calls of 8
  (`tests/test_concept_groups.py::test_160_one_slide_sections_make_20_calls_of_8`).
- **The default is still serial.** `TRAINING_CONCEPT_CONCURRENCY` defaults to 1, so the saving is the call
  count, not parallelism.
- The model sees a section's slides together, so a concept name has section context — at the cost that one
  bad call now takes out up to 8 slides rather than 1. The retry and the per-slide failure rule are the mitigation, asymmetric on purpose: a raise is a call-level fault, a missing entry a slide-level one.
- `Section.summary` / `objectives` and `TEACHES.related_terms` are **nondeterministic**; the golden fixture shows their shape only (contract §4.6), so a re-ingest of identical bytes can change them.
- **Sections are the exception to "a re-ingest MERGEs".** They can be `DETACH DELETE`d because no workbench
  relation ends at a Section, so no user edge is lost — unlike a Course, Slide or Concept
  ([ADR-0161](ADR-0161-teaches-edges-are-replaced-in-one-write.md)).
- The orphan clause (`o2.id STARTS WITH $id_prefix`) exists because positional ids outlive the edge: a
  section whose `HAS_SECTION` was lost is still reachable by its id prefix, and without that clause a
  shrunken outline would leave it behind for ever.
- **The survival property is pinned only by a test outside the default run.** That the replace leaves Course,
  Slide, Concept, `TEACHES` and `ALIGNS_TO` alone is `tests/test_section_replace_survival.py`, marked
  `neo4j_live` and skipped unless `NEO4J_URI` is set; the logic lives in
  `scripts/training_section_replace_survival.py` so it can run in a pod with no pytest. The default suite
  pins the *shape* of the write (`tests/test_training_workbench_golden.py:127` for the `HAS_SECTION` edge set, `tests/test_training_section_concepts.py::test_section_rows_carry_summary_and_objectives` for the
  rows), not the live survival. A green local suite is not evidence of it.
- One id scheme is shared by the Section nodes, the concept calls and the Weaviate section objects
  (`training.py:373-375`), so a change to `flatten_outline`'s ordering moves all three at once.

## Alternatives considered

- **One call per slide.** Rejected, and it is the state this replaces: `concept_groups.py:10-12` names the
  cost, and one-section-per-slide decks are the case that made it unacceptable.
- **One call per section, whatever its length.** Rejected by the `MAX_SLIDES` cap: a section longer than 8
  slides splits into near-equal pieces, because an unbounded call is an unbounded prompt.
- **Pack calls to the cap by splitting runs.** Rejected explicitly in §4.6 — packing never splits a run,
  which is what keeps a section's slides together and its marker meaningful.
- **A per-section reply instead of a per-slide one.** Rejected: `TEACHES` is slide-level
  (`baml_src/training.baml:24` is explicit that the reply has *"Exactly one entry per '=== Slide N ==='
  marker, in order, including slides that teach nothing"*), so a section-level reply would lose its anchor.
- **MERGE the Sections on re-ingest, like everything else.** Rejected by §4.4 rule 4: positional ids make a
  MERGE an overlay, not an update. The reason Sections *may* be deleted where a Concept may not is recorded
  there too — no workbench relation ends at a Section.
- **Delete the old sections in one transaction and write the new ones in another.** Not taken: the write is
  deliberately one statement, so a failure leaves the old outline intact and fails the run. No alternative
  ordering is recorded as considered.
