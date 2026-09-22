# HANDOFF — doc-tools :: lane/7f

Branch `lane/7f`, PR #1 **MERGED** 2026-09-22 03:19Z as merge commit
`38f3d39` (merge commit, not squash — the twelve lane commits stay ancestors
of `main`, so this branch rebases with only its own work left to replay).
Rebased onto `main` after the merge; `2905153` replayed as `2449354`.

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
  draw," explicitly kept out of PR #1.
- `aitool_linker.py:602-606` `data.replace` on `Predicate` — same stripping
  shape, unbitten (135 rows, 0 vectorless), architect's ruling, held.
- The 16 vectorless BFO/IOF_Core rows + the `IOF_Core` double-manifest
  collision (`prime_databases.py:174` and `:229`) — folded into the vector-
  strip item above, belongs to Lane 1's held manifest work, not this lane's.
- Local test suite hang (python-magic blocks at import on win32, 27/40 test
  files unrunnable here) — recorded as debt. See memory entry below; gate on
  CI, not local runs.

## Owned by other lanes
- Lane 74 (fleet repo): reading the gateway/frontend re-post endpoint that
  actually explains the 77s Predicate gap (my own saga-inference guess was
  withdrawn per architect's correction — see finding file §3).
- Lane 1 (orchestrator): the manifest work above; "fleet settled" is the
  other of the two words Chris is waiting on.

## Pre-existing untracked (not touched, not mine)
4 items: `eval_draft.json`, `mfg_corpus_report.json`,
`mfg_corpus_report2.json`, `tests/fixtures/`.

## Open questions for Chris
- Whether/when to authorize the vector-strip writer fix ("the walks draw").
  Still NOT authorized as of 2026-09-21.
- The sandbox re-pin: `values-sandbox.yaml:34` needs the digest from the
  `main` build of `38f3d39` before the merged code runs anywhere. Chris
  rolls; this lane narrates only.

NEXT TASK: Report the `main`-event build of `38f3d39` — whether it pushed,
its tag and digest, read from the run's job log rather than the workflow
source. Then hand Chris the re-pin line and roll command (do not run
either). After Chris rolls and confirms the running image, narrate the
`mesh_system.ttl` prime — embed gateway checked FIRST, additive only, Chris
runs every command. Do not start the vector-strip writer fix without an
explicit new order.
