# ADR-0122 — `extracted_count` and `extracted_total` are two fields, not a fraction

**Status:** built
**Date:** 2026-10-02 (architect ruling) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/utils/dagster_resources.py:211-227` — a code comment on two
`ClassVar` constants, which was the **only** written statement of this ruling before this
record. Pinned by `tests/test_ingest_id_and_domain_ruling.py` part C (`test_c1`, `test_c2`).
**Related:** [ADR-0123](ADR-0123-the-stage-post-is-a-runs-last-act.md) (the post that
carries these two fields),
[ADR-0120](ADR-0120-ingest-id-is-one-canonical-spelling.md) (the id they are posted
against), [the document-to-review-record flow](../arch/flows/document-to-review-record.md)

## Context

`IngestStatusResource.update()` posts a stage transition for an ingest and may carry
`extracted_count` and `extracted_total`. The two names read as a progress fraction, and
nothing in the wire shape says otherwise.

They are not a fraction. At the pin the stage post fills them from two different manifest
facts — `element_count` and the length of `pages` — and the declared units say so:

| Field | Unit |
|---|---|
| `extracted_count` | unstructured **elements** extracted from the document |
| `extracted_total` | **pages** rasterized from the source PDF |

So `extracted_count / extracted_total` divides elements by pages, and **`count > total` is
the normal case** — a one-page notice with 412 elements is healthy. A consumer rendering
"412 of 9" has not found a bug in the extractor; it has mistaken the contract. The same
reading in the other direction is worse: a clamp, a progress bar that saturates, or a
seal on `count <= total` would fire on correct extractions for ever.

The units were real but unwritten. This seam is a **validating no-op** — there is no
transport to Lane 1's ingest store yet — so the log line it emits is its entire observable
surface. Units living only in a docstring are units a reader of the logs does not have.

## Decision

**They are two independent fields in two stated units. They are not numerator and
denominator, and nothing derives a ratio from them.**

- The units are named as **constants**, not prose: `EXTRACTED_COUNT_UNIT` and
  `EXTRACTED_TOTAL_UNIT`. Naming them as constants is what lets the emitted log carry the
  units beside every value it prints, which is the point — the docstring alone would not
  reach the only consumer this seam currently has.
- They are `ClassVar`, not fields. `ConfigurableResource` is a pydantic model, so a bare
  annotated attribute here would be read as a **required config field** and an unannotated
  one is refused outright — either of which breaks the import of `doc_tools.definitions`
  and therefore every asset in this repo, not just this seam.
- `count > total` emits cleanly: **no clamping, no warning, no reordering**, because it is
  correct.
- `update()` validates the two values' carrier (`ingest_id` must be canonical, per
  [ADR-0120](ADR-0120-ingest-id-is-one-canonical-spelling.md)) but derives nothing from the
  counts themselves.

## Consequences

- A consumer that wants a completion signal must get it from the **stage**, not from these
  two numbers. There is no progress fraction on this seam and this record is the place that
  says so.
- The units are pinned twice over: `test_c1` asserts the two constants differ and that one
  names elements and the other names pages; `test_c2` drives `update()` with
  `extracted_count=412, extracted_total=9` and asserts both values **and** both unit
  strings appear in the emitted log. The deliberately inverted pair in that test is the
  record of the misreading.
- The cost is that the two names still *look* like a fraction on the wire. Renaming them is
  not this lane's to do — Lane 1 owns the field names on the route — so the mitigation is
  the units travelling with every value instead of the names being fixed.
- When the transport lands, the units must cross with it or this protection is lost: the log
  line is the carrier today, and a row in another lane's store is not.

## Alternatives considered

- **Put the units in the docstring only.** Rejected at the site, in as many words: this
  seam is a no-op whose log is its entire observable surface, so units in a docstring are
  units the logs do not have.
- **Rename the fields so they stop implying a ratio.** Not taken. The names are Lane 1's
  route vocabulary, and renaming them here would make this repo's post disagree with the
  field the other lane will persist. Not recorded as deliberated beyond that ownership
  line.
- **Seal on `count <= total` to catch an extractor defect.** Rejected by the measurement:
  `count > total` is the normal case for every multi-element page, so the seal would fire
  on healthy documents and teach a reader to ignore it. There is no recorded alternative
  seal; a defect in either number has to be caught by what produced it.
- **Declare them as pydantic fields with defaults.** Rejected for a mechanical reason, not
  a stylistic one: on a `ConfigurableResource` that makes them config, which changes what
  every caller must pass and breaks the definitions import.
