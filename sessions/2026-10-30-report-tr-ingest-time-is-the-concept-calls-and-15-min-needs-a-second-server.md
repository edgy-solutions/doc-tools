to: invincible-agent/seat/architect
cc: doc-tools/lane/7f
from: doc-tools/lane/tr
date: 2026-10-30
relay: Chris
This report carries no secret. Nothing was changed: every measurement below writes nothing.

# Ingest time: 90% is the per-slide concept calls, and they're serial on one server; no vision to skip

## Bottom line
- **Where the 81–100 min goes:** 160 sequential `ExtractConcepts` calls at 27.3 s mean is about 73 min. Add the outline at 5 min and render at 1 min, and that's 81 min.
- **Vision is not on the course path at all.** The Vision client is used only by sustainment ExtractParts. "Skip vision when the text layer is clean" has nothing to cut.
- **Parallel page renders save at most about 20 s.** Render is 57 s of the 81 min, and the pod is capped at 2 CPUs.
- **The model server serializes requests.** 4 concurrent concept calls ran 1.03× faster than sequential. Threading the calls in the pod buys nothing.
- **The real cut: lean output plus batching per section.**
  - **Lean output:** ask only for the fields the job keeps. `description`, `related_terms`, `summary` and `objectives` are generated and then discarded.
  - **Batching per section:** about 8 slides per call, one entry per slide.
  - **Measured:** 4.4× fewer generated tokens and 3.5–6× less wall time.
  - **Projection:** about 25 min for 150 slides, not 15.
- **Reaching ≤15 min needs model throughput, not code:** a second server for half the batches, or parallel decoding on A. Both are Chris's boxes, so both are decisions. Neither is measured.

## Method
- Write-free scripts, run by hand in pod `doc-tools-65766ddbdc-46bgv` (imageID `01f016e4…`, main with #174/#175/#180/#167).
- **Deck:** `training/course/long-160-slides/long-160-slides.pptx`. It's synthetic and text-only: 160 slides, 146–188 chars a slide.
- **Calls:** the same functions the job calls. LLM variants POST the job's exact `b.request.ExtractConcepts` body with one change, and are parsed back.
- Nothing else ran in the pod during the measurement.
- **Caveats:**
  - **No Dagster record:** no training deck has run through Dagster since the pod started, so there are no step timestamps for a course run. The 81–100 min figure is reproduced here by the stage sum, not read from a run. Chris's drop will be the end-to-end check.
  - **Shared server:** server A is shared with iagent, and generation measured 18–31 tok/s across the session. The same 8-slide request took 191 s once and 333 s an hour later. **Token counts are the load-independent measure,** so both are given.
  - **Real decks are denser:** expect more concepts, and therefore more tokens, per slide than long-160 has.

## 1. Stages, job order (long-160, 160 slides)
| stage | measured | 160-slide total | note |
|---|---|---|---|
| partition (`extract_text_and_metadata`) | 13.1 s | 13 s | |
| render (`render.pages`: soffice 4 s + pdftoppm 52 s) | 57.0 s | 57 s | pdftoppm split 4 ways: 29.7 s; 8 ways: 35.1 s (2-CPU cgroup) |
| outline (`ExtractOutline`) | 2 calls: 156.5 s, 147.4 s | 304 s | sequential chunks of `(8192-4000)*3` chars |
| **concepts (`ExtractConcepts`)** | 24 calls: **mean 27.3 s**, p50 28.4, min 6.4, max 51.9 | **≈ 4,370 s ≈ 73 min** | 0 errors |
| concepts, 4 concurrent | 638 s for 24 (against 655 s) | — | **1.03×**: server-side queueing, p50 per call 111 s |
| embed (24 slides) | 1.02 s single, 0.41 s batched | ≈ 7 s | not worth a change |
| Neo4j round trip | 10 ms | < 30 s | |
| Dagster step launches | ~95 s (from sustainment run 9daf1ad2) | ~95 s | not measured on a course run |

**Sum ≈ 81 min.** At 32 tok/s, the concept calls are generating ~800–1,000 tokens a slide.

## 2. Concept-call variants (the same 8 slides, `gpt-oss-128k:120b` on A)
| variant | wall for 8 | generated tokens | parse | note |
|---|---|---|---|---|
| today, one call per slide | 191 s / 333 s | 5,968 / 7,425 | 8/8 | two runs, an hour apart |
| today + `reasoning_effort=low` | 138 s | 4,153 | 8/8 | 1.4× |
| **lean output**, one per slide | 150 s | 3,607 | 8/8 | half of today's 7,425, in the same run |
| lean + low | 92 s | 1,868 | 8/8 | |
| today's schema, 8 slides in one call | 98 s | 3,037 | 1 merged answer | not per-slide; at low effort it collapsed to 6 concepts |
| **lean, 8 slides in one call, one entry per slide** | **54.8 s** | **1,672** | 8/8 entries | **4.4× fewer tokens than today**; ≈ 6.9 s a slide |
| lean batch + low | 73.7 s | 1,351 | 8/8 | low didn't pay at batch size, within the load noise |

- **What the job keeps:** `TrainingPlugin.augment` keeps `concepts[].name`, `concepts[].salience` and `figure_references`. It builds `objectives`, but nothing on the training path reads them; there's no write.
- **What the schema asks for:** `Concept.description`, `related_terms` and `summary`. None of them reaches the graph or Weaviate.
- **The p132/p102 swallowed failures were `summary` missing from a reply.** A lean schema removes that failure class as well.

## 3. Proposed cut, in order (nothing done; each is its own PR on your go)
1. **Lean ExtractConcepts output:** concepts as {name, salience} plus figure_references. Measured at half the tokens, and it removes the "missing summary" parse failure.
2. **One call per section of ≤8 slides, one entry per slide.** It uses #172's outline sections, falling back to fixed runs of 8 when a section is bigger or missing. Measured at a further ~2× on tokens and 54.8 s per 8 slides.
3. **Projection with 1+2, at 150 slides:**
   - concepts ≈ 150 × 6.9 s ≈ 17 min;
   - outline 5 min, fixed stages ~3 min;
   - **total ≈ 25 min**, from 81–100.
4. **To reach ≤15 min,** about 2× more model throughput is needed. Two options, both on Chris's hardware:
   - **(a) Route half the batches to a second server.** D (`.169:11435`) is the only other port that may serve the 120b. This is real parallelism, unlike threads against A. The outline can also run there alongside the concepts, because per-slide concepts don't need the outline. **Projection: 22 min of serial LLM work split over two servers, plus 3 min fixed, is ≈ 14 min.** Unmeasured: it would load 64 GB on D, which I won't do without Chris.
   - **(b) Parallel decoding on A** (`OLLAMA_NUM_PARALLEL`). It's the same box iagent pins on. Aggregate gain is unmeasured.
5. **Small and safe:**
   - Overlap render with the step-2 LLM work instead of running it in step 1: about −1 min.
   - Splitting pdftoppm saves −20 s at most, so it isn't worth its own PR.

## 4. Risks
- **Concept identity moves.** #167 keys Concept on hash(domain, normalized name). In this sample, lean and batched names cover the same topics, but they drift toward sentences ("Phases are 120° apart" where today gives "Phase Angle Separation").
  - So a prompt change re-keys concepts against the 20 courses already in sandbox and their goldens.
  - **Gate:** before adopting, add a noun-phrase instruction and measure TEACHES overlap against the 20 deck goldens.
- **Untested beyond 8 slides a batch, on real decks, and under load.** Chris's drop measures the first two; the gate covers the rest.

## Raw
- Scripts and outputs are in tr's scratchpad: `ingest_bench.py`, `concept_variants.py`, `concept_lean.py`, `store_rtt.py`, and `*_long160.lines.log` with every number above and the per-slide concept names.
- Pod copies are `/tmp/{bench,cv,cl}_long160.log`.

## Next
- **Chris's drop:** still none at 01:40Z; the sensor is skipping. When it lands, tr records the run's step timestamps and reads back the stores, then adds the real-deck per-slide tokens to this report.
- **The order you gave stands:** re-ingest _p132/_p102, then #172's pod runs, then #172 out of draft. No ingest-time code until you choose from §3.

— lane tr
