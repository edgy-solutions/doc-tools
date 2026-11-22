# ADR-0130 — a null row value is excluded from scoring, and says nothing about the document

**Status:** measured
**Date:** no ruling date is recorded for this row; the mechanism the decision depends on
shipped 2026-10-10 (`5f82b1a`) · recorded 2026-11-18
**Deciders:** this lane, recording a property of the corpus scorer in the field catalogue. No
individual ruler is recorded for the row-value half.
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `registry/export_field_catalogue.json:634` (the `notes` of `row.extracted_value`);
the exclusion itself at `scripts/pcn_score.py:644` (row values) and `:496-497`, `:580` (the
header `pending` status, documented at `:75-81`); the status that *does* score an absence at
`:428-463`, measured in `tests/test_pcn_score_headers.py:400-440`
**Related:** [ADR-0128](ADR-0128-evidence-ref-is-served-as-is.md),
[ADR-0183](ADR-0183-declined-is-the-third-bucket.md),
[ADR-0189](ADR-0189-the-published-report-is-the-authority.md)

## Context

`row.extracted_value` is nullable, and a reader looking at a scored corpus run has two
questions about a null: does it count against the score, and does it mean the document did not
state the value? The two answers point in opposite directions, and conflating them is the
failure this record exists to prevent.

The concrete case is measured. Before 2026-10-10 the only way ground truth could declare *the
document states no value for this field* was `value: null`, which reports `pending` and is
**excluded from the score in both directions**. So a run that **invented** a last-time-buy date
for a notice that states none scored **exactly as well** as a run that correctly wrote nothing.
The one case the instrument had to stay silent about was the fabrication. TI's
PCN#20210316000 is the real case: a die-coat qualification change announcing no discontinuation,
which prints a proposed first-ship date in the same block where a last-time-buy would go — the
bait adjacent to where the answer belongs, which is the shape that produces a confident wrong
date.

The same collapse recurs on the read side, in a different place and with the same shape. A
**ruled** None and a **missing** None are the same value at a branch, so a mechanism that
inspects the value cannot tell a deliberate blank from a field nobody read.

## Decision

**A null row value is excluded from corpus scoring, and a null says nothing about whether the
field was in the document. A reader cannot infer absence from it.**

- **Excluded, both ways.** Row values that are null are dropped before the set comparison
  (`pcn_score.py:644`). On the header side the equivalent state is `pending` — ground truth has
  not established the value — which is *"NOT SCORED, in either direction"* and is left out of
  every total. Scoring against a guess would manufacture a result; reporting it silently as a
  pass would hide the gap, so it is printed as pending and excluded.
- **Epistemically empty.** A ruled None is indistinguishable from a missing one, so a null in
  this field does **not** mean the field was absent from the document. It means no value was
  written — by a reader that found nothing, by a reader that was never run, or by a ruling that
  says there is nothing to find. The field does not record which.
- **Absence, when it is a finding, is declared separately and positively.** `expect_absent: true`
  plus a `_why` is the state that scores it: nothing written is `correctly_absent`, a **pass**
  counted apart from `exact` because there was no value to have matched; a value written is
  `hallucinated`, a **failure**. That branch sits **before** the `expected is None` check, which
  would otherwise swallow it as `pending` — the two carry no value and mean opposite things.
- **Therefore a null is never evidence of anything.** To claim the document states nothing, the
  claim is declared; to claim the field is unestablished, the null stands and the row is out of
  the score. Nothing may be read off the null itself.

## Consequences

- **The score is honest about its own coverage at the cost of being smaller.** A corpus of rows
  whose values are null measures nothing, and the denominator says so rather than crediting a
  pass. The hazard is the other way round: adding a notice whose field is genuinely empty,
  declared `value: null`, adds a row to the corpus and tests nothing — *a widening that looks
  like coverage*. Build the mechanism before the data, or the data is a blind spot.
- **A consumer of the served row cannot distinguish the three cases**, and no key tells it apart
  from outside. That is the live cost of the collapse, and it is a limit of the contract rather
  than a defect in a particular run; the catalogue entry states it so a consumer does not infer
  absence and act on it.
- The epistemic claim must not be overstated in the other direction either: a null does **not**
  mean the field *was* in the document. It licenses no inference at all.
- Nothing is silently excluded. `pending` fields are printed by name beside the totals
  (`pcn_score.py:800-802`), so a reader can see the size of what was not scored. An unobserved
  header section prints **NOT SCORED** with its reason rather than zero failures, because a
  header score of "0 failures" over a run that measured no headers is the exact shape of a guard
  that is green because it never ran.
- Because a declared absence is a pass counted apart from `exact`, the parts and header totals
  stay comparable across pins only when the declarations are held constant — a new
  `expect_absent` declaration changes what the score covers, not only its value.

## Alternatives considered

- **Score a null as a miss.** Rejected by the mechanism's own documented reasoning: ground truth
  may not have established the value — the live case is a field where the text layer and the
  witness disagree and the page has not been read directly — and scoring it against a guess
  manufactures a result.
- **Score a null as a pass.** Rejected for the opposite reason: it is the pre-2026-10-10
  behaviour, and it is exactly what let a fabricated date score as well as a correct silence.
- **Distinguish a ruled None from a missing one in the served field** — a second key, or a
  sentinel value. Not recorded as considered for this field. The served contract is closed and
  exhaustively enumerated ([ADR-0128](ADR-0128-evidence-ref-is-served-as-is.md)), so such a key
  would be a change to the pinned shape with Lane 1, not a local addition.
