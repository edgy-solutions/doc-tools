# ADR-0107 — no fetch mode, and the scorer never normalises

**Status:** accepted + built
**Date:** no ruling date is recorded; standing guidance in `AGENTS.md` · recorded 2026-11-18
**Deciders:** this repo's standing agent guidance (`AGENTS.md` §Batch fixtures), stated there as
*"two rules here that are not negotiable"*; no individual decider is recorded
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:47-51`; `doc_tools/batch/cli.py:3-5`; `doc_tools/batch/score.py:3-7` and
`:127`; pinned by `tests/test_batch_score.py:58`
**Related:** [ADR-0106](ADR-0106-batch-is-an-operator-cli-not-the-pipeline.md) (what the tool is),
[ADR-0205](ADR-0205-a-length-and-a-hash-prefix-never-a-value.md),
[ADR-0230](ADR-0230-the-batch-column-map-seam.md),
[ADR-0130](ADR-0130-a-null-row-value-is-excluded-from-scoring.md)

## Context

The batch tooling has two obvious conveniences, and both are traps.

**The fetch.** The CLI resolves every `source.field` through the `Catalogue`, which names the
route that would serve those fields. Adding `--fetch` would save an operator a manual export. It
would also create a tool that **reads production and writes its output next to a terminal
transcript**. The operator path is where private document values are handled, so the hazard is not
a leak in principle — it is a leak in the ordinary case where someone pastes a command and its
output into a report.

**The normalisation.** The scorer compares an exported cell against a hand-typed truth cell. Case,
whitespace and date form differ constantly, so a run full of mismatches invites a fix: strip, lower,
parse the date, compare. That fix destroys the instrument. The extractor's own defects *are* case,
whitespace and date form — a trailing newline in an MPN, a part number upper-cased, a date
re-rendered in the wrong order. A scorer that normalises before comparing reports a clean set over
exactly the corpus that would have shown the defect.

## Decision

**Two rules, stated as non-negotiable: neither command gets a fetch mode, and the scorer never
normalises before comparing.**

- **No fetch mode.** Both entry points' docstrings open with *"Reads files only"* and say what
  is excluded: `cli.py:3-5` — *"It does NOT fetch (no network, no credentials: the route that
  serves the catalogue fields is never called from here)"*; `score.py:3-4` — the same, plus *"no
  catalogue: the scorer never resolves a field"*. Measured at the pin, neither `argparse` parser
  has a flag that could reach a service: `cli.py` takes `--profile`, `--extraction`, `--out`,
  `--fail-on-warning`, `--dry-run`; `score.py` takes `--rows`, `--truth`, `--profile`, `--key`,
  `--scorecard`, `--detail`, `--fail-under`.
- **No normalisation.** A truth value must equal the exported cell **byte for byte**. The
  comparison is a single `got == want` (`score.py:127`) with no transformation on either side —
  not case, not whitespace, not date form.
- **One reserved token, and only one.** An empty truth cell asserts nothing (a half-filled truth
  set is the normal case) and `<empty>` asserts the exported cell is empty (`score.py:122`). That
  is the only thing a cell may say beyond its literal value.
- Pinned by test: `test_mismatch_is_counted_and_not_normalised`
  (`tests/test_batch_score.py:58`) scores a truth row whose cells differ from the export only by
  **case and a trailing space**, and asserts both are counted as mismatches and the column's rate
  is `0.0`.

## Consequences

- An operator exports by hand before scoring. That step is the cost, and it is paid every run.
- **A low rate is the normal first result**, and reading it takes care: a mismatch may be a real
  extraction defect or a truth cell typed with different spacing. The scorer cannot tell them
  apart, by design, and the detail file (values, never leaves the box) is where the distinction is
  made by a human.
- The scorecard stays publishable because it holds integers, floats, profile column names and
  fixed vocabulary only — no fetch means no value from a live system can enter it either.
- The rule is about *comparison*, not about the pipeline: the exporter is allowed to be strict
  elsewhere, and a separate decision governs what a null row value means for a score
  ([ADR-0130](ADR-0130-a-null-row-value-is-excluded-from-scoring.md)). Normalising at the
  comparison is what is forbidden.
- A future field served by lane 1 needs **no change to the CLI** — every `source.field` resolves
  through `Catalogue` — so there is no pressure to add a fetch "just for the new field".

## Alternatives considered

- **A fetch mode guarded by a flag, a read-only token, or a non-production endpoint.** Rejected:
  the stated ground is the tool's *capability*, not its configuration — *"a tool that can fetch is
  a tool that can be pointed at prod and piped into a transcript"*. A guard is a setting, and a
  setting is what gets passed wrong.
- **Normalise case and whitespace but not dates** (or any partial normalisation). Rejected by the
  same sentence that rejects the whole: the three named axes — case, whitespace, date form — are
  each a defect class the scorer exists to catch.
- **A second, normalising score mode alongside the strict one.** Not recorded as considered. The
  shape is clear and the cost is clear — two rates, and every report then has to say which one it
  quotes. It is **not** recorded as weighed.
