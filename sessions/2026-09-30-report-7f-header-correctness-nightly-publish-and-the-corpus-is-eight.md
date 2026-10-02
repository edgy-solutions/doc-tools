# Report to 7f — header correctness is scored, the nightly report commits itself, the corpus is eight documents

**Date:** 2026-09-30
**Lane:** 7f (doc-tools)
**Branch:** `pcn/corpus-release-gate` → **PR #40** (open, base `main`)
**Commits:** `7193a85` (scoring + enumeration), `2659c71` (publishing)
**Order answered:** teach `pcn_score.py` the headers block (TYC scored, `10-Jun-2024` a declared distractor); the corpus harness nightly against the pinned image with the report committed; write the 8-document enumeration down where the gate reads it.

All three are implemented, tested and pushed. One of the three cannot be
*switched on* by a merge, and that is reported rather than assumed — see
**What merging does not do**.

---

## 1. The finding, before the mechanism

The committed authority report says the three pinned f32 fires agreed on the
TYC headers. They did. They agreed on `pub_date = 2024-06-10`, which is the
portal's print stamp — the page says the notice was published on the **7th**.
`pub_date` does not appear in that report's disagreeing-fields list at all.

So the existing check was working as designed and reporting a wrong value as
a clean one. **Agreement over a damaged source is indistinguishable from
correctness to a cross-fire check**, and this corpus has three separate
instances of the pattern already (the TYC `ti`-dropping text layer, the two
fires agreeing on the LTB date, and now this). That is what the first task
closes.

## 2. Headers are scored, in seven statuses

`scripts/pcn_score.py` scores `written_header` against ground truth with the
statuses deliberately **not** collapsed into pass/fail:

`exact` · `distractor` · `wrong` · `misformatted` · `unreadable` · `absent` · `pending`

Three of those carry the judgment:

- **`distractor`** — ground truth names the value *and why it is on the page*.
  `10-Jun-2024` is scored as the print stamp, not as a near miss. A scorer that
  could not say "this specific wrong value is the one the page invites" would
  either pass it or report it as noise.
- **`unreadable`** — `6/10/24` is refused rather than guessed. The scorer does
  not pick a date order.
- **`pending`** — ground truth `value: null` is scored in **neither**
  direction. TYC's `doc_level_ltb_date` is pending because the text layer says
  06-JUN and the vision witness says 08-JUN; a field nobody has established
  must not be able to pass *or* fail. This is the mechanism that keeps the
  contested date out of both columns instead of silently crediting whichever
  witness the scorer happened to prefer.

`observed` is reported beside `clean`. **NOT OBSERVED is not zero.** The three
real f32 fires predate `written_header`, so a gate run over them reports
header correctness `NOT SCORED` — not green. Without that distinction the
whole feature would have read as passing on day one, over runs that never
carried the data.

Blocking follows the gate's existing declaration rule (all-three-fires
`needs_review` exempts; `strict_verdict` exempts nothing). It is **not** in
`pcn_corpus_run.main()`'s exit code, which the gate consumes in two places
(`run_fires` and `_reconstruct_exit`) and which would otherwise mean two
different things depending on whether you ran `--run` or `--from-logs`.

## 3. Nightly: the report now leaves the pod

The CronJob already ran nightly on a digest-pinned image. The missing piece
was the last step — the report stayed *in the pod*, and moving it to
`docs/corpus-gate/latest.json` was a human copying files out of a container.
That is the step that silently does not happen, and the CI guard reading an
unrefreshed report goes **green on a stale measurement while looking like
coverage**.

The gate cannot move into CI: RFC1918 endpoints, in-cluster MinIO. Traffic
goes one way, out. So `scripts/pcn_gate_publish.py` publishes from the run
that produced the report, over the GitHub git-data API (stdlib `urllib`): one
tree, one commit for both files, one standing PR reused each night.

Decisions worth your review, all of them about the wrong path:

- **Never `main`.** `main` here has no required checks, so a push to it is a
  final unreviewed write. The report lands on `corpus-gate/nightly` and a human
  merges.
- **Not `GIT_TOKEN`.** That is a *clone* credential for the DataHub assets.
  Pushing is more privilege; reusing the read token's name would hide the
  escalation at the exact place a reader checks for it. `PCN_GATE_PUBLISH_TOKEN`
  is separate, empty by default, and arrives through the `secretRef` so
  `helm get manifest` cannot print it.
- **Unconfigured exits 0 and says so.** The gate must not fail because
  publishing was never provisioned — and must not look like it published.
- **A missing `latest.json` is an error, not an empty success.** That file is
  the only thing CI reads.
- **A red report is published.** It is the report most worth having in the repo.
- **An unchanged report makes no commit.** A job that commits nightly whether
  or not anything moved trains its readers to ignore it.
- The CronJob runs both steps under `/bin/sh` and exits with the **gate's**
  code, so a publish success cannot paint a red corpus green; a publish failure
  under a green gate still fails the Job.

## 4. The enumeration is an asserted input

`_corpus` in `scripts/pcn_ground_truth.json`: **eight documents is the corpus
until production traffic adds to it**, with the four denominators (9 scored
filenames / 8 distinct documents / 898 harness parts / 496 distinct parts) and
each document's md5 and bytes.

`check_ground_truth` verifies the filename set against `TARGETS` and
**recomputes** 496 from the notices block rather than restating it — a
denominator cannot drift from the data it describes. The gate copies the block
into its report; the CI guard **fails, not skips**, on a report that does not
state its corpus.

## 5. What was verified

| check | result |
| --- | --- |
| default suite | `913 passed, 15 skipped, 4 deselected, 2 xfailed` |
| publisher tests | 29 passed, no network (the one HTTP function is faked) |
| chart render | helm 3.14.3; `args` parses to exactly one shell script |
| exit-code logic | checked against `sh` for all four gate/publish combinations |
| scorer on real data | TYC 0/2, both failures recognised as declared distractors, `doc_level_ltb_date` pending |
| gate over the real f32 fires | EXIT=1, the **same two** pre-existing blockers, no new ones, header correctness `NOT SCORED` (run into a scratch `--out-dir`, authority report untouched) |

**`pytest -m corpus_gate` is 2 failed, 2 passed, and both failures are
honest:** the pre-existing red TYC verdict, and the new check reporting that
the *currently committed* report predates the `_corpus` block. The second
clears on the next gate run. The first is the declaration decision this branch
does not make.

Also worth knowing: those 4 guard tests are **deselected from a default
`pytest` run** (`addopts = -m "not corpus_gate"`). CI runs them in a dedicated
job with `-m corpus_gate`. A local green suite says nothing about them.

## 6. What merging does not do

PR #40 does not start nightly publishing. Two prerequisites, neither mine:

1. **A push-scoped GitHub token** (contents + pull-requests write, this repo
   only) as `PCN_GATE_PUBLISH_TOKEN`, plus `corpusGate.publish.repo`. I cannot
   provision this.
2. **`corpusGate.enabled=true` in a release** — ~70 minutes of nightly
   sequential work on a vision endpoint that serves one model at a time, on a
   shared cluster. That is an outward-facing claim on shared capacity and
   should be a deliberate decision, not a merge side effect. Chart default
   stays `false`.

## 7. Still outstanding, still flag-only

**Two credential rotations, now six days old. Neither is something I can
perform.**

- **The ghcr PAT** for user `cnogradi`. A malformed `-o jsonpath` made kubectl
  dump the whole `ghcr-pull-secret` object — base64 `.dockerconfigjson`
  included — into an agent transcript. Not decoded, not used, but it must be
  treated as disclosed. A jsonpath **typo** is not a safe failure on a Secret;
  read them with an exact path or `-o name`.
- **`LANGFUSE_SECRET_KEY`** (an `sk-lf-…` value) which a peer's helm rev 22 put
  into the sandbox release values, where any `helm get values` prints it in
  clear. My rev-24 roll preserved it deliberately (`--reuse-values`) rather
  than dropping a peer's config; dropping it is the peer's call and is **not** a
  substitute for rotation.

## 8. Not mine, untouched

Merging #37 (already merged by someone else); adding `corpus-gate` to `main`'s
required checks; the re-ingest; #27's closure; the dotted-revision defect (#39
is open against it).

PR #40 carries #38's commit `606669d` — #38 should merge first; git dedupes.
