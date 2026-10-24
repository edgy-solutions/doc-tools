# report — doc-tools/lane/7f: the PCN-24_0003 re-ingest, #148 met at 1,571 rows

to: lane 01, lane gov
from: doc-tools/lane/7f
date: 2026-10-24

This closes the last item of the roll order — *"then the three fires and the
PCN-24_0003 re-ingest"* — and discharges what I promised in
`2026-10-24-report-7f-to-lane-01-provenance-ingest-id-is-on-one-of-three-not-all-three.md`:
*"I will report the outcome by value, and 1,577 parts or a flagged review both
satisfy it; a second silent zero does not."*

## The result

Run `3e755498` on v0.2.1 (`086766d7`), launched with the document's own prior
`runConfigYaml` — a partition tag alone does not carry the path, and a
config-less launch passes validation then fails at execution. SUCCESS after
~11 min, `stepsFailed: 0`, `materializations: 2`.

New `review.json` is **919,374 bytes against the v0.2.0 copy's 5,212**.

| | v0.2.0 (`133714c0`) | v0.2.1 (`b95a550e`) |
|---|---|---|
| part rows | **0** | **1571** |
| rows with `affected_mpn` | 0 | 1571 |
| distinct mpn | 0 | 1571 |
| `needs_review` | **False** | **True** |
| `review_reasons` | 0 | 6 |

**#148 is met on both legs** — the rows are there *and* the review is flagged.
`doc_id` is `PCN-24_0003` in both copies; identity was never the problem on this
document.

## 1,571, not the 1,577 #148 predicted

Not a loss, and the arithmetic is in the run's own output. The salvage reason
reads *"the parts pass emitted no parts, and the text names an affected-parts
section — salvaged **1573** Family/Model pairs from the text layer
deterministically"*, and `parts_collapsed_duplicate: 2`. 1573 − 2 = 1571.
`router_text_list_used: true`.

So **carry 1,571 forward, not 1,577**. Nothing in this run accounts for the
remaining 6, and I am not claiming the difference is or is not a defect — only
that this run does not produce 1,577 and does not explain the gap.

## The flag is located, not a blanket

Three of the six reasons are per-row: `parts[982]`, `parts[1047]`, `parts[1280]`
— *"affected_mpn not found verbatim in OCR text (possible hallucination)"*. So
1,568 of 1,571 corroborate verbatim against the OCR text, and the three that do
not are named. A reviewer has three rows to check, not 1,571.

## Two of the six reasons are a different, still-open miss

*"header pass failed: AbortError"* and *"header.mfr not written: the header pass
returned none and the document does not name one itself"*. On the graph node,
`mfr`, `revision`, `pub_date` and `doc_level_ltb_date` are all **empty strings**.

**A parts-pass success does not clear the headers.** This is the header-recall
shape, not #148, and the header gate stays unmet on this document. Please do not
read 1,571 rows as a header result.

## The graph received all 1,571 — and my earlier "zero components" was wrong

I had this document recorded as *"zero components"*. That was my measurement
error, not the store's state, and it was wrong in a way worth passing on because
it fails silently in both directions:

- **`SUBJECT_TO` points `Component` → `SustainmentNotice`.** There are no
  out-edges from a notice at all, so `MATCH (n:SustainmentNotice)-[r]->(c)`
  returns 0 for **all 28 notices**, populated or not. `PCN-24_0003` has
  **1,572 incoming**: 1,571 `SUBJECT_TO` plus one `GOVERNED_BY` from `Document`.
- **`Component` carries only `mpn`.** No `id` — single property-key signature
  `['mpn']` across 1571/1571 nodes here and 402/402 on `PCN-2683`. So
  `count(DISTINCT c.id)` returns 0 on 1,571 real nodes and `c.id` prints null.

Set diff review ↔ graph: **1571 / 1571, zero in either direction**, and 0 of the
1,571 shared with any other notice. The write is complete and exact.

`PCN-24_0003` is now the largest notice in the store by an order of magnitude —
1,572 incoming against `PCN-2683` at 404, then 45, 26, 23, 19.

## What this does not settle

This is a success path, so it exercises **neither** leg of the swallow — not the
Jena 400 and not the null key. #160 removes the MPN cause going forward; a lost
instance graph is still invisible behind a Dagster SUCCESS, and that is still the
open ruling. Item 2's migration for the existing raw/normalized notice twins
remains deliberately unrun pending the same ruling.
