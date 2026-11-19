# ADR-0152 — no HITL for code-controlled tool registrations

**Status:** built
**Date:** no ruling date is recorded for the rule itself; it implements `iagent:ADR-0004`, and
the trigger named in the guidance was retired 2026-06-13 per `iagent:ADR-0006` §Addendum ·
recorded 2026-11-18
**Deciders:** invincible-agent's records — `iagent:ADR-0004` (predicate-graph routing) and
`iagent:ADR-0006` (DataHub inbox, Neo4j substrate) — relayed into this repo's guidance; no
individual is named
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:176`, `AGENTS.md:185-188` (§AITool Binding Plane 2); implemented at
`doc_tools/assets/aitool_linker.py:179`, `:632-654` and
`doc_tools/components/aitool_sensor.py:61`, `:155`, `:185`; the trigger's retirement is at
`doc_tools/definitions.py:434-470` and `:573-579`
**Related:** [ADR-0151](ADR-0151-semantic-tags-are-late-bound-through-hitl.md) — the sibling and
the deliberate opposite: a **Dataset** linking is a human judgement, a **code-controlled**
registration is not. Also [ADR-0105](ADR-0105-the-aitool-binding-plane-travels-as-a-unit.md)
and [ADR-0225](ADR-0225-a-local-checkout-is-not-the-deployed-contract.md)

## Context

`iagent:ADR-0004` routes mesh tool calls over a predicate graph: a registered tool becomes a
typed Neo4j relationship from its input class to its output class. This repo owns one half of
that — the half that reads a registration out of DataHub and materialises the edge — because it
already has the Dagster sensor, the DataHub poll and the Neo4j write (`AGENTS.md` §Note on
scope).

Whether that materialisation needs a human, as a `Dataset` tag does
([ADR-0151](ADR-0151-semantic-tags-are-late-bound-through-hitl.md)), turns on what is being
approved. A Dataset tag asserts a *business meaning* — "these rows are maintenance work
orders" — which a human knows and a classifier guesses. A mesh tool
registration asserts *what the code already does*: the verb IRI, the input and output class
URIs, the endpoint URL and the OpenAPI schema are emitted by the SDK from the running service's
own declaration. There is no judgement for a reviewer to add. A HITL queue there would be a
person pressing approve on a machine's statement about itself, and the only thing it would
reliably produce is latency between a service starting and its tool being routable.

The matching risk is that a registration is indistinguishable from a real ML model registration,
since both are `mlModel` entities: auto-approval without a marker would materialise predicate
edges from entities that never claimed to be tools.

## Decision

**A code-controlled mesh tool registration auto-approves. There is no HITL queue on the AITool
side, and the marker that makes auto-approval safe is `customProperties.mesh_is_registration =
"true"` on an `mlModel` entity, which the SDK must set.**

- The marker is checked, not assumed, on both ends: the sensor skips any entity whose flat
  properties lack it (`components/aitool_sensor.py:155`), and the asset refuses again at run time
  — *"not a mesh tool registration"* (`assets/aitool_linker.py:179`, `:654`).
- `sync_aitool_predicate_to_neo4j` (`aitool_linker.py:632`) writes the typed edge through APOC's
  `apoc.merge.relationship`, with the verb's local name as the relationship type and the full IRI
  preserved as a property (`AGENTS.md:189-198`).
- DataHub's flat string properties are restored to arrays and booleans before the write
  (`_build_relationship_properties`, `:251`), pinned by `tests/test_aitool_linker.py:54`, `:91`,
  `:121`.
- **No proposal, no approval state and no steward queue exists for this path** — which is what
  distinguishes this record from its sibling.

## Where the ruling and the code disagree

`AGENTS.md:185-188` says *"the `aitool_registration_sensor` watches DataHub and fires
`sync_aitool_predicate_to_neo4j` runs directly"*. **At the pin, no sensor fires anything.** The
component still exists, but its instantiation is commented out (`definitions.py:465-470`) under a
2026-06-13 retirement note citing `iagent:ADR-0006` §Addendum: invincible-agent's
`agent_fleet/mesh_registrar` (gateway v0.2) is now the **sole writer** of AITool predicate edges,
writing them synchronously in the registration request path with saga compensation. The asset is
still loaded (`:580`, via `all_assets` at `:473`) so a one-off manual re-sync through the Dagster
launchpad remains possible, and the module's banner says it outright — *"A CHANGE HERE DOES NOT
REACH A LIVE EDGE"* (`aitool_linker.py:1-27`).

So the *rule* is in force and is built; the *mechanism* named in the guidance is retired, and
`AGENTS.md:185-188` is stale. **This row belongs in `DEBT.md`**; this record edits neither file.

## Consequences

- Registration latency is bounded by code, not by a reviewer's attention; on the live gateway
  path, by the request itself.
- The `mesh_is_registration` marker is load-bearing and owned by the **SDK**, not by us. If an
  SDK release stops setting it, every registration silently stops materialising — refused at two
  places, both of which log a skip rather than fail.
- A wrong registration is a wrong routable edge immediately, with no human in front of it. The
  compensating control is on the far side of the seam (the gateway's bounded retry and saga
  compensation), not here.
- The retirement adds a hazard this record partly exists to defuse: a reader tracing "where does
  this property get written" lands in `aitool_linker.py`, finds a complete, plausible projection,
  and builds against a corpse. The banner records that happening **twice**, once producing a
  cross-repo request that called this module "the single gate" on a feature it could not gate.

## Alternatives considered

- **A HITL queue for tool registrations, mirroring the Dataset flow.** Not taken, on the ground
  recorded in the code and attributed there to `iagent:ADR-0006`: Datasets need human
  classification, code-controlled registrations do not (`aitool_linker.py:48-50`,
  `components/aitool_sensor.py:8-11`).
- **Auto-approve every `mlModel` entity.** Ruled out by the marker requirement — real ML model
  registrations share the entity type, and disambiguating them is the whole purpose of
  `mesh_is_registration` (`AGENTS.md:182-184`).
- **Delete the retired module rather than deactivate it.** Rejected in the retirement note
  (`definitions.py:443-452`): the asset is idempotent and takes a `tool_urn` config, so keeping
  it preserves a manual re-sync, and rollback is a one-line revert of the sensor block.
