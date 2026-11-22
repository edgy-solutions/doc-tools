# ADR-0124 — header identity precedence: the text layer has primacy

**Status:** built + measured
**Date:** 2026-10-24 (architect ruling; narrowed the same day) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `tests/test_header_identity_precedence.py:1-50` (the ruling, verbatim, as a test
docstring) and `tests/test_doc_id_text_layer_arm.py:1-15`; implemented at
`doc_tools/plugins/sustainment.py:1794-1826` (`doc_id`), `:2034-2056` (`mfr` and the dates,
via `sustainment_header_trust.apply_text_layer_primacy`, `sustainment_header_trust.py:959`)
and `:2058-2087` (clause 3); the narrowing and its measurement are at
`sustainment_header_trust.py:908-936`.
**Related:** [ADR-0127](ADR-0127-a-title-signal-has-an-order-not-a-score.md),
[ADR-0182](ADR-0182-the-written-arm-compares-canonical-forms.md),
[ADR-0183](ADR-0183-declined-is-the-third-bucket.md) (the gate that consumes `needs_review`)

## Context

A notice's identity fields — `doc_id`, `mfr`, `pub_date`, `doc_level_ltb_date` — have two
possible readers: the document's own text layer, read by a deterministic arm, and the
header (model) pass. They disagree, and before this ruling **the model won on a
disagreement** and the disagreement was merely reported.

The reason for that is not stupid, and it is why this record is worth having.
`needs_review=True` is consumed by the corpus gate as an **EXEMPTION**, so a flag raised on
an *unscored* identity field can exempt a notice whose *scored* fields are wrong: flagging a
disagreement buys a human a look at the right thing and sells the gate a reason to stop
looking. Against that stood what the two readers are — a notice number is **printed once**
and does not sample, while the model's `doc_id` came back different across fires on
byte-identical input.

## Decision

**A text-layer value, when the arm yields one, IS the written value. The header pass
corroborates it.**

- **Clause 1.** A disagreement **keeps the text-layer value** and sets `needs_review` with
  **both** values in the reason — naming only the winner leaves a human re-deriving what
  was discarded.
- **Clause 2.** The model pass fills only what the text layer did not yield, and every
  model-filled field marks `needs_review=true`. Clause 2 **flags; it does not blank**.
- **Clause 3.** A model `AbortError` with a text-layer value present is **not a failure of
  the field**. The pass failure stays recorded — it bounds the rest of the extraction — but
  on its own it reads as "no identity was extracted", which is measurably false. So the
  survivors are named explicitly, the casualties as **absent, not defaulted**, never as a
  filename.
- **Clause 1 reverses what the arm did before.** The note that stood at the `doc_id` site
  said, in as many words, *"Disagreement is REPORTED and does NOT force review"*, and two
  tests in `tests/test_doc_id_text_layer_arm.py` asserted exactly that. The ruling of
  2026-10-24 reversed both. **The reversal is written into those two tests rather than
  edited out of them**, because the old behaviour's reason has not become mistaken — it has
  become a cost the ruling accepts.
- **Primacy is gated OFF on a measured-degraded text layer.** A damaged layer corroborates
  itself and cannot be trusted to *spell* a name, so primacy there would promote a
  misspelling from "refused" to "authoritative"; there the model's reading stands.
- **Primacy grants no exemption from sourcing.** It runs *after* the echo refusal, so a
  label-echoed model value is not re-reported as a disagreement, and *before* the unsourced
  refusal, so a value it writes is corroborated like any other.

### The narrowing, measured the same day

Clause 1 as first shipped made **any** text-layer reading primary. One corpus fire (image
`39b47e6`) measured what that does to the one field whose arm is **name-shaped** rather than
pattern-bound: on two of the ten corpus notices the `mfr` arm took a page-furniture heading
as the manufacturer, each displacing a manufacturer name the page prints verbatim. **The
corpus gate read `clean: true` over both**, because only three of the ten notices carry
`mfr` ground truth. The heuristic cannot be tightened into a fix — uniqueness is that arm's
safety, a stricter predicate refuses real names, a looser one refuses the page — so the
ruling was narrowed where the measurement pointed, and not further:

- `mfr` is primary **only on a gazetteer match**. An unmatched candidate corroborates and
  may dissent, never displaces; a disagreement there keeps the **model's** value and spends
  a `needs_review` with both readings named.
- `doc_id` and the two dates keep clause 1 as written: their arms are **pattern-bound** (the
  `doc_id` arm requires a notice-number code and a digit), so a heading cannot satisfy them
  the way a name-shaped predicate is satisfied by any capitalised word. The defect does not
  transfer, so the narrowing does not either.

## Consequences

- An identity field is now reproducible where an arm exists: a notice re-run on identical
  bytes gets the same `doc_id`. **But the gate pays for it** — every flag this raises on an
  unscored field is an exemption the corpus gate honours, so a green gate beside a flagged
  notice is an expected shape, not a contradiction. The trade is the architect's, made
  knowingly, and recorded here and in the two reversed tests.
- The two dates have **no arm**. They get clause 2's flag and clause 3's accounting, but no
  text-layer primacy, because writing a `pub_date` arm is its own measured step and not a
  drive-by. Until it exists, "text-layer primacy" is true of `doc_id` and `mfr` only.
- A per-field instrument (`header_identity_arms`, `doc_id_arm`) records origin, both values,
  agreement and whether primacy was gated off. The corpus gate has no header ground truth
  for `doc_id`, so that instrument is the only way this arm is observable at all.

## Alternatives considered

- **Keep the model primary and only report disagreements.** This *was* the behaviour and was
  reversed; its argument — `needs_review` is a gate exemption — is preserved, still true.
- **Make every text-layer reading primary.** Shipped, then narrowed within the day by the
  measurement above. Recorded as an alternative because it was tried, not imagined.
- **Make primacy skip the unsourced-header refusal.** Rejected by the ordering argument
  above: a value that skips the citation check is a fabrication with a winner's badge.
