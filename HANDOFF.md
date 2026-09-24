# HANDOFF — doc-tools :: lane/7f

Branch `lane/7f`, pushed at `59771d9`, nothing unmerged of its own.

State as of 2026-09-23:
- PR #1 MERGED as `38f3d39`; PR #2 MERGED as `0279d83`.
- Sandbox runs helm rev 12 at image `0279d83`, imageID
  `sha256:71a662f0f41a3cbc1484f0b465c83871b3cf3ec09b2487b0a8cc6aea72606046`
  — VERIFIED against that commit's own build log (run 35804122987), not
  taken on report. `38f3d39` is an ancestor of `0279d83`, so the blank-node
  filter on both legs and fix D are both in the running pod.
- `main` has since moved to `6d04e93`. Two files differ between the running
  image and `main` that are not docs: `doc_tools/plugins/sustainment.py` and
  `charts/doc-tools/values-sandbox.yaml`, both from `b11323e`. The 8192
  vision cap is live via the CHART (helm rev 12); the sustainment.py change
  from that commit is NOT in the running image. Nothing in the MESH prime
  touches that path, but do not read "main is green" as "main is deployed".

## Verified this session
- **The green that merged was at `9a5ae75`, not `bee5b4c`.** Correcting the
  earlier report in this file: `bee5b4c` was green (run 35484058642,
  2026-09-20), but Chris pushed `9a5ae75` ("Remove forge") on top before the
  merge decision, and that is the head PR #1 carried into `38f3d39`. It is
  green on its own run, 35680441996 (2026-09-22): all 3 jobs, `tests` 407
  passed / 13 skipped / 0 failed. The delta between the two heads is one
  24-line deletion, `.forge/skills/check-part-sustainment/SKILL.md`.
- Both PR-event runs printed `push: false` in `build-and-push` — a
  `pull_request` build never pushes an image. The push, if any, belongs to
  the `main` event on `38f3d39`.
- No `if:` anywhere in the workflow, so nothing could have been silently
  skipped in either run.
- Blank-node filter asymmetry (Weaviate leg had neither SPARQL nor Python
  layer; Neo4j leg had both) fixed at `a8e2b3e`, test now asserts both legs
  per-function (`_leg_source`), not module-wide. Verified by single-line
  deletion: each leg's guard fails independently; the OLD guard would have
  stayed green with the Neo4j-only fix — that blindness is why this shipped
  unnoticed for 3 months.
- `n<hex>b<counter>` and `N<32hex>` are the SAME writer (rdflib), two parsers
  (notation3 vs rdf/xml). No second writer; existing `isinstance(BNode)`
  check already covers both spellings.
- `aitool_linker` is MANUAL-ONLY in this repo: sensor commented out
  (`definitions.py:221-226`), no `schedules=` anywhere (repo-wide grep,
  empty), no job selects the asset. Cleared as cause of the 77s
  create→update gap on 3 Predicate rows.

## Read, not measured against a live server
- A Weaviate batch re-write with a failed embed OMITS the `vector` kwarg
  (not `None`) → client replaces the whole object → an existing vector is
  stripped, not left alone (weaviate-client 4.21.3 docstrings + wire
  format, `grpc_batch.py:78-91`). Ruled a LOSS by the architect, not "a
  thinner row." Full trace:
  [sessions/2026-09-19-finding-7f-a-rewrite-strips-the-vector-and-the-linker-is-manual-only.md](sessions/2026-09-19-finding-7f-a-rewrite-strips-the-vector-and-the-linker-is-manual-only.md)

## Standing constraint — DISCHARGED
The finding file above was deliberately uncommitted until the PR #1 merge
decision, so that no commit could move the head the merge gate was measured
at. The decision came; it is now committed by name, on its own, after the
rebase. Nothing else rode with it.

## Held / not started (do not build without new authorization)
- The vector-strip writer fix itself — "first writer item after the walks
  draw," explicitly kept out of PR #1. STILL NOT AUTHORIZED (2026-09-23).
- **SECOND WRITER ITEM: `_index_chunk`** (`semantic_assets.py:42-73`), held
  under the same order. Read and confirmed 2026-09-23, a DIFFERENT shape from
  the vector strip, not a restatement of it:

      insert_kwargs = {"properties": properties}
      if vector is not None: insert_kwargs["vector"] = vector
      client.collections.get(name).data.insert(**insert_kwargs)

  Three facts, in the order they compound. (1) It is `data.insert`, not a
  replace or an upsert. (2) **No `uuid=` is passed**, so Weaviate mints a
  random one — unlike the ontology writer, which keys on
  `generate_uuid5(str(uri))` and is therefore idempotent for named classes.
  (3) On embed failure the `except` sets `vector = None` and the row is
  written anyway, by deliberate design ("BM25 queries still work, and a
  follow-up backfill can populate vectors once the gateway is restored").

  Together those make an ORPHAN VECTORLESS CHUNK: the row has no stable
  identity, so the promised backfill cannot find it to repair it, and a
  re-ingest does not overwrite it — it adds a second copy. The docstring's
  own remedy is unreachable by the row it is written about. Callers:
  `semantic_assets.py:333` and `:373`, and `xml_ingestion.py:294` imports it.
  Same "backfill" promise the vector-strip finding counted unredeemed.
- `aitool_linker.py:602-606` `data.replace` on `Predicate` — same stripping
  shape, unbitten (135 rows, 0 vectorless), architect's ruling, held.
- The 16 vectorless BFO/IOF_Core rows + the `IOF_Core` double-manifest
  collision (`prime_databases.py:174` and `:229`) — folded into the vector-
  strip item above, belongs to Lane 1's held manifest work, not this lane's.
- Local test suite hang (python-magic blocks at import on win32, 27/40 test
  files unrunnable here) — recorded as debt. **"GREEN" MEANS CI AT A NAMED
  SHA, AND NOTHING ELSE.** Carried forward at the architect's instruction
  2026-09-23. No local run is evidence here; any claim of green must name the
  run id and the sha it ran on. The `bee5b4c`/`9a5ae75` correction above is
  what happens when that discipline slips by one commit.
- **PR #7 — paths-ignore on `build-and-push`.** Ordered to ride with the PCN
  lane's next CODE PR, not to open as its own. NOT STARTED, and it needs a
  design decision before it can be: **`paths-ignore` cannot be applied to a
  job.** It is only valid under `on.<event>`, where it would skip the WHOLE
  workflow — which contradicts the requirement that tests and telemetry still
  run on docs PRs. The current `on:` block (`build-container.yml:3-21`) has
  push/main + tags, pull_request/main, workflow_dispatch, and no path filter
  at all. The shape that satisfies the order is a job-level `if:` fed by a
  changed-paths filter, with `charts/**` counted as build-triggering.
  Two things to carry into that PR:
    * The chart and the image must stay in lockstep — `values.yaml:24-27`
      pins `command: ["/opt/venv/bin/python"]` and says in so many words
      "Keep in lockstep with the Dockerfile in build-container.yml". That is
      the reason `charts/**` is excluded from the ignore, and it should be
      cited in the diff, not left implicit.
    * This repo has VERIFIED "no `if:` anywhere in the workflow, so nothing
      could have been silently skipped" as a property (recorded above). This
      change spends that property. Whatever lands must make a skipped build
      legible as skipped rather than absent — the `3db8dbb` believed-built
      incident in the same file's comment is the precedent.

## Owned by other lanes
- Lane 74 (fleet repo): reading the gateway/frontend re-post endpoint that
  actually explains the 77s Predicate gap (my own saga-inference guess was
  withdrawn per architect's correction — see finding file §3).
- Lane 1 (orchestrator): the manifest work above; "fleet settled" is the
  other of the two words Chris is waiting on.

## Pre-existing untracked (not touched, not mine)
4 items: `eval_draft.json`, `mfg_corpus_report.json`,
`mfg_corpus_report2.json`, `tests/fixtures/`.

## The MESH prime — measured before it runs, 2026-09-23
Narration written, nothing run. Predictions taken off
`invincible-agent/setup/ontologies/mesh_system.ttl` itself so the run can be
read against a number rather than a hope: 75 named `owl:Class`, 63 of them in
the response-shape closure, so **12 groundable classes reach Weaviate while
75 reach Neo4j** — the two stores MUST move by different amounts. Zero
`owl:Restriction` and zero real blank-node structures, so the blank-node skip
count must read **0**. Exactly one class carries `mesh:universalReferent`:
`mesh:Thing`, which is the flag path PR #1 built and the cluster has never
exercised.

TWO THINGS THE ORDER DOES NOT YET ACCOUNT FOR, both in the runbook:
- `prime_databases.py` has **no per-entry flag** — `--upload-only`,
  `--trigger-ingest` and `--wait-for-ingest` all iterate the full manifest.
  A single-file prime has to be driven at the bucket + the one Dagster
  partition (`mesh__mesh_system.ttl`), not through the script.
- **A red retrievability seal costs the Neo4j leg.** The seal RAISES, after
  the Jena POST and after the Weaviate write, and
  `sync_jena_ontologies_to_neo4j` is `deps=[ingest_ontology_to_jena]` — so a
  red leaves MESH in Jena and Weaviate, absent from Neo4j, with `mesh:Thing`
  still missing. Half-landed, and not visible from "the run failed".
  I also do NOT think that red is certain: the seal probes a row THIS RUN
  wrote, fix D writes by name into the space the index actually reads, and
  what `collections.exists` short-circuits is the CREATE, not the write. The
  standing warning was written about the pre-fix writer. Unsettled; the prime
  is what settles it.

## Open questions for Chris
- Whether/when to authorize the vector-strip writer fix ("the walks draw")
  and `_index_chunk`. Both still NOT authorized as of 2026-09-23.
- Whether a red retrievability seal on the MESH prime should be re-driven at
  all. The module has NO auto-retry on the Jena POST by design (an ambiguous
  ReadTimeout could double the graph), so re-firing the partition is a
  decision, not a recovery.

NEXT TASK: Chris runs the MESH prime from the runbook — embed gateway first,
then the one partition, counts either side, then the seals. When he reports
the numbers and the seal lines, draft the two packets: `ia-74/lane/74` and
`ia-01/lane/01`, both carrying the landed count, which is what unblocks 32's
probe and the backfill. Then record the retrievability-seal outcome here,
because it settles a question the code comment and the standing warning
currently answer differently. Do not start the vector-strip writer fix or
`_index_chunk` without an explicit new order.
