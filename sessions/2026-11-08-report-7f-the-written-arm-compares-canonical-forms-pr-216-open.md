# 7f — the written arm compares canonical forms now; one of four blockers clears

**Date:** 2026-11-08
**Lane:** 7f (doc-tools)
**Branch:** `7f/written-arm-canonical` → PR #216, based on `main`
**Ruling implemented:** the architect's 2026-11-08 packet — *"the written arm
compares canonical forms, not strings"*

## What was wrong

One report held two standards for one string. `scripts/pcn_score.py` resolves a
written header to its canonical form and then compares canonical forms, so TI's
`mfr` read as `TEXAS INSTRUMENTS` is credited: that spelling is a key in the
notice's own `accepted` block, declared verbatim-correct for this document. The
gate's written arm compared the strings, found three fires split
`['Texas Instruments Incorporated', 'Texas Instruments Incorporated', 'TEXAS
INSTRUMENTS']` on identical bytes, and blocked the whole report.

## What changed

- `_written_equality_key` maps each read through `pcn_score.score_header_field`
  and compares **what it resolves to**. `exact`, `alias` and `misformatted`
  unify. `distractor`, `wrong`, `unreadable`, `hallucinated` and `pending`
  resolve to no canonical form and fall through to the previous key.
- `compare_written_headers` takes `specs`; `written_header_specs()` loads them
  from ground truth. **This is the first time the gate reads the `notices`
  block** — it has only ever loaded `_corpus`. The correctness arm reads totals
  the scorer already computed from these declarations; this arm compares reads
  to **each other**, and nothing in a score JSON says what a third spelling
  would have resolved to.
- The report gains `written_agreement.canonical` — `{notice: [fields]}` that had
  a declaration to resolve against — and the markdown says so in a sentence.

## Two things that are deliberate and will look wrong

**The unifying set is not `HEADER_FAILURES`' complement**, and it is written out
longhand so nobody derives it. `misformatted` is *in* `HEADER_FAILURES` — it
fails correctness — and it unifies **here** anyway, because a mangled spelling
of an accepted form still carries the content the page printed. The two arms ask
different questions of one status.

**No spec is not a degradation.** A notice ground truth does not declare, a
field it does not declare, or a caller passing nothing gets the 2026-11-02
case-folded string comparison, which is **stricter** — it separates values the
scorer unifies. That is why every test written before this ruling still passes
unchanged, and why the fallback needs no warning: it cannot let anything
through.

## Measured, on values that already existed

Replayed `docs/corpus-gate/latest.json` (the 2026-11-08T031500Z report) through
the new comparator — the report's own recorded reads, not a new fire:

| notice | `mfr` as recorded | before | after |
|---|---|---|---|
| `TI_PCN_20210316000.pdf` | `['Texas Instruments Incorporated', 'Texas Instruments Incorporated', 'TEXAS INSTRUMENTS']` | DISAGREE | **agree** |
| `onsemi_Generic_IPCN25300X.pdf` | `['ONSEM.', 'onsemi', 'onsemi']` | DISAGREE | DISAGREE |

**One of the report's four blockers.** onsemi stays red and that is correct:
`ONSEM.` sits in that spec's `not` block, a named trap rather than a spelling of
the name. The identity arm (onsemi `mfr` unstable) and the correctness arm
(onsemi `mfr` distractor) are untouched by this change and still block.

**The red does not lift from the report until a fire reads it.** This changes
what the comparator says about recorded values; `docs/corpus-gate/latest.json`
keeps its `fail` verdict until the gate runs again.

## Suite

From PowerShell, per the repo rule: **2637 passed, 13 skipped, 17 deselected**
in 4m48s. The written-agreement file alone: 44 passed, up from 33.

## Also on this branch

`sessions/2026-11-08-packet-to-lane-01-the-playbook-door-row.md` — the packet
owed to Lane 1 from the same work order. It needs no code: the `HELD_OUT` lift
for `playbook` **already shipped** in #209 (`e604b59`).
