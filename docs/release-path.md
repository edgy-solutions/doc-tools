# The release path, as it is practised

**Measured from the tree at `origin/main@54de79c`, 2026-11-16.** Nothing here is
aspirational: every step below is one this lane has run, and every trap named is
one that has already cost a measurement. It was unwritten until now — it lived in
PR descriptions, chart comments and agent memory, which is why it is written as an
ordered path rather than a set of tips.

**What "a release" means here.** The deployed thing is **a digest**, pinned in
`charts/doc-tools/values-sandbox.yaml` as `image.digest`. A version tag
(`v0.2.0`) is **an assertion about which bytes that version names** — not a
build, and not what the cluster follows. The two are rolled separately and
checked separately.

---

## 1. Land the change

1. **Base the PR on `main`.** A PR stacked on another branch **dispatches no CI at
   all** — not a failure, not a skip, no run record:
   `.github/workflows/build-container.yml` is this repo's only workflow and its
   `pull_request` trigger is scoped `branches: [main]`. Rebase onto `main` before
   expecting a verdict.
2. **A push to a non-`main` branch fires nothing.** The only triggers are a push
   to `main`, a `v*` tag, a published release, a PR against `main`, and
   `workflow_dispatch`.
3. **A green `build-and-push` on a PR pushes no image.** A PR run proves the image
   builds; it does not publish one.
4. **The build-skip allowlist diffs the WHOLE PR, not the last commit.** The
   `changes` job decides `code=true/false` over the PR range, so one touched
   source file anywhere in the branch means a full build.
5. **`main` has no branch protection and no required checks.** A merge is final
   and unreviewed; CI is advice unless somebody reads it. Merge with a **merge
   commit**, not a squash — a squash strands the later commits of a stacked
   branch, and ancestry cannot see that it happened.

## 2. Get the digest

The image is built by `build-and-push` on the `main` push. Take the digest from
**that run**.

- The job summary prints it, and the comment above the `digest:` key in
  `charts/doc-tools/values.yaml` says to copy it from there.
- **Prefer `digest` over `tag`.** A tag is guessable from `git log`; a digest is
  not. A tag pin additionally needs `image.unverifiedTagAck`, because the chart
  guard (`charts/doc-tools/templates/_helpers.tpl`, `doc-tools.image`) refuses one
  without it.
- That guard is a **shape** check only — `sha256:` plus 64 hex, 71 characters.
  Helm reaches no registry when it renders a template, so it cannot prove the
  bytes were ever pushed. `scripts/verify_image_pin.py` is that proof, and it is
  the check that would have caught the 2026-09-25 `d7434d6` pin: no such image was
  ever pushed, because that commit failed its own build.
- **A pin bump is TWO digests** (§4), and the index you pin must carry a child for
  the architecture sandbox schedules onto (arm64) — see the measured notes in
  `values-sandbox.yaml`.

## 3. Measure the candidate before rolling it, when the gate is in scope

The corpus gate cannot run in CI: its fires need the header LLM and the vision
endpoint on RFC1918 addresses, and the corpus in in-cluster MinIO. So CI checks a
**committed report** (`tests/test_corpus_gate_guard.py` against
`docs/corpus-gate/latest.json`), and a pod produces it.

- The CronJob is **`suspend: true`** by the ruling of 2026-10-27
  (`charts/doc-tools/values.yaml`); its `schedule` is inert and kept only because
  the API server rejects a CronJob without one. Every fire in practice is a hand
  fire.
- A hand fire **takes the roll lock** (ruled 2026-11-04), and the lock is a
  ConfigMap. Declare **3 hours** for a full fire; measured 2h22–2h42.
- The ordinary fire path copies the CronJob pod template, whose image is *the
  current pin* — so a candidate cannot be measured until after it is rolled, which
  leaves a red window (accepted as an interim cost 2026-10-27).
  `scripts/pcn_gate_prefire.py` closes it by firing against a **built but not yet
  pinned** image, so a pin-bump PR can carry a report for the digest it lands.
- **Never run `scripts/pcn_gate_prefire.py --dry-run` into a transcript or into a
  file.** It prints the pod environment inline, live credential values included.
- `corpus-gate-verdict` is `if: needs.changes.outputs.charts == 'true'`, so **a
  pin bump that touches only the chart makes the verdict check skip itself** unless
  a report is already there to read. A **pre-roll** report in the same PR defeats
  the skip, and a `pre_roll` report carrying `checked: false` is **by design**.

## 4. The roll: one roll, two applies

[`../tools/README.md`](../tools/README.md) carries the detail. The shape:

1. Bump `image.digest` in `charts/doc-tools/values-sandbox.yaml`.
2. **Show the values diff before the roll.** `tools/preroll_diff.py` is the
   sanctioned path: it renders the chart against the live manifest and redacts
   **both sides** before any output. Do **not** run `helm get values` or `helm get
   manifest` wholesale, and never print a secret value — a secret appears as
   `len=N sha256:XXXXXXXX`, first 8 hex.
3. `helm upgrade` (apply 1).
4. **Read the pods** and take `corpusGate.expectImage` off
   `.status.containerStatuses[*].imageID` — `imageID`, never `image`, and never
   copied from `image.digest`. The two being equal is the result being asserted,
   not the source of the value. Nothing automatic keeps them in step: the job that
   would compare them is the one being checked.
5. Write that value into the values file and `helm upgrade` again (apply 2).
   **Ruled 2026-11-07: the second write is part of the roll**, so the roll is not
   finished until apply 2 lands. `tools/patch_expect_*.py` are the two worked
   examples, and they refuse rather than guess.

**`kubectl rollout status` lies.** Measured 2026-10-17 on helm rev 48: for ~84s
after *"successfully rolled out"*, both the new and the previous pod were
`Running`, so a read of "the pods" returned **two distinct digests**. Wait for the
pod count to settle, then assert the distinct digest count is exactly 1 (the loop
is in `AGENTS.md` under Safety Guardrails). A reading taken on the strength of the
rollout message can arm the gate against the image being replaced — and makes a
recorded "one distinct value" false, which claims a check that was never
performed.

**Two more measured traps.** A roll **reverts a rotation** that was applied by
hand and never written into the values file. And `kubectl`/`helm` have **no
`current-context`** on this workstation: a bare invocation targets
`localhost:8080` and reports *connection refused*, which reads exactly like a down
cluster. Prepend a credential-free overlay holding nothing but
`current-context: edge` to `KUBECONFIG` rather than copying or mutating the user
kubeconfig, and run these from **PowerShell** — MSYS rewrites slash-bearing
`kubectl` arguments.

## 5. Publish the report

`scripts/pcn_gate_publish.py` commits the report from inside the cluster, because
the network allows one direction only (out of it). It writes to a branch with a
standing pull request and **never to `main`**: `main` is unprotected, so a machine
writing there would be the one unreviewed write in the pipeline. The report lands
under `docs/corpus-gate/`, and `latest.json` is the file CI reads.

- A **red** authority report does **not** freeze merges. It blocks a chart diff
  through `corpus-gate-verdict`, which is a narrower thing.
- A **stale** `latest.json` blocks a comparator PR: the guard runs when the diff
  touches `charts/` **or** the gate scripts.

## 6. Cut the version tag afterwards

A tag ref **no longer rebuilds** (changed 2026-10-23). `resolve-release-image`
finds the digest CI already built for that commit, and `tag-release-image` adds
the version tag to it with `packages: write` — so a retag needs that scope. A
rebuild on a tag can never be a no-op, because **the build is not reproducible**:
same commit, different bytes.

The incident that forced this, measured 2026-10-23: publishing `v0.2.0` on
`133714c` fired the tag trigger, rebuilt that same source for 36 minutes, and
pushed the result as **both** `v0.2.0` and the commit-sha tag. Two things broke at
once. `v0.2.0` named bytes that had never been through a gate — in that same run
`corpus-gate` and `corpus-gate-verdict` both failed while `build-and-push`
succeeded, because the gate is not in its `needs`. And the commit-sha tag was
**moved off** the gated index the sandbox pins, which was the only evidence
linking that digest to its commit, since the build stamped no
`org.opencontainers.image.revision`. Nothing deployed changed — a digest is
immutable and the pin is a digest — but the digest became unreachable by any tag,
and the mapping had to be recovered out of the original build run log.

So: cut the release **after** the digest is rolled and measured, then check the
assertion with `scripts/verify_release_tag.py`. To repair a tag that was already
moved, dispatch the workflow with `version` **and** `digest`: the supplied digest
is asserted to exist in the registry before any tag is pointed at it, and a
mismatch with the commit-sha tag is warned about rather than silently accepted.

## 7. What is deliberately not here

- **Rotations are not part of a roll.** They are the operator's, and a roll
  reverts one that was never written down (§4).
- **No gate exemption.** An intermittently cut fire can never earn the instability
  exemption; a one-fire blank can.
- **Only the owning lane commits in this repo.** A placed packet is committed by
  the lane that owns the tree, along with its own work.
