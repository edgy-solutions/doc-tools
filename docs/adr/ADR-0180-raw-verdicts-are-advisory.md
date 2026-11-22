# ADR-0180 — Raw verdicts are advisory and never the verdict

**Status:** built
**Date:** 2026-10-26 (ruled) · recorded 2026-11-18
**Deciders:** the architect — the code records it as "the 2026-10-26 ruling" and names no
relay; do not read a name into it
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `scripts/pcn_corpus_gate.py:2007` (and the rationale at `:255-267`,
`unstable_raw_rows` at `:338`, the report key at `:2197`) — a code comment, which was the
**only** written statement of this ruling before this record
**Related:** [ADR-0182](ADR-0182-the-written-arm-compares-canonical-forms.md) (the arm that
does block), [ADR-0183](ADR-0183-declined-is-the-third-bucket.md),
[ADR-0189](ADR-0189-the-published-report-is-the-authority.md),
[`docs/arch/components/corpus-gate.md`](../arch/components/corpus-gate.md)

## Context

The gate has two header instruments and they measure different things.

The **plain-mode** run (`scripts/pcn_header_agreement.py` over the three fire logs) reads
what the header model **returned**, before any downstream trust logic touches it — eight
`RAW_FIELDS`, the four `*_source` companions among them. The **written** comparison
(`compare_written_headers`, `:474`) reads the `written_header` block each fire recorded in
its own corpus JSON: what the pipeline actually **published** after witness supply,
document-wins and refusal.

Before the ruling, the plain run's exit code contributed to the verdict. That blocked pins
on the wrong fact. A raw disagreement is the model rotating between forms; the question the
gate exists to answer is whether the pipeline silently **wrote** one of two values. Those
come apart in practice: a field whose raw reads were identical in all three fires can be
written three different ways, and a field whose raw read takes a declared distractor every
time can be published correctly every time, because the supplier is doing the work.

Replaying with `--written` is not the fix, and the comment at `:255-267` records why: the
replay cannot build the vision witness the product consults, so the degraded notice comes
back `WITNESS_DECLINED` and its written fields read **NOT MEASURED** — which fails the gate.
A `--written` comparison would measure the pre-witness trust logic and newly block a notice
on an instrument gap.

## Decision

**A raw verdict is advisory. It is reported and it never blocks a pin.**

- Raw DISAGREE / BLANK notices feed the report's **`unstable_raw`** block (`:338`, `:2197`) —
  an unsteady reader kept visible — and no blocking list.
- The plain run's **exit code no longer appears** in the verdict expression (`:2129-2140`).
  What replaced it is the written arm plus the identity arm.
- Two raw conditions **still block**, because they are not value disagreements: a notice
  **ABSENT** or **NOT MEASURED** in the plain run (the instrument could not measure), and an
  unparseable crash. There is no declaration exemption for either.
- The plain run is **kept**, not deleted: the raw rotation is worth seeing, and the recorded
  values need no replay, no S3 and no log parsing.

**`strict_verdict` grants nothing, and that is the entire safety** of this arm's demotion as
it is of the exemption rule and the declined rule ([ADR-0183](ADR-0183-declined-is-the-third-bucket.md)).
It is computed from `written_unsettled` (blank rows included), `identity_half_unstable`, the
void reasons and every header-correctness failure, with no exemption of any kind, and it is
printed beside the verdict in the same report. A reader who distrusts an advisory
classification has the unclassified view in hand without asking for it.

## Consequences

- A red raw reading no longer blocks a merge, and **that is a deliberate loss of teeth** on
  one measurement: a model that rotates forms while the trust logic repairs every one of them
  will not red the gate. It will show in `unstable_raw`, where somebody has to read it.
- A claim about model behaviour must say which instrument produced it. Raw and written are
  cited separately, by name — see [ADR-0189](ADR-0189-the-published-report-is-the-authority.md),
  where a conclusion drawn from the wrong one came out exactly backwards.
- A raw-mode finding about a `*_source` field cannot be carried forward as a predicted red:
  the written tuple holds no `_source` companion at all.
- `unstable_raw` is derived from the plain run only, so it is empty whenever that run could
  not parse — an empty block is not evidence of a steady reader.

## Alternatives considered

- **Keep the raw exit code in the verdict.** Rejected by the ruling: it blocks on
  pre-trust-logic behaviour, which is not what the pipeline publishes.
- **Replace the plain run with a `--written` replay.** Rejected on the measured ground
  recorded at `:255-267`: the replay cannot build the vision witness, so it returns NOT
  MEASURED for the degraded notice and would newly block it on an instrument gap rather than
  on a value.
- **Delete the plain run entirely.** Rejected: the raw disagreement is the only visible
  evidence that the reader underneath is unsteady, and it costs nothing to keep — it parses
  logs the fires already wrote.
