# ADR-0201 — the build-skip allowlist is deliberately not widened

**Status:** accepted
**Date:** 2026-11-03 (ruled) · recorded 2026-11-18
**Deciders:** ruled 2026-11-03 and recorded in the workflow itself; the comment names no person
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `.github/workflows/build-container.yml:1040-1053` — a code comment, which was the
**only** written statement of this ruling before this record; restated at the output it governs,
`.github/workflows/build-container.yml:175-177`
**Related:** [ADR-0200](ADR-0200-a-stacked-pr-runs-no-ci-gate.md),
[ADR-0189](ADR-0189-the-published-report-is-the-authority.md),
[the corpus gate component record](../arch/components/corpus-gate.md)

## Context

The one workflow in this repo decides by hand which jobs a diff needs. GitHub Actions has no
job-level `paths-ignore`, so the `changes` job runs a plain `git diff --name-only` and publishes
three outputs that other jobs' `if:` conditions read (`:104-112`, `:159-211`). Two of those
outputs are allowlists, and the pressure to widen each of them is constant:

- **`code`** — the build-skip allowlist proper. Its ignore list is `^docs/` and `^sessions/`
  **and nothing else** (`:114`), it fails open on anything it cannot positively prove
  (`:140-150`), and `charts/` must never be added to it, because a values file is how a commit
  reaches a running pod *without* an image (`:115-124`).
- **`gate_scripts`** — true when the diff touches the corpus gate's own script surface: the
  three `scripts/pcn_*.py` comparators and `scripts/pcn_ground_truth.json` (`:177-179`). It
  exists because of a measured hole: PR #206 rewrote the gate's own equality key and **both**
  gate jobs concluded SKIPPED, since `charts/**` was the only thing that dispatched them — the
  one PR the gate never ran on, and the skip then repeated on `main`'s own push build of
  `5c113ce` (`:181-186`).

Having paid for `gate_scripts`, the obvious tidy-up is to let every gate job read it. That is
the move this record refuses.

## Decision

**`gate_scripts` is read by `corpus-gate` only. `corpus-gate-verdict` keeps its chart-only
scope, ruled 2026-11-03, and the asymmetry is not a bug to fix.**

- `corpus-gate`'s `if:` is `charts == 'true' || gate_scripts == 'true'` — two legs, because a
  typo in a new output name reads empty, the `if:` reads false, the job skips, and a skip
  satisfies a required context. As a second leg, a typo can only degrade the job to its
  pre-2026-11-03 scope; it cannot make the gate inert (`:197-205`).
- `corpus-gate-verdict`'s `if:` stays `needs.changes.outputs.charts == 'true'` (`:1053-1054`).
- The reason is what the two jobs assert. `corpus-gate` asserts the committed report is current,
  schema-valid and identity-reconciled. `corpus-gate-verdict` asserts the **outcome** — and the
  outcome is a literal the image computed during its fire, so on a PR that changes a comparator
  the verdict in `docs/corpus-gate/latest.json` is still the *old* comparator's answer, which no
  edit to those scripts can move. **Measured on #206's branch: the fix applied, the test still
  failing, because the verdict is read and not recomputed** (`:1044-1052`).
- The legitimate way to move a verdict is a fresh fire from an image carrying the change, which
  arrives as a pin bump, which is `charts/**`.
- The ignore list for `code` is treated as an allowlist of paths that provably **cannot** reach
  the image. A path read at runtime — `prompts/`, `registry/`, `baml_src/` — fails that test
  however documentary it looks (`:135-138`).

## Consequences

- A PR that changes a comparator gets the currency and identity checks and **no** verdict. That
  is the intended reading, not a gap: dispatching the verdict job there would report a red the
  PR cannot clear by any means available to it — a permanent false block, not a finding.
- The comparator's *behaviour* is covered instead by the `tests` job, which dispatches on
  `code`; the three dispatch-only paths buy a re-assertion of the committed report before a
  comparator change lands (`:189-195`).
- The two conditions look inconsistent to anyone reading the YAML alone, and will keep inviting
  a "fix". This record and the comment are the only things standing between that reading and a
  wedged repository.
- `corpus-gate-verdict` is **advisory** until it is added to `main`'s required contexts, and
  making it required would re-create the original wedge by another name — a red verdict blocking
  the extraction fix that turns it green (`:1031-1038`). Any such change needs an explicit
  override the job reads, not an `if:`.

## Alternatives considered

- **Widen `corpus-gate-verdict` to `gate_scripts` too.** Rejected by the ruling, on the #206
  measurement above: the job would assert a stored literal against a PR that cannot change it.
- **Add `charts/` to the build-skip ignore list.** Rejected outright in the same file: it is the
  single worst version of the optimization, because `charts/` is precisely what deploys
  (`:115-124`).
- **Use `dorny/paths-filter` or another action instead of the hand-rolled diff.** Rejected: the
  point is a single auditable `git diff` a reader of this file can verify by eye, not a
  dependency on someone else's path-matching semantics (`:108-112`).
- **Make the verdict job recompute the verdict rather than read it.** Not recorded as
  considered. It is the obvious shape of a fix that would make widening safe, and nothing in the
  tree at the pin says it was weighed or declined.

## A note on this record's own title

The census row this record rescues is phrased "the build-skip allowlist is deliberately not
widened to `gate_scripts`", and the line it cites (`:1040`) is the **dispatch scope of
`corpus-gate-verdict`**, not the `code` ignore list. Both are allowlists published by the same
`changes` job and both are deliberately narrow, so the title stands; the ruling of 2026-11-03 is
the second one.
