# ADR-0190 — Ground truth for the TI second table: devices only

**Status:** measured
**Date:** 2026-10-10 (ruled for TI) and 2026-10-29 (generalised to every notice) · recorded
2026-11-18
**Deciders:** the architect, relayed by Chris — the ruling is recorded as data in ground
truth rather than as prose
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `scripts/pcn_ground_truth.json:734` (the `source` note carrying the ruling), with
the alias enumeration at `:732` and the rule-as-data at `:733`; the row-by-row enumeration
and its guards in `tests/test_ti_pcn_live_miss.py:107` and `:396-520`
**Related:** [ADR-0129](ADR-0129-a-customer-part-number-is-never-an-affected-part.md) (the
general rule), [ADR-0188](ADR-0188-the-denominator-is-a-rate-not-a-count.md) (the denominator
this moved), [ADR-0222](ADR-0222-the-corpus-validation-is-the-authority.md),
[ADR-0189](ADR-0189-the-published-report-is-the-authority.md)

## Context

The TI notice in the corpus carries **two** part-bearing tables.

Page 3 holds the qualification table whose `DEVICE` column names the **nine** affected
devices, all nine verbatim-confirmed in the source PDF's text layer. Page 2 holds a **second
table of 15 rows**, `DEVICE | CUSTOMER PART NUMBER`: **11 distinct customer part numbers**,
**3 literal `null` cells** and **1 duplicate** (one customer identifier appears against two
devices).

The question that second table raises is whether a customer's own part number is an affected
part. The 2026-09-21 corpus validation left it open — "worth a decision at some point". Until
it was decided, ground truth for this notice declared nine parts and the gate passed, and it
passed for an accidental reason: `page.find_tables()` returns **zero** tables for page 2,
measured on the real PDF on 2026-10-10 and again on 2026-10-29 under both the `lines` and the
`text` strategy. The page was simply invisible to the extractor. A change to table detection,
or a vision pass over that page, would have admitted all 11 strings with no rule having
changed.

## Decision

**Page 2 is devices only, as to affected parts. A customer part number is the customer's own
designation for the device beside it, not an additional affected part.**

- Ruled for TI on **2026-10-10** and for **every notice** on **2026-10-29**, in the same
  direction.
- The 8 devices page 2 names are a **strict subset** of the 9 on page 3 (page 3 adds one, and
  page 2 names no device page 3 omits — measured 2026-10-29 from the page 2 text layer). So
  page 2 changes this notice's affected **count** not at all; what it adds is the 11 aliases.
- The 11 are enumerated **twice, deliberately**: once as what they are **not**
  (`expect_absent_mpns`, so the gate can fail by name) and once as what they positively
  **are** (`customer_mpns`). The duplication is kept rather than cross-referenced because the
  two fields answer different questions.
- They are **not a recall target**. No tier can read page 2 today, so scoring them would be
  scoring a page no tier can see; they are what the extractor *should* emit as `customer_mpn`
  the day page 2 becomes visible.
- The rule is **implemented** as well as declared: since 2026-10-29
  `doc_tools/utils/table_text_layer._is_customer` (`:135`, applied at `:386` and `:420`)
  vetoes a customer column out of the affected role, so were page 2 ever detected, those 11
  would be emitted as `customer_mpn` and never as affected parts.

## Consequences

- A regression fails **by name**. If table detection or a vision pass ever admits page 2, the
  11 enumerated strings score as `ruled_out` in `scripts/pcn_score.py` rather than as 11
  anonymous spurious parts, and `tests/test_ti_pcn_live_miss.py` asserts that page 2 can
  contribute nothing but a real device or one of them — `spurious` and `ruled_out` are
  asserted to be the same set.
- The enumeration is **no longer the only thing** standing between the gate and 11 spurious
  parts, since the extractor implements the veto; it stays because it is what makes the guard
  checkable by name.
- Generalising the rule **cost recall on another notice, deliberately**: the one notice that
  had been scoring that column as genuine affected parts went from 26 to **16 affected plus
  10 customer aliases**, and the corpus denominator moved **522 → 512**
  ([ADR-0188](ADR-0188-the-denominator-is-a-rate-not-a-count.md)). The two notices no longer
  use that column to mean two different things.
- The customer aliases score on their own advisory denominator of 21, and TI's 11 are
  permanently 0 until page 2 becomes readable at all.
- Page 2's invisibility is now a **recorded fact rather than a convenient accident**. A
  reader who finds the page unextracted should not treat it as a defect to fix without
  reading this record and [ADR-0129](ADR-0129-a-customer-part-number-is-never-an-affected-part.md)
  first.

## Alternatives considered

- **Count the customer column as affected parts.** This is what the corpus did for one notice
  until 2026-10-29, and the measurement against it is decisive: the conflated ground truth
  scored that notice **522 / 522 clean** while the pipeline was publishing ten customer
  identifiers as affected parts. Re-scored against the corrected ground truth, the same fire
  is **512 / 512 with 10 spurious**. A conflated ground truth is worse than a wrong one — it
  scored a ten-part fabrication as perfect and no instrument disagreed, because the instrument
  had been taught the fabrication.
- **Keep the question open per notice.** Rejected on 2026-10-29: the objection recorded
  earlier was that a global rule would cost one notice ten parts, and that is exactly what
  happened, knowingly. Component IRIs are shared and a row fact names no notice, so those ten
  were the non-withdrawable kind of wrong.
- **Drop the enumeration now that the extractor implements the veto.** Rejected: the
  enumeration is what makes a future regression fail by name instead of anonymously.
