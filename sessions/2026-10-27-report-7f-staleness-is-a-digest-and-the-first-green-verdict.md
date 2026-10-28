# 7f — staleness is a digest, the first GREEN verdict, and onsemi closed without a cause

**Date:** 2026-10-27
**Lane:** `doc-tools/lane/7f`
**Branch:** `7f/gate-triggers-suspend-nightly` @ `f0613c8`
**PR:** [#179](https://github.com/edgy-solutions/doc-tools/pull/179) — all checks pass; `build-and-push` pending at time of writing
**Order:** architect packet of 2026-10-27 (third), items 1–4, relayed by Chris

Supersedes the same-day report filed while the arm was red
(`…-the-arm-is-red-on-a-pin-that-already-landed.md`, removed — it was never
committed and its content is carried here).

## The headline

**The gate produced its first PASS verdict**, and #179's required check went
from fail to pass by *measuring* rather than by skipping. Three commits:

| commit | what |
|---|---|
| `94d36b7` | staleness is a digest comparison; `CORPUS_GATE_MAX_AGE_DAYS` deleted |
| `2762e3e` | the red window recorded in the guard docstring, with the `--admin` harm named |
| `f0613c8` | today's report cherry-picked in, three files |

## Item 1 — the report is here, and the publisher needed no fix

Cherry-picked from `origin/corpus-gate/nightly` with `git show <ref>:<path>`,
proved lossless two ways: `git hash-object` per file against the published
blobs, and `git diff --stat origin/corpus-gate/nightly HEAD -- docs/corpus-gate/`
**empty** before #178 was closed.

- `docs/corpus-gate/latest.json` — verdict `pass`, `measured_image …c056fa70`
- `docs/corpus-gate/report-2026-10-27T092941Z.md`
- `docs/corpus-gate/report-2026-10-26T211901Z.md` — **yesterday's, taken
  deliberately.** The publisher's carry-forward was the only thing preserving
  it; with the nightly suspended nothing will carry it again, so closing #178
  without it would have stranded it permanently.

**#178 closed**, with a comment recording the empty diff.

**The publisher fix the packet ordered was already in the tree.** Verified
rather than assumed: `scripts/pcn_gate_publish.py` resolves
`PCN_GATE_PUBLISH_BASE` (default `main`) fresh every run and force-parents
every commit on that tip; the carry-forward reads back every unmerged
`report-*.md` off the branch via the git data API, `latest.json` being the
deliberate exception. Live state at the time of reading: nightly tip
`74c95a8`, parent `b8a3dd0` = main's tip, 1 commit, 2 files, #178
`mergeable: MERGEABLE`.

So no code was written for this item. What was wrong was a **memory**, which
read the PR's non-green status as the old conflict defect. `UNSTABLE` is not
`DIRTY`; the memory is corrected.

## Item 2 — the red window is recorded where a bypass would be reached for

`2762e3e`, in the docstring of the module the arm lives in, headed
**"TRANSITIONAL, AND IT BLOCKS — THE RED WINDOW IS ACCEPTED, DO NOT ROUTE
ROUND IT"**: the window's size (~2.5 h, three sequential fires), the ruling
that accepts it until `pre_roll` exists, and the specific harm —

> A `--admin` merge here would land a pin whose image has never been measured,
> which is the exact condition this arm was added to make visible; it would
> also leave no trace that the gate was bypassed, because the arm reports
> nothing once it is skipped.

## Item 3 — onsemi is closed, and the stated cause is disproved

Fire 3 is clean, so it is **closed** and reopens only on recurrence. No old
logs were read. But *"fixed by #165"* does not survive contact with the tree,
and this needs to be said rather than filed:

- `docs/corpus-gate/report-2026-10-26T211901Z.md:11` — yesterday's **FAIL**
  measured `…c056fa70`, that notice at **10/19, 9 missing**.
- Today's **PASS** measured the **same digest**.
- `git merge-base --is-ancestor 1dbf2bd 38b7937` → true. **#165 is already
  inside v0.2.2 = `38b7937` = `c056fa70`.** The image that failed contained
  the fix.

No code change separates the red from the green. What closed is the ticket,
on a reasonable call about where to spend — not a demonstrated cause. The
behaviour underneath is unchanged: an intermittent miss on byte-identical
source at one image, now observed clean 3/3 fires and dirty in 2/2 earlier
runs **on the same code**. Calling it fixed by #165 would send the reopen
hunting a regression in header-cancel code that was never involved. Both the
disposition and the disproof are in memory together.

Guarded against a false clean before accepting it: `header_totals` has
`wrong`/`misformatted`/`absent`/`hallucinated`/`distractor`/`unreadable` all
empty, with 14 exact + 1 alias + 1 correctly-absent = 16 — so the clean is
not the known `needs_review` 10/10 exemption doing the work. The header half
is still unproven for the same reason: that exemption is live.

## Measurements

| what | value |
|---|---|
| job | `doc-tools-corpus-gate-29884740` — `Complete 1/1` at 149 min, exit 0 |
| verdict | **pass** — the first one |
| `measured_image` | `…c056fa70` = the chart's exact pin, read from the pod's `imageID` |
| fire 1 / 2 / 3 | exit 0, 3074.9 / 2952.5 / 2930.8 s, **522/522** exact each, 0 spurious / 0 missing / 0 malformed |
| headers | 14 exact + 1 alias + 1 correctly-absent = 16, clean in all three fires |
| source bytes | identical across fires, verified for all 10 notices |
| publisher commit | `b79dfde`, parent `b8a3dd0` |
| #179 required `corpus-gate` | **pass** — `6 passed, 1 deselected` |
| #179 advisory `corpus-gate-verdict` | **pass** — `1 passed, 6 deselected`, run with `-rs` and reporting no skip |
| local suite | **90 passed, 1 skipped** (from 89/2) |

The arm earned its keep before it went green. On the previous head it read
*"it measured sha256:086766d7…, but this chart pins sha256:c056fa70…"* —
**#177 moved the pin yesterday and no report for `c056fa70` had ever
landed.** The 3-day age limit was blind to that, because the stale report was
one day old. The first thing the replacement did was surface a hole the old
rule could not see.

The remaining local skip is `REQUIRE_HELM unset`, local-only, which CI sets.
The skip that stopped skipping is `test_verdict_is_pass` — the first time the
verdict arm asserts instead of waving itself through, which is also how the
v0.2.2 pin bump went green carrying no measurement of the image it landed.

## Still open

- **The `pre_roll` trigger** — item 1 of the queue, now unblocked (the onsemi
  item that gated it is closed). Explicit image override so the Job runs the
  candidate as its own container; a named `pre_roll` identity mode with
  identity = the container's own digest; the guard sentence moved from
  "D must be rolled" to "D must be built" (the docstring already states the
  destination, so code and doc will not diverge).
- **The header exemption per field**, so #176's arm measures:
  `needs_review` is 10/10 and exempts every header disagreement.
- **#167's contract edit + the Neo4j migration dry run.**
- **The batch fixture chain.**
- **`failed:vision_timeout`** — waits on the SDK's closed `REASON_CODES`
  (`ca, v0.9.12`) and Lane 1 accepting in the same pin. Interim as ruled:
  recorded per notice in the gate report, mapped to `unexpected_error` on the
  wire with the real code in `detail`, counted per notice in the gate report
  and per run in the ingest ledger, **not** in crop-seal totals. Lane 1 is
  packeted.
- The required job's warning text still falsely claims a measured fail
  *"still blocks the next pin through the corpus-gate-verdict job"*.
- `sessions/**` is still not in the build-skip allowlist; it must ride a PR
  that already touches the workflow.
