# ADR-0203 — the `expectImage` patch is part of the roll

**Status:** accepted + built
**Date:** 2026-11-07 (ruled) · recorded 2026-11-18
**Deciders:** ruled 2026-11-07; recorded in the roll script and in the values file, naming no
person
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `tools/patch_expect_ca3e7d83.py:1-7` — a module docstring, which with the values-file
comments was the **only** written statement of this ruling before this record;
`charts/doc-tools/values-sandbox.yaml:1385-1387` and `:1425-1429`; restated in
`tools/README.md:29-33`
**Related:** [ADR-0202](ADR-0202-expect-image-is-read-off-the-pods.md) (where the value comes
from), [ADR-0204](ADR-0204-show-the-values-diff-before-a-roll.md),
[the corpus gate component record](../arch/components/corpus-gate.md)

## Context

A pin bump in this repo is **two** digests, not one: `image.digest`, which the Deployment runs,
and `corpusGate.expectImage`, which the gate requires a fire to have run under. They cannot be
written in the same commit, because the second one's value does not exist until the first one is
running — it is read off the pods ([ADR-0202](ADR-0202-expect-image-is-read-off-the-pods.md)).

So the roll is one roll in **two applies**: bump `image.digest`, apply, read the pods, write
`expectImage` from that reading, apply again (`tools/README.md:29-33`).

The failure this record prevents is stopping after the first apply. Between the two applies the
cluster is **red on image identity by construction** — the gate would compare a run under the
new digest against an expectation naming the old one. Treating the second write as a follow-up,
a next-session task, or someone else's ticket leaves that window open indefinitely, and the
window is silent: no job fails, because the Job that would is the one being disarmed.

It has already gone wrong in a worse shape than a two-digest skew. At the `ca3e7d83` roll the
`expectImage` line named a **third** image: `03599b10afcd` had been pinned and never rolled,
while the live release (rev 57) ran `01f016e430eb`. The gate's expectation matched neither the
chart nor the cluster, and a nightly would have been **voided on image identity** rather than
reporting on the corpus (`tools/patch_expect_ca3e7d83.py:119-123`, in the comment it writes).

## Decision

**The post-roll `expectImage` write is part of the roll, not a follow-up. The roll is not
finished until the second apply lands.** Ruled 2026-11-07.

- The sequence is fixed: bump `image.digest` → apply → wait for the pods to settle → read them
  → write `expectImage` from that reading → **apply again**.
- A commit that bumps `image.digest` and leaves `expectImage` alone is a correct, deliberate
  half-step, and it says so in the values file: *"`corpusGate.expectImage` IS DELIBERATELY NOT
  MOVED IN THIS COMMIT"* (`charts/doc-tools/values-sandbox.yaml:1425-1429`). It is not a
  forgotten line, and the next actor's job is to finish it, not to tidy it.
- The window between the applies is accepted as red, with its safety stated rather than assumed:
  it was harmless at `ca3e7d83` **only** because the nightly CronJob is `suspend: true`, which
  the pre-roll diff proved — `suspend` appeared zero times in the diff, so live and rendered
  agreed (`tools/patch_expect_ca3e7d83.py:41-46`, restated at `:125-128`). Do not lean on that
  if the CronJob is ever
  unsuspended.
- The write is **built**: `tools/patch_expect_ca3e7d83.py` performs it, refuses on every
  mismatch, and writes the values file as bytes with LF so a CRLF rewrite cannot break a pinned
  sha elsewhere in the tree (`:137-139`). `tools/patch_expect_2bf85719.py` is the same write for
  the earlier roll, kept as a second worked example so what is procedure and what was per-roll
  can be told apart (`tools/README.md:17`).

## Consequences

- A roll is finished by a definition that includes a second `helm upgrade`. A report that says
  "rolled" without it is describing a half-roll, and the gate is armed against the wrong image
  until the rest arrives.
- The scripts are per-roll artifacts by design: each carries its own anchors and refuses unless
  they match exactly once, which also makes a double-application impossible
  (`tools/patch_expect_ca3e7d83.py:106-109`).
- The stale digest stays visible in comments after the write — the script counts the remaining
  occurrences and says they are comments only (`:141-145`) — so a later grep for it finds
  history, not a live pin.
- **If you bump `image.digest` and stop, you have armed the identity failure yourself.** That
  sentence is in the comment the script writes into the values file, where the next reader of
  that line will find it (`:130-132`).

## Alternatives considered

- **Write both digests in one commit, copying `image.digest` into `expectImage`.** Rejected by
  [ADR-0202](ADR-0202-expect-image-is-read-off-the-pods.md): it would make the identity check
  tautological, which is the whole reason the second apply exists.
- **Leave `expectImage` as a follow-up task.** Rejected by this ruling. The window is red and
  invisible, and the only thing that closes it is the person doing the roll.
- **Have the chart derive `expectImage` from the running pods at render time.** Not recorded as
  considered. It is the obvious shape of an automated fix; nothing in the tree at the pin weighs
  it, and `tools/README.md:37-38` notes why a CI comparison would not substitute — the Job that
  would compare is the one being checked.
