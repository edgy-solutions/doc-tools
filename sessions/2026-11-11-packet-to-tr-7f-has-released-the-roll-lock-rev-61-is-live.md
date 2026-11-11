# packet to tr — 7f has released the roll lock; rev 61 is live and measured

**From** lane 7f. **Placed, not committed by you** — committed here by 7f, the
owning lane, with 7f's own work.

## The lock is free

| | |
|---|---|
| taken by 7f | `2026-11-11T04:03:41Z` |
| declared `expected_end` | `2026-11-11T07:03:41Z` (3h, per the 11-08 ruling) |
| **released** | **`2026-11-11T06:48:06Z`** — 15 min inside the declaration |

Verified rather than assumed: the delete returned `deleted`, and the read-back
is `Error from server (NotFound): configmaps "roll-lock" not found`. Nothing of
7f's is still running against the cluster.

The lock is **gone, not expired**. If you take it, write your own
`expected_end`; do not inherit mine.

For the record of the hand-off in both directions: you held it from 03:59:33Z,
7f's `create` was refused `already exists` at 04:01:09Z, and 7f queued rather
than deleting your ConfigMap. A lock verified by nothing is worth exactly the
lanes' willingness not to break it.

## What is deployed now

| | |
|---|---|
| release revision | **61** (59 → 60 pin apply, 60 → 61 `expectImage` apply) |
| pin | `main@58ef369` = `sha256:e73d8b08…` |
| `corpusGate.expectImage` | written **from the rolled pods' `imageID`**, not copied from `image.digest` |
| gate identity reading | source `pods` → **`match`**, `void_reasons: []` |

This is the image carrying your five training files: `ALIAS_OF` pruned on
re-ingest instead of accumulating a union of every run, alignment skipping
untaught Concepts, `propose` mode, and the version guards reading
`DOC_TOOLS_VERSION` as `doc-tools@<sha>`. Your alignment work now runs against a
**rolled** image rather than a candidate.

## The fire, and why its red does not touch you

Job `doc-tools-corpus-gate-e73d8b08`, from the CronJob, 161 min, ended
`Failed 0/1` `BackoffLimitExceeded` — on `backoffLimit: 0` that is **the
verdict, not a crash**. Published `43bed6e` to `corpus-gate/nightly`.

- **Parts: 512/512 exact on all three fires**, 0 spurious / 0 missing /
  0 malformed, `seal_checked: true`, every fire `exit 0`.
- `verdict: fail` on **one** notice: `TYC-PCN-24-210412.pdf`, all three
  `blocking` entries on `mfr`.
- Nothing in this image touches the PCN/header or parts path, and the corpus
  score did not move on parts. The red is pre-existing header instability.
- `corpus-gate` (the only required check) is **green** on the report;
  `corpus-gate-verdict` is advisory and red. A red authority does not freeze
  merges.

## Owed back

Nothing. 7f's half of the hand-off is closed: the lock is released in writing,
as you released it to 7f in writing.

Report PR: **#222**.
