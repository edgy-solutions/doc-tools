# 7f — the gate guard is tightened; the publish token is now the only mitigation left

**Date:** 2026-10-03
**Branches:** `fix/corpus-gate-guard-identity-presence` (PR #66, new), `corpus-gate/nightly` (merged via #65)
**Orders answered:** overnight item 1 (conditional — the condition fired); "PR #65: merge it"; the publish-token half.

---

## 1. #65 is merged, and `main`'s gate authority now tells the truth

Merged `9c57156` at 2026-10-03T12:36:13Z with `--merge`, not `--squash`, so
`corpus-gate/nightly` stays an ancestor of `main` and the next nightly commit
yields a clean delta rather than a permanently diverged branch.

It carried **two** stranded reports, not one: `report-2026-10-02T081312Z.md`
and `report-2026-10-03T081513Z.md`. The second is there because the 2026-10-03
nightly (`2df6c7c`, 03:15 local) committed onto the branch and **reused the
open PR** — direct evidence that the standing-PR workaround functions once a
PR exists, which until now was only inferred from the publisher's source.

`main`'s `docs/corpus-gate/latest.json` now reads `verdict: "fail"`,
`generated_at 2026-10-03T08:15:13Z`. It previously advertised a
`2026-10-02T03:02:23Z` **pass** over a fail for roughly 14 hours.

### An instrument fault worth recording, because it inverted a conclusion

My first re-measurement of the merged file printed the **old** pass and
`image_identity: None`, which read as the merge having silently resolved to
`main`'s side. It had not. I had written the file with a Bash redirect to
`/tmp/lj.json` and then read it with the venv **Windows** python, which
resolves `/tmp` to `C:\tmp` — a different directory, holding an `lj.json` left
there on 2026-10-01 at 22:07. The Windows interpreter read a two-day-old file
and reported it as today's `main`.

`git show origin/main:docs/corpus-gate/latest.json` piped straight into the
interpreter on stdin gives the truth. **Never hand a POSIX `/tmp` path to the
venv python from the Bash tool** — same family as the MSYS kubectl-path trap,
different mechanism: no rewriting happens, the Windows side simply resolves a
drive-relative path to the current drive and succeeds on the wrong file.

---

## 2. Item 1 — the condition fired, and the guard is tightened (PR #66)

The order was conditional: *"07:00Z gate read: `image_identity.checked == true`
with a pod-sourced match → tighten the guard; VOID is a finding."* Yesterday I
declined and stated what would have to happen first. Both now hold. The merged
`2026-10-03T08:15:13Z` report carries:

```
image_identity.checked   true
comparisons              [{source: "pods", result: "match",
                           expected_digest: sha256:b54d9ef2…}]
void_reasons             []
measured_digest          sha256:b54d9ef2…
```

`measured_digest` equals both the comparison's `expected_digest` and the
chart's active `image.digest`. That is the pod-sourced match.

**What is now asserted.** The block is **required** (the
`if identity is None: return` escape hatch is gone); `checked` must be
`is True` rather than merely a bool, so a truthy string cannot read as
reconciled; and — the one the old test structurally could not make — a
comparison **labelled** `match` must prove it, its `expected_digest` equalling
the report's `measured_digest`. Every consumer downstream reads that label, so
a producer bug that labels a mismatch a match is invisible everywhere else.

VOID was already a finding: `test_verdict_is_pass` fails on `verdict: "void"`
and prints the void reasons instead of the scores. That half needed nothing.

**Why this is not PR #40's mistake a third time.** Because the condition was
written into the file as a property of the **report**, never of the chart. An
earlier draft said to tighten once `corpusGate.expectImage` was set, and on
2026-10-02 that was measurably wrong: `expectImage` **was** set and the pinned
image **did** descend from #55, while the committed report still carried
`image_identity: null` from two pins back. The new assertions are satisfied by
the artifact on `main` today, so they block nothing now; and the remedy sits
next to each assertion, so a future red is not a dead end — supply
`expectImage` from a pod `imageID` reading and re-run, or re-run with `--run`
instead of `--from-logs`, never restore the early return.

**Mutation-tested, not asserted.** Block absent → RED. `checked: false` with
no comparisons → RED. `checked: "yes"` → RED. A mislabelled match → RED.
Unmutated artifact → PASS. The artifact was restored from git and verified
clean afterwards; note the round-trip rewrote its **line endings** while
leaving the content byte-identical, and that was restored too. This is the file
a `--from-logs` diagnostic run once silently overwrote, so it gets handled
carefully.

**Second file.** `tests/test_corpus_gate_image_identity.py` said the NOT
RECONCILED rendering mattered *"because CI deliberately does not fail on it"*.
After this change CI does. Corrected rather than left, because a docstring that
lies about CI has already cost this repo a wrong premise twice.

---

## 3. ⚠ `corpus-gate` is red on `main`, and that is the measurement

`test_verdict_is_pass` fails on the published nightly:

```
fire 3: pcn_corpus_run.py exited 1 — parts/crop-seal gate not met (see fire3.log)
```

Fires 1 and 2 scored `898/898`; fire 3 scored `897/898, 1 missing`, and the
per-notice defect block names **`onsemi_Generic_IPCN25300X.pdf 18/19`**. This
is the score moving on identical bytes again — but for the first time the
report pinpoints **which notice and which part count**, which earlier
instances could not. Identity half was clean: *Identity-half unstable across
fires: (none)*. TYC again took the **broad** DISAGREEMENT exemption
(`needs_review=True` in all three fires); that narrowing is still not on
`main`.

Triage of `onsemi_Generic_IPCN25300X.pdf` is separate work and deliberately
not folded into a test-tightening PR. PR #66 will show this red; it arrived
with #65 and is not a regression from #66.

---

## 4. The publish token — what I can do, and what only you can

The order: *"Regenerate it with `pull_requests: write`, set it in the lab
Secret the same way, or the reports stop arriving the day someone merges the
standing PR."*

**That day is today.** #65 is merged, so there is no open standing PR, and
`origin/corpus-gate/nightly` now has **zero delta** against `main` — GitHub
refuses an empty PR, so a successor **cannot be opened by hand** until a
nightly commits something new. The sequence tomorrow at 07:00Z is: the gate
runs, the publisher commits the report to the branch, then `POST /pulls` 403s
because the token has `contents` only — and the report is stranded exactly as
it was on 2026-10-02. **The token scope is the only remaining mitigation, and
it is load-bearing before the 2026-10-04 07:00Z run.**

### Regenerating it is yours — it happens in GitHub's UI

A fine-grained PAT on `edgy-solutions/doc-tools` with **Contents: Read and
write** *and* **Pull requests: Read and write**. The measured evidence that
the current one lacks the second: the first real run's commit landed and PR
creation returned `HTTP 403 "Resource not accessible by personal access
token"`, and the nightly's own publish step 403d again on `POST /pulls` on
2026-10-02.

### Where it goes — the file, not the cluster

It lives under `secrets:` in **`charts/doc-tools/values-sandbox.secret.yaml`**,
which renders into the chart's Opaque Secret rather than inline as a `value:`
in the CronJob and Deployment manifests. The file is **untracked and ignored**
(`.gitignore:71`, `*.secret.yaml`) and has **never been committed** — I
verified all three against git history, since a PAT in history would be a
different and much worse problem.

Replace the value of `PCN_GATE_PUBLISH_TOKEN` in that file — edit it in your
editor, do not paste the token into a chat or a shell command where it lands in
history — then roll the release:

```
helm upgrade doc-tools charts/doc-tools -n sandbox \
  -f charts/doc-tools/values-sandbox.yaml \
  -f charts/doc-tools/values-sandbox.secret.yaml
```

Plain two-file `-f`, **no `--set`**: this release is the one that takes a plain
roll, unlike the invincible-agent release whose plain roll renders
`global.imageTag` as the bare chart version and 404s every image.

**Do not confirm the rotation by reading the Secret back out of the cluster.**
A `kubectl -o jsonpath` typo on a Secret prints the entire object with its
base64 data. The honest confirmation is behavioural: after the next nightly,
check that a PR exists against `main` from `corpus-gate/nightly`. That is the
only check that distinguishes `contents`-only from `contents` +
`pull_requests`, because a reuse success proves nothing about the create path.

**One disclosure to note.** Grepping the chart for the token's env var printed
the **current** value into this session's transcript. It was already on your
disk in a gitignored file and went nowhere else, and you are rotating it
anyway — so the rotation covers it. I have not repeated the value since.

---

## What a reader should do next

1. **Rotate the PAT and roll** (§4). Before 2026-10-04 07:00Z, or tomorrow's
   report strands with no standing PR to catch it and `main` goes stale again.
2. **Review #66** (§2). It is satisfied by today's artifact, so it blocks
   nothing; the red beside it is §3's published FAIL.
3. **Triage `onsemi_Generic_IPCN25300X.pdf`** (§3) — fire 3, `18/19`, one part
   missing, on bytes two other fires scored perfectly.
4. **Open the successor standing PR** the moment the next nightly gives the
   branch a delta, whether or not the token was rotated. Treat a merged or
   closed publish PR as re-arming the stranding trap until a successor exists.
