# ADR-0186 — The gate clock is off, and a fire is a deliberate act

**Status:** accepted + measured
**Date:** 2026-10-27 (architect ruling, relayed by Chris) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `charts/doc-tools/values.yaml:289-296` (the ruling, the measurement, and
`suspend: true`), with `schedule` kept inert at `:288`; the consequence for the required
check is in `tests/test_corpus_gate_guard.py:35-45`
**Related:** [ADR-0185](ADR-0185-pre-roll-checked-false-is-by-design.md) (same ruling, the
staleness half), [ADR-0187](ADR-0187-a-hand-fire-takes-the-roll-lock.md),
[ADR-0189](ADR-0189-the-published-report-is-the-authority.md),
[`docs/arch/components/corpus-gate.md`](../arch/components/corpus-gate.md)

## Context

The corpus gate is a CronJob, and for a time it ran nightly. What it measures did not change
nightly: the same **ten notices**, against whichever image the chart pins, whether or not a
pin moved and whether or not anyone read the result.

What a run costs is measured and recorded in the values file beside the key:

- one run is **three sequential fires of ~49 min**;
- **~99% of that wall clock is waiting on model calls** — **47 vision calls per fire,
  2412 s of a 3060 s fire**, to an endpoint that serves one model at a time, plus **10 header
  calls, 323 s**;
- the fires are sequential because the endpoint serves one model at a time, so there is no
  parallel fire to be had.

A scheduled run therefore spent hours of a shared single-model endpoint re-measuring an
unchanged image, and produced a fresh artefact whose only new content was its timestamp —
while a **diagnostic run overwrites the authority report**, so an unread nightly is not even
harmless.

It also had a second-order cost the repo paid in CI: the required check once reddened on
report **age** alone, so suspending the nightly would have blocked every `charts/` PR three
days later ([ADR-0185](ADR-0185-pre-roll-checked-false-is-by-design.md)).

## Decision

**The clock is off. The gate runs only when something changed and someone will read the
result.**

- `corpusGate.suspend: true` in `charts/doc-tools/values.yaml` is set **by ruling, not by
  neglect**, and it is what decides whether the gate fires.
- `corpusGate.schedule` is kept and is **inert**, documented as such: a CronJob without
  `schedule` is rejected by the API server, so the key must carry a value that never fires.
- `corpusGate.enabled` is `false` by default, so the gate is opt-in per environment as well.
- A fire is **deliberate**: a pin moved, or a change landed whose effect on extraction
  quality someone intends to read. It takes the roll lock
  ([ADR-0187](ADR-0187-a-hand-fire-takes-the-roll-lock.md)).
- Staleness is therefore measured against the **pinned digest**, never against the clock. The
  age arm is deleted, not loosened.

## Consequences

- There is **no fresh measurement waiting** when a question arrives. Answering a question
  about extraction quality that the published report does not already answer costs a fire —
  three sequential fires and a block of a shared endpoint — which is why the published report
  is read first ([ADR-0189](ADR-0189-the-published-report-is-the-authority.md)).
- The newest report can be weeks old and still be the authority, because what makes it the
  authority is the digest it measured, not its date. Report age does not bound code age, a
  pin bump apart.
- The declared duration of a fire must be the measured one. The 90-minute lock convention is
  **shorter than one run**, so a fire declared at 90 minutes overruns it every time —
  `docs/pcn-pre-roll-fire-design.md:92-108` measures a run at **2h22m–2h34m** and says to
  declare the measured duration plus the publish.
- A fire nobody will read is the thing this ruling forbids, and that includes a fire taken to
  refresh a date.
- The values block's own opening sentence still describes a run as "roughly 70 minutes end to
  end", which the measured numbers immediately beneath it contradict (3 × ~49 min ≈ 2h27m).
  The ruling is unaffected; the stale sentence belongs in `DEBT.md`.

## Alternatives considered

- **Keep the nightly and accept the cost.** Rejected by the ruling on the measurement above:
  it re-measures an unchanged image on a shared single-model endpoint, and a diagnostic run
  overwrites the authority report, so an unread nightly can destroy the artefact a merge
  decision rests on.
- **Run nightly but only on a pin change.** Not recorded as considered. The obvious shape
  would be a scheduled job that exits when the pinned digest already has a report — which is
  what a deliberate fire does by hand, without a schedule that must be reasoned about.
- **Keep a wall-clock staleness arm so an old report eventually reds.** Rejected with the
  same ruling, and measured: the arm reddened on a clock that no longer ticks and would have
  blocked the pin-bump PR that fixes a stale report.
