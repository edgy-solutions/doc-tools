# ADR-0221 — the PDN diagnostic grades a stored artifact, not an extractor change

**Status:** measured
**Date:** 2026-09-21 (established by the corpus validation) · recorded 2026-11-18
**Deciders:** a property of the instrument, not a choice — recorded because its *output* reads
like a measurement of extraction
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:27-32` §Domain handoffs caution 2;
`docs/handoff-pdn-continuation-table-pairing.md:30-36` and `:44-55`;
`docs/pcn-corpus-validation-2026-09-21.md:8-24` §"How it was run"
**Related:** [ADR-0220](ADR-0220-the-136-of-402-figure-is-retracted.md) (the figure this
mechanism produced), [ADR-0222](ADR-0222-the-corpus-validation-is-the-authority.md),
[ADR-0225](ADR-0225-a-local-checkout-is-not-the-deployed-contract.md) (the same failure shape,
one layer out)

## Context

The PDN parts diagnostic (`pdn_parts_diagnostic.py`, on the investigation branch — not in this
tree at the pin) takes the `extraction.json` a notice already produced and classifies each
extracted part against the document's tables: affected-exact, affected-partial,
from-unheadered-table, from-replacement-column, not-in-any-table. It takes a `--tl-path`
argument pointing at a `table_text_layer` module, which invites an obvious and wrong reading:
point `--tl-path` at the fixed module, re-run, and see whether the fix worked.

It cannot show that. **The parts it grades were produced by whatever code ran at ingest.** The
module handed to `--tl-path` is used only by the instrument's own table indexing and header
detection — it changes how the stored values are *classified*, never which values exist. So an
A/B over `--tl-path` moves the classification columns and the extractor is untouched on both
sides.

The consequence is not a null result, it is a confident wrong one. That is exactly how the
retracted figure of [ADR-0220](ADR-0220-the-136-of-402-figure-is-retracted.md) was produced: the
instrument's own inheritance, applied without a caption check, invented a column of
"replacement-sourced" parts out of correctly extracted ones, and the report presented it as a
property of the document. The handoff adds a second trap on top: once `table_text_layer`'s
`_is_affected` vetoed alias headers, pointing `--tl-path` at the fixed module changed the
instrument's header detection *as well as* production behaviour, so the two effects are no
longer separable even in principle.

## Decision

**The diagnostic grades a stored artifact. To measure an extractor change, drive the extractor.**

- A `--tl-path` A/B is a measurement of **the instrument**, and any claim it supports is a claim
  about classification, never about extraction.
- To measure an extractor change, **drive `parts_from_grid` / `parts_from_pages` directly over
  the PDFs, baseline and candidate** — the way each side's own caller drives it: the baseline
  per page, the candidate with the header threaded across pages, both calling `parts_from_grid`
  per table so every emitted part keeps its `(page, table, row, col)` and can be traced to the
  column header it came from. `doc_tools/utils/table_text_layer.py` defines all three entry
  points (`parts_from_grid`, `parts_from_page`, `parts_from_pages`).
- The baseline side must be **the deployed module, proved to be that module**, not a checkout
  assumed to match it. The 2026-09-21 run established the baseline by hashing the module in the
  running pod and showing it byte-identical to `origin/main`
  ([ADR-0225](ADR-0225-a-local-checkout-is-not-the-deployed-contract.md)).
- `docs/pcn-corpus-validation-2026-09-21.md` §"How it was run" is the recorded procedure. A new
  extractor measurement follows it or says why it differs.

## Consequences

- There is no cheap way to measure an extractor change. The sanctioned path needs the real PDFs
  and two modules driven side by side; re-running an existing instrument over stored output is
  the cheap thing, and it answers a different question.
- The diagnostic keeps a real use — grading what a *past* run produced, which is how a demo
  defect is reproduced from the artifact that shipped it. Nothing here says to delete it.
- Re-ingesting to refresh the stored `extraction.json` is not a shortcut either: that measures
  the deployed image's extractor, which is the pinned one, not a candidate tree.
- The handoff's advice is blunter than this record and worth keeping as written: **do not re-run
  the diagnostic for this at all.**

## Alternatives considered

- **Make `--tl-path` re-extract, so the flag means what a reader expects.** Not recorded as
  considered, and the obvious shape of it — the instrument importing the candidate module and
  re-driving extraction over the source PDFs — turns a grading tool into a second extractor
  driver with its own call convention, which is the thing most likely to disagree with
  production for reasons nobody can see. The validation report chose the other direction:
  drive the real entry points, keep the instrument out of the path.
- **Remove the `--tl-path` flag.** Not recorded as considered. It would close the trap at the
  cost of the flag's legitimate use (changing how a past artifact is classified), and the script
  is not in this tree at the pin, so it is not this repo's change to make.
