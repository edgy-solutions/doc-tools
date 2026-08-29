# Request: project `mesh_slots` in `_build_relationship_properties`

**Raised by:** invincible-agent, Lane 1 · **Date:** 2026-08-28 · **Size:** one allowlist row + two tests
**Producer side:** landed and inert — `invincible-agent@7f3e225`

> ## BUILT 2026-08-29 — AND THE REQUESTED IMPLEMENTATION WAS WRONG
>
> The ask stands; the code it specified does not. **This request asked for `mesh_slots` to be
> `json.loads`-ed into a list of dicts and passed through like `mesh_domains`. That would have
> failed the Neo4j write for every verb that declares a slot.**
>
> `slots` is a list of **maps**, and a Neo4j property value may only be a primitive or an
> array of primitives. Measured against the sandbox Neo4j in a rolled-back transaction — one
> property, three value shapes:
>
> ```
> [{"name": "group_by", ...}]     REJECTED   Neo.ClientError.Statement.TypeError:
>                                            "Property values can only be of primitive
>                                             types or arrays thereof"
> '[{"name": "group_by", ...}]'   ACCEPTED   (a string is a primitive)
> ["A", "B"]                      ACCEPTED   (control — the `domains` idiom this asked to copy)
> ```
>
> **The tell was in this file the whole time and the request read past it.** Of the projected
> properties, three are `json.loads`-ed — `synonyms`, `anti_synonyms`, `domains` — and every
> one of them is a list of **strings**. The single structured payload, `openapi_schema`, is
> passed through as a **raw string** with no decode. That asymmetry is not an oversight in
> doc-tools; it is the constraint showing through, and `mesh_slots` belongs on the
> `openapi_schema` side of it.
>
> **As built:** `"slots": slots_json` — the JSON text, validated but not decoded, malformed
> input becoming `"[]"` so the never-raise contract still holds and a consumer's own
> `json.loads` cannot be handed garbage this function chose to pass along.
>
> **Consumer side corrected too** (`invincible-agent`): the supervisor did
> `list(truth.get("slots") or [])`, which on a JSON string yields one entry **per character**
> — every declaration a one-character string. That is the same container-traded-for-elements
> defect that produced `422 unknown fiscal period(s): F, Y, 2, 6, -, Q, 4` a day earlier.
> Decoding now happens in one place, `iagent_pure.slot_acceptance.decode_declarations`, and
> anything unparseable becomes `[]`, which the guard treats as "declare nothing, accept
> nothing" — a corrupt declaration fails **closed**.
>
> **Noted for later, not done:** one `:Slot` node per parameter would be queryable in Cypher,
> which a JSON string is not. Not needed by the consuming use case (the router always wants
> the whole list, never a filtered subset) and a much larger graph-schema change. The shape to
> reach for if slot-level Cypher ever becomes a requirement.

## What is being asked

`_build_relationship_properties()` in `doc_tools/assets/aitool_linker.py` translates DataHub's flat
`customProperties` into typed Neo4j relationship properties **from an explicit allowlist**. A new
producer key, `mesh_slots`, is now emitted and needs a row:

```python
"slots": slots_json,   # alongside "domains", "cost_class", …
```

~~decoded the same way `mesh_verb_synonyms` and `mesh_domains` already are~~ — **NO. See the
correction at the top: decoding this into a list of dicts fails the Neo4j write.** Validated
but kept as text, following `openapi_schema`:

```python
slots_json = props.get("mesh_slots", "[]") or "[]"
try:
    json.loads(slots_json)          # validate only — a Neo4j property cannot hold maps
except json.JSONDecodeError:
    slots_json = "[]"
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
  {"name": "window", "kind": "spoken-optional", "type": "list[str]", "required": false},
  {"name": "baseline_state", "kind": "handle", "type": "PlanState", "required": true}
]
```

> **Corrected 2026-08-28.** `window` was shown here as `"str"`. It is `list[str]`, and the
> earlier version was not a typo in this document — it was what the producer actually
> emitted. The derivation unwrapped `Optional[X]` by taking the single non-`None` arm, which
> silently unwrapped `Optional[list[str]]` twice and reported the element type. A consumer
> believing that declaration sends `"FY26-Q4"` where a list is required, and the engine
> replies `422 unknown fiscal period(s): F, Y, 2, 6, -, Q, 4` — it iterated the string.
>
> Fixed producer-side (`invincible-agent@bd233cf`); union origins are now distinguished from
> container origins, and enum values are read from *inside* a container so a multi-select
> keeps its vocabulary. **No change is required on the doc-tools side** — the field was
> always an opaque string in an opaque record — but the shape is stated correctly here
> because this document is the contract another team reads.

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

**A third was added beyond what this asked for**, pinning the string-ness itself:
`test_mesh_slots_is_a_STRING_because_neo4j_cannot_hold_a_list_of_maps`, with the `domains`
list as its non-vacuity control. The inconsistency with `domains` looks exactly like a bug to
a reader who does not know the constraint, so it is asserted rather than only commented — a
tidy-up that "fixes" it breaks registration for every verb that declares a slot.

**And the negative, which we could not find an equivalent of:**

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
