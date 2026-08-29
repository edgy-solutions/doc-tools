# Request: project `mesh_slots` in `_build_relationship_properties`

**Raised by:** invincible-agent, Lane 1 · **Date:** 2026-08-28 · **Size:** one allowlist row + two tests
**Producer side:** landed and inert — `invincible-agent@7f3e225`

## What is being asked

`_build_relationship_properties()` in `doc_tools/assets/aitool_linker.py` translates DataHub's flat
`customProperties` into typed Neo4j relationship properties **from an explicit allowlist**. A new
producer key, `mesh_slots`, is now emitted and needs a row:

```python
"slots": slots,   # alongside "domains", "cost_class", …
```

decoded the same way `mesh_verb_synonyms` and `mesh_domains` already are:

```python
try:
    slots: List[dict] = json.loads(props.get("mesh_slots", "[]"))
except json.JSONDecodeError:
    slots = []
```

**Absent means `[]`, and `[]` means today's behaviour** — exactly the contract `mesh_domains`
already has (*"missing `mesh_domains` defaults to an empty list (domain-agnostic) — matches the
SDK-side default"*, `tests/test_aitool_linker.py:99`). Additive only; no existing registration
changes shape.

## Why it matters — the key is dropped SILENTLY today

This is the whole reason the request is filed rather than assumed. The producer emits `mesh_slots`
right now, and the projection **discards it with no error and no warning**, because the allowlist
names every key explicitly. A verb's declarations therefore reach DataHub and stop there.

We named the shape **declared-then-dropped**, because it is the sibling of a defect measured in
invincible-agent the same week: slots were *extracted* by BAML and then dropped at the dispatch
boundary, so every verb ran on its defaults and a question saying *"by initiative"* silently
returned organisations. Same failure, one layer over: **a declaration that is made, carried, and
discarded by a consumer that never says so.**

It was found by reading this projection *before* trusting the pipeline. Had we not, the producer
work would have looked green — registration succeeding, tests passing, DataHub carrying the
property — while the graph never held a single slot.

## What the payload looks like

One record per parameter, derived from the engine's own function signatures (never
hand-transcribed — the enum values are read out of the `Literal`):

```json
[
  {"name": "group_by", "kind": "spoken-optional", "type": "enum",
   "required": false, "values": ["org", "initiative"], "default": "org"},
  {"name": "window", "kind": "spoken-optional", "type": "str", "required": false},
  {"name": "baseline_state", "kind": "handle", "type": "PlanState", "required": true}
]
```

`kind` is one of `spoken-mandatory | spoken-optional | handle | ceremony`. It is the only fact no
type system carries: `baseline_state: str` and `site_id: str` are identical shapes with opposite
provenance — one is supplied by the route, the other must be spoken by a user. The router needs
that distinction to know whether it may ask for a value.

**doc-tools does not need to interpret any of this.** It is an opaque JSON list to the projection,
exactly as `domains` is. Decode, default to `[]`, pass through.

## Tests — the two existing patterns, plus one that does not exist yet

**Copy the defaults idiom** (`tests/test_aitool_linker.py:99` and `:108`):

1. **missing key defaults** — `flat` without `mesh_slots` → `props["slots"] == []`
2. **malformed JSON falls back** — `{"mesh_slots": "[not valid json"}` → `props["slots"] == []`,
   never raised

**And please add the negative, which we could not find an equivalent of:**

3. **a key NOT in the allowlist demonstrably does not project** — e.g.
   `{"mesh_not_a_real_key": "x"}` → that key is absent from the returned dict.

Why we are asking for (3) specifically: the discard behaviour is currently **incidental** — it
falls out of the allowlist being a literal dict, and nothing states it is intended. That is what
made `mesh_slots` droppable without a signal in the first place. A test pins the discard as a
**decision**, so the next producer that invents a key learns from a red test what we learned from
reading the source.

## What is NOT being asked

* No change to how the edge is written, queried, or consumed downstream.
* No interpretation of `kind` or `values` in doc-tools.
* Nothing urgent-by-deadline: the producer side is committed and **inert** until this lands, by
  design — declarations sit dark rather than half-lit. Landing order was chosen so that a partial
  state is invisible rather than misleading.

## Contact / provenance

Full finding: `invincible-agent:docs/plans/slots-are-extracted-then-dropped-at-dispatch.md`.
Producer: `agent_fleet/utils/mesh_registration.py` (`mesh_slots` in `custom_props`), values derived
by `agent_fleet/planning_agent/slots.py`.
