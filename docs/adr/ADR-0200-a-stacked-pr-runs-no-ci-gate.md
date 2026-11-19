# ADR-0200 — A stacked PR runs no CI gate, and no run record says so

**Status:** measured
**Date:** measured from the tree; carried as a standing convention since the 2026-10-06 fleet
directive · recorded 2026-11-18
**Deciders:** a property of the workflow, not a choice — recorded because its *effect* is
routinely misread
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `.github/workflows/build-container.yml:47-49`; `CLAUDE.md` §Conventions
**Related:** [ADR-0201](ADR-0201-the-build-skip-allowlist-is-not-widened.md),
[ADR-0202](ADR-0202-expect-image-is-read-off-the-pods.md),
[ADR-0208](ADR-0208-only-the-owning-lane-commits.md)

## Context

This repo's lanes stack pull requests: a branch is based on the previous branch, not on `main`,
so work continues without waiting for a merge. That is the working convention and it is
deliberate.

Measured at the pin, `.github/workflows/build-container.yml` is this repository's **only**
workflow, and its `pull_request` trigger is scoped:

```yaml
pull_request:
  branches:
    - main
```

The `branches:` filter on a `pull_request` trigger matches the **base** branch. A PR whose base
is another feature branch therefore matches nothing, and **GitHub dispatches no workflow at
all**.

The trap is in how that looks. It is not a failure. It is not a skip. **There is no run record
of any kind** — the PR's checks area is empty, which reads identically to "checks have not
started yet" and, to a reviewer scanning for red, identically to "nothing is wrong". A stacked
PR can therefore be merged in the belief that tests passed on it, when nothing ever ran.

`main` has no required checks, so nothing downstream catches it either.

## Decision

**A stacked PR has no CI verdict, and the absence of a run is not evidence of a pass.**

- A PR based on another branch is **expected** to show no run record. Looking for a skipped job
  is looking for something that does not exist.
- To obtain a verdict, **rebase onto `main`** — or merge the stack bottom-up, which puts each
  branch's content onto a PR whose base is `main` in turn.
- A PR body for a stacked PR **says so explicitly**, says that no workflow dispatches, and says
  to merge bottom-up. The statement is part of the PR, not knowledge the reviewer is assumed to
  have.
- The local suite, run per [ADR-0206](ADR-0206-the-venv-and-powershell-rule.md), is the only
  evidence a stacked PR carries. Its result goes in the PR body with its counts.

## Consequences

- The stacking convention keeps its benefit — no lane blocks on a merge — at the cost that CI
  moves to merge time, in stack order.
- **A green local suite is load-bearing.** It is the only check a stacked PR has, which is why
  the suite is run in full and its counts are quoted rather than summarised as "tests pass".
- A reviewer must know the base branch before reading the checks area. A PR body that names the
  stack is what makes that possible without opening the branch graph.
- Three distinct ways a PR in this repo ends up with no gate are now recorded: this one, the
  build-skip allowlist ([ADR-0201](ADR-0201-the-build-skip-allowlist-is-not-widened.md)), and a
  pin bump making the verdict check skip itself. They are separate mechanisms with the same
  appearance.

## Alternatives considered

- **Widen the `pull_request` trigger to all base branches.** Not taken here, and it is not a
  free change: every stacked PR would build a container image, and the build is the expensive
  job (tens of minutes). The cheap correctness jobs are the ones worth having on a stack, and
  they are not separable under the current single-workflow layout without restructuring it.
- **Require checks on `main`.** Would not help: the problem is a PR that dispatches nothing, and
  a required check that never runs blocks the merge rather than verifying it. It is also a
  repository setting, not a tree change, so it is not this lane's to make.
- **Stop stacking and wait for merges.** Rejected by the standing fleet directive — *"Do not
  wait for merges. Stack each PR on your previous branch and keep going."* The directive accepts
  this cost knowingly; the record is here so the cost is known rather than discovered.
