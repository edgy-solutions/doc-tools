# ADR-0125 — before the title read, a pdf runs parse and text layer only

**Status:** built
**Date:** 2026-10-21 (leaf ruling, item 4) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/utils/leaf_read.py:3-5` — a module docstring, which was the **only**
written statement of this ruling before this record; the read is dispatched at
`doc_tools/components/document_parser.py:712-749`. Pinned from both sides by
`tests/test_user_drop_runs_parse_only.py`
(`test_the_user_drop_parse_asset_takes_only_s3`,
`test_the_parse_module_dispatches_no_extraction_pass`,
`test_the_title_read_needs_no_resource_so_the_lift_stays_inside_the_invariant`).
**Related:** [ADR-0126](ADR-0126-the-leaf-read-output-shape.md) (what the read returns),
[ADR-0112](ADR-0112-a-kind-may-declare-no-domain.md),
[ADR-0121](ADR-0121-a-null-domain-type-is-not-a-defect.md),
[ADR-0127](ADR-0127-a-title-signal-has-an-order-not-a-score.md),
[the extraction pipeline](../arch/components/extraction-pipeline.md)

## Context

The plugin that extracts a notice is selected by `domain_type == "sustainment"`. The leaf
is what makes a document's domain sustainment. The read that produces the leaf —
`sustainment_header_trust.doc_type_from_titles`, measured **9/9 on the nine-notice corpus,
0 ambiguous** — lived **inside that plugin**, and had exactly one caller: the plugin.

So the dependency was circular in practice. You needed the leaf to select the plugin, the
plugin held the read, and the read is what produces the leaf. A drop that declared its kind
never needed the read at all; a drop that did not could never reach it, and **ran green
writing nothing** — run `16f30b9a`, 2026-10-21.

The ruling fixes the order. The risk it creates is the one this record is mostly about: an
extraction pass creeping in **before** anything knows what the document is. That invariant
held at the time only by accident — the user-drop parse asset takes only an S3 resource, so
it has no model client to run a pass with. **Nothing stated it and no test failed if it
changed.** It fell out of a downstream `origin_unresolved` short-circuit that is tested on
the *graph* asset, not on the parse.

## Decision

**Before the title read, a pdf runs parse and the text layer only. The title read is the
next step, and parts extraction waits on its leaf.**

- The parse step is **parse + text layer**. No model call, no plugin dispatch, no BAML
  client, no store.
- The title read is the **next** step and it runs **in the parser**, right after the
  elements are in hand, because that is where the ruling orders it and because the read is
  a **deterministic text read**: its whole input is `elements` from the parse — no resource
  client, no network, no manifest field. That is what makes item 4 possible as written. The
  lifted read adds **no resource** to a step that is handed only S3.
- The leaf is stamped as a **top-level sibling** of `provenance` on the manifest, for the
  same reason that block is: a consumer reads the leaf without reaching into
  domain-specific metadata shape.
- It is written **only when `obtained_via` is configured**. For every vetted sensor the
  manifest is byte-for-byte what it was.
- A read that raises must **not** cost the drop its parse artifacts: the failure is logged
  and the block is absent. **The absence is the signal**; a half-written block would be
  worse than none.
- The block is **write-only for now, deliberately**. Nothing reads it yet — the graph asset
  still resolves origin from the declared `content_kind` and still returns "origin
  unresolved" for a format-level one. Holding extraction on the **leaf** is a separate step,
  because it moves the gate every ingest passes and does not belong in the same change as
  the thing that merely records the answer.

## Consequences

- The circular dependency is gone: the read runs where nothing needs to know the domain
  yet, so a kindless drop reaches it instead of running green and writing nothing.
- An unstated invariant became a **stated and tested** one. The seal is deliberately
  two-sided: one test asserts the asset's resource keys are S3 and nothing else; another
  greps the parser's own source for a forbidden set (`import baml`, `from baml`,
  `baml_client`, `doc_tools.plugins`, `get_plugin`, `ExtractHeader`, `ExtractParts`,
  `ExtractWorkInstructions`) and fails if any appears.
- The source-grep seal is the weaker half and will mis-fire on a harmless mention of one of
  those names in the parser — a comment, a docstring, a log string. That is the cost of
  pinning an absence in a file rather than a behaviour that needs a model client to observe.
- A third test earns the file: it drives the title read and asserts it needs **no**
  resource. If the read had needed a model, item 4 would be impossible as written — the
  lift would have had to bring in the very resource the invariant forbids. That test is what
  keeps the restriction honest rather than merely restrictive.
- Because the leaf block is write-only, a reader who finds `manifest["leaf"]` and expects
  routing to follow it is wrong today. The log line the parser emits (leaf, source, outcome,
  candidates, declared kind) is the only consumer at the pin.

## Alternatives considered

- **Leave the read in the plugin and reach it some other way.** Rejected by the finding
  that shaped the module: the plugin is selected by the thing the read produces, so any
  route to it runs through the decision it is supposed to make.
- **Run the read later, in the graph asset, where resources already exist.** Not taken —
  the ruling orders it as the step after parse, and the measured reason is that the
  elements are in hand there and the read needs nothing else. Running it later would also
  leave the manifest, which is the artifact a consumer reads, without a leaf.
- **Hold extraction on the leaf in the same change.** Explicitly deferred at the site: it
  moves the gate every ingest passes, and landing it beside the recording change would mean
  one change that both decides and enforces, with no step in between to measure.
- **Duplicate the title read outside the plugin instead of lifting it.** Not recorded as
  considered. Its shape would have been two readers of the same titles, which is the
  divergence the lift's own tests (the decision is unchanged, 9/9 preserved) were written
  to rule out.
