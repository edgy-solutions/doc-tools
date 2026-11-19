# ADR-0131 — the wire half validates a steward's row edits against the server's batch

**Status:** built
**Date:** 2026-10-10 (architect ruling) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `tests/fixtures/cortex_bff_extraction_pin.json:394` (the pinned `RowEdits`
schema), `:286` (the sibling `HeaderEdit`); the catalogue entries at
`registry/export_field_catalogue.json:994-1047` and the `row_edit_counts.*` entries that
follow; sealed by `tests/test_export_field_catalogue.py:126`, `:152` and `:168`
**Related:** [ADR-0128](ADR-0128-evidence-ref-is-served-as-is.md),
[ADR-0230](ADR-0230-the-batch-column-map-seam.md),
[ADR-0111](ADR-0111-a-disputed-value-is-a-packet-not-an-edit.md)

## Context

A steward approving a grouped review does not only say yes. They add rows the extraction
missed, correct rows it got wrong, and delete rows that are not parts at all, and the approval
carries those edits. The rows they are editing are the rows **the server authored** — the batch
doc-tools produced and the BFF served
([ADR-0128](ADR-0128-evidence-ref-is-served-as-is.md)).

The failure mode is a payload that refers to rows that do not exist, or to fields the batch does
not have: a stale card, a second tab, a client that renumbered its rows, a replayed request. If
such a payload is accepted at the edge and only rejected later, the rejection happens **inside
the workflow** — after a durable step, with a half-applied correction to unwind and an error a
steward sees as a failed approval rather than a bad request.

There are therefore two places the same rules can live: the wire, and the workflow. The ruling
of 2026-10-10 puts them in both, and this record is about which one is which.

## Decision

**The rules are stated twice, on purpose. The workflow's `steward_correction.validate_row_edits`
restates every rule against the server-authored batch; the wire half is the pinned `RowEdits`
schema, so a bad payload is a 422 before it reaches Restate.**

- The payload is three arrays — `added`, `corrected`, `deleted` — each defaulting to `[]`, so
  an approval that edits nothing carries a well-formed, empty object rather than an absent one.
- The container is **closed** (`additionalProperties: false`): an unknown edit key is a 422, not
  a silently ignored instruction. A silently ignored edit is the worst outcome available here,
  because the steward has already been told their correction was accepted.
- The reference point for every rule is **the server-authored batch**, not the payload's own
  internal consistency. A row index, a field name and a prior value are valid only against the
  batch the server served.
- `RowEdits` is also the **document_promotion** wire — carried on a `promoted` decision and
  server-flagged by `IAGENT_PROMOTION_ROW_EDITS` (named, never valued) — so one shape covers
  both routes rather than a second, drifting copy.
- `HeaderEdit` is the sibling for header corrections, on the **same wire and the same flag**,
  and its `field` is a **closed enum** of three header fields. A header correction is therefore
  not a free-text patch.
- `RowEditCounts` is the third container in the pin: **how many of each edit a steward's
  correction carried**. It is catalogued beside `RowEdits` and seals as the same kind of thing,
  a count rather than a payload.

## Consequences

- A steward's bad payload fails as a **422 at the edge**, with nothing durable written and
  nothing to unwind. That is the whole benefit, and it is bought with a duplication: the same
  rules exist on the wire and in the workflow, and they can drift apart. The ruling accepts that
  cost explicitly — the workflow *restates* the rules rather than relying on the edge — because
  an edge check is not a safety property of the workflow, which can be reached by another
  caller.
- **The validator is not in this repo.** `steward_correction.validate_row_edits` is the
  platform's; what is built here is the **pinned shape** and the catalogue that seals our field
  names against it. doc-tools' stake is that these are the rows it authored, so a record of the
  contract belongs on this side even though the enforcement does not.
- **What this record evidences is bounded by the pin.** The fixture is an **extract** covering
  the catalogue-versus-contract hop only: `added`, `corrected` and `deleted` are `$ref`s to
  `AddedRow`, `CorrectedRow` and `DeletedRow`, and **those three schemas are not in the
  extract**. So the three arrays, their defaults and the closed container are pinned here; the
  per-item rules are not, and the authority for them is the platform's validator. Re-take the
  pin with those schemas included before citing an item-level rule from this tree.
- The catalogue's eleven `steward_edit` entries carry `served_by: null` by design — they are a
  different route from `GET /ingest/{ingest_id}/extraction`, and the seal at
  `tests/test_export_field_catalogue.py:126` allows exactly that combination rather than
  treating it as a missing value.
- A new edit kind is a change to the platform's schema and then to this pin and the catalogue,
  in that order. It cannot be introduced from this side.

## Alternatives considered

- **Validate only in the workflow.** Rejected by the ruling: the rejection would then land after
  a durable step, and a malformed request would read to the steward as a failed approval. The
  workflow check is kept, so this is an addition rather than a replacement.
- **Validate only on the wire.** Not viable, and the ruling says why by restating the rules in
  the workflow: the edge is one caller's path, and a rule that protects the batch has to hold
  wherever the correction arrives from.
- **An open edit object, ignoring unknown keys.** Refused by `additionalProperties: false`. The
  reason is the same one that closes the served `EvidenceRef`
  ([ADR-0128](ADR-0128-evidence-ref-is-served-as-is.md)): an unknown key is either a client bug
  or a newer client, and both need to be visible rather than dropped — here with the extra cost
  that the dropped thing is a human's correction.
- **A separate wire for document promotion.** Rejected by the ruling, which puts promotion on
  the same wire and the same flag. Two shapes for one payload is how one of them stops being
  updated.
