# ADR-0185 — `pre_roll`'s `checked: False` is by design

**Status:** accepted
**Date:** 2026-10-27 (architect ruling; narrowed for `pre_roll` 2026-10-29) · recorded
2026-11-18
**Deciders:** the architect
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `tests/test_corpus_gate_guard.py:25` (the reversal) and `:57` (the accepted
cost), with the `pre_roll` narrowing at `:607-674` and the assertion it produced at `:647` —
a test docstring, which was the **only** written statement of this ruling before this
record; restated in `docs/pcn-pre-roll-fire-design.md:152-154`
**Related:** [ADR-0186](ADR-0186-the-gate-clock-is-off.md) (the same ruling removed the
clock), [ADR-0187](ADR-0187-a-hand-fire-takes-the-roll-lock.md),
[ADR-0202](ADR-0202-expect-image-is-read-off-the-pods.md),
[ADR-0203](ADR-0203-the-expect-image-patch-is-part-of-the-roll.md),
[ADR-0189](ADR-0189-the-published-report-is-the-authority.md)

## Context

`corpus-gate` is the single required check on `main`, and one of its arms asserts that the
committed report **names the digest the chart pins**. A report also carries an
`image_identity` block saying whether it was reconciled against something external, and
since 2026-10-03 the guard asserted `checked is True` unconditionally — the state a nightly
report reaches by comparing its measured digest to a pod `imageID`.

A **pre-roll** report cannot reach that state and is not supposed to. No pod runs the
candidate, no chart pins it, and the prefire script blanks the expectation on purpose: the
Job runs the candidate image as its own container and measures in process. So the
unconditional assertion made the required check **unpassable for the very strategy pre-roll
exists to enable**, and its stated remedy — supply an expectation and re-run — was
unreachable before the roll.

The ruling that created that strategy also **reversed a paragraph that stood in this test's
own docstring**. The paragraph said that a report for digest *D* can only exist after *D* has
been built **and rolled**, so requiring one would make every new pin permanently unmergeable.
The ruling replaced **"rolled" with "built"**: the gate Job runs the candidate as its own
container, so no pod has to run the candidate for a report about it to exist, and identity is
the container's own digest. The reversal runs in the direction of **more** being required of
a pin-bump PR, not less — the PR must now carry a report for the digest it lands.

## Decision

**A `pre_roll` report's `image_identity.checked: False` is by design, not a gap, and the
guard's remaining cost is accepted until `pre_roll` changes.**

- `checked: False` is accepted **in `pre_roll` mode and in no other mode** (`:647`). The
  relaxation is bounded three ways: it requires the producer's own `self_declared` flag to
  agree, it still demands the substitute instrument the producer names in
  `check_image_identity`, and the `checked == bool(comparisons)` assertion holds either way.
- An expectation supplied in `pre_roll` is still compared and still **voids**, so a pre-roll
  report may legitimately arrive with `checked: True`.
- In every other mode a missing or unreconciled block is a **finding**, and the remedy is to
  make the gate reconcile — never to restore the early return or relax the assertion.
- **Wall-clock staleness went with the same ruling.** `CORPUS_GATE_MAX_AGE_DAYS` is
  **deleted, not loosened**: with no nightly ([ADR-0186](ADR-0186-the-gate-clock-is-off.md))
  age measures only how long ago someone chose to fire. A report is stale when its
  `measured_image` is not the digest the chart pins, and only then.
- The red window between a roll and its report is **accepted, and is not to be routed
  round** — in particular not with an `--admin` merge, which would land a pin whose image has
  never been measured and leave no trace that the gate was bypassed. Wait for the fire, or
  fire pre-roll.

## Consequences

- A pin-bump PR carries its own report, and the report and the pin **cannot be split across
  PRs**: the arm accepts `checked: False` only when the measured digest equals the chart's
  pin.
- The guard is strict in the one place it can be strict cheaply, and silent about everything
  a pre-roll report genuinely cannot know. That asymmetry is deliberate and is the reason the
  record says *which* mode.
- **Status is `accepted`, not `built`, and the gap is a measurement, not a script.** The
  docstring's own standard is that the window closes when a pre-roll report lands in a
  pin-bump PR, not when the code merges.
- The docstring paragraph at `:46-56` states that `pre_roll` "has never been FIRED at a
  cluster". That statement is **stale**: agent memory
  `pcn-corpus-denominator-is-898-not-896` records a pre-roll Job firing a candidate on
  2026-11-02, under the roll lock, whose report was cherry-picked into the pin-bump PR and
  flipped the guard from 3 failed / 3 passed to 6 passed. The ruling is unaffected; the
  docstring's status sentence is what has drifted, and it belongs in `DEBT.md`.
- A reader who sees `checked: False` on a published report must check `identity_mode` before
  concluding anything. In `rolled` mode the same value means the run was given no expectation
  to compare against, which **is** a finding.

## Alternatives considered

- **Assert `checked is True` in every mode.** This is what the code did, and it made the
  required check unpassable for a pre-roll pin bump. Rejected on that measurement.
- **Skip the identity arm for `pre_roll` reports.** Rejected by the shape of the narrowing:
  the arm is kept and bounded instead, because an arm that reports nothing once it is skipped
  leaves no trace that it was skipped — the same objection the docstring raises against an
  `--admin` merge.
- **Keep an age arm as well as the digest arm.** Rejected with the clock: the age arm reddened
  on a clock that no longer ticks and would have blocked every `charts/` PR three days after
  the last manual fire, the pin-bump PR among them.
