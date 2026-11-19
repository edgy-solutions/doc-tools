# ADR-0110 — the platform owns what a kind is; doc-tools owns what it runs

**Status:** accepted + built
**Date:** 2026-10-24 (ruled, amending the ruling of 2026-10-07); the collision behind it closed
2026-10-30 · recorded 2026-11-18
**Deciders:** the architect
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/utils/kind_registrations.py:23-35` and `:37-49` — a code comment, quoted in
the docstring of `tests/test_overlay_kind_drift.py:25-29`, which was the **only** written
statement of this ruling before this record. Built at `kind_registrations.py:116`
(`PLATFORM_OWNED_FIELDS`) and `:119` (`registration_for`), pinned by
`tests/test_kind_registry.py:397`
(`test_the_platform_owned_fields_are_absent_by_ruling`) and `:445`
**Related:** [ADR-0111](ADR-0111-a-disputed-value-is-a-packet-not-an-edit.md) (how the values we
do not write reach the platform), [ADR-0112](ADR-0112-a-kind-may-declare-no-domain.md),
[ADR-0113](ADR-0113-the-kind-wins-over-the-manifest.md)

## Context

A content kind is defined twice in this fleet. doc-tools holds `KIND_MAPPING` and projects it
into `registry/content_kinds/*.yaml` through the SDK's `ContentKindRegistration` model; the
platform holds a deployment overlay of content-kind rows, and the platform's server is what
routes a real drop. At the v0.9.11 pin the SDK model is `extra="forbid"` with thirteen fields,
of which doc-tools sets three on every row (`kind`, `passes`, `outputs`) and projects four more
conditionally.

Four of the remaining fields — `domain`, `arrives_as`, `review_shape`, `label` — are left at
their model defaults. Nothing in the generated YAML says why. The concrete failure is a reader
who finds four empty fields on a model that accepts them and fills them in: this repo then
becomes a second source of truth for fields the platform rules on, and the two registries
disagree about what a kind *is* while both look authoritative.

That is not hypothetical. invincible-agent's SDK changelog for v0.9.11 says, of `arrives_as`,
*"ca adds the field, 7f fills in KIND_MAPPING's rows with it"* — dated 2026-10-21, three days
before the ownership ruling moved the field to the platform. This lane declined to fill the rows
and reported the collision instead of settling it by editing a file.

## Decision

**The platform owns what a kind IS (`kind`, `domain`, `arrives_as`, `review_shape`, `label`);
doc-tools owns what it RUNS (`passes`).**

- The authoritative registry for those five is **the deployment overlay in `invincible-agent`**,
  which is that repo's to edit. Our rows are the side that gets mirrored.
- The four fields are left at the model default **as a choice, pinned as one**:
  `PLATFORM_OWNED_FIELDS` keeps them as data rather than prose so
  `tests/test_kind_registry.py` can assert that every emitted row leaves all four unset.
- `passes` flows the other way. The overlay **mirrors** this registry; the overlay's `passes` are
  documentary, so a divergence is always the overlay's to correct and never a reason to narrow
  what this image declares (`tests/test_overlay_kind_drift.py:258`).
- Our own `domain_type` column is **not** withdrawn by the ruling. It drives this image's write
  path, and it is published beside the rows in `registry/content_kind_domains.json`
  ([ADR-0112](ADR-0112-a-kind-may-declare-no-domain.md)).
- The architect's ruling of 2026-10-30 closed the changelog collision: *"ownership stands as
  ruled 10-24 … Your decline + test stay."* The changelog line is superseded, and what this lane
  owes is a packet, not a row ([ADR-0111](ADR-0111-a-disputed-value-is-a-packet-not-an-edit.md)).

## Consequences

- doc-tools cannot complete a kind's definition on its own. A new kind is routable only once
  Lane 1 has filled the five platform fields, so a kind's arrival carries packet latency that no
  change in this tree can shorten.
- The declining test arm is **permanent**, not a placeholder awaiting a ruling. Deleting it
  re-opens the second source of truth that both the 10-24 and the 10-30 rulings close.
- The seal that measures the two registries against each other reads a foreign repo, so it is
  resolved from the sha in `tests/pins/invincible-agent.ref` and never from a working tree. It
  **fails under CI and skips locally** when the overlay cannot be resolved
  (`tests/test_overlay_kind_drift.py:147-185`), so a green local suite is not evidence that the
  seal ran.
- A field left empty here reads as a ruling rather than an oversight, which is the whole point:
  the next reader is stopped by a test, not by a comment they would have to find first.

## Alternatives considered

- **Fill `arrives_as` (and the other three) in `KIND_MAPPING`'s rows here**, as
  invincible-agent's v0.9.11 changelog instructed. Rejected by the 10-24 ruling and again by the
  10-30 ruling: it would make this repo a second source of truth for fields another repo rules
  on, which is precisely the drift the cross-repo seal exists to catch.
- **Drop the test arm that pins the four fields as unset**, since an unset field needs no test.
  Rejected in the arm's own docstring: four empty fields with nothing asserting them is how the
  next reader comes to fill them, and the absence then stops being a decision.
- **Let the overlay own `passes` as well**, which would give the platform the whole row. Not
  recorded as considered. Its shape is clear enough — processability is a property of *this*
  image, resolved through `doc_tools.passes.dispatch` — but no ruling on it is recorded, and this
  record does not supply one.
