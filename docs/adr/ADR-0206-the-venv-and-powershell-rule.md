# ADR-0206 — Python through this repo's venv, and the suite from PowerShell

**Status:** measured
**Date:** measured 2026-10-02 (the hung processes) and 2026-09-25 (the shell half) · recorded
2026-11-18
**Deciders:** this lane, from its own measurements; carried as a convention in `CLAUDE.md`
§Conventions, which supersedes the earlier note #64
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `CLAUDE.md:36-52`; agent memory
`doc-tools-local-suite-hangs-on-libmagic` and
`the-venv-rule-is-windows-shaped-and-ci-is-linux` (the scope limit)
**Related:** [ADR-0108](ADR-0108-dependencies-through-uv-never-pip.md),
[ADR-0200](ADR-0200-a-stacked-pr-runs-no-ci-gate.md) (why a green local suite is load-bearing
here), [ADR-0207](ADR-0207-cis-interpreter-is-pinned.md)

## Context

Two things have to be right to run anything Python in this repo — **the interpreter and the
shell** — and both failure modes present as *no output at all*.

The interpreter: every module in this tree pays for `python-magic`, because
`doc_tools/__init__.py` imports the Dagster defs, which pull `unstructured`, which pulls
`python-magic` (`CLAUDE.md:48-50`). A system interpreter from `PATH` loads a different
`python-magic`/libmagic pairing and **blocks for ever at import** inside `magic/compat.py`: no
output, one core pegged, and the process outlives the session. **Measured 2026-10-02: four of
these had been running for one to two days** (`CLAUDE.md:44-46`). Sometimes it takes a native
Windows access violation instead, which reads like environment-wide breakage.

The shell: the *identical* command with the *identical* venv interpreter path, run through the
Bash tool (git-bash), **hangs in collection and produces zero bytes of output** — killed at 400
s having printed nothing. From PowerShell the same command finishes in 27 s (agent memory
`doc-tools-local-suite-hangs-on-libmagic`: `514 passed, 8 skipped in 26.71s`).

The cost of misreading this is recorded and it is the reason the rule is worth a record. No
output reads as proof: *the suite cannot run here*. On that conclusion, AST-based harnesses were
written to replicate tests that were never broken, and two subagents in one session reported
their work "unverified by any green run" and stopped — one of them having shipped a test that
**failed**, which the suite caught in 20 seconds. A believed-unrunnable suite converts a red
test into a shrug.

This repo has also had a conclusion **inverted** by a stale interpreter from another checkout's
venv reading a stale file successfully (`CLAUDE.md:38-39`) — a failure that produces output, and
confident output at that.

## Decision

**Python runs through this repo's venv only, and the suite runs from PowerShell, redirected to a
log.**

- `uv run`, or `.venv/Scripts/python` — `pyproject.toml` and `uv.lock` are here. Never a bare
  `python`/`py` from `PATH`, and never another checkout's venv (`CLAUDE.md:36-40`).
- The suite, from PowerShell:

  ```powershell
  & .\.venv\Scripts\python.exe -m pytest tests/ -q > pytest.log; Get-Content pytest.log -Tail 5
  ```

  Redirect, then show the tail — the full output is noisy and a `sqlite3.ProgrammingError`
  traceback from SQLAlchemy pool reset appears mid-run and fails nothing.
- **The usable rule, and the one to remember: a run that produces no output is an
  interpreter-and-shell problem before it is a code problem** (`CLAUDE.md:50-52`). Kill it rather
  than leaving it running, and re-run it under PowerShell.
- Do not accept "tests could not run locally" without asking **which interpreter and which
  shell**. Replicating a test by parsing its source is strictly weaker evidence than running it.
- There is no `pytest-timeout` plugin installed, so `--timeout` is an unrecognized-argument
  error, not a safety net.

## Consequences

- A PR in this repo carries a quoted local suite result with its counts, which matters more here
  than usual: a stacked PR dispatches no workflow at all, so the local run is the **only**
  evidence it has ([ADR-0200](ADR-0200-a-stacked-pr-runs-no-ci-gate.md)).
- A hung run is an operator's mess, not a background task: it pegs a core and survives the
  session that started it. The 2026-10-02 state — four processes, one to two days old — is what
  "leave it and see" looks like.
- **Scope limit, and it is a real one: this rule is Windows-shaped, and CI is Linux.** The
  prescribed `.venv\Scripts\python.exe` path belongs in a docstring telling a *human* how to run
  something. Anything the suite itself executes uses `sys.executable`, which honours the rule on
  both platforms and cannot drift from it. Reading the rule as "write this literal path" imports
  a Windows assumption into code that runs on Linux: measured 2026-10-25 on PR #169, 28 passed
  locally and the whole `tests` job red in CI with `FileNotFoundError` on
  `.venv/Scripts/python.exe`, because the runner is Linux and has `.venv/bin/python` (agent
  memory `the-venv-rule-is-windows-shaped-and-ci-is-linux`).
- `test_venv/` in this tree is dead — POSIX-layout symlinks pointing at a missing
  `/usr/bin/python3.12`. Use `.venv`.

## Alternatives considered

- **Run the suite under the Bash tool with the venv interpreter.** Disproved by measurement:
  same `python.exe`, same cwd, same args, zero bytes of output at 400 s; 27 s from PowerShell.
- **Accept that the suite is unrunnable locally and verify by reading the source.** This was
  tried, recorded as a conclusion, and was wrong. It produced harnesses that replicated
  assertions instead of running them, and it suppressed a genuinely failing test.
- **Pin libmagic / vendor a matching `python-magic` so a system interpreter works.** Not
  recorded as considered. It is the obvious root-cause fix for the interpreter half; nothing in
  the tree at the pin weighs it, and it would not touch the shell half at all.
