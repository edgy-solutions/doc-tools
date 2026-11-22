# ADR-0101 — processable kinds are published by PUT from inside the pod

**Status:** built
**Date:** 2026-10-16 (ruled, F2) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/components/processable_kinds_publisher.py:1-29` and
`:146-159`; `doc_tools/api/kinds.py:3-8`; `doc_tools/definitions.py:250-258` — code comments and
a docstring, which were the **only** written statement of this ruling before this record
**Related:** [ADR-0100](ADR-0100-doc-tools-is-a-code-location-not-a-service.md) (the other half:
why there is no HTTP surface to call),
[ADR-0110](ADR-0110-the-platform-owns-a-kind-doc-tools-owns-its-passes.md),
[ADR-0114](ADR-0114-xml-is-held-out-until-a-drop-proves-it.md),
[ADR-0115](ADR-0115-the-playbook-hold-is-lifted.md)

## Context

[ADR-0100](ADR-0100-doc-tools-is-a-code-location-not-a-service.md) records that doc-tools has no
HTTP surface. That leaves the question this record answers: **Lane 1's ingest door still has to
know what this image can process.** The door decides whether to accept a drop at the moment the
drop arrives.

A door that reaches a Dagster code location to find out is a door that **fails closed while that
code location is rolling** — exactly when the answer is most likely to have changed. The
publisher's docstring states the failure in those terms, and a code location rolls on every pin
bump.

Nor can the answer be recomputed by the consumer. `doc_tools/api/kinds.py` is explicit about why:
processability is a property of *this image* — each declared pass is resolved through
`doc_tools.passes.dispatch`, and the user-drop parser table is a literal in
`doc_tools.assets.xml_ingestion` — and the SDK's `ContentKindRegistration` is `extra="forbid"`, so
no registration row can carry the answer either. A value cached anywhere else goes stale against
the image that would run the pass.

## Decision

**The list travels outward: doc-tools PUTs its ingestable-kinds list to Lane 1's door from inside
the Dagster pod, every tick, and nothing calls doc-tools to obtain it.**

- `build_processable_kinds_publisher_sensor()` (`processable_kinds_publisher.py:140`) is
  registered in `definitions.py` as `processable_kinds_publisher_sensor` and **launches no runs**
  — it exists for its side effect, and every tick skips with the outcome in the `SkipReason`.
- Target: `PUT {IAGENT_GATEWAY_URL}/ingest/processable-kinds`, default
  `http://iagent-cortex-bff:8090`, 10 s timeout, `minimum_interval_seconds` 300 (`:46-53`).
- The body is the **same** `ingestable_kinds()` payload the unserved `GET /kinds/processable`
  would return (`api/kinds.py:142`). One definition, two transports, never two lists.
- **Every tick publishes.** The cursor holds the last outcome as a *record* for the tick log and
  is never a gate (`:165-172`).
- **A sensor, not a schedule**, measured on run records: a schedule's unit of work is a run, so a
  publishing schedule would mint **288 runs a day** that carry no materialisation and bury the
  runs someone is looking for (`:148-154`).
- **Publishing is not the flip.** Lane 1 gates its own door on
  `INGEST_DOOR_READS_PROCESSABLE_KINDS`. This publisher makes the list available; which pin
  carries it is *reported* to Lane 1, not inferred by them.

## Consequences

- doc-tools needs **no HTTP surface, no Service and no probe that means anything** — the whole of
  [ADR-0100](ADR-0100-doc-tools-is-a-code-location-not-a-service.md) rests on this route existing.
- The dependency is **reversed, and that is a cost**: doc-tools must now know the gateway's
  address and hold a service identity to call it. A token is minted per publish; an unset
  `KEYCLOAK_REALM_URL` or client secret means **nothing is sent**, and the tick says so rather
  than publishing anonymously (`:124-129`).
- Staleness is bounded by the interval, not by change detection: a door that restarts, is
  redeployed, or is rolled back to a build that never received our PUT is re-told within 300 s.
- A failure is a **refusal, never an exception**: a connection failure, a 404 (the route is not
  deployed yet) and a 401 (an entitlement answer, not a mint failure) are each named distinctly
  in the tick log.
- The door caches our answer, so **two components now hold the list**. Ours is authoritative; the
  door's copy is a cache whose refresh is this sensor and nothing else.

## Alternatives considered

- **Serve `GET /kinds/processable` and let the door poll it.** Rejected by the ruling: the door
  fails closed when the code location is rolling, and a poll adds a Service, a probe and a
  consumer loop. The route still exists in the tree, unserved, for a human
  ([ADR-0100](ADR-0100-doc-tools-is-a-code-location-not-a-service.md)).
- **A fingerprint cursor, publishing only when the list changes.** Rejected, and the docstring
  gives the general form of the mistake: *a cursor that records what WE did is not evidence of
  what the OTHER SIDE still holds.* A fingerprint-gated publisher never re-tells a door that was
  rolled back, so the list stays stale for as long as nothing in this image changes.
- **A Dagster schedule.** Rejected on the run-record cost above.
- **Let the consumer recompute processability from the kind registry.** Not possible, not merely
  rejected: `ContentKindRegistration` is `extra="forbid"`, so there is no row to carry it.
