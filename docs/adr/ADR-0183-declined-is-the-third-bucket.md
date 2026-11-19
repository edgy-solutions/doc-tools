# ADR-0183 — DECLINED is the third bucket, and the strict verdict grants nothing

**Status:** built + measured
**Date:** 2026-11-16 (ruled; commit `135e0a4`, PR #224) · recorded 2026-11-18
**Deciders:** the architect — the code records it as "ruled 2026-11-16" and names no relay
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `scripts/pcn_corpus_gate.py:1224-1248` (the rule), `classify_declined` at `:1300`
with its four conditions, `_gt_published_in_fire` at `:1251`, `_gt_scores_field` at `:1277`,
`identity_instability_declined` at `:1346`, the report key at `:2206`; pinned by
`tests/test_corpus_gate_declined.py` — a code comment and a test docstring, which were the
**only** written statement of this ruling before this record
**Related:** [ADR-0181](ADR-0181-a-declaration-is-keyed-to-its-field.md) (what counts as
declared), [ADR-0182](ADR-0182-the-written-arm-compares-canonical-forms.md),
[ADR-0184](ADR-0184-a-red-line-says-which-fires-declared.md),
[ADR-0180](ADR-0180-raw-verdicts-are-advisory.md),
[`docs/arch/components/corpus-gate.md`](../arch/components/corpus-gate.md)

## Context

Until this ruling the gate had two buckets, and one real shape fitted neither.

A header field is **blank** in one fire and populated in the other two. The blank fire
**declared** it — `needs_review` set, and a reason naming that field with a withdrawal verb
([ADR-0181](ADR-0181-a-declaration-is-keyed-to-its-field.md)). The two fires that answered
published the **ground-truth** value, measured by the scorer. The shape has exactly one
producer: the two withdrawal branches of `require_mfr_witness_agreement`
(`doc_tools/utils/sustainment_header_trust.py:1322`, `:1343`) — the region witness refusing
to vouch for an uncorroborated reading.

Reported as **instability** it charges the pipeline with a defect it does not have: nothing
disagrees, because one fire wrote nothing. Reported as an **exemption** it charges it with a
defect a warning excuses and leaves on the books. What varied is whether the pipeline was
**willing to vouch**, which is the witness doing its job.

## Decision

**A field blank in one fire with a declared withdrawal, where every other fire published the
ground-truth value, is DECLINED: not unstable and not wrong.**

The four conditions are **conjunctive**. A row qualifies when all of them are measured true
(`classify_declined`, `:1300`):

1. it is **blank in at least one fire** and populated in at least one other;
2. **every blank fire declared a problem with that field** (`needs_review` plus a reason
   naming the field with a declaring verb, never a bare flag);
3. **every other fire published the ground-truth value**, read from the scorer's located
   lists rather than from ground truth directly;
4. **ground truth holds a value for the field at all.**

Any one failing leaves the row exactly where it was — blocking, or exempted by the blank-fire
rule. The classification only ever clears a row when all four hold.

**`strict_verdict` stays beside it, and that is the whole safety of the rule.** It reads
`written_unsettled` (blank rows included), `identity_half_unstable` and
`header_correctness.failing_notices` directly, granting **nothing**, so a declined row stays
red there with no wiring at all — which is why `check_header_correctness` skips only the
blocking/exempted *line* and leaves `failing_notices` intact. The strict verdict is printed
beside the verdict in the same report, always: a reader who distrusts this classification
never has to ask for the unclassified view.

Two conditions close holes. `correctly_absent` is **not a publication**: ground truth holds
no value there, so there is nothing for another fire to have declined. And **positive
evidence is required** that ground truth scores the field (`_gt_scores_field`), because a
pass is read as "named in no failure list" — so a never-scored field would read as published
correctly in *every* fire, and a real instability would be declined on the strength of never
having been measured.

Where identity-half instability is **wholly explained** by declined fields, the identity line
is declined too (`identity_instability_declined`): a declined blank nulls one component, so
no key is formed, so `compute_stability` reports *both* identity fields as moving — right for
an exemption, wrong here, since it charges `doc_id` with a difference it does not have.

## Consequences

- **Measured, by a no-fire recompute**, not by a run: the 2026-11-11 verdict recomputed under
  this rule goes from **3 blocking to 0, with 1 declined, and the strict verdict still
  FAIL**. No fire was taken for this ruling, and nothing here should be read as one — the
  inputs were the stored record of that fire. A recompute against a stored verdict is
  evidence only while it reproduces that verdict; see
  [ADR-0189](ADR-0189-the-published-report-is-the-authority.md).
- The report gains a `declined` list and `declined_lines`, **additive to schema 1**. A
  consumer that does not know the key is unaffected; one that does must **not** read an
  absent key as "nothing declined", because every report written before this rule classified
  these rows as blocking or exempted.
- The `## Declined` section renders **even when it is empty**, saying none: a section that
  appears only when it fires is one whose absence a reader cannot trust. Its lines name the
  notice, the field, which fires declined, which published and the basis — and **no document
  value**, pinned by test.
- The gate can now show `verdict: pass` with `strict_verdict: fail` on the same fire set.
  Anyone quoting a pass quotes both, or quotes nothing.

## Alternatives considered

- **Leave the row blocking.** Rejected: the measurement describes no defect, and a red that
  cannot be cleared by improving the pipeline teaches people to route round the gate.
- **Treat it as an exemption.** Rejected, and reported in its own section instead: an
  exemption says "a defect, but a human was warned"; declined says there is no defect to warn
  about, and conflating them loses the distinction the report exists to draw.
- **Clear the strict verdict too.** Never proposed, and it is the one change this record
  rules out: the strict view granting nothing is what makes the classification safe to make
  at all.
