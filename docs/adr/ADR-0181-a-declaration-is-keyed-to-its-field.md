# ADR-0181 — A declaration must be keyed to the field under test

**Status:** built
**Date:** 2026-10-27 (architect's ruling; the verb half ordered 2026-11-14) · recorded
2026-11-18
**Deciders:** the architect
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `scripts/pcn_corpus_gate.py:805-835` (THE DECLARATION RULE), `:879-902` (KEYED TO
THE FIELD UNDER TEST), `:926-967` (the verb list, 2026-11-14), with
`_field_declaration_basis` at `:982` and `header_declaration_for_field_in_fire` at `:1009` —
code comments, which were the **only** written statement of this ruling before this record
**Related:** [ADR-0183](ADR-0183-declined-is-the-third-bucket.md),
[ADR-0184](ADR-0184-a-red-line-says-which-fires-declared.md),
[ADR-0180](ADR-0180-raw-verdicts-are-advisory.md),
[`docs/arch/components/corpus-gate.md`](../arch/components/corpus-gate.md)

## Context

The gate's exemption is **earned by the product declaring the problem**, not granted by the
gate deciding to look away. A notice flagged `needs_review` goes to a human, so a
disagreement there is a known, handled condition; a notice that disagrees with
`needs_review` false means the pipeline silently wrote one of two values with no flag, which
is the defect.

Consumed as a **document-level** flag, that rule collapses. Two measurements say why:

- `needs_review` went from 3/4/3 of ten notices on v0.2.1 to **10 of 10** on v0.2.2, because
  the `doc_id` precedence ruling makes the plugin narrate a `doc_id` reason on **every**
  notice (`doc_tools/plugins/sustainment.py:1812`). A flag about `doc_id` — which is not a
  scored header field — then bought a notice an exemption for `mfr`, `pub_date` and
  `doc_level_ltb_date`.
- A **degraded text layer sets the flag unconditionally and permanently**, so the one notice
  with a measurably wrong header held an exemption no measurement could revoke.

The second half is a verb problem, found on 2026-11-14. The matcher accepted exactly one
phrasing — `header.<field> refused` — while the rule it implemented was "a reason naming the
field". The product has another way of saying a field was not published, and the one it uses
on a withdrawn manufacturer is **`withdrawn`**
(`doc_tools/utils/sustainment_header_trust.py:1322` and `:1343`, the two branches of
`require_mfr_witness_agreement` at `:1260`). That reason names the field, names the problem,
and was invisible to the gate: a **declared** withdrawal read as an undeclared silent write.

## Decision

**A declaration is a `needs_review` flag plus a reason that names the field under test with
a verb saying the field was not published.** A bare flag is not an answer to the question the
gate asks.

- The decision is made per `(notice, field)`. One notice may have one field exempted and
  another blocking, and each gets its own line.
- Naming the field is **necessary and not sufficient**. The same `header.<field>` prefix also
  carries narrations that declare nothing — corroborated, readings agree, supplied, taken
  from, kept from, citation replaced, recovered — and the first of those is the *opposite* of
  a declaration. Accepting them would exempt a field **because** it was corroborated, and
  "taken from the text layer" is narrated routinely, so a blanket prefix match would hand
  nearly every field an exemption on nearly every notice.
- Two markers are **header-wide** by construction and exempt every field: `header pass
  failed` (the pass raised, nothing was extracted) and `region witness DISABLED`
  (`_HEADER_WIDE_DECLARATION_MARKERS`, `:903`).
- Field and verb must appear in the **same reason**, not across the list, or a reason about
  one field would lend its verb to another.
- One trailing `_source` is stripped before matching (`_declaration_field_base`, `:914`): the
  companion is the citation for the same field, and the product never narrates a refusal of
  the companion by name.
- Matching is `header.<field>` with a non-word boundary, so a reason about a `*_parent`
  field does not exempt the field it is derived from.
- `needs_review` is still **required**: a narrated reason on a document nobody is told to
  review is not a declaration.

## Consequences

- The exemption got narrower in both axes, and the gate went **redder** on the day of the
  ruling. That is the intended direction: the previous reading was granting exemptions no
  measurement could revoke.
- A verb is added to the list **only together with the producer line that emits it**. The
  list is deliberately a closed vocabulary rather than a pattern, so widening it is a visible
  edit next to a citation.
- Field names are shared vocabulary — `doc_tools/utils/witness_regions.py` declares the same
  keys `scripts/pcn_ground_truth.json` scores — so there is no alias table here and none may
  be added.
- `"could not be located"` is deliberately **not** a marker. Its only emitter is a refusal
  clause, so it appears only inside a `header.<field> refused: …` reason about one field,
  which the refusal shape already covers; re-adding it header-wide would re-widen the
  exemption to every field.
- The failure is reported either way, and `strict_verdict` — which grants no exemptions —
  counts it regardless.

## Alternatives considered

- **Read `needs_review` alone, as before.** Rejected on the measurement above: it is
  document-level, it is set unconditionally by a degraded text layer, and the `doc_id`
  narration sets it on all ten notices.
- **Add a structured per-field declaration field to the product's output.** Not taken: the
  product narrates, and a structured field would mean two representations of the same fact to
  keep in step. The declaration is therefore matched as a substring of `review_reasons`, with
  the vocabulary written out beside the producer line that emits each phrase.
- **Accept any reason naming the field.** Rejected on 2026-11-14, with the list of
  publication narrations as the evidence: it would re-open by verb exactly the hole the
  per-field keying closed by name.
