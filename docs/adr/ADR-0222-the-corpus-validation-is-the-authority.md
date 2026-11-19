# ADR-0222 — the 2026-09-21 validation is the authority for `table_text_layer`

**Status:** measured
**Date:** 2026-09-21 (the measurement) · recorded 2026-11-18
**Deciders:** this lane, naming one authority rather than leaving each claim to be re-derived
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:16-18` §Domain handoffs (the document is listed there as "the authority
for any claim about how `table_text_layer` behaves on real data");
`docs/pcn-corpus-validation-2026-09-21.md` — §"How it was run" (`:8-24`), the per-notice result
(`:26-41`), §2 (`:75-112`), §3 (`:113-142`), §4 (`:143-164`), the verdict (`:198-224`)
**Related:** [ADR-0220](ADR-0220-the-136-of-402-figure-is-retracted.md),
[ADR-0221](ADR-0221-the-diagnostic-grades-a-stored-artifact.md),
[ADR-0189](ADR-0189-the-published-report-is-the-authority.md) (the same authority rule for the
corpus gate), [ADR-0129](ADR-0129-a-customer-part-number-is-never-an-affected-part.md)

## Context

`table_text_layer` is the tier-1 parts extractor: it decides, per table, which columns hold
affected parts, which hold replacements and which are customer aliases to be vetoed. Almost
every interesting claim about it is a claim about real documents — does the alias veto fire
where it should, does header inheritance ever fire, how many notices yield nothing — and those
claims cannot be settled from the module or from its tests. The tests pin decisions; they are
written against grids chosen to pin a decision.

What goes wrong without a named authority is on the record twice over. Once by invention: a
figure derived from an instrument's own behaviour was read as a property of the corpus, cited in
four places, and used to motivate a production change
([ADR-0220](ADR-0220-the-136-of-402-figure-is-retracted.md)). Once by re-derivation: the obvious
way to check an extractor change is to re-run the diagnostic, which measures something else
entirely ([ADR-0221](ADR-0221-the-diagnostic-grades-a-stored-artifact.md)). Both are cheap to
repeat and neither is cheap to notice.

The 2026-09-21 validation is a baseline-vs-candidate A/B over the nine distinct source notices
in sandbox object storage (twenty stored runs collapse to nine documents). The baseline was the
module in the running pod, hashed and shown byte-identical to `origin/main`, so the comparison
is against deployed code rather than an assumption about it; each side was driven the way its
own caller drives it, per table, so every emitted part keeps `(page, table, row, col)` and traces
back to the header it came from.

## Decision

**`docs/pcn-corpus-validation-2026-09-21.md` is the authority for any claim about how
`table_text_layer` behaves on real data. A claim that contradicts it is wrong until a new
measurement of the same shape replaces it.**

- It is the authority for the four things it measured: that the alias veto fires on exactly one
  notice (removing fourteen alias values and no genuine part), that no notice lost a part, that
  header inheritance **never fires** on any of the nine under the deployed table reader, and
  that five of nine notices yield zero tier-1 parts and fall through to the vision pass.
- It is the authority for the two things it **disproved**: the retracted replacement-column
  figure, and the premise that an instrument A/B could have shown an extractor change.
- Its §"How it was run" is the **procedure** a replacement measurement follows — real documents,
  the deployed module proved deployed, both sides driven through the extractor's own entry
  points.
- A claim about this module that cites a test, a docstring or a diagnostic report is **not** of
  this kind and does not compete with it. Per the status vocabulary, a test that *could* measure
  is not a measurement.
- Where the document records a design item it deliberately did not take (the tier-1 recall gap
  in §4, and the content-gated header-vocabulary addition it describes), that item is open, not
  settled — this record does not promote it.

## Consequences

- One file to read, and it is tracked, so the authority travels with the repo instead of living
  in whoever ran it. `AGENTS.md` sends a fresh session there before it touches PCN/PDN
  extraction, which is the point.
- The measurement is **not re-runnable from this tree**: the drivers were one-off instruments and
  are not committed, by the instrument-hygiene rule, and the documents live in object storage,
  not in git. Reproducing it means rebuilding the harness from §"How it was run". That is the
  standing cost of this decision and the reason the written record carries so much of the detail.
- It is dated, and it ages. It measures the module as of 2026-09-21 against nine notices; a
  later change to the extractor, the table reader beneath it, or the corpus makes it a historical
  authority. Anything leaning on it for a claim about today's code says which it is relying on —
  the procedure, or the numbers.
- Its §3 finding is load-bearing in an unobvious way: inheritance not firing is what currently
  keeps the fix away from the mistake the diagnostic made, and that is a property of how the
  table reader widths those pages, not a guarantee from the code. A change to the table reader
  can make the inheritance path live without touching `table_text_layer` at all.

## Alternatives considered

- **Let the tests be the authority.** Rejected by the status vocabulary and by the history
  above: the continuation tests were themselves written against a figure that did not hold, and
  they were green throughout. A test says a decision is pinned, not that the decision is right
  about documents.
- **Re-measure per change instead of naming an authority.** Not rejected — it is what a new
  claim requires — but it is not a substitute: without a named baseline, each re-measurement is
  compared against memory, and the retracted figure is what that looks like.
