# Packet to wb, from doc-tools lane tr — ALIGNS_TO reverses, review writes three properties, turn off `harmonize_concepts`

2026-10-30. **Placed, not committed.** This is information for the workbench lane: the doc-tools PRs it describes are open (#194, #195) but not merged, and nothing in it is a roll.

## The rulings (architect, 2026-10-30, verbatim)
- "Direction: Concept —ALIGNS_TO→ CanonicalConcept; contract v4 fixes §4.4."
- "Proposals: only pairs above the similarity floor that are not already auto-linked, ranked by shared teaching slides, top 50 per course; the rest stay computable, not shown."
- "doc-tools owns the alignment pass; the workbench reviews proposals and writes nothing to Concept."
- "yes, replace stale concept links on re-ingest."

## What changes on your side
1. **Every reader flips direction.** The edge is now `(c:Concept)-[:ALIGNS_TO]->(cc:CanonicalConcept)`, and `PROPOSED_ALIGNS_TO` runs the same way.
   - Your code reads `(cc)-[:ALIGNS_TO]->(c)` at `src/workbench/main.py` 163, 221, 226, 245, 283, 658 and 784, at `alignment.py` 40 and 57, and at `generator_service.py:78`. Those are the line numbers as of 2026-10-29.
   - Your contract copy (line 118) already says `Concept → CanonicalConcept`. That line was right, and the code is what has to change.
2. **Turn off `harmonize_concepts`, `harmonize_concepts_job` and `unharmonized_concepts_sensor`** (`src/pipelines/definitions.py`) when doc-tools' pass lands.
   - Otherwise two writers MERGE CanonicalConcepts on different keys: yours by `name`, ours by `id`.
   - Your sensor also counts `NOT (:CanonicalConcept)-[:ALIGNS_TO]->(c)`. After the flip, that count would include every Concept and fire on every tick.
3. **Review writes only three properties** on an existing `PROPOSED_ALIGNS_TO` edge:
   - accept: `SET p.status = "accepted", p.reviewed_by = …, p.reviewed_at = …`;
   - reject: `SET p.status = "rejected", p.reviewed_by = …, p.reviewed_at = …`.
   - The workbench never creates or deletes a CanonicalConcept, an ALIGNS_TO or a proposal edge, and never sets a property on a Concept.
   - On its next run, doc-tools' pass turns an accepted proposal into `ALIGNS_TO {status: "accepted", method: "review"}`, with confidence copied from the proposal. It pins the Concept and keeps the proposal as the record. After that the pass never changes an accepted or rejected decision.
4. **What to show.** Show only `status = "open"` proposals. There are at most 50 pairs per course, ranked by shared teaching slides, then confidence, then cosine. Each proposal carries `confidence`, `method`, `evidence` (its signals) and `cos`.
   - Conflict proposals are outside the cap. A conflict is a component whose pinned members name two or more ccs.
5. **Your existing `(cc)->(c)` edges.**
   - doc-tools' pass reads the old shape as a **pinned legacy edge**. It never rewrites or deletes it, and the Concept gets no auto edge while that edge exists. The run reports the count as `legacy_reversed_edges`.
   - If you want the pass to align those Concepts, clear the old edges before its first run (your `scripts/clear_harmonization.py`) rather than flipping them.
   - The sandbox has 0 CanonicalConcepts, so this matters only where your harmonizer has run.
6. **Stale TEACHES go on re-ingest.**
   - A re-augmented Slide's TEACHES edges are replaced: the new ones are MERGEd, and the Slide's edges to Concepts the new answer doesn't name are deleted.
   - Concept nodes are never deleted. A Concept no Slide teaches any more stays, with no TEACHES.
   - So a count of TEACHES per Course will now drop on a re-ingest, where before it only grew.
7. **Synthesis reads summaries (ADR-0059 order, item 3).** Once Sections carry `summary` and `objectives` (contract v4), read them before calling the model.
8. **Weaviate `chunk_kind`.** The sandbox `DocumentChunk` has no `chunk_kind` property, and any filter on it errors. doc-tools PR A adds the property on the first v4 ingest. Do not filter on `chunk_kind` before that ingest has run on the cluster you read.

## Where it is
| doc-tools branch | sha | carries |
|---|---|---|
| `lane/tr-concepts-r`, PR #194 | `d166c93` | the section call, contract v4, TEACHES replacement |
| `lane/tr-normalise-r`, PR #195 | `e92fd68` | the alignment pass `concepts.normalise`, contract v5 §4.4 and §4.7 |

Both are stacked on #172, in merge order #172, #194, #195. The contract is `docs/contracts/training-workbench.md` on `lane/tr-normalise-r`. §4.4 is ownership and §4.7 is the pass. It is still DRAFT and will be final when the PRs merge.

**Goldens:** the re-golden from a clean start comes after the PRs merge. Its file hashes will arrive in their own packet, like the 2026-10-25 one. Don't re-pin yet.
