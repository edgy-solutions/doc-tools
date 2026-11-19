# ADR-0211 — the Dockerfile is generated in the workflow

**Status:** built
**Date:** not recorded; in force since the container build was written · recorded 2026-11-18
**Deciders:** not recorded; stated as a standing guardrail in `AGENTS.md` §Safety Guardrails
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:62` — a one-line guardrail, which was the **only** written statement of
this ruling; the implementation is `.github/workflows/build-container.yml:1150-1383`
**Related:** [ADR-0207](ADR-0207-cis-interpreter-is-pinned.md) (the same 3.12 constraint, pinned
for CI), [ADR-0108](ADR-0108-dependencies-through-uv-never-pip.md),
[ADR-0201](ADR-0201-the-build-skip-allowlist-is-not-widened.md) (which reasons about this build
context)

## Context

There is no `Dockerfile` in this repository. Measured at the pin, `git ls-files` matches **zero**
files named `Dockerfile*` and **zero** `.dockerignore`. Both are written at build time, by a
`run:` step in the only workflow, from two quoted heredocs:

- `.dockerignore` — `.github/workflows/build-container.yml:1153-1237`
- `Dockerfile` — `:1240-1383`

Nothing points the build at them: `docker/build-push-action@v5` takes `context: .` and no
`file:` input (`:1453-1459`), so it picks up the `./Dockerfile` the previous step just wrote.

Someone looking for the image definition will therefore not find it by looking for the file, and
a change made to a local `Dockerfile` — created to try something — is invisible to the build and
untracked by git. That is the hazard this record exists to name.

## Decision

**The image is defined by the generator step in `.github/workflows/build-container.yml`. System
packages belong in the `apt-get install` block inside that step** (`AGENTS.md:62`).

- A new system-level dependency is added to the final image's `apt-get install`
  (`:1300-1311` — the list that carries tesseract, poppler, `libmagic1`, LibreOffice, Inkscape
  and the MS ODBC driver), not to a layer invented elsewhere.
- Build-time-only packages go in the builder stage's own `apt-get`
  (`:1249` — git, cmake, build-essential, bison).
- Both stages are `python:3.12-slim` (`:1247`, `:1282`). The builder exists to compile
  CycloneDDS 11.0.1 from source and carry the wheels forward, because the PyPI wheel for this
  interpreter cannot be relied on — the same constraint that forced the CI interpreter pin
  ([ADR-0207](ADR-0207-cis-interpreter-is-pinned.md)).
- Python dependencies are **not** resolved in the image: the step before exports them from the
  lock with `uv export --locked` (`:1148`), so the image installs exactly what the suite ran
  against.
- The runtime contract is set here and nowhere else: `COPY . /app` (`:1363`),
  `ENV PYTHONPATH="/app"` (`:1367`), and the webserver `CMD` (`:1383`).

## Consequences

- One file holds the build, its path filtering, its gates and its image definition, and it is
  **1751 lines** at the pin. Reading it is the only way to answer what is in the image.
- The image definition cannot be built or tested locally with `docker build` without first
  extracting it from the YAML by hand. There is a partial substitute: the *Diagnose context
  size* step prints what `.dockerignore` would exclude (`:1447-1448`), which is a build-log
  reading, not a local one.
- A heredoc inside YAML has two levels of quoting to get right, and the Dockerfile's own `$`
  expansions survive only because the heredoc is `<< 'EOF'` — quoted. Unquoting it would let the
  shell eat `${CYCLONEDDS_REF}` and friends silently.
- **A stale statement in the same file, which belongs in [DEBT.md](DEBT.md):** the build-skip
  reasoning at `:131-133` describes the build context as *"`.` with an EMPTY `.dockerignore`"*.
  The generated `.dockerignore` is not empty — it is ~80 lines and excludes `tests`,
  `Dockerfile*`, caches and data extensions (`:1231-1236`). The *conclusion* it supports
  survives: `docs/` and `sessions/` appear nowhere in that ignore list, so both trees do still
  land in the image as files, exactly as the comment says. Only the word "EMPTY" is false.

## Alternatives considered

- **Commit a `Dockerfile` at the repo root and have the build use it.** Not recorded as
  considered, and it is the obvious alternative: it would make the image definition greppable,
  diffable and locally buildable. Nothing in the tree at the pin weighs it.
- **Keep the apt packages somewhere other than the generator step.** Explicitly closed by
  `AGENTS.md:62`: the `apt-get install` block in this step is named as the place they belong.
- **Resolve dependencies inside the image instead of exporting the lock.** Rejected by the
  export step's own reasoning (`:1140-1148`): without `--locked` on both halves, the image can
  re-resolve and stop being what the tests job tested.
