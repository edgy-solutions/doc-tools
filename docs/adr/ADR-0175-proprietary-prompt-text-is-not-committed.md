# ADR-0175 — proprietary prompt text goes through `PROMPT_SOURCE`, not the repo

**Status:** accepted
**Date:** no ruling date is recorded; carried in `AGENTS.md` as standing guidance · recorded
2026-11-18
**Deciders:** `AGENTS.md` §Manufacturing Overlay 4, this repo's standing guidance — no
individual ruling is on record
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:97` (§Manufacturing Overlay 4)
**Related:** [ADR-0174](ADR-0174-an-overlay-field-is-data-not-code.md) (the same problem for
*fields*), [ADR-0170](ADR-0170-prompts-are-files-and-the-file-path-is-production.md),
[ADR-0171](ADR-0171-production-does-not-depend-on-langfuse.md)

## Context

[ADR-0174](ADR-0174-an-overlay-field-is-data-not-code.md) keeps proprietary *field* names and
descriptions out of the tree by loading them from a secret spec. The obvious next move is to
treat proprietary *instruction text* the same way — add it to the overlay, or inline it into
`prompts/*.md` behind a conditional.

Both are wrong, and the failure mode is the same one in two costumes. Prompt text inlined into a
committed file is in the history permanently; there is no editing it out of a transcript or a
tag that has shipped. Prompt text smuggled into the overlay spec turns a field descriptor into a
prompt store, so the thing that declares extraction-and-persistence for one field starts
carrying the instructions for a whole pass, and neither the overlay tests nor the drift check
cover it.

The two concerns also differ in what they need. A field needs a schema injection and a
persistence mapping. Text needs a source, a version, and a review route — which the prompt
machinery already has.

## Decision

**Proprietary prompt text is a separate concern from proprietary fields. It travels by the
`PROMPT_SOURCE` mechanism, not by the committed prompt and not by the overlay spec.**

- `AGENTS.md:97` states it directly: proprietary *prompt text* is a separate concern — use the
  `PROMPT_SOURCE` path, not the committed prompt.
- The environment variables involved, by name only and with no value recorded anywhere in this
  repository: `PROMPT_SOURCE` selects the source, `LANGFUSE_PROMPT_LABEL` selects the version on
  the non-file source. `MANUFACTURING_OVERLAY_SPEC` is **not** the route for text; it is the
  route for field descriptors, and the separation is the decision.
- The committed `prompts/*.md` files stay the canonical public text. Nothing proprietary is
  inlined into them, conditionally or otherwise.
- The mechanism is already used for non-proprietary text that would otherwise be frozen in code:
  `doc_tools/utils/witness_regions.py:312-319` keeps the per-region vision questions in
  `prompts/sustainment_read_region.md` rather than in the module, *"so they ship through the
  ordinary prompt path — git-committed canonical text, editable in Langfuse under
  `PROMPT_SOURCE`"*. The pattern this record relies on is in use; the proprietary case is not.

## Consequences

- No proprietary wording enters the tree or the commit history, and the public prompts remain
  reviewable as what they are.
- **The status is `accepted`, not `built`, and the reason is a real tension with
  [ADR-0171](ADR-0171-production-does-not-depend-on-langfuse.md).** Measured at the pin,
  `doc_tools/plugins/base.py:111-132` implements exactly two sources: `file` (the committed
  prompt) and `langfuse` (the live label). There is no third. So the only non-file source is the
  one [ADR-0171](ADR-0171-production-does-not-depend-on-langfuse.md) refuses for production and
  [ADR-0170](ADR-0170-prompts-are-files-and-the-file-path-is-production.md) treats as a stop
  condition for a measurement. Proprietary prompt text therefore has a named route and, today,
  no route that a production deployment or a gated measurement may actually take.
- That tension is the record's main content: it is a decision in force whose implementation is
  **absent**, not partial. A deployment needing proprietary wording now would have to either run
  on the refused source or inline the text — and inlining is the irreversible one.
- The obvious missing piece is a file-backed secret source: a mounted prompt directory or spec,
  parallel to the overlay's secret, selected by `PROMPT_SOURCE` and therefore still committed-by-
  reference and still checkable. **It is not recorded as considered anywhere in the tree.** It is
  named here as the shape of the gap, not as a decision.
- Keeping the concerns separate costs a second mechanism: an operator configuring a deployment
  with both proprietary fields and proprietary wording sets two unrelated variables and debugs
  them separately.
- The drift check ([ADR-0172](ADR-0172-the-drift-check-reads-the-runtimes-own-var.md)) walks
  `prompts/*.md`. Any text that does not live there is outside its coverage by construction,
  whatever source eventually serves it.

## Alternatives considered

- **Inline proprietary text into the committed prompt, perhaps behind a marker or a
  conditional.** Rejected by `AGENTS.md:97`. It is also the one choice that cannot be undone:
  committed text is in the history and in every shipped image layer.
- **Carry prompt text in the overlay secret spec alongside the field descriptors.** Rejected by
  the separation this record states. The overlay spec's schema
  (`doc_tools/plugins/manufacturing_overlay.py:177-205`) parses field descriptors; it has no
  text member, and giving it one would put prompt versioning inside a field registry.
- **Add a file-backed secret prompt source so the ruling has a usable implementation.** Not
  recorded as considered — see the Consequences above. Writing it here as a decision would be
  inventing one.
