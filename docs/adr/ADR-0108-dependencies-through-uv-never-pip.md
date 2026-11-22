# ADR-0108 — dependencies through `uv add`, never pip

**Status:** accepted
**Date:** no ruling date is recorded; standing guidance in `AGENTS.md` · recorded 2026-11-18
**Deciders:** this repo's standing agent guidance (`AGENTS.md` §Workflow Guide 4); no individual
decider is recorded
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:58` (§Workflow Guide 4); `pyproject.toml`, `uv.lock` and `.python-version`
at the repo root; `CLAUDE.md` §Conventions ("Python through this repo's venv only");
`.github/workflows/build-container.yml:608-650`, `:823`, `:1148` and `:1359`
**Related:** [ADR-0206](ADR-0206-the-venv-and-powershell-rule.md) (which interpreter),
[ADR-0207](ADR-0207-cis-interpreter-is-pinned.md) (which Python),
[ADR-0211](ADR-0211-the-dockerfile-is-generated-in-the-workflow.md)

## Context

`pip install <package>` is the reflex, it succeeds, and the import then works. In this repo it
leaves the package in **exactly one place on earth** — one interpreter's `site-packages` on one
machine — and nothing downstream ever learns of it.

Two things make that failure quiet rather than loud here.

**The lockfile is what ships.** Measured 2026-09-19 and recorded in the workflow: `uv export
--format requirements-txt` emits *the lock's resolved commit, character for character* — it reads
`uv.lock` and does not resolve independently (`build-container.yml:626-640`). The image is built
from that exported `requirements.txt` with `uv pip install --python /opt/venv` (`:1148`, `:1359`).
So a dependency that is not in the lock is not in the image, and the symptom is an `ImportError`
in a pod, on a pin that passed locally.

**And the interpreter is ambiguous.** Per `CLAUDE.md` §Conventions and
[ADR-0206](ADR-0206-the-venv-and-powershell-rule.md), Python here runs through `uv run` or
`.venv/Scripts/python` and never a bare `python`/`py` from `PATH` — this repo has already had *a
conclusion inverted by a stale interpreter reading a stale file successfully*. A `pip install`
typed at a bare `python` therefore installs into **an interpreter the repo does not use**. The
import that proves it worked was resolved by that same wrong interpreter, so the check and the
mistake share a blind spot: the package is absent from the repo venv, absent from `uv.lock`, and
absent from the image, while the terminal says it is installed.

## Decision

**New libraries arrive through `uv add <package>`, which updates `pyproject.toml` and `uv.lock`
together. Do not use pip.**

- `pyproject.toml` and `uv.lock` are the two files that define this repo's dependency set, and
  they are both tracked at the root. `requires-python = ">=3.12"`, with `.python-version` pinning
  `3.12` ([ADR-0207](ADR-0207-cis-interpreter-is-pinned.md)).
- CI installs with **`uv sync --locked`** (`:823`) and runs the suite as `uv run -- python -m
  pytest -q -rs` (`:850`), so the tests run against the dependency set that actually ships. The
  flag is carried at **both** ends — here and on the `uv export` in build-and-push — so neither
  can silently re-resolve and drift from the other (`:648-650`).
- Hand-editing `pyproject.toml` without re-locking is the same defect in a different spelling:
  `uv sync --locked` fails when the lock is out of date with respect to `pyproject.toml`.
  Measured in the same comment: `uv lock --check` → *"Resolved 384 packages"*, exit 0, lockfile
  untouched.

## Consequences

- Adding a dependency is a **tracked change** that a reviewer sees: two files in the diff, and the
  resolved version visible in the lock.
- A pip install is not merely discouraged, it is **unreproducible downstream**: the image's venv
  has no pip at all. The Dockerfile says so where it installs the spaCy model — *"uv environments
  don't have pip"* (`:1370`) — and uses `uv pip install --python /opt/venv` instead.
- The rule is **not** enforced by a check of its own, which is why this record is `accepted` and
  not `built`. What catches a missing dependency is indirect: CI's suite runs under the locked
  environment, so code that imports a pip-only package fails there — but only if a test imports
  that code. A package installed locally and used nowhere a test reaches is invisible until a pod
  raises.
- Anything the lock cannot express is a **separate, visible exception** rather than a quiet pip
  call: the spaCy model wheel and the NLTK/HuggingFace downloads are explicit `RUN` lines in the
  generated Dockerfile (`:1370-1376`), not dependencies.
- A dependency added for local tooling only still pays the image cost, because the image installs
  the exported lock wholesale. `langchain` is the standing example — declared, imported by
  nothing ([ADR-0104](ADR-0104-a-new-domain-is-a-schema-and-a-plugin.md)).

## Alternatives considered

- **`pip install` into the repo venv, then edit `pyproject.toml` by hand.** Rejected by this rule.
  It is the near-miss case: the venv and `pyproject.toml` agree, the lock does not, and
  `uv sync --locked` fails CI — a loud failure, but one that costs a round trip, and only when the
  edit was remembered at all.
- **A bare `uv sync` in CI instead of `--locked`.** Argued for in this repo and then **reversed**
  on measurement, 2026-09-19 (`:608-650`). The stated goal was that the tests run against what
  ships; since `uv export` reads the lock, the bare form is what defeats that goal. The record of
  the reversal is kept in the workflow rather than replaced, because the premise expired
  underneath the conclusion.
- **`requirements.txt` as the source of truth.** Not recorded as considered. It exists only as a
  generated intermediate inside the build (`:1148`), and the `--no-emit-project` flag is there so
  it carries dependencies and not this project itself.
