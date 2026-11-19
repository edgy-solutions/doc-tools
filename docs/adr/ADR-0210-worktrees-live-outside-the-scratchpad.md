# ADR-0210 — worktrees live outside the scratchpad

**Status:** accepted
**Date:** 2026-11-07 (ruled, all lanes) · recorded 2026-11-18
**Deciders:** ruled 2026-11-07 for every lane; Lane 1 holds it in the board's conventions
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** agent memory `the-temp-cleaner-deletes-files-inside-scratchpad-worktree-venvs` — an
agent-memory note, which is the **only** written statement of this ruling; **nothing in this
repo's tree states it at the pin**
**Related:** [ADR-0209](ADR-0209-session-files-are-placed-never-committed.md),
[ADR-0206](ADR-0206-the-venv-and-powershell-rule.md) (the venv a deleted file breaks)

## Context

A lane working two branches at once uses `git worktree`, and the obvious place to put a
throwaway checkout is the session scratchpad under `%TEMP%` — it is already the directory for
transient files, and it is already excluded from the repo.

It is the one place a worktree must not go. **A Windows `%TEMP%` cleaner was found on 2026-11-06
to have deleted individual files inside such trees: 159–452 files per tree, all showing as `D`
in `git status`, and files inside the venvs as well.** The deletion is partial and silent — not
a missing directory, which would be obvious, but a tree that still looks like a checkout with
holes punched through it.

The resulting failures do not look like file loss. One tree lost
`en_core_web_sm/__init__.py` from its venv, which presents exactly as the known spaCy-model
failure where `uv sync` removes the model and three golden tests fail — the same symptom, a
different cause, and a diagnosis that goes to the wrong place. Any conclusion drawn from a run
in such a tree is suspect, including a green one.

## Decision

**Lane worktrees live in `C:\Users\cnogr\git\wt\<lane>\` — never under `%TEMP%` (the session
scratchpad), and never under `C:\tmp`.** Ruled 2026-11-07, for every lane.

- New worktrees are created under `git\wt\<lane>\`. Lane tr's trees are under
  `C:\Users\cnogr\git\wt\tr\`.
- An existing one is moved with `git worktree move`, after checking for unpushed commits and a
  dirty tree.
- Cleaner deletions are restored with `git ls-files -d -z | git checkout-index -z --stdin`,
  which touches only the deleted paths and nothing else.
- The venv is re-pointed afterwards with
  `uv sync --frozen --inexact --reinstall-package doc-tools`, because the editable finder holds
  the old absolute path.
- The scratchpad keeps its proper job: transient outputs — a pod reading, a render log — which
  is why the operator scripts in `tools/` still write there (`tools/README.md:56-57`). Losing
  one of those costs nothing.

## Consequences

- Worktrees are no longer excluded from backup and cleanup policy by accident of location, and a
  lane's second checkout survives between sessions.
- `git\wt\` must be managed deliberately: nothing cleans it, so stale trees accumulate and are
  the lane's to prune.
- A tree that *was* under `%TEMP%` cannot be trusted retroactively. The restore command above is
  the first step, not the whole fix — a venv missing files needs the re-sync, and the spaCy model
  may have to be copied from the main checkout's `.venv`.
- **This ruling exists only in agent memory.** It is cross-repo, applies to every lane, and a
  newcomer to this tree has no way to find it except this record. That is the shape of gap this
  directory was created to close, and this is the clearest example of it among the CI rows:
  there is no file, line or comment in doc-tools to cite.

## Alternatives considered

- **Keep worktrees in the scratchpad and re-create them when they break.** Rejected by the
  failure mode: the breakage is silent and partial, so it is not noticed as file loss but
  misdiagnosed as a dependency or test problem. Re-creating a tree you do not know is damaged is
  not a strategy.
- **Exclude the worktree directories from the `%TEMP%` cleaner.** Not recorded as considered.
  It is the obvious alternative and it is a workstation-policy change rather than a lane
  convention, which may be why; nothing records it being weighed.
- **`C:\tmp` as the home instead.** Explicitly excluded by the ruling alongside `%TEMP%`.
