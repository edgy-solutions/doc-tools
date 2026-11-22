# doc-tools — lane conventions

Working guidance for this repo lives in [`AGENTS.md`](AGENTS.md): the pipeline,
the extension patterns, and the safety guardrails. This file carries the
standing *conventions* of the 2026-10-06 fleet directive, which apply to every
repo and are mirrored in `invincible-agent/CLAUDE.md`. Placed here by packets
from `ia-01/lane/01` and `ia-gov/lane/gov`, and committed by the owning lane:
this file is a convention record, not a session file.

## Conventions

- **Only the owning lane commits in this repo, and a session file is never
  committed at all.** Packets and handoffs are *placed* under `sessions/` and
  stay local files there -- ruled 2026-11-12, every repo, and `sessions/` is
  gitignored here. Anything else a peer places in this tree is committed by
  the owning lane along with its own work, so authorship and review stay with
  the lane that owns the tree.

  A branch that still *tracks* files under `sessions/` loses them from disk
  the moment it merges a master that untracked them: the merge records the
  deletions and git removes the files. From the worktree root, run
  `git ls-files sessions | head -1`; if it prints anything, run
  `git rm -r -q --cached sessions` and commit **before** merging. If a merge
  has already deleted them, `git archive HEAD^1 sessions | tar -x` restores
  the tree and leaves the index alone, where `git checkout HEAD^1 -- sessions`
  would stage them all over again. Never `git add -f` a session file.

- **Print a length and a hash prefix, never a secret value.** A secret's
  presence or equality is shown as `len=N sha256:XXXXXXXX` (first 8 hex). This
  is not hypothetical here: a drift script in this repo once printed three live
  credentials into a transcript, and the transcript is not editable.
  `tools/drift_check.py` now redacts on a name match.

- **A stacked PR runs no CI gate.** Measured from the tree, not assumed:
  `.github/workflows/build-container.yml` is this repo's only workflow and its
  `pull_request` trigger is scoped `branches: [main]`. A PR based on `main` is
  built; a PR stacked on another branch dispatches nothing at all — not a
  failure, not a skip, no run record. Rebase onto `main` before expecting a
  verdict.

- **Show the values diff before a roll.** Before a `helm upgrade` from
  `charts/`, render with the deployed values (`helm template`) and diff against
  the live release (`helm get values` / `helm get manifest`); show that diff to
  whoever approves the roll. Secret-bearing keys appear by length and sha256
  prefix only, per the rule above.

- **Python through this repo's venv only.** `uv run` or `.venv/Scripts/python`
  — `pyproject.toml` and `uv.lock` are here. Never a bare `python`/`py` from
  `PATH` or another checkout's venv: this repo has already had a conclusion
  inverted by a stale interpreter reading a stale file successfully.

  And run the suite **from PowerShell**, redirecting to a log:
  `& .\.venv\Scripts\python.exe -m pytest tests/ -q > pytest.log; Get-Content pytest.log -Tail 5`.
  A system interpreter loads a different `python-magic`/libmagic pairing and
  blocks for ever at import (`magic/compat.py`): no output, one core pegged,
  and the process outlives the session — on 2026-10-02 four of these had been
  running for one to two days. The venv interpreter under the Bash tool hangs
  in collection the same way and prints nothing; from PowerShell the suite
  finishes in well under a minute. Every module pays for this because
  `doc_tools/__init__.py` imports the Dagster defs, which pull `unstructured`,
  which pulls `python-magic`. **A run that produces no output is an
  interpreter-and-shell problem before it is a code problem** — kill it rather
  than leaving it running. (From #64, which this supersedes.)
