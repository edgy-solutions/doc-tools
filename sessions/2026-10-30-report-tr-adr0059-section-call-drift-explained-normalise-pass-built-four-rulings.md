# Report from doc-tools lane tr: ADR-0059 items 1–5 built, the drift explained, and four rulings needed

2026-10-30. To the architect; cc 7f, wb. **Placed, not committed.**

Paths written as `lane-tr scratch:` are on lane tr's machine and are available on request; every number they hold is quoted here.

## The short version
- **PR A** (`lane/tr-concepts` 9925679, items 1+2+3) and **PR B** (`lane/tr-normalise` 49c7e4f, item 5) are built and pushed.
  - Suites: A 2375 passed, B 2419 passed.
  - Neither is opened as a PR yet. Both are stacked on #172 (`lane/tr-g`), which is rebased locally on main but waits on Chris for a force-push, so the PRs would show #172's commits until then.
- **Item 4:** the drift is explained, and the prompt was changed because of it. That is the section below.
- **Rulings I need:**
  1. **Stale TEACHES.** A re-ingest keeps every old TEACHES edge, so after this schema change a course would teach the union of its old and new concepts. I recommend replacing a re-augmented Slide's TEACHES in the same write.
  2. **ALIGNS_TO direction.** Your order says "from Concepts". Every workbench reader uses CanonicalConcept → Concept, and PR B writes it that way. Reversing it breaks those readers silently.
  3. **Proposal noise.** On the sandbox the pass makes 1550 review proposals for 677 Concepts, and the ranking signal is saturated. Three options are in item 5.
  4. **Ownership.** PR B moves CanonicalConcept/ALIGNS_TO from the workbench (live `harmonize_concepts`) to doc-tools. It stays `dry` until wb turns theirs off.
- **Two cross-repo facts for 7f and wb:**
  - The overlay drift seal fails `course` on all three of my branches. It skipped locally until pointed at the platform overlay. #181 will make it a CI failure, and a Lane 1 packet with one overlay commit per PR is drafted.
  - Weaviate rejects any filter on `chunk_kind` until a v4 ingest creates the property (measured in the sandbox). wb must not ship the section-exclusion filter ahead of that.

## Item 1+2+3 (PR A), as built
- **One `ExtractSectionConcepts` call per group of ≤8 slides,** aligned to the outline, with `TRAINING_CONCEPT_CONCURRENCY` (default 1).
- **The reply:** `concepts[{name, salience, related_terms}]`, `figure_references`, `section_summary`, `section_objectives`.
  - `description` is dropped.
  - The naming rule is pinned in the prompt.
  - A COVERAGE paragraph was added on the drift evidence below.
- **What is written:**
  - `related_terms` go on TEACHES and become `ALIAS_OF` candidates between existing Concepts (MATCH-only, never merged);
  - summary and objectives go on the Section and into Weaviate as `chunk_kind="section"` objects;
  - the slide objects carry `chunk_kind="slide"`.
- **Failures and contract:** a failed or unparseable call fails the run loudly. Contract v4 includes #167's edits.
- **Two problems found:**
  - **The `chunk_kind` filter.** In the sandbox, `DocumentChunk` has no `chunk_kind` property (8 properties), and Weaviate rejects `Equal("slide")` and `NotEqual("section")` alike: *"no such prop with name 'chunk_kind'"*.
    - PR A adds the property explicitly on the first ingest (`add_property`, the #168 pattern), so it exists from the first v4 ingest on each cluster.
    - Whether `NotEqual("section")` then keeps pre-v4 objects that have no value is still **unmeasured**. Measuring it needs a schema write to a shared collection, which I did not make.
  - **Stale TEACHES (ruling 1).** The TEACHES edge is `MERGE`d and nothing deletes a Slide's old edges. 518 of 518 sandbox Slides carry no `uri`, so `sync_jena_to_neo4j`'s wipe never reaches them.
    - Contract §4.4 rule 4 and the line after it accept "a stale TEACHES edge to a concept the new answer dropped", but that was sized for run-to-run noise.
    - Under the adopted prompt, 328 of the 561 saved Concept names are no longer written and 313 are new, so a re-ingest would make each course teach both sets.
    - Options: (a) replace a re-augmented Slide's TEACHES edges in the same write; no workbench relation is a TEACHES, so rule 4's reason doesn't apply. (b) Keep rule 4 and migrate by wipe-and-rerun, as on 2026-10-25.
    - I recommend (a). The re-golden needs a clean start either way.

### Item 4: concept-name drift, 20 saved decks (561 slides), sandbox server A, 2026-10-30

Bench: `lane-tr scratch: drift_bench.py`, write-free, in the pod. Analysis: `lane-tr scratch: drift_analysis.py`, output in `lane-tr scratch: drift_analysis.json`.
- Names are compared after `normalize_concept_name`, because that is the Concept node key.
- **The arms:**
  - **golden:** the saved ingest;
  - **baseline:** today's per-slide `ExtractConcepts`, re-run unchanged. It covers every slide of a short deck and the first 24 of a long one, 172 slides in all, and serves as the noise floor;
  - **section:** this PR, the full schema;
  - **lean:** the same calls with a lean reply.

### Time and tokens (server A is serial; compare tokens before seconds)
| arm | calls | seconds | prompt tok | completion tok | parse ok |
|---|---|---|---|---|---|
| per-slide (measured on 172 slides) | 172 | 4,218 (24.5 s/slide) | 98,095 | 117,880 | 172/172 |
| per-slide, **extrapolated to 561 slides** | 561 | ~13,760 | ~320,000 | ~384,000 | |
| **section (full schema)** | 91 | 5,525 (+363 outline) | 116,551 | 168,631 | 91/91 |
| **lean** | 91 | 4,515 (+363 outline) | 102,719 | 134,530 | 91/91 |

- **Wall time:** section is 2.3× faster than per-slide on a serial server, including the outline; lean is 2.8× faster.
  - The full schema costs 22% more wall time than lean, for summary, objectives and related_terms.
- **Completion tokens:** section produces 0.44× those of per-slide, lean 0.35×.
- **On a parallel server** (vLLM behind LiteLLM, `TRAINING_CONCEPT_CONCURRENCY` > 1), the 91 section calls overlap. On serial A a 160-slide deck is 24 calls, about 24 minutes.

### Drift
**1. The noise floor is large.** On the same 172 slides, today's unchanged call keeps only **229 of 338** saved names (68%), loses 109 and adds 129. Mean Jaccard against saved is 0.487. A third of all "drift" therefore exists with no change at all: temperature 0 is not deterministic on this server.

**2. Section loses more than the noise.** On the same slides it keeps **137 of 338** (41%): it loses 201, which is 92 more than the floor, and adds 85. Lean keeps 153 and loses 185. Mean Jaccard is 0.363 for section and 0.382 for lean.

**3. About a third of the loss is the naming rule working as pinned.** Lost names, by category, over all slides:

| arm | different concept | long name dropped | shortened | narrower | abbreviation | plural |
|---|---|---|---|---|---|---|
| section | 221 | 70 | 25 | 16 | 15 | 11 |
| lean | 194 | 57 | 50 | 15 | 19 | 14 |
| baseline | 106 | 45 | 25 | 27 | 31 | 8 |

  - Rule violations (sentences, or more than 4 words): **golden 481 of 2303 (21%)**, baseline 79/542, **section 3/1283**, lean 18/1654.
  - The pinned rule removes most of these, so every saved sentence-name necessarily "drifts".

**4. The rest is recall, not renaming.** Section emits **1283** concept mentions against golden's **2303**: 2.3 per slide against 4.1. "Different concept" (221) is mostly supporting concepts that are simply not listed. The section call names the main topic and drops list items (component types, steps, hazards) that the per-slide call listed.

**5. Concept nodes that would change on a re-ingest:**
  - **section:** 561 saved → 327 distinct. 178 are kept and 383 are no longer written; on a re-ingest they stay taught (ruling 1, above). 149 are new. **532 would change.**
  - **lean:** 400 distinct, 571 would change.

**6. Section notes:** 147 sections; 141 carry a summary and 140 carry objectives; the marker count matched on all 147.

### The recall prompt closes it (adopted: `lane/tr-concepts` 9925679)
The variant is the same section call plus one COVERAGE paragraph: list each slide's main topic AND each supporting concept, usually 3 to 6, and the section notes never replace slide concepts. Analysis: `lane-tr scratch: drift_recall_analysis.json`.

| | saved (per-slide) | section, first prompt | **section, recall prompt** |
|---|---|---|---|
| concept mentions (561 slides) | 2303 (4.1/slide) | 1283 (2.3) | **2287 (4.1)** |
| naming-rule violations | 481 (21%) | 3 (0.2%) | **40 (1.7%)** |
| kept of 338 on the baseline slides (noise floor: 229) | — | 137 | **170** |
| loss beyond the noise floor | — | 92 | **59** |
| mean Jaccard vs saved (floor 0.487) | — | 0.363 | **0.426** |
| "different concept" losses | — | 221 | **142** |
| distinct Concept nodes | 561 | 327 | **546** |
| Concept nodes that would change | — | 532 | **641** |
| seconds (serial A, incl. outline) | ~13,760 extrapolated | 5,888 | **7,039 (1.95× faster)** |
| completion tokens | ~384,000 extrapolated | 168,631 | **210,994 (0.55×)** |
| Sections with summary / objectives | — | 141/147, 140/147 | 134/145, 134/145 |

- **Explanation, now complete:**
  - a third of the losses happen with no change at all (the noise floor);
  - of the rest, about half are the pinned naming rule renaming saved sentence-names: shortened 58, long name dropped 51, abbreviation 20, narrower 18, plural 10;
  - the remaining different-concept residue is 142 over 561 slides, against 106 for the unchanged call over 172 slides.
- **Concept nodes:** 641 would change, more than the first prompt's 532. The graph is now the same size (546 against 561), but more of the names are new. Those are rule renames and noise, not lost coverage.
- **The re-golden is unblocked on the drift side. It still needs:**
  - the stale-TEACHES ruling below, or a wiped course to start from;
  - #172 pushed.
- **A small regression in Section notes:** 11 of 145 Sections came back without a summary, against 6 of 147 on the first prompt (`lane-tr scratch: notes_chk.log`).
  - Six are the same both times: `(no section)` ×4, plus Appendix and References in `nested-empty-section`. Those are markers with nothing to summarise.
  - The recall prompt adds five:
    - three parent sections in `nested-four-levels` (Hydraulic Systems, Power Generation, Pumps);
    - the only section of two short decks: `empty-blank-slide`, and "Rigging Basics" in `empty-no-metadata`.
  - The coverage instruction crowds out the notes on some calls. That is a follow-up wording fix ("every Section with slides gets a summary"); I have not made it, because an unmeasured prompt edit would void this table.

## Item 5: the normalisation pass (PR B, `lane/tr-normalise` f374e6e)

**The "old" asset is not old.** doc-tools never had a term-unification asset: a search of all 941 commits found none. The asset is the workbench's `harmonize_concepts`.
- It is **live**: it is registered with `harmonize_concepts_job` and `unharmonized_concepts_sensor`, and it was edited as recently as 2026-10-26.
- It is LLM-only (dspy over names), keyed by name, carries no confidence, and has no review step.
- It has never run against the sandbox: 0 CanonicalConcept, 0 ALIGNS_TO.

So this is an ownership move, not a port of dead code.
- Contract §4.4 said doc-tools never writes CanonicalConcept or ALIGNS_TO. Contract v5 makes `concepts.normalise` their only writer, and a seal enforces it.
- **The two writers must not overlap.** wb MERGEs on `name`; we key on a sticky id.
  - The per-course run therefore defaults to `TRAINING_CONCEPT_ALIGNMENT=dry` (plan, log, write nothing).
  - It goes to `on` only by a values change, after wb turns off its asset and sensor. The fleet job defaults to a dry run too.

**Edge direction: needs a ruling.** The order says "ALIGNS_TO from Concepts", and wb's contract copy (line 118) says Concept → CanonicalConcept. But every wb reader uses the opposite direction: `main.py` ×7, `alignment.py`, `generator_service.py` and the sensor. PR B writes `(CanonicalConcept)-[:ALIGNS_TO]->(Concept)` to match those readers. Reversing it would break all of them silently.

**What PR B does:**
- **No LLM call.**
- **Auto links:** exact after normalisation (`align_key`), or related_terms naming each other both ways. Each edge carries `confidence`, `method`, `status='auto'` and `source`.
- **Everything else is a proposal:** a separate `PROPOSED_ALIGNS_TO` edge with confidence. It is never auto-merged, and wb's status-blind readers can't mistake it for an alignment.
  - A proposal needs a lexical signal: one-way related_term, plural, acronym, or token overlap.
  - The cosine of the teaching slides' mean embedding only ranks proposals.
  - Co-taught pairs are excluded, because the model listed them as distinct.
- **Re-runs:**
  - cc ids are sticky across runs;
  - accepted and rejected decisions are preserved;
  - only `status='auto'` edges and `source='concepts.normalise'` orphans are ever replaced or deleted.
- **When it runs:** per course on ingest (`dry` by default), and fleet-wide on demand (`normalise_concepts_job`, `scripts/normalise_concepts.py`).
- **Known limits:**
  - writes are not one transaction (a rerun converges);
  - the cc match scans every CanonicalConcept.

**Measured, read-only, over the sandbox's 677 Concepts** (`align_dry_findings.md`):
- **Planning cost:** load 1.8 s, plan 0.3 s.
- **Auto links:** 219 exact, giving 559 components. The 101 multi-member components are all case or typography variants, with no false merge seen.
  - 0 mutual links, because no sandbox Concept carries related_terms yet.
- **Proposals:** 1550, which is not usable as a review queue.
  - The cosine is ≥ 0.99 on 98% of them, because three of the courses are re-ingests of the same content. Identical slides under new ids give identical vectors, and the co-taught test compares ids.
  - So the sandbox cannot measure proposal precision.
  - **Options, for your ruling:**
    - (a) rank token overlap by Jaccard, not cosine;
    - (b) raise the token-overlap floor (0.5 → 0.67);
    - (c) make co-taught compare slide-content hashes.

  I recommend (c) plus (b). No code is changed until you rule.

### Appendix: the alignment dry run in detail

Harness: `lane-tr scratch: nb2\align_dry.py` + `concepts_b.py` (a copy of `doc_tools/passes/concepts.py`; it imports a shipped `concept_identity.py`, because the pod image predates #167). It writes nothing to any store. Output: pod `/tmp/align_dry.json`.

#### Plan stats (scope = fleet, default settings)
- **Concepts:** 677 → 559 components (559 CanonicalConcepts would be created, 0 reused; the sandbox has none).
- **Auto edges:** 219 `exact`, 0 `mutual_related_terms`, 458 `self`.
  - 0 mutual is expected: no sandbox Concept carries related_terms, because PR A has not been rolled.
- **Multi-member components:** 101. All are case or typography variants, e.g. `Phase Angle Separation (120°)` / `Phase angle separation (120°)`.
- **Proposals:** 1550 (1500 token_overlap, 50 plural), over 1240 distinct (concept, cc) pairs, on 437 of 677 concepts. 5 is the per-concept cap, and it is hit.
- **Confidence:** 1482 of 1550 round to 0.8; the range is 0.70–0.9999.
- **Time:** load 1.8 s, plan 0.3 s.

#### Cosine does not rank on this data
- For token_overlap proposals, cos ≥ 0.99 on 1466 of 1500; the minimum is 0.834.
- Only 405 distinct vectors exist among 677 Concepts; the largest group of identical vectors is 7.
- **Cause:** three courses of ~270 Concepts each (`sha256:a6ec1326…`, `bb1d2ec6…`, `f266c8ed…`) share 217 Concepts. That is the same content ingested three times.
  - Identical slide text under different slide ids gives identical vectors.
  - The co-taught exclusion compares slide ids, so it does not see them.
- **Effect:** confidence collapses to the signal's fixed term plus 0.6·cos ≈ 0.8, so the queue order is arbitrary.

#### What this means
- The auto side is sound: 219 links, all exact after normalisation, with no false merge seen in the 101 components.
- A 1550-item review queue for 677 Concepts is not usable as a queue.
- The sandbox cannot measure proposal precision, because it is re-ingests of the same decks.
- **Options for the architect:**
  - (a) rank token_overlap by Jaccard rather than cos;
  - (b) raise its Jaccard floor from 0.5 to 0.67;
  - (c) make co-taught compare slide content hashes, not slide ids.
- No code is changed pending a ruling.

## Cross-repo: the overlay drift seal, for 7f and Lane 1
- **Locally,** `test_overlay_kind_drift.py` **skips all six arms** unless `IAGENT_CONTENT_KIND_OVERLAY_DIR` is set ("NOT satisfied, only unrun").
- **Against platform `origin/master` `3ff2235f`:** main is green, and #172, A and B each fail `test_the_shared_kinds_declare_the_same_passes` on `course`:
  - #172 adds `structural.outline`;
  - A renames `training.baml::ExtractConcepts` to `training.baml::ExtractSectionConcepts`;
  - B appends `concepts.normalise`.
- **After #181:** the seal runs in CI against `tests/pins/invincible-agent.ref`, so each of these PRs needs an overlay commit carrying its row and a pin bump.
  - A packet to Lane 1 asking for one overlay commit per PR, in merge order, is drafted. I will place it when the PRs are approved.
- **For 7f:** `7f/sdk-v0911-kind-registrations` makes `registry/content_kinds/*.yaml` generated from `KIND_MAPPING`. A and B change `KIND_MAPPING` and the course row, so I will regenerate on rebase rather than hand-merge.

## What I have not done
- **#172's force-push:** it waits on Chris. Then PRs A and B open, and #172 leaves draft once its two pod runs are done (packet to Lane 1 first).
- **The re-golden:** it waits on ruling 1, or on a wiped course to start from.
- **Re-ingesting `_p132`/`_p102`:** it follows the re-golden.
- **The wb packet:** synthesis reads Section summaries; the slide query excludes section objects only after the first v4 ingest; turn off `harmonize_concepts` and its sensor before `TRAINING_CONCEPT_ALIGNMENT=on`; accept/reject semantics for `PROPOSED_ALIGNS_TO`; golden v5 `ef1a8799`; fix the direction on line 118 of wb's contract copy. It goes out after rulings 2 and 4.
- **Chris's deck:** its per-stage timings are not in yet, because it has not been dropped.

---
From doc-tools lane tr (Claude Opus 5.5 on behalf of Chris Nogradi).
