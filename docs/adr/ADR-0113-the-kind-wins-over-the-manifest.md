# ADR-0113 — where the manifest and the kind disagree on domain, the kind wins

**Status:** built
**Date:** 2026-10-02 (architect ruling) · recorded 2026-11-18
**Deciders:** the architect
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/assets/semantic_assets.py:765` (the ruling, in the disagreement warning)
and `:739` (the same ruling on the domain-less path) — a code comment, which was the **only**
written statement of this ruling before this record. The resolution chain is `:757-785`
**Related:** [ADR-0112](ADR-0112-a-kind-may-declare-no-domain.md) (the companion ruling of the
same day), [ADR-0121](ADR-0121-a-null-domain-type-is-not-a-defect.md),
[ADR-0124](ADR-0124-header-identity-precedence.md) (precedence recorded for a different field)

## Context

Two things claim to know a document's domain. The manifest carries `domain_type`, and the
registered content kind declares one. They are not the same kind of claim:

- the manifest's value is **derived** — from an S3 prefix, or from a Lane-1 sidecar that in at
  least one live case hardcodes null;
- the kind's value is a **registered row** with a `target_ontology_class` behind it, generated
  into `registry/content_kind_domains.json` and sealed against the platform's overlay
  ([ADR-0110](ADR-0110-the-platform-owns-a-kind-doc-tools-owns-its-passes.md)).

With no stated precedence, the two are resolved by whichever branch the reader of the code writes
first, and the failure is silent: the document is written into a domain graph, with that domain's
Neo4j label, through that domain's plugin, and nothing marks the choice as contested. A drop
under a mis-derived prefix becomes a member of a domain it was never vetted for, and the only
trace is which `MERGE` ran.

## Decision

**Where the manifest and the registered kind disagree on domain, the kind wins.**

- When a `KIND_MAPPING` row matches, `domain_type` is **the kind's**. The manifest's value is not
  consulted for the answer.
- A disagreement is **logged as a warning** naming both values, the `doc_id` and the kind, and
  saying which won and why — *"the manifest's value is derived from an S3 path or a sidecar, the
  kind's is a registered row with a `target_ontology_class` behind it. Correct the upstream
  manifest/path if this is unexpected."* The disagreement stays visible instead of being resolved
  invisibly.
- The rule holds **in the `None` direction too**: a kind that declares no domain does not fall
  back to the manifest's value even when one is present
  ([ADR-0112](ADR-0112-a-kind-may-declare-no-domain.md)). Taking it would be choosing a vetted
  domain for unvetted content from the file format.
- The manifest is the authority **only where no kind row matches at all**. If neither resolves,
  the asset raises `DomainTypeNotResolvableError` rather than defaulting: per the same ruling the
  domain comes from the registered kind and never from a run tag, so there is no third source —
  and the `"Training"` default that used to sit there would have written the document into the
  training domain's graph on no evidence.

## Consequences

- A mis-derived prefix no longer re-routes a document. It produces a warning on a run whose write
  went to the right graph, which is the recoverable order of those two events.
- The warning is the whole instrument. It is not an error, nothing fails, and no counter records
  it, so a sustained mismatch between an upstream path convention and the registry is visible
  only in run logs — and absence from a run log is not evidence that it did not happen.
- Fixing a disagreement means fixing the **upstream manifest or path**, never adding a branch
  here. There is deliberately no override by which a manifest can win.
- Adding a kind row therefore changes the routing of drops that already arrive under a path, with
  no change to the dropper. That is the intended direction — the registry is the one place a
  domain is declared — but it means a row is a routing change, not only a declaration.

## Alternatives considered

- **Let the manifest win**, on the ground that it is closer to the drop. Rejected by the ruling,
  and the warning text carries the reason: a derived value and a registered value are not peers,
  and on this path the sidecar's value is known to be hardcoded null in a live case.
- **Fall back to the manifest when the kind declares no domain.** Rejected explicitly in the
  domain-less branch's comment (`:739` and the block above it): the manifest's value there is not
  evidence of origin, and taking it is the exact hazard the companion ruling names.
- **Treat a disagreement as a halt**, so no document is written while two sources contradict each
  other. Not recorded as considered. Its shape is obvious — refuse the drop, make a human
  reconcile — and the code took the other branch, writing to the kind's domain and warning. No
  ruling on that option is recorded, and this record does not supply one.
- **Take the domain from a run tag.** Named and rejected in the raise's own message: the ruling
  allows no third source.
