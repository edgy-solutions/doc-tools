# ADR-0105 — the AITool binding plane travels as a unit if the repo splits

**Status:** accepted
**Date:** no ruling date is recorded; standing guidance in `AGENTS.md` · recorded 2026-11-18
**Deciders:** this repo's standing agent guidance (`AGENTS.md` §Note on scope); no individual
decider is recorded
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:206-213` (§Note on scope), with the plane itself described at
`AGENTS.md:176-204`; the three files are `doc_tools/assets/aitool_linker.py`,
`doc_tools/assets/global_aitool_ingestion.py`, `doc_tools/components/aitool_sensor.py`
**Related:** [ADR-0152](ADR-0152-no-hitl-for-code-controlled-registrations.md),
[ADR-0151](ADR-0151-semantic-tags-are-late-bound-through-hitl.md),
[ADR-0102](ADR-0102-assets-and-declarative-components.md), [FOREIGN.md](FOREIGN.md) for
`iagent:ADR-0004` and `iagent:ADR-0006`

## Context

doc-tools processes documents. The AITool binding plane processes **no documents at all**: it
takes mesh tool registrations that the SDK lands in DataHub as `mlModel` entities carrying
`mesh_is_registration: "true"`, and writes a typed predicate edge into Neo4j —
`(s:OntologyClass)-[verb]->(o:OntologyClass)` — per `iagent:ADR-0004`.

It lives here for one reason, stated plainly in `AGENTS.md`: it **shares the infrastructure** the
Dataset binding plane already needed — the Dagster sensor shape, the DataHub poll, the Neo4j
write. Putting it anywhere else in 2026 would have meant a second copy of all three.

That is an accretion, not a scope decision, and the risk is what happens at the next
reorganisation. A reader who sees "doc-tools processes documents" and files these three files
under "document tooling" will split the repo along the wrong line, and the plane will come apart:
the sensor in one repo, the asset it fires in another, the backfill in a third.

## Decision

**The AITool binding plane sits in this repo because it shares the Dagster sensor + DataHub poll
+ Neo4j write infrastructure, and nothing more. If `doc_tools` is renamed or split, these three
files travel as a unit:**

- `doc_tools/assets/aitool_linker.py` — the predicate sync, including
  `sync_aitool_predicate_to_neo4j` and `_build_relationship_properties` (DataHub's
  `customProperties` are flat strings, so arrays and booleans are restored before the write).
- `doc_tools/assets/global_aitool_ingestion.py` — `ingest_global_aitool_registrations`, the
  backfill that polls DataHub for every tagged `mlModel` and reports the list.
- `doc_tools/components/aitool_sensor.py` — `AIToolSensorComponent`.

The unit is the whole plane, not the files that happen to be imported together: the sensor, the
asset it targets, and the catch-up path all describe one contract with DataHub and one edge shape
in Neo4j.

## Consequences

- The repo's name understates its scope, permanently, until a split happens. This record and
  `AGENTS.md` §Note on scope are the only places that say so.
- **The unit is already partly inert, and a splitter must not read that as "two files, not
  three".** Measured at the pin: the sensor block in `doc_tools/definitions.py:465-470` is
  **commented out** — deactivated 2026-06-13 because gateway v0.2 (`agent_fleet/mesh_registrar`)
  became sole writer of AITool predicate edges, per `iagent:ADR-0006` §Addendum. The reasons
  given for deactivating rather than deleting are that the asset stays callable from the Dagster
  launchpad for a one-off re-sync of a `tool_urn`, and that rollback is a one-line revert
  (`definitions.py:443-453`). `aitool_linker` is still loaded through `load_assets_from_modules`
  (`:473`) for exactly that reason.
- The Dataset binding sensor (`datahub_sensor`) is **unchanged** and is not part of this unit: it
  operates on glossary terms and Dataset `HAS_DATA` edges, which v0.2 does not touch.
- **The ruling and the guidance disagree with the code here.** `AGENTS.md:187-188` still says
  *"the `aitool_registration_sensor` watches DataHub and fires `sync_aitool_predicate_to_neo4j`
  runs directly"*, which was true before 2026-06-13 and is not true at the pin. The behaviour it
  describes — auto-approval with no HITL
  ([ADR-0152](ADR-0152-no-hitl-for-code-controlled-registrations.md)) — now happens in the
  gateway's request path, not in a sensor here. **This row belongs in
  [DEBT.md](DEBT.md).**
- Because the plane is deactivated rather than removed, the status of this record cannot be
  `built` on anything stronger than its files existing. Nothing in the tree enforces that they
  move together; only this record and the note do.

## Alternatives considered

- **Move the plane to invincible-agent, next to the mesh registrar.** Not recorded as considered
  at the time; the stated ground for keeping it here is shared infrastructure. Since 2026-06-13
  the write path *has* moved there (`iagent:ADR-0006` §Addendum) while these three files stayed,
  which makes the move the live question rather than a settled one — it is in
  [FOLLOW-UPS.md](FOLLOW-UPS.md), not decided here.
- **Delete the three files, since v0.2 is sole writer.** Rejected in `definitions.py`: a one-off
  manual re-sync and a one-line rollback are both worth keeping while v0.2 is young.
- **Rename the repo so its scope is honest.** Not recorded as considered. The note's phrasing
  ("if `doc_tools` is later renamed or split") treats a rename as a possible future event and
  states the constraint that would apply to it, which is the decision actually taken.
