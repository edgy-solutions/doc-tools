# 7f — the pin for #217/#218 is `e73d8b08`, and the values diff for the roll

**Date:** 2026-11-09 (the build and the merges are stamped 2026-11-10Z)
**Lane:** 7f (doc-tools)
**Branch:** `7f/pin-58ef369-e73d8b08`, based on `main`
**Order:** *"pin-bump PR for #217/#218 once merged, with the values diff rendered
for tomorrow's roll."*

## The pin

| | |
|---|---|
| commit | `58ef369c9ecb9934dbb0888596b60e834a1d08e5` (`main`, merge of #218) |
| index | `sha256:e73d8b08eada030e3a135eb2625e33bd3c9a31e9fed968f8c683603d242d8c8c` |
| amd64 child | `sha256:33325050951b657b7ccec9c7d864a015fad33891841b87acc22a84dccbc84e51` |
| arm64 child | `sha256:7194b45673f0c7c565e0e1b6428247c715a0971b869086f238ba2a72da8ab303` |
| run | 42750495296, `build-and-push` success |
| previous pin | `sha256:ca3e7d830c75…` (rev 59) |

**Verified independently of the build log**, per the chart's own rule. `crane
digest …doc-tools:58ef369c9ecb…` resolves to this index **from the tag**, and
`tools/read_index.py` read each child's **config blob** rather than the index's
platform claim: both children carry revision `58ef369c9ecb…`, plus two
attestation manifests that satisfy no platform. `scripts/verify_image_pin.py`
(the same check CI's `verify-image-pin` job runs) returns `OK`, HTTP 200, both
platforms — so that job will be green.

### The near miss, recorded because it would have pinned a phantom

The first line matching `/Digest:/` in that job's log is **not ours**: `Set up
QEMU` prints `Digest: sha256:400a4873…` for the binfmt image it pulls. That
digest is `MANIFEST_UNKNOWN` in this repository — pinning it would have rendered
perfectly and died at the kubelet, which is the `d7434d6` failure shape from a
new direction. The pin is `containerimage.digest`, which the workflow also
prints in its own *"Publish the image digest as the pin to copy"* step. **Grep
for that, never for `/Digest:/`.** Written into the chart comment too.

## What the image carries

#217 re-took the 20 deck goldens at contract v5 from the `ca3e7d83` pod; #218 is
the behaviour change. Of 120,464 inserted lines, almost all are fixtures and
goldens — the **shipped** diff against `97ef4b5` is five files:

    doc_tools/assets/semantic_assets.py
    doc_tools/concept_alignment_job.py
    doc_tools/passes/concepts.py
    doc_tools/plugins/training.py
    scripts/normalise_concepts.py

In words: `ALIAS_OF` is pruned on re-ingest (it used to accumulate a union of
every run), concept alignment skips untaught Concepts, there is a propose mode,
and the version guards read `DOC_TOOLS_VERSION` as `doc-tools@<sha>`. **Nothing
touches the PCN/header or parts path**, so the corpus score is not expected to
move — if it does, that is a finding, not a side effect.

## The values diff for the roll

Rendered with `tools/preroll_diff.py` (the sanctioned path — not `helm get
values`/`get manifest` wholesale), live release **rev 59** against this branch's
tree. Secrets are shown as `len=N sha256:XXXXXXXX` on both sides before any
output; none appears below.

**A control was rendered first, before the pin edit:** `main`'s tree against rev
59 differed by **exactly one object**, the `test-connection` Pod — a
`helm.sh/hook` that `helm template` renders and `helm get manifest` excludes.
So the chart had **no drift** from what is deployed, and everything below is the
pin and nothing else.

**44 changed lines. The whole inventory:**

| what moves | where | count |
|---|---|---|
| `app.kubernetes.io/version` label `sha256-ca3e7d830c75` → `sha256-e73d8b08eada` | ServiceAccount, Secret, Service, Deployment (+ pod template), gate CronJob | 6 |
| container `image:` | Deployment container, gate CronJob container | 2 |
| `DOC_TOOLS_IMAGE` env value | the same two | 2 |
| the `test-connection` hook Pod | excluded from `get manifest` by design, not drift | +22 |

The two substantive hunks:

```diff
@@ -117,5 +117,5 @@
-          image: "ghcr.io/edgy-solutions/doc-tools@sha256:ca3e7d830c75294f18406444d79e5b52e7751ef7352e3ab7ba6bde3457d0fc4c"
+          image: "ghcr.io/edgy-solutions/doc-tools@sha256:e73d8b08eada030e3a135eb2625e33bd3c9a31e9fed968f8c683603d242d8c8c"
@@ -291,5 +291,5 @@
-              image: "ghcr.io/edgy-solutions/doc-tools@sha256:ca3e7d830c75294f18406444d79e5b52e7751ef7352e3ab7ba6bde3457d0fc4c"
+              image: "ghcr.io/edgy-solutions/doc-tools@sha256:e73d8b08eada030e3a135eb2625e33bd3c9a31e9fed968f8c683603d242d8c8c"
```

**Note what the second one is:** the **gate CronJob's** image. The roll moves the
corpus gate onto this image as well as the deployment, so the next fire — by
hand or on a schedule — runs `e73d8b08`.

## Two things the roll itself needs, neither of them in this PR

**1. `expectImage` is read-then-write, and the second apply is part of the
roll.** `corpusGate.expectImage` still names `ca3e7d83` **on purpose**. The
sequence is: bump `image.digest` → apply → read the pods'
`.status.containerStatuses[*].imageID` → write `expectImage` from **that**
reading → apply again. Ruled 2026-11-07 that the second write is part of the
roll, not a follow-up, so the roll is not finished until it lands. The value is
never copied from `image.digest`; the two being equal is the assertion, not the
source.

**2. The required `corpus-gate` context is RED on this PR, by design.**
Measured, not assumed: `corpus-gate` is the **only** required status check on
`main` (branch protection `contexts: ["corpus-gate"]`, `strict: false`, no
required reviews). `docs/corpus-gate/latest.json` measured `ca3e7d83`; this
chart now declares `e73d8b08`, so
`test_the_report_measures_the_pin_this_chart_declares` **fails** — and it fails
rather than skipping precisely so a pin cannot land carrying no measurement of
the image it pins. Its own message names the two ways out:

- **a pre-roll fire of the candidate** — `scripts/pcn_gate_prefire.py --image
  <candidate>` — whose report is committed on this PR. This needs
  `sandbox/roll-lock` and ~3h declared (measured 2h22–2h42), so it is a
  scheduling decision, not a lane one; or
- **the stated interim**: merge, roll, fire, then a follow-up PR carrying the
  report.

`corpus-gate-verdict` will **skip** itself here for the same digest mismatch, as
it does on every pin bump. A green verdict job on a pin bump is a skip, never
evidence.

## Expected CI on this PR

| check | expected |
|---|---|
| `verify-image-pin` | **pass** — run locally, `OK`, HTTP 200, both platforms |
| `tests`, `telemetry-contract` | pass |
| `build-and-push` | runs (a `sessions/` path is not `^docs/`, so `code=true`) |
| `corpus-gate` | **FAIL, by design** — the required context; see above |
| `corpus-gate-verdict` | skip (digest mismatch) |
