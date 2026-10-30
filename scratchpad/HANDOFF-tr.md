# Lane tr handoff (in-flight state only)

Updated 2026-10-23. The worktree is under the session scratchpad: `C:\Users\cnogr\AppData\Local\Temp\claude\c--Users-cnogr-git-doc-tools\89a7899d-7fa6-4826-acdd-9d2abcc98b28\scratchpad\dt-tr`. It was moved from `C:/tmp/dt-tr` on 2026-10-23, per the architect: no /tmp, worktrees included. Find it with `git worktree list`. After the move the venv was re-pointed with `uv sync --frozen --inexact --reinstall-package doc-tools`, and the gate is unchanged: 37 passed, 5 xfailed. Main has moved to `089a6ad` (#152).

## STATE 2026-10-29 latest: PR B COMMITTED + pushed (`lane/tr-normalise` f374e6e on 3aa81a1, no PR yet; suite 2419 passed); alignment dry run DONE; drift bench 16/20
- **PR B dry run** (read-only, in the pod) over 677 Concepts: 219 exact auto links, 101 multi-member components, and 1550 proposals with cos saturated (≥0.99 on 98%, because three courses are re-ingests of the same content). The queue is unusable as ranked. Findings and options are in `SP\align_dry_findings.md`; they go in the architect report. No code change without a ruling.
- Harness: `SP\nb2\{align_dry,dup_chk,course_chk}.py` plus `concepts_b.py` and a shipped `concept_identity.py` (the pod image lacks it).

## STATE 2026-10-29 late: PR A COMMITTED + pushed (`lane/tr-concepts` 3aa81a1, no PR yet); drift bench 9/20
- **#172 rebased** to `8020dde` on main `7ffb6a2` in `SP\dt-tr-g` (`lane/tr-g`). Full suite: 2342 passed (`SP\pytest_g_full.log`). **NOT PUSHED:** auto mode denied `git push --force-with-lease origin lane/tr-g`. That needs the user; don't work around it.
- **PR A:** `SP\dt-tr-c`, `lane/tr-concepts` 3aa81a1 on 8020dde, PUSHED. The PR is NOT opened yet: the drift numbers go in its body.
  - Reviewed: training.py, semantic_assets and contract v4. The NotEqual-on-missing-`chunk_kind` claim is now marked UNMEASURED.
  - Suite: 2375 green, run before that doc edit.
  - The CRLF-only baml_client files (config/globals/tracing) are left unstaged on purpose.
  - It is stacked on the unpushed #172, so a PR would show #172's commits until `lane/tr-g` is force-pushed.
- **Drift bench:** `SP\drift_bench.py` is running in the pod (`nohup setsid`, out `/tmp/drift/<slug>.jsonl`, log `/tmp/drift.log`); the bundle is `/tmp/nb` (from `SP\nb`). It is write-free and takes ~6 h. A rerun skips the decks that have a "done" line.
  - **To analyse:** `kubectl cp` to `SP\drift_out`, then venv python `-I SP\drift_analysis.py SP\drift_out SP\dt-tr\tests\fixtures\training SP\dt-tr-c\doc_tools\utils\concept_identity.py SP\drift_analysis.json`.
  - **Early signal (2 decks):** the full section schema gives about HALF the concepts of today's per-slide call (17 vs 32); lean gives 26. Explain this before any re-golden.
- **PR B (item 5):** the implementer is building it from `SP\spec_pr_b.md` in `SP\dt-tr-n` (`lane/tr-normalise` off 3aa81a1), uncommitted; review its result before committing.
  - Design choices to put in the report:
    - no LLM;
    - auto links = exact `align_key`, or mutual related_terms;
    - proposals are a separate `PROPOSED_ALIGNS_TO` (so wb's status-blind readers don't treat them as alignments) and need a lexical signal, with cos used only to rank;
    - co-taught pairs are excluded;
    - sticky cc ids;
    - a failed per-course run doesn't fail the ingest;
    - the fleet job defaults to a dry run.
  - **Sandbox Neo4j census (read-only):** 677 Concepts, ZERO CanonicalConcept, ALIGNS_TO or ALIAS_OF. wb's harmonizer never ran here, so there is nothing legacy to migrate.
  - **Correction to memory:** wb's `harmonize_concepts` is LIVE. `8040cf4` kept it, and its sensor is registered. wb's readers all use CanonicalConcept → Concept; wb's contract copy (line 118) says the reverse.
- **Item 5 lookup:** the old asset is wb's `harmonize_concepts` (memory file). Contract §4.4 says doc-tools NEVER writes CanonicalConcept/ALIGNS_TO, so PR B is an ownership change in the contract. Raise it in the report.

## STATE 2026-10-30 ~02:10Z: ARCHITECT ORDER (supersedes tonight's three lines): PR A = 1+2+3 with the measurements in 4, then PR B = 5
1. **One ExtractConcepts call per section** (≤8 slides). Concurrency is a setting, default 1: home is serial, while work's vLLM behind LiteLLM decodes in parallel.
2. **Schema:** concepts[{name, salience, related_terms}], figure_references, section_summary, section_objectives. Drop `description`. The prompt pins concept naming: a noun phrase of ≤4 words, never a sentence.
3. **Write all of it:**
   - related_terms become ALIAS_OF candidate edges between Concepts, never auto-merged.
   - Section summary and objectives go on the Section node and into Weaviate.
   - Contract v4, with #167's edits.
   - wb's synthesis reads the summaries.
4. **Drift:** measure against the 20 saved outputs before and after, count the Concept nodes that would change, and re-golden only once the drift is explained. Time both this schema and the lean one.
5. **Normalisation pass:** find the old term-unification Dagster asset in git history and port it as an ADR-0059 pass.
   - Inputs: names, related_terms, and slide embeddings. Output: CanonicalConcept, with ALIGNS_TO edges carrying confidence.
   - Auto-link on an exact match or reciprocal related_terms; everything else becomes a review proposal in wb.
   - Runs per course on ingest, and fleet-wide on demand. wb's CanonicalConcept writes move onto it.
- Chris's real deck still gets its per-stage timings in the ingest report when it lands.
- **Lookups are out** (Explore ×3): the write path and contract, the goldens, and the old unification asset.

## STATE 2026-10-30 ~01:50Z: INGEST-TIME REPORT PLACED (no code changed); Chris has not dropped yet
- **Report:** `doc-tools/sessions/2026-10-30-report-tr-ingest-time-is-the-concept-calls-and-15-min-needs-a-second-server.md` (untracked, to the architect cc 7f).
  - 27.3 s per slide for ExtractConcepts accounts for ~73 of the 81 min. A serializes: 4 threads ran 1.03×. There's no vision on the course path.
  - Lean schema plus 8-slide batches gives 4.4× fewer tokens and a projection of ~25 min. Reaching ≤15 min needs a 2nd server or parallel decoding on A, which is Chris's decision.
- **Bench scripts** are in SP: `ingest_bench.py`, `concept_variants.py`, `concept_lean.py`, `store_rtt.py`. Result lines are in `SP/*_long160.lines.log`; pod copies are in `/tmp/*_long160.log`.
- **Gotcha:** `pkill -f ingest_bench` inside `kubectl exec sh -c '...ingest_bench...'` kills the sh itself (exit 143). Use `pgrep -f "[i]ngest_bench.py"` patterns.
- **Waiting on:** Chris's drop (sensor skipping at 01:40Z), then the architect's pick from report §3.
- **When the drop lands:** `run_events.py` gives step timestamps, then read back the stores, then add the real-deck tokens per slide to the report.
- **Then the order stands:** re-ingest _p132/_p102, then #172's pod runs (packet to Lane 1 first), then #172 out of draft.

## STATE 2026-10-30 ~00:25Z: SENSOR ON, BACKFILL DONE (31,630/31,630, all PASS), lock released
- Pod `doc-tools-65766ddbdc-46bgv`, imageID 01f016e4, helm doc-tools 57, iagent 221. #174/#175/#180/#167 are in main.
- training_sensor is RUNNING with cursor `2026-10-24 04:28:46.672000+00:00`; every tick SKIPS. The next object Chris uploads fires.
- Report: `doc-tools/sessions/2026-10-30-report-tr-sensor-on-and-has-slide-backfilled-31630-of-31630.md`. Lock packets (taken and released) are in `invincible-agent/sessions/2026-10-29…` and `…2026-10-30…`.
- NEXT, in order:
  1. Watch Chris's drop end to end: the tick, the run, the run log for "Plugin augmentation failed" and link_write, and a readback of Neo4j, Weaviate and MinIO.
  2. Re-ingest _p132/_p102 and re-golden them.
  3. #172's pod runs (packet to Lane 1 first). #172 must be rebased onto main first, because #167 is merged (the 7f packet said it conflicts). Architect: the ALIGNS_TO direction fix goes in contract v4 with #167. Measured on main: the header still says "Contract version 2", and §4.4 line 121 ALREADY reads CanonicalConcept → Concept. So find the wrong-direction line (in #172's v3 text?) before writing v4.
  4. #172 out of draft.

## STATE 2026-10-26 ~19:00Z: #174 MERGED (`3277ed1`); **PR #175 open** (lane/tr-link-write rebased to `a579f22` on main; gate 30/30)
- Architect: "Backfill after both rolls, dry run then write. The canonical/plain direction fix (§4.4 ALIGNS_TO, CanonicalConcept→Concept) goes in contract v4 with #167."
- Next: #175 CI → Chris merges. Then wait for 7f's pin roll (pod imageID ≠ 086766d7) and for 208 to finish (iagent was rev 218 pending-upgrade). Then: sensor dry/--apply, backfill dry/--apply under the lock, tell Chris the path.

## STATE 2026-10-26 ~18:30Z: link_write+backfill COMMITTED `07b78e9` on lane/tr-link-write (pushed, stacked on #174); NO PR yet
- Reviewed it myself. Gate: 30 passed. Full suite: 2176 passed, 20 skipped, 7 deselected, 1 xfailed (`SP\pytest_lw_full_mine.log`).
- When #174 merges: `git rebase --onto origin/main origin/lane/tr-has-slide lane/tr-link-write`, rerun the gate, force-push with lease, then open the PR against main.
- **The backfill needs a main image in the pod.** It imports `doc_tools.utils.graph_overlay` (#157), which v0.2.1 doesn't carry. So run it AFTER 7f's pin roll AND after 208, under the lock, announced: dry run first, then `--apply`. `Neo4jClient.execute_query` returns `[record.data()]` (checked in the pod), so the script's `rows[0][key]` holds.
- 208 is in flight: the iagent release is rev 218 `pending-upgrade`, deployed 12:24:58 (10-26). The doc-tools pod is still imageID 086766d7 (v0.2.1), helm rev 54.
- wb FYI packet (`invincible-agent/sessions/2026-10-26-packet-to-tr-canonicalconcept-is-empty-live-wb-own-label-nothing-asked.md`): nothing asked. **At the next contract revision,** §4.4's ALIGNS_TO direction must read CanonicalConcept → Concept. That isn't in #172 (it would move the v3 pin).

## STATE 2026-10-26 ~17:30Z: architect ruled; #174 green (Chris merges); link_write+backfill PR with the implementer
- Architect: "#174: Chris merges when green. Next PR: (a) swallowed print → failed:link_write on the run; (b) one-time HAS_SLIDE backfill, a single Cypher mirroring HAS_CHILD→HAS_SLIDE, counted before/after, run UNDER THE LOCK AFTER 208 FINISHES. Sensor: set the high-water mark to now and turn it on after 7f's pin roll; the 21 decks are not re-ingested. Then tell Chris the path."
- (a)+(b): spec `SP\spec_link_write.md`. Worktree `SP\dt-tr-lw`, branch `lane/tr-link-write` off `lane/tr-has-slide`. REBASE onto main after #174 merges, BEFORE opening the PR (a stacked PR gets no CI).
- 208 = Lane 1's iagent chart 0.4.70 roll (iagent is at rev 217 / 0.4.69 now). It restarts Neo4j and takes the sandbox roll lock. It waits on Chris's OK. I told Lane 1 that tr does not hold it.
- Sensor start: `SP\start_training_sensor.py` (dry by default; `--apply` sets the cursor, reads it back, starts, and waits for one SKIPPED tick). kubectl cp it to the pod /tmp. Its state query was validated against ingress_user_sensor.
- Packet: `doc-tools/sessions/2026-10-26-packet-to-7f-and-lane-01-from-tr-sensor-ruled-roll-when-ready-208-not-held-by-tr.md`

## STATE 2026-10-26 ~16:30Z: REAL DECKS blocked on a roll; HAS_SLIDE PR with the implementer
- Architect: "Real decks today: give Chris the drop path and formats, confirm the sensor fires <1 min, watch the drop end to end. HAS_SLIDE gap is yours, next PR. #172 stays draft until the pod window after."
- **Sandbox runs v0.2.1 (`b95a550`, imageID 086766d7), which has NO training_sensor** (#155 isn't in it; there are 14 sensors in the location and none watches training/course/). A roll to the main image built at `5027cc8` is 7f's call. Packet: `doc-tools/sessions/2026-10-26-packet-to-7f-and-architect-from-tr-sandbox-has-no-training-sensor-real-decks-need-a-roll.md`
- **After the roll, DON'T start the sensor bare.** There are 21 objects under the prefix, and get_s3_keys returns everything unless the cursor EXACTLY equals an object's str(LastModified). Read the newest object's str(LastModified), setSensorCursor, startSensor, check one SKIPPED tick, and only then let Chris drop. Tools: `SP\sensor_state.py` (read-only GraphQL) and `SP\list_course_prefix.py` (read-only S3), run in the pod via kubectl cp to /tmp.
- Drop guide for Chris: `SP\drop_guide_chris.md`.
- HAS_SLIDE: **PR #174 open** (lane/tr-has-slide, pushed; it merges clean with #172). The existing 20 courses need a re-ingest or a backfill. Main also shows 20 skipped, so #172's 20th skip is not new.

## STATE 2026-10-26 ~04:00Z: step g is DRAFT PR #172 (`lane/tr-g` @ `44cb196`, pushed); waiting on the pod
- Local run (PowerShell, venv): gate 94 passed, 2 skipped (pre-existing cad/xml). Full suite 2195 passed, 20 skipped, 8 deselected, 0 xfailed. Main has 19 skipped, so **one new skip is still unidentified** (it's not in the gate files). Logs: `SP\pytest_g*.log`.
- Hashes: contract v3 `c77d44fc…ae3cf1`; golden `04cd8ba3…febcb0`. The golden is PROVISIONAL (`recorded:false`).
- **Before #172 leaves draft (both need the pod):**
  1. Record a real hydraulics ExtractOutline reply (LLM only). Put it in `make_golden.py` FALLBACK_OUTLINE, set `recorded: True`, fix the note, regenerate, and check the derived sections still assert.
  2. Run `scripts/training_section_replace_survival.py` in the pod, by path from `/tmp` (PYTHONPATH=/app wins), against sandbox Neo4j. It is the first live check of `FOREACH … DETACH DELETE`.
- Packets placed (untracked):
  - Lane 1: `invincible-agent/sessions/2026-10-25-packet-to-lane-01-from-tr-step-g-needs-two-short-pod-runs.md`, asking for a pod window.
  - 7f: `doc-tools/sessions/2026-10-25-packet-to-7f-from-tr-step-g-takes-contract-v3-and-conflicts-with-167.md`
  - wb: `doc-tools/sessions/2026-10-25-packet-to-wb-from-tr-step-g-contract-v3-provisional-golden.md`
- Then: wait for 7f's augmentation-swallow fix and re-golden p132/p102. Regenerate the 20 deck goldens after #172 and #167. `lane/tr-decks` (`efea7ca`) PRs only on Chris's go-ahead.

## STATE 2026-10-26 ~03:30Z: e (#164) and f (#166) MERGED by Chris; step g with the implementer
- Architect's order: "Step g; then wait for 7f's parse fix and re-golden 132/102. #166 merge is Chris's." Chris then merged #164 (`ac661e4`) and #166 (`36b7e34`) at 03:05Z. Main is at `05d8f7b`.
- **Step g design (user + architect, decided):**
  - Deck first, LLM fallback. `Course.outline_source` is deck|llm.
  - LLM fallback titles are pinned in the golden (`neo4j.outline.fallback`), so re-runs compare rather than regenerate.
  - Build-then-replace: a single-statement Section subtree swap; a failed build keeps the old one and fails the run.
  - The §4 survival test counts TEACHES, COVERS and ALIGNS_TO before and after. The contract §4 sentence goes in the same PR, at v3.
- Spec: `SP\spec_step_g.md`. Worktree `SP\dt-tr-g`, branch `lane/tr-g` off `05d8f7b`. Delegated to the implementer.
- **Measured for the spec:** on small decks, 98% of LLM section titles equal a slide Title after normalization, but the LLM's start_page is right on only ~35%. Long decks get synthesized titles. The probe is `SP\anchor_probe.py`.
- **Before g leaves draft:**
  - (1) Record a real hydraulics ExtractOutline reply in the pod (LLM only, no store writes) to replace the provisional `fallback`, `recorded:false`.
  - (2) Run `scripts/training_section_replace_survival.py` in the pod against sandbox Neo4j. Both need the pod, which was handed to Lane 1 at 08:14Z, so packet Lane 1 first.
- Survival test: no real Neo4j exists in the suite (MagicMock only), so it is a `neo4j_live`-marked test that skips in CI. Say so in the PR.
- `lane/tr-decks` (`efea7ca`): #164 has merged, so it can PR once Chris says go.
- 7f has not replied on #167, the contract v3 edit, or ALIGNS_TO. g takes v3; whichever of g and #167 lands second takes v4.

## STATE 2026-10-25 ~08:40Z: overnight order DONE through "hashes to wb"; f is PR #166; g next

- **Rerun:** 20/20 OK, finished 08:04:48Z.
  - Two swallowed `Plugin augmentation failed` errors: long-with-blank-gaps p132 (run `2f1a9649`) and long-160 p102 (run `7b13e210`). Both are BAML "missing summary", and those slides have 0 TEACHES.
- **Lane 1 packets** are in invincible-agent `sessions/`: `...-tr-rerun-finished-0804z-readback-next.md`, then `...-tr-readback-pulled-0814z-pod-is-yours.md`. The pod is released.
- **Readback** `SP/rbpull2/` (rb/ + runs.jsonl), tgz sha `f7dc5c86`.
- **Goldens:** `lane/tr-decks` @ `efea7ca`, pushed, 20 golden.json only.
  - deck_table: 0 NO.
  - `_fig_` (f) on 4 image decks: 2/10/5/1.
- **wb packet:** `doc-tools/sessions/2026-10-25-packet-to-wb-from-tr-deck-goldens-at-d-e-and-hashes.md`, 59 file hashes. Head is `SP/report_head_de.md`, assembler is `SP/assemble_packet_de.sh "" <out> <head>`.
- **7f's #167** (Concept id = hash(domain, casefolded name), plus a constraint) is OPEN. It changes contract §3/§4.1/§8/§9 but doesn't edit them.
  - Packet to 7f: `doc-tools/sessions/2026-10-25-packet-to-7f-from-tr-pr-167-needs-contract-4-and-aligns-to-points-at-concept.md`. It covers:
    1. the contract v3 edit, 7f's or tr's;
    2. wb's ALIGNS_TO points AT Concept, so the migration aborts or needs an architect ruling;
    3. the swallowed augmentation failure.
  - The goldens regenerate after f + g + #167.
- **Next:** step g (outline pages from element metadata).
- **Also open:** #164 (e), #166 (f), and the PR for tr-decks once #164 merges and there's a go-ahead.

## STATE 2026-10-25 ~05:00Z: step f PR #166 open; rerun 18/20

- **#163 (d) MERGED** at 02:13Z, as `f1d736d`. #164 (e) is still OPEN.
- **Step f is PR #166**: `lane/tr-f` at `3d05530`, off main `3418171`, in worktree `scratchpad/dt-tr-f`.
  - Training only: `_index_chunk(require_vector=True)` raises `MissingVectorError` before any write. The asset raises at its end if training `errors > 0`. Training skips the `_fig_` loop.
  - Gate: 19 passed, 2 xfailed (e, g). Suite: 2098 passed. Body in `SP/pr_f_body.md`.
  - **Not yet run live.** That needs a candidate with e+f.
- **Rerun watcher `bln9iznkt`** is still waiting on `DONE rc=` in `run_E.log`.
- **Next, in this order:**
  1. Lane 1 one-line finish-time packet.
  2. `rb_all.sh`.
  3. Pull `/tmp/rb2.tgz`; it unpacks as `rb2/`, but build_all reads `rbpull2\rb\`.
  4. `build_all.ps1`.
  5. `deck_table`.
  6. Commit the goldens on `lane/tr-decks`.
  7. NEW packet head for d+e (the old `report_head.md` is pre-d). Contract sha comes from #164's `8add339`, not from tr-decks HEAD.
  8. Hashes to wb.

## STATE 2026-10-25 ~02:45Z: WIPE DONE, 21-deck RERUN RUNNING
- **The architect said GO.** No 7f packet: the gazetteer shipped and #162 rules on clause 1. The ALIGNS_TO flip is accepted.
- **The wipe ran:** Neo4j deleted 1970 nodes, 0 left. Weaviate deleted 581 with 0 failed, leaving the other 452 objects.
- **Hydraulics smoke run** (`run_H.log`, 154 s): TEACHES salience is on 18 of 18 edges and 0 nodes. COVERS is scored on 33 of 33. `pages/page_1..4.png` are written and the manifest has 4 pages.
- **The other 20** run SEQUENTIALLY as one nohup stream: `/tmp/cand_tr/run_E.log`, started 02:42Z, long decks last. The waiter is task `bln9iznkt`.
  - Why sequential: Neo4j has NO uniqueness constraint on Concept. So parallel name-only MERGEs could race and create duplicate Concepts.
- **When it's done:**
  1. In the pod, run `sh rb_all.sh`. It writes `rb2/` (per-slug readback + never_written + runs.jsonl) and `/tmp/rb2.tgz`.
  2. kubectl cp it to `<SP>/rbpull2/` and check the sha.
  3. Run `build_all.ps1 -Slugs <20>`. It now uses the COMMITTED `tests/fixtures/training/sandbox/build_golden.py`, reading from rbpull2.
  4. Run `deck_table.py`, then commit on `lane/tr-decks`.
  5. Write a NEW packet head; the old `report_head.md` is pre-d.
- **Uncommitted on `lane/tr-decks`:** build_golden `pending_steps` is `["f","g"]`, and deck_table shows no `(d)` when salience is on the edge.

## STATE 2026-10-24 afternoon: step d PR'd; step e building; wipe awaiting go
- #155 and #157 are MERGED. **Step d is PR #163** (`lane/tr-d` `e179c66`, off main). TEACHES salience is on the edge and the Concept merges on name. Gate: 11 passed, 3 xfailed. Suite: 1949 passed.
- **Step e:** the implementer is on `lane/tr-e` (off origin/main), working from `<SP>/spec_step_e.md`. Review it, then commit and push.
  - Measured in the pod: LibreOffice needs `ExportHiddenSlides` (147 pages vs 150), and pdftoppm names files `p-001.png`.
  - Expect Lane 1's overlay course-row drift on `render.pages`; that needs a packet.
- **The pod changed** to `doc-tools-6f69954b98-qskmt` (image `086766d7`, v0.2.1). The old `/tmp/cand_tr` is gone. Weaviate has an empty API key (len=0), so connect with no auth.
- **Wipe (Chris chose "wipe training, rerun"; counts shown, waiting on go):**
  - Neo4j: 1970 TRAINING nodes and 130,538 rels; 0 edges cross into other domains.
  - Weaviate: 581 of 1033 DocumentChunk objects are TRAINING.
  - MinIO is kept.
  - The script is `<SP>/sandbox-run/tr_wipe_training.py`; run it in the pod with `--go --expect-nodes 1970 --expect-weaviate 581`.
  - Wiping breaks wb's store-backed e2e until the rerun.
- **Step e is PR #164** (`lane/tr-e` `006f32d`, off main, pushed). A real render in the pod gave 4/4, 150/150 (hidden slides) and 5/5 (blank last slide); 150 slides take 53 s.
  - The overlay drift test shows only `doors-export` red, so no course-row drift is confirmed and no Lane 1 packet has gone out.
- **#164 also carries `8add339`:** §4.4 `ALIGNS_TO` now runs CanonicalConcept → Concept, per wb `5ccbe01` and the architect's own-labels rule. The contract sha at 8add339 is `b7dda76d…`. wb has been told and re-vendors once #164 merges.
- **`lane/tr-decks` was rebased onto main** and force-pushed with lease: `8bf6bfc`, fixtures only.
- **Candidate `lane/tr-cand-de` = `9d00b71`** (e + merge d + merge decks), LOCAL ONLY. Gate: 41 passed, 1 skipped, 2 xfailed (f, g).
  - It is unpacked in pod `/tmp/cand_tr`, with tgz sha `bf9cea66…`, `CAND_SHA` and the scripts.
  - MinIO still holds the 21 decks and 20 metadata files, so no upload is needed. A `rm -rf` in the pod was blocked by the safety check; it wasn't needed.
- **Next, once Chris says go:** in the pod, run `python tr_wipe_training.py --go --expect-nodes 1970 --expect-weaviate 581`. Then rerun the 21 decks from cwd `/tmp/cand_tr`.
- **After e:** build the candidate (main + d + e + tr-decks tools), wipe, rerun all 21 decks from cwd `/tmp/cand_tr`, then rebuild the goldens with pending `["f","g"]`, then send the hash packet to wb.
- `lane/tr-decks` `e50d0df` still sits on the old tr-c `d2de104`, so do `git rebase --onto origin/main d2de104`.

## STATE 2026-10-24 ~11:05Z: TONIGHT'S THREE ITEMS DONE
- **Step c:** #157 at `d2de104` is green and CLEAN. #155 is green and CLEAN. Both wait only on Chris to merge.
- **Decks:** `lane/tr-decks` = `e50d0df` on origin, holding all 20 folders with goldens. It is stacked on tr-c, so it has no CI. It needs a PR after #157 merges, and the PR needs a go-ahead.
- **Packet placed (untracked):** `doc-tools/sessions/2026-10-24-packet-to-wb-from-tr-twenty-decks-with-sandbox-goldens-and-the-table-four-cases-the-ingest-cannot-produce.md`. It carries the table, a sha256 for each of the 59 files, the four cases, the outage and the CRLF note.
- **long-160:** clean rerun; 160 sections; the golden is 22MB. The LLM page ranges are open-ended, giving 13022 section→slide edges (step g).
- **Pod `/tmp/cand_tr`** can be cleared later; it holds nothing that isn't in git or the scratchpad. The courses stay in the sandbox stores, so wb's e2e can see them.
- **Next:** the Lane 1 atlantia trace when it arrives; then step d (TEACHES on the edge), off main once #157 merges.
- **wb vendored all 20 (~11:30Z)** and every pin matched. Their findings and my answers:
  - Step d must make COVERS.score non-null too. It is null on all 92,344 COVERS edges in the goldens, as salience is on all TEACHES edges; the packet now says so. wb fixed their sort in `a5e83e5`.
  - Step g, which needs metadata-derived outlines:
    - nested-four-levels gets 0 Sections;
    - nested-empty-section has no empty section;
    - nested-sibling-same-title has no same-titled siblings.
    The step-g goldens must show these cases, and their hashes will change.
  - **wb checked the sha packet.** All 59 match, the contract `1284ba54` matches, and the root hydraulics files equal main. Their 63 is 59 + 3 root files + the contract.
  - The deployed workbench (training namespace) serves the 20 decks in fixture mode. wb re-vendors on the step-g packet.

## STATE 2026-10-24 ~09:50Z (supersedes the 04:40Z block where they differ)
- **The iagent helm rev 215 roll (another lane, 04:51:27Z)** recreated neo4j-0 and weaviate-0 mid-run. Errors were swallowed, so runs still said OK.
  - Four decks were rerun as streams C and D (09:26Z): dup-title-a/b (had FAILED), dup-same-bytes-b (23 swallowed errors), long-160 (1 chunk error, no Weaviate p12).
  - Attribution by run id: the other 15 had E=0.
- **`lane/tr-decks` = `baada33` on origin**, holding 19 of 20 folders, restacked on tr-c `d2de104`.
  - metadata.json is committed `-text` (CRLF, the ingested bytes) via `tests/fixtures/training/.gitattributes`. Pins were verified against the blobs.
- **#157 got `d2de104`**: a §10 contract correction (text-less LAST slide vanishes; notes are text; hidden slides; same-bytes outline union). CI is rerunning.
- **#155 and #157 were both CLEAN/green before d2de104.** Merging needs Chris.
- **Remaining:**
  - long-160 rerun (stream C; waiter running).
  - Then readback → kubectl cp (gzip + sha) → `build_all.ps1 -Slugs long-160-slides` → never_written.
  - Then commit (metadata byte-exact) → push.
  - Then `deck_table.py` over all 20.
  - Then assemble the packet: `<SP>/report_head.md` + `deck_table.md` + `fixture_sha256.txt`. Replace the `__DECKS_HEAD__`/`__CONTRACT_SHA__`/`__LONG160_LINE__` placeholders. Place it in `doc-tools/sessions/` (untracked).
- **Lane 1's atlantia `d1a7ee0b` trace has NOT arrived** (checked both sessions dirs at 09:45Z). Lane 1's 10-24 packet to tr (training:Course + course row on platform master `a31b61cb`, roll 207 not live, no group holds TRAINING) is info only.

## STATE 2026-10-24 ~04:40Z
- Step c: **PR #157 OPEN**. `lane/tr-c` is at `d028096`, rebased onto `03e3d4c` and pushed. Watch its CI.
- Candidate `lane/tr-cand` = tr-c + a merge of origin/lane/tr-b, at `7ad71e36`. It is LOCAL ONLY, a throwaway for the sandbox run. Gate on it: 40 passed, 4 xfailed.
- Pod `/tmp/cand_tr` holds the candidate tree, decks and scripts. All 21 decks are uploaded to `processing-artifacts/training/course/<slug>/`.
- **Run from cwd `/tmp/cand_tr`.** The prompts resolve against the cwd. Run 1 of hydraulics, from `/tmp`, was a false green: every LLM pass failed with "Prompt file not found" and the run still reported success. It is in runs.jsonl, but build_golden takes the last record.
- Hydraulics check run 2: OK in 143s. It matches the committed golden on Course, Slides and edges; the only gaps are e (pages), f (_fig_) and d (salience on the node).
- The two streams run under nohup in the pod: A = the 3 long decks, B = the other 17. Logs are `/tmp/cand_tr/run_{A,B}.log`, which end with a `DONE rc=` line.
- `lane/tr-decks` (from tr-c) has the 20 folders, `make_decks.py` and `sandbox/` tools staged. NOT committed; the goldens are still missing.
- wb was told: the goldens are pre-d (salience_location=concept_node, produced_by.pending_steps); dup-same-bytes has one Course with filename=same_bytes_b.pptx in both goldens.
- After the runs: tr_readback per deck → kubectl cp → build_golden → tr_never_written → commit → push → packet with the sha256s → deck table report.

## TONIGHT (architect: "don't stop"): step c + 20 decks + table
- Step c: `lane/tr-c` cut from origin/main `62c9caa`; the implementer is building it in this worktree. Scope is training only:
  - doc_id = ingest id;
  - `training/generated/<hex>/<ver>/`;
  - current.json `prefix`, plus manifest `current_key`;
  - Course title/filename/current_key;
  - overlay Course/Slide/HAS_SLIDE from a data descriptor;
  - empty-text lines dropped;
  - a Slide for every page.
  Then: suite (PowerShell) → push → PR (the directive's "PR when green" is the go-ahead).
- #155 at last check: tests and the other gates green, build-and-push in progress.
- Decks: the variation list is wb's five cases (wb message, 2026-10-23): nested sections, image-only, long 150+, duplicate names, empty text.
  - 20 folders in the layout `tests/fixtures/training/<slug>/{<slug>.pptx, golden.json, metadata.json?}`.
  - Generator: `<scratchpad>/decks-build/make_decks.py`, with the measure in `measure.json`.
  - The decks go on branch `lane/tr-decks`, stacked on tr-c. wb asked for a sha256 per file in the packet.
- Goldens: the sandbox pod `doc-tools-557cc96c6b-7v2z2` runs image `ac853308` (`DOC_TOOLS_VERSION=doc-tools@133714c0`); its uv.lock and pyproject match main.
  - The run is by hand in the pod: `kubectl cp` the candidate to pod `/tmp/cand_tr`, then `PYTHONPATH=/tmp/cand_tr:/app`, an ephemeral DagsterInstance, and `execute_in_process`. No helm roll, so no values diff is needed.
  - Use `DOC_TOOLS_VERSION=doc-tools@<tr-c sha>`.
  - No deployed sensor watches `training/`, so a drop triggers nothing.
  - Scripts are in `<scratchpad>/sandbox-run/` (tr_run_by_hand, tr_readback, build_golden).
  - Use kubectl from Bash with `MSYS_NO_PATHCONV=1`; PowerShell 5.1 mangles quoted `sh -c`.
- The goldens are what step-c code WRITES. d/e/f/g gaps show up in them, and the deck table is where they are named.

## Saturday 2026-10-24: FIRST READ is Lane 1's trace of why atlantia can't see `d1a7ee0b`
- Then check #155's CI, and only after that pick up step c.

## Step a: MERGED. #154 squash-merged as `62c9caa` (2026-10-24 03:49Z)
- Contract v2. Golden `88017f94…aae2`, contract `12468b6d…d867`.
- wb has vendored v2 and pushed `lane/wb` (6019f65, 1b415a7, 338918e). The backend serves the golden with SOURCE_READER=fixture. wb now waits on the ADR-0060 manifest shape and needs nothing from tr.
- `lane/tr` is spent. Cut step c from main.

## Step b: PR #155 OPEN. `lane/tr-b` at `6444607`, rebased onto `62c9caa` and PUSHED
- CI was dispatched (tests and 4 other jobs pending at push). Rebased suite: 1932 passed, 19 skipped, 7 deselected, 5 xfailed. Overlay seal: 6 passed, 1 failed (doors, expected until Lane 1's 207 merges).
- Fleet rule (architect, 2026-10-23): push the lane branch at the end of EVERY work block. A non-main push fires no CI.

## Step b history (pre-rebase notes)
- Contents: the `course` row, `inbound_suffix_pattern`, `training_sensor` on `training/course/`, the `training:Course` phantom, RULED_DOMAINS with provenance, the renamed path-derive test with a positive control, and the regenerated registry.
- Gate: 7 passed, 5 xfailed. Suite: 1930 passed, 19 skipped, 7 deselected, 5 xfailed.
- Next:
  - Architect, 2026-10-23: rebase onto main once #154 merges. Do NOT wait on 7f's #99 unless Chris has merged it; if it lands later, 7f rebases its own. As of this update, #154 is OPEN/UNSTABLE and #99 is OPEN.
  - After the rebase: regenerate the registry (venv, PowerShell), rerun the gate and the suite, then ask Chris before push + PR.
- On the deck path the declared passes are documentary: `run_passes_for_kind` has one caller, doors. TrainingPlugin still runs, and `extractor_config` has no consumer.
- `course` is not in `ingestable_kinds()` until a real drop has been processed.

## Packets placed (2026-10-23)
- Lane 1: `invincible-agent/sessions/2026-10-23-packet-to-lane-01-from-tr-the-course-kind-owes-a-training-class-and-an-overlay-row.md`. It asks for the `training:Course` TTL and a `course` overlay row, and reports the doors-export seal red.
  - Tonight's directive makes both Lane 1 deliverables, on 207 or 208, with the class under `setup/ontologies/`. Do not build either. A green CI is NOT evidence they landed, because the seal skips; check the overlay directory directly.
  - doors-export is already fixed on Lane 1's 207 (`b102f1f9`), rolling Monday. No action.
- 7f: `doc-tools/sessions/2026-10-23-report-from-tr-to-7f-step-b-committed-your-three-asks-and-a-red-doors-seal.md`.

## Next steps after b
c ids + versioned folder + current.json; d TEACHES score on edge; e render.pages; f Weaviate vectors; g structural.outline; h rollup stays a hook. Each step is its own PR and flips its xfail.

## Gotchas
- Run Python that imports `doc_tools` from PowerShell only. Use Write rather than a heredoc for text with apostrophes. Write pinned files as bytes.
- Quote `git show "rev:path"` in PowerShell.
- The overlay seal skips from this worktree. Set `IAGENT_CONTENT_KIND_OVERLAY_DIR=C:\Users\cnogr\git\invincible-agent\policy\overlays\openddil-lab\content_kinds`.
