# ADR-0187 — A hand fire takes the roll lock, not a new lock

**Status:** accepted + built
**Date:** 2026-11-04 (ruled, Chris) · recorded 2026-11-18
**Deciders:** Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `docs/pcn-pre-roll-fire-design.md:97-108` (the ruling and what carries it) and
`:162-165` (two of the note's three open questions closed the same day)
**Related:** [ADR-0186](ADR-0186-the-gate-clock-is-off.md) (a fire is a deliberate act),
[ADR-0185](ADR-0185-pre-roll-checked-false-is-by-design.md),
[ADR-0204](ADR-0204-show-the-values-diff-before-a-roll.md),
[`docs/arch/components/corpus-gate.md`](../arch/components/corpus-gate.md)

## Context

With the clock off ([ADR-0186](ADR-0186-the-gate-clock-is-off.md)), every fire is applied by
hand, and a fire is a long, exclusive use of shared infrastructure: three sequential fires
against an endpoint that serves one model at a time, measured at 2h22m–2h34m for the run.

Two hand fires of **different digests** overlapping is the failure to avoid, and it is not
hypothetical in kind — this repo has already read six fires as three when two fire scripts
wrote the same log paths. Overlapping fires of different digests produce two reports with no
way to tell which image either one measured, which is worse than having no report.

`concurrencyPolicy: Forbid` does not solve it: it is on the **CronJob**, so it governs
scheduled runs, and scheduled runs are what the clock ruling removed.

The pre-roll design note opened three questions. This was one of them.

## Decision

**A hand fire takes the roll lock — the same `sandbox/roll-lock` ConfigMap, held the way a
roll holds it. Not a new lock and not a new guard.**

- A fire therefore never runs unlocked, and two fires of different digests cannot overlap:
  the second waits on the lock rather than on a mechanism that does not exist.
- The declared hold is the **measured duration plus the publish**. The 90-minute convention
  is shorter than one fire, so a fire taken under a 90-minute lock overruns it by about an
  hour every time; declare the real figure and say that it exceeds the default rather than
  overrunning quietly.
- Two candidates in one window is therefore **~5h serial**. That is the price of the ruling,
  and it is the right price: the alternative was two reports and no way to tell which image
  either one measured.
- Two fires of the **same** digest additionally collide on the default job name
  (`pcn-gate-preroll-<short12>`), and the apply reports it.

## Consequences

- **The ruling is carried by the operator and by nothing else.** `sandbox/roll-lock` is a
  ConfigMap asserted by the operator and verified by nothing on this path:
  `scripts/pcn_gate_prefire.py` does not check the lock, and the only script in the tree that
  requires naming a holder is `scripts/neo4j_concept_id_migration.py --under-lock
  LANE/ISO8601` (`:79`, with the lock's own 90-minute staleness rule at `:116`). So **a quiet
  fire is not evidence of a held lock, and this ruling is not a guard.** The `built` half of
  this record's status is the lock mechanism and the convention around it, not an enforcement
  of it on the fire path — the row belongs in `DEBT.md` on that reading.
- A free lock does not mean the previous holder released it deliberately; waiting to see a
  lane *hold* the lock is the only thing that establishes who held it.
- Firing competes with rolls for the same lock, by design. A roll and a fire cannot run at
  once, which is the behaviour wanted: a roll changes the pinned digest a fire is measuring.
- One question the note opened is still **open**: exemptions — a one-fire BLANK is
  exemptable, while an intermittent cut never earns the instability exemption, so a fire that
  produces one is a fire to repeat rather than a fire to argue about.

## Alternatives considered

- **A new, fire-specific lock.** Rejected by the ruling: a second lock means two mechanisms
  that must agree about exclusivity, and the one case that matters — a roll and a fire
  overlapping — is exactly the case a separate lock would not cover.
- **Rely on `concurrencyPolicy: Forbid`.** Rejected because it governs the CronJob's
  scheduled runs only, and hand fires are applied Jobs.
- **Rely on the job-name collision.** Rejected as insufficient: it holds only for two fires
  of the *same* digest, and the dangerous overlap is two *different* digests.
- **Teach `pcn_gate_prefire.py` to require `--under-lock` the way the migration script
  does.** This is the obvious shape of the enforcement the ruling currently lacks, and it is
  **not** recorded as considered on 2026-11-04.
