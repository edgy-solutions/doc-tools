# ADR-0202 — `expectImage` is read back off the settled pods

**Status:** measured
**Date:** measured 2026-10-17 on helm rev 48 · recorded 2026-11-18
**Deciders:** a property of the rollout, not a choice — recorded as a guardrail because the
rollout message invites exactly the wrong read
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:63-68` (§Safety Guardrails); the refusal that enforces it,
`tools/patch_expect_ca3e7d83.py:83-87`, with the procedure in that file's docstring (`:1-47`)
**Related:** [ADR-0203](ADR-0203-the-expect-image-patch-is-part-of-the-roll.md),
[ADR-0204](ADR-0204-show-the-values-diff-before-a-roll.md),
[ADR-0186](ADR-0186-the-gate-clock-is-off.md),
[the corpus gate component record](../arch/components/corpus-gate.md)

## Context

`corpusGate.expectImage` is the gate's image-identity expectation: the digest a fire must have
run under for its report to count. A roll moves `image.digest`, and the obvious way to move
`expectImage` with it is to copy the digest just typed into the values file. That makes the two
lines agree by construction and proves nothing.

The check `expectImage` exists to perform is **independent**: that the image the cluster is
actually running is the image the chart declares. Copying one line into the other removes the
only reading that could fail, and leaves a record claiming a check that was never performed.

Reading the pods instead has its own trap, and it is measured. **`kubectl rollout status` reports
"successfully rolled out" while the previous pod is still `Running`.** Measured 2026-10-17 on
helm rev 48: for **~84 s** after that message both the new and the previous pod were `Running`
(the old one pending termination), so a read of "the pods"
`.status.containerStatuses[*].imageID` returned **two distinct digests** (`AGENTS.md:63`).

A read taken on the strength of the rollout message can therefore capture **the digest being
replaced** — arming the gate against the wrong image — and, worse, it makes a recorded "ONE
distinct value" false.

## Decision

**`corpusGate.expectImage` is read off the running pods, never copied from `image.digest`; and
the read waits for the pod count to settle before it is taken.**

- The value comes from `.status.containerStatuses[*].imageID` on the pods. The two lines being
  equal afterwards is **the result being asserted, not the source of the value**
  (`tools/patch_expect_ca3e7d83.py:9-11`).
- Wait for the count first. `AGENTS.md:64-67` gives the loop:

  ```bash
  until [ "$(kubectl get pods -n sandbox -l app.kubernetes.io/name=doc-tools \
    --no-headers | wc -l)" = "1" ]; do sleep 10; done
  ```

- Then **assert** the distinct-digest count is 1 rather than assuming it. The pod-count form is
  valid only for a single-replica Deployment; with more replicas, count **distinct digests** and
  require exactly one (`AGENTS.md:68`).
- The write refuses rather than guesses. `tools/patch_expect_ca3e7d83.py` stops, values file
  untouched, when there is no pod reading on disk (`:74-78`), when more than one distinct
  `imageID` is present (`:82-87`), when the `imageID` is not digest-pinned (`:89-90`), when the
  pods disagree with `image.digest` (`:96-103`), or when its anchor line does not match exactly
  once (`:106-109`).
- The reading is taken **from PowerShell**: MSYS rewrites slash-bearing `kubectl` arguments, and
  `kubectl` on this workstation has no `current-context`, so it needs a credential-free overlay
  naming `edge` (`tools/patch_expect_ca3e7d83.py:13-28`, `tools/README.md:47-57`).

## Consequences

- A roll has a wait in it that cannot be skipped, and `rollout status` returning success is not
  the end of it. The wait is ~84 s on the one measurement available; it is not a constant and
  the loop is what decides, not the number.
- The refusal costs the operator the window: if the script is run too early it exits rather than
  picking a digest, and the pods must be read again. That is deliberate — the alternative is a
  gate armed against the previous image.
- "One distinct value" is a claim that must come from a reading, and the script prints what it
  observed so a report can quote the reading rather than the intention.
- Nothing automatic keeps `image.digest` and `expectImage` in step: no test and no CI job
  compares them, because the Job that would is the one being checked
  (`tools/README.md:35-38`). The discipline is the only mechanism.

## Alternatives considered

- **Copy `image.digest` into `expectImage` as part of the pin bump.** Rejected: it makes the
  equality tautological and deletes the check. This is stated at the top of both
  `patch_expect_*` scripts because it is the thing a hurried roll will do.
- **Trust `kubectl rollout status` and read immediately.** Disproved by the 2026-10-17
  measurement: two distinct digests for ~84 s after the success message.
- **`kubectl get -o jsonpath` instead of `-o custom-columns` for the reading.** Rejected,
  measured: a jsonpath needing a newline escape cannot be written in a PowerShell single-quoted
  string — the backtick is literal there, so the escape reaches `kubectl` as U+0060 and it
  errors `unrecognized character in action` (`tools/patch_expect_ca3e7d83.py:22-25`).
- **Have CI compare the two lines.** Not recorded as considered, and the file says why it would
  not help: the Job that would do the comparing is the one under test.
