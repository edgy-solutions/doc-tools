# HANDOFF — doc-tools :: lane/7f

Branch `lane/7f`, PR #1 (OPEN, MERGEABLE). Head at last check: `9a5ae75`
("Remove forge", Chris directly, already on `origin/lane/7f` — not mine, no
divergence, nothing to reconcile).

## Verified this session
- CI green at `bee5b4c` (run 35484058642): all 3 jobs, all steps, read
  individually — no `if:` anywhere in the workflow, so nothing could have
  been silently skipped. `tests`: 407 passed, 13 skipped (all reasoned).
  `build-and-push` log literally printed `push: false`. Posted to PR #1.
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

## Standing constraint — do not commit this file
The finding file above is **deliberately uncommitted** (`??` in git status).
Order stands: commit it only after Chris makes the PR #1 merge decision — a
commit now moves the head and invalidates the sha the merge gate was
measured at. Do not fold it into any other commit either.

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
- Merge decision on PR #1 — CI is green at `bee5b4c`, gate is met, decision
  is explicitly yours.
- Whether/when to authorize the vector-strip writer fix ("the walks draw").

NEXT TASK: Wait for the merge decision on PR #1. Once given, commit the
finding file (as-is, no edits) with a message noting the merge decision,
then stand by for the vector-strip writer fix authorization — do not start
that fix without an explicit new order.
