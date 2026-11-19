# ADR-0116 — a sensor cannot declare a content kind; the drop path carries it

**Status:** accepted + built
**Date:** contract v2 (the drop moved to `training/course/`); contract v5 is dated 2026-10-30 ·
recorded 2026-11-18
**Deciders:** the architect, through the training-workbench contract
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `docs/contracts/training-workbench.md` §2 (`:39-42`), with the v1 history in the
contract's version line (`:3`). Built at `doc_tools/definitions.py:124-131` (the training sensor)
and `doc_tools/utils/content_kind.py:757` (`resolve_content_kind`) with the path derivation at
`:741`
**Related:** [ADR-0112](ADR-0112-a-kind-may-declare-no-domain.md),
[ADR-0113](ADR-0113-the-kind-wins-over-the-manifest.md),
[ADR-0114](ADR-0114-xml-is-held-out-until-a-drop-proves-it.md),
[ADR-0234](ADR-0234-the-training-workbench-seam.md)

## Context

Version 1 of the training-workbench contract had the sensor declare the content kind: the
training sensor watched a prefix, and the kind `course` was to come from the sensor that fired.
**There was no mechanism for that.** The kind-selection chain is
`manifest.metadata.content_kind` → the path segment after the `domain_type` segment → HALT
(`iagent:ADR-0021`), and a sensor appears in none of those three places. `resolve_content_kind`
takes two arguments — the manifest metadata and the S3 key — so there is no parameter through
which a sensor's belief about the kind could reach the resolver, and at the pin no sensor
construction in `doc_tools/definitions.py` passes one.

The concrete failure that leaves is a drop that halts on a correct configuration. A key under a
prefix whose second segment is not a registered kind path-derives that segment and finds no row:
`manufacturing/inbound/<file>` derives `inbound`, which is in no `KIND_MAPPING` row, so the chain
halts with `UnclassifiableContentKindError` — correctly, because nothing in the drop says what
the document is. A sensor that "knows" it is watching courses cannot repair that, however
confident its name.

## Decision

**A sensor cannot declare a content kind. The drop path carries it, and the sensor only decides
which keys are seen.**

- The kind comes from the path, by `iagent:ADR-0021`'s existing rule
  `<domain>/<kind>/<folder>/<file>`: the first segment is the domain (`training` → `TRAINING`),
  the second is the content kind (`course`).
- Contract v2 therefore **moved the drop** to `training/course/` rather than adding a mechanism.
  Nothing new was invented: no sensor-supplied kind, no new precedence level. The precedence
  stays metadata > path > HALT.
- A kind **names the document, not the domain** — a course in the training domain, the way a PCN
  is a notice in sustainment.
- The sidecar needs no `content_kind` or `domain_type`. If it has them they must be `course` and
  `training`, because a sidecar value wins over the path and any other value re-routes the drop.
- What the sensor *does* own is the key filter: the prefix it watches, the patterns it ignores
  (`archive/`, `metadata.json`, `generated/`) and the suffixes it accepts — and even those are
  generated from the kind's own row (`s3_filter=inbound_suffix_pattern(KIND_MAPPING["course"])`),
  never written by hand.

## Consequences

- A new kind of drop is a **path decision**, settled with whoever drops, not a sensor
  configuration this repo can make alone. That is slower and it is the point: the kind is
  declared by something the document carries, so the same key resolves the same way whichever
  sensor, backfill or hand replay reads it.
- The resolver keeps exactly one shape of answer, so a replay from a key — with no sensor
  involved — resolves identically to the live drop. A sensor-declared kind would have made the
  sensor part of the document's identity.
- A path that does not match the convention halts rather than defaulting. A dropper who invents a
  folder gets an error, not a silent mis-filing, and the error names the registered kinds.
- The sensor's prefix and the kind's row must agree, and nothing in this tree asserts that they
  do: `prefix="training/course/"` is a literal, and a kind renamed in `KIND_MAPPING` without the
  prefix being changed would leave the sensor watching a path whose second segment no longer
  resolves. The suffix filter is generated from the row; the prefix is not.

## Alternatives considered

- **Have the sensor declare the kind** — v1's design. Rejected because it had no mechanism: the
  precedence chain has three levels and a sensor is in none of them, so the kind would have had to
  be injected into the manifest or a fourth level added.
- **Add a precedence level for a sensor-supplied kind.** Rejected by the contract's own words —
  *"no sensor-supplied kind, no new precedence level"* — in favour of moving the drop, which
  needed no code at all.
- **Have the sidecar carry the kind for every course drop.** Not taken, though it is permitted:
  the sidecar may carry `content_kind` and it wins when present. The contract makes it optional
  because a required sidecar is a second thing that can be missing, and `metadata.json` must land
  before the deck or it is not seen at all.
