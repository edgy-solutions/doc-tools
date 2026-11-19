# ADR-0207 — CI's interpreter is pinned to 3.12

**Status:** built + measured
**Date:** measured 2026-11-05 (the breakage); pinned in PR #210 · recorded 2026-11-18
**Deciders:** forced by the runner image, not chosen; the pin landed as this lane's PR #210
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `.python-version:1` (the whole pin, one line); the reasoning in
`.github/workflows/build-container.yml:797-821` — a code comment, which was the **only**
written statement of this ruling in the tree before this record; `pyproject.toml:6`
**Related:** [ADR-0206](ADR-0206-the-venv-and-powershell-rule.md),
[ADR-0108](ADR-0108-dependencies-through-uv-never-pip.md),
[ADR-0211](ADR-0211-the-dockerfile-is-generated-in-the-workflow.md) (where the same problem is
solved by hand for the image)

## Context

Nothing in this repo declared a Python version. There was no `.python-version`, and no
`python-version:` input on any `astral-sh/setup-uv` step, so `uv` took the newest interpreter
satisfying `requires-python = ">=3.12"` (`pyproject.toml:6`) — in practice, whatever
`/usr/bin/python3` happened to be on the GitHub runner image.

On **2026-11-05 the runner image moved that to CPython 3.14.4** and the dependency install began
failing on **every branch including `main`, with no commit in this repo to explain it**:

```
Using CPython 3.14.4 interpreter at: /usr/bin/python3
error: Failed to build `cyclonedds==11.0.1`
Could not locate cyclonedds. Try to set CYCLONEDDS_HOME
```

`cyclonedds` 11.0.1 publishes wheels for **cp312 and cp313 only** — countable in `uv.lock` —
so 3.14 fell through to a source build, which needs the CycloneDDS C library, which is not on
the runner. Every `uv sync` in the workflow broke at once (`:802-812`).

This is the ambient-dependency failure the file's neighbouring helm-version comment argues about
in the abstract, arriving for real (`:799-801`): nothing requested a version, so the environment
chose one, and then changed its mind.

## Decision

**The interpreter is a declared dependency of this repo. `.python-version` at the repo root pins
3.12, and `uv` reads it in CI.**

- One declaration, one line: `.python-version` contains `3.12`. It governs the workstation as
  well as the runner, and `uv` downloads a managed 3.12 when the runner ships none.
- **3.12 is not an arbitrary pick.** It is the version the shipped image runs — the container
  build in the same workflow has a `cyclonedds-builder` stage on `python:3.12-slim`
  (`:1247`) that compiles CycloneDDS and carries the wheels forward precisely because PyPI
  cannot be relied on for it — and it is the version the workstation venv runs (3.12.11)
  (`:813-816`).
- The pin lives in `.python-version`, **not** in a `python-version:` input on the six
  `astral-sh/setup-uv` steps. One file cannot disagree with itself; six inputs can.
- **Stated so it is not mistaken for fixed:** the bare `python3 scripts/verify_release_tag.py`
  call sites still take the runner's ambient interpreter (`:818-821`). Measured at the pin there
  are **four** — `:507`, `:524`, `:1671`, `:1717` — plus the same command echoed into the
  release row at `:1748`. They pass on 3.14 today. They are the same defect shape and their own
  item.
- `uv run --no-project` sites, including `verify_image_pin.py`, are covered by the pin.

## Consequences

- A runner image bump can no longer choose this repo's interpreter. The failure it caused was
  red on `main` and on every open PR simultaneously, with nothing to revert.
- **The recognition rule is the durable part:** a red that appears on `main` and every open PR
  at once, with no merge to blame, is an ambient-runner dependency, not code. Check the chosen
  interpreter first — `grep "Using CPython"` in the job log — before reading it as a dependency
  or lock problem.
- The pin must move when `cyclonedds` or the shipped image moves. Three places then agree or
  they do not: `.python-version`, the `python:3.12-slim` stages in the generated Dockerfile, and
  the workstation venv. Nothing compares them automatically.
- `requires-python = ">=3.12"` stays open at the top, so a contributor's local 3.13 still
  resolves. The pin constrains what CI *chooses*, not what the project permits.

## Alternatives considered

- **Cap `requires-python` at `">=3.12,<3.14"`.** Rejected as a hotfix: it states the real
  constraint, but it forces a lock regeneration across 383 packages, which is a far larger diff
  than a one-line declaration under a red `main`.
- **Add `python-version:` to each `setup-uv` step.** Rejected in favour of a single root
  declaration: six copies are six chances to drift, and `.python-version` governs the
  workstation too.
- **Build CycloneDDS in CI the way the image does.** Not recorded as considered for the `tests`
  job. The builder stage exists for the image ([ADR-0211](ADR-0211-the-dockerfile-is-generated-in-the-workflow.md));
  paying its compile cost on every test run was never the question once a 3.12 interpreter was
  available.
