# ADR-0106 — `doc_tools/batch/` is an operator CLI, not the pipeline

**Status:** built
**Date:** no ruling date is recorded; standing guidance in `AGENTS.md` · recorded 2026-11-18
**Deciders:** this repo's standing agent guidance (`AGENTS.md` §Batch fixtures); no individual
decider is recorded
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:34-51` (§Batch fixtures); `doc_tools/batch/cli.py:1-11` and
`doc_tools/batch/score.py:1-30`
**Related:** [ADR-0107](ADR-0107-no-fetch-mode-and-the-scorer-never-normalises.md) (the two rules
that keep it this way), [ADR-0230](ADR-0230-the-batch-column-map-seam.md) (the column-map seam),
[DEBT.md](DEBT.md)

## Context

`doc_tools/batch/` sits inside the `doc_tools` package, next to `assets/`, `components/` and
`plugins/`. Everything else at that level runs in the deployed code location. A reader who assumes
the same of `batch/` draws two wrong conclusions, and both are expensive.

The first: that it is part of the pipeline, so its defects are production defects and its column
map is a runtime contract. It is neither. It turns **saved** extraction responses into fixture
rows and scores them against a hand-typed truth set, on an operator's own box.

The second, worse one: that because it is "in the package", it may be given the pipeline's
affordances — a resource, a client, a token — to make it more useful. The moment it can reach a
live service it becomes a tool that can be pointed at production and piped into a transcript,
which is the hazard [ADR-0107](ADR-0107-no-fetch-mode-and-the-scorer-never-normalises.md) exists
to prevent.

## Decision

**`doc_tools/batch/` is an operator CLI, not the pipeline.**

- **Nothing under `doc_tools/` imports it.** Measured at the pin: the only imports of
  `doc_tools.batch` are from inside `doc_tools/batch` itself (`cli.py:24`, `score.py:41`).
- **No network and no credentials.** The three modules import stdlib plus `yaml` and
  `jsonschema`, and nothing else. Both entry points' docstrings open with *"Reads files only"*.
- **It is not part of any pipeline graph** — no `@asset`, no job, no sensor, so there is no path
  by which a Dagster run reaches it.
- It is invoked by hand: `python -m doc_tools.batch.cli` and `python -m doc_tools.batch.score`,
  documented in [`docs/batch-fixture-runbook.md`](../batch-fixture-runbook.md), with its column
  map contracted at `contract_version: 2` in
  [`docs/contracts/batch-column-map.md`](../contracts/batch-column-map.md).
- Its outputs are split by what may leave the box: the scorecard carries integers, floats,
  profile column names and fixed vocabulary only; the detail file carries values and never
  leaves; stderr diagnostics name line numbers and counts, never a cell value
  (`score.py:14-17`).

## Consequences

- A defect in `batch/` is an **operator-tooling defect**. It cannot affect an ingest, and a fix
  needs no pin bump or roll.
- Nothing may be added to it that holds a credential or opens a socket. That is not a style
  preference: it is the property that lets an operator run it over a private corpus on their own
  machine.
- The column map it reads is a **seam to lane 1**, not an internal detail — which is why it has a
  contract document and its own record ([ADR-0230](ADR-0230-the-batch-column-map-seam.md)).
- **The guidance overstates one half, and the row belongs in [DEBT.md](DEBT.md).** `AGENTS.md:39`
  says it is *"in no deployed image"*. At the pin that is false as stated: the build context is
  `.`, the generated `.dockerignore` excludes `tests` and caches but not `doc_tools/batch`
  (`.github/workflows/build-container.yml:1153-1237`), and the Dockerfile does `COPY . /app`
  (`:1363`). The files **are** in the image. What is true is the thing that matters — nothing
  imports them, no entry point reaches them, and the container's command is
  `dagster api grpc -p 3030` ([ADR-0100](ADR-0100-doc-tools-is-a-code-location-not-a-service.md)),
  so they never execute. The precise claim is *inert in the image*, not *absent from it*.
- Because they ship, `batch/` must stay importable under the image's interpreter — it is part of
  what `COPY . /app` puts on `PYTHONPATH=/app`. An import-time dependency added there would be a
  new image dependency, not a local one.

## Alternatives considered

- **Make it an asset so it can be run from the launchpad.** Rejected by this decision: an asset
  runs in the pod, where the saved responses are not and the credentials are, which inverts both
  of the properties above.
- **Move it out of the repo entirely.** Not recorded as considered. The shape is obvious — a
  separate operator tool with its own packaging — and the cost it would add is a second copy of
  the column-map contract and of the profile schema, which is the second-master problem recorded
  for ontologies in [ADR-0103](ADR-0103-substrate-priming-is-the-platforms.md). It is **not**
  recorded as weighed.
- **Exclude `doc_tools/batch/` from the image via `.dockerignore`.** Not recorded as considered,
  and it is what would make the guidance's wording literally true. It is listed as a follow-up
  rather than taken here, because the build-skip and ignore lists are deliberately conservative
  ([ADR-0201](ADR-0201-the-build-skip-allowlist-is-not-widened.md)).
