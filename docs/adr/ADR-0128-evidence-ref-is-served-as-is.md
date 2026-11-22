# ADR-0128 — `evidence_ref` is served as is, and nothing else is served

**Status:** accepted + built
**Date:** 2026-10-21 and 2026-10-28 (architect rulings; the null-bbox half is ruling 205) ·
recorded 2026-11-18
**Deciders:** the architect, relayed by Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `tests/fixtures/cortex_bff_extraction_pin.json:16` (the pinned `EvidenceRef`
schema — **the authority for this record**). Producers:
`doc_tools/utils/leaf_read.py:362` (`wire_evidence_ref`) and
`doc_tools/utils/sustainment_merge.py:245` (`_row_wire_evidence_ref`). Sealed by
`tests/test_export_field_catalogue.py:235` and `:311`, and
`tests/test_leaf_read.py:493-555`.
**Related:** [ADR-0126](ADR-0126-the-leaf-read-output-shape.md),
[ADR-0230](ADR-0230-the-batch-column-map-seam.md) (the catalogue-vs-contract seam this pin
covers), [ADR-0130](ADR-0130-a-null-row-value-is-excluded-from-scoring.md)

## Context

This is the record a consumer gets wrong, and the way it goes wrong is by **addition**. A review
card wants to draw a box on a page. doc-tools' internal evidence ref is rich — nine keys on the
leaf-read side, carrying the element id, the element index, the element type and the layout
divisor the fractions were computed from. The review rows carry more still: `text_layer_bbox`,
`text_layer_page`, `text_layer_page_dims`. A consumer that needs page dimensions, a unit name or
a quality score can see all of it in the manifest and reasonably assume that some of it is on
the wire, or that it could be added cheaply.

It cannot. The served schema is **closed** (`additionalProperties: false`), and the failure is
not a graceful one: an extra key is a **422** at Lane 1's BFF, and cortex's candidate reader
**drops the whole list** when one item is invalid. One surplus key on one row therefore costs a
reviewer every box on the card, not one.

The second half of the trap is how absence is expressed. The reader **discriminates on
presence** — it asks whether a key is there. So a field that is sometimes meaningless cannot be
served as `null`: a `null` is a key that is present, and the reader would treat it as an answer.

## Decision

**doc-tools emits `wire_evidence_ref` and the BFF serves it as is: `{page, bbox, note?}`. No
renaming, no synthesising, no page dims of its own. Nothing else is served.**

- `bbox` is **page fractions** `[x0, y0, x1, y1]`, origin top-left, `0 <= x0 < x1 <= 1` and
  `0 <= y0 < y1 <= 1`. Fractions are unit-free, so there is no space key and the same numbers
  mean the same thing everywhere `evidence_ref` appears. Producers convert layout pixels and
  word-layer points **before** writing, through the one conversion
  (`provenance.to_page_fractions`).
- A **null `bbox` means "on this page, no box"** (ruling 205). It is not a missing ref: the page
  is the locator and the box only refines it, so the card jumps to page N and labels it. `bbox`
  is **present and null** here, never omitted: an absent key and a null one are the same to a
  reader using `.get()` but not to a reader that discriminates on presence, so the producer
  always emits the key (`tests/test_leaf_read.py:510`).
- **`page` may not be null.** A ref with no page yields **no `evidence_ref` at all** — which is
  also the derived-field case the same ruling settles: a derived value is on no page, so a
  `page` would be a fiction.
- **Nothing else is served, exhaustively: no `bboxes`, no `page_dims`, no `units`, no
  `quality`.** This is a negative list, not an example of one. The richer ref stays in the
  manifest, where no shape contract binds it, and `wire_evidence_ref` is a **projection** of it
  — never a rename, because a rename is where a key quietly stops being populated.
- **Absence is an omission, never a null.** `note` is omitted when there is nothing to say, and
  the pinned schema gives it no null branch (`pattern: "\\S"`), so a null `note` is invalid. The
  seal states the rule in the shape it is most often broken: *"it must be OMITTED, never
  nulled"* (`tests/test_export_field_catalogue.py:322-323`). The one exception is `bbox`, whose
  null is itself a positive statement.

## Consequences

- A field doc-tools would like to add to the card cannot be added here. It goes somewhere else
  on the row, or the pinned contract is re-taken with Lane 1 — not widened locally.
- The pin fixture, not this record and not the producer, is the authority. It carries its own
  `_pin` block (source path, ref, `sha256_of_whole_file`, date taken), and
  `tests/test_export_field_catalogue.py:431` refuses a pin that does not declare those. Re-take
  the pin before asserting that the platform's shape changed.
- The pin is an **extract**, covering the catalogue-versus-contract hop only. That the platform
  still serves this shape is **not** sealed here, and the fixture says so.
- Two defences are cheap and both are kept: the projection drops surplus keys at the producer,
  and the seal fails the suite if one survives. Neither alone would catch a new key added to the
  internal ref by a second writer.
- The projection copies the bbox list rather than aliasing it, so a consumer that mutates what it
  was handed cannot rewrite the manifest block it came from (`tests/test_leaf_read.py:504-507`).

## Alternatives considered

- **Serve the internal ref and let the consumer ignore what it does not need.** Refused by the
  mechanism rather than by taste: the closed schema makes a surplus key a 422, and cortex drops
  the whole candidate list on one invalid item.
- **Drop a ref that has a page but no box.** This is what the projection did in its first cut,
  and ruling 205 reversed it: it threw away the half that works, since a candidate with a page
  and no outline is strictly more locatable than one with no ref at all.
- **Name the coordinate space in a `units` key.** Rejected with its reason recorded in
  `leaf_read.py:172-177`: the space needed naming only because magnitudes were ambiguous — row
  geometry arrives in image pixels on one notice and PDF points on another. A fraction is
  self-describing, every value is `<= 1`, so a box in the wrong space is visible rather than
  silent, and the key becomes dead weight on a closed schema.
- **Serve `page_dims` so the consumer can recover pixels.** Rejected: fractions need no page
  size, no DPI and no PDF to place. The divisor is kept internally (`layout_width`), so the
  layout pixels remain recoverable on our side without crossing.
