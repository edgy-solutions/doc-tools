# ADR-0223 — the mesh-slots request document records the correction, not the request

**Status:** measured
**Date:** 2026-08-29 (built, and the requested implementation corrected; raised 2026-08-28) ·
recorded 2026-11-18
**Deciders:** this lane, on a measurement against the sandbox graph — the request came from
invincible-agent, Lane 1, and the correction was carried back to it
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `docs/mesh-slots-projection-request.md:5-47` (the correction banner, above the
request it supersedes); `doc_tools/assets/aitool_linker.py:299-330` and `:387` — the evidence is
kept in place, in a comment at the allowlist row; pinned by
`tests/test_aitool_linker.py:574` and `:600`
**Related:** [ADR-0111](ADR-0111-a-disputed-value-is-a-packet-not-an-edit.md) (how a
disagreement with Lane 1 travels), [ADR-0147](ADR-0147-mesh-is-the-canonical-prefix.md),
[ADR-0145](ADR-0145-domain-labels-go-on-nodes-only.md), [FOREIGN.md](FOREIGN.md)

## Context

`_build_relationship_properties()` (`doc_tools/assets/aitool_linker.py:251`) translates the
platform's flat `customProperties` into typed Neo4j relationship properties from an explicit
allowlist. A new producer key, `mesh_slots` — one record per parameter a verb takes — was being
emitted and silently dropped, and Lane 1 raised a request for the allowlist row: one row and two
tests, specified as `json.loads`-ing the value into a list of dicts and passing it through "the
same way `mesh_domains` already is".

**That implementation is wrong, and wrong in a way that fails closed only after a deploy.**
`slots` is a list of **maps**, and a Neo4j property value may be a primitive or an array of
primitives, nothing else. Measured against the sandbox graph in a rolled-back transaction, one
property, three value shapes: the decoded list of maps is **rejected** with
`Neo.ClientError.Statement.TypeError` ("Property values can only be of primitive types or arrays
thereof"); the same payload as JSON text is **accepted**, because a string is a primitive; and an
array of strings is accepted as the control — that being the `domains` idiom the request asked to
copy. Decoding it as asked would have failed the relationship write for **every verb that
declares a slot**.

The tell was in the request's own target file. Of the projected properties, three are decoded —
synonyms, anti-synonyms, domains — and all three are lists of **strings**; the one structured
payload, `openapi_schema`, is passed through as a raw string with no decode. That asymmetry is
not an oversight to tidy up, it is the constraint showing through.

So the document that looks like a request is nothing of the kind. It carries a `BUILT` banner
over a struck-through specification, and a reader who skims to "What is being asked" reads the
rejected design as the design.

## Decision

**`docs/mesh-slots-projection-request.md` records the correction, not the request. Read its
banner as the specification; the body below it is superseded in place.**

- As built: `"slots": slots_json` — the JSON **text**, validated but not decoded. Malformed
  input becomes `"[]"`, keeping the never-raise contract the other allowlist rows have, so a
  consumer's own `json.loads` cannot be handed garbage this function chose to pass along.
- `mesh_slots` sits on the `openapi_schema` side of the allowlist, not the `domains` side, and
  the measurement that says why is kept **at the row**, not only in the document
  (`aitool_linker.py:299-324`). Anyone "fixing the inconsistency" with a `json.loads` meets the
  evidence before the deploy does.
- Both directions are pinned: that the declarations survive byte for byte and decode to the
  same structure (`tests/test_aitool_linker.py:574`), and that the projected value **is a
  string** (`:600`) with a failure message naming the consequence.
- The correction was carried to the consumer side rather than left as a note. The platform's
  supervisor did `list(truth.get("slots") or [])`, which over a JSON string yields **one entry
  per character** — the same container-traded-for-elements defect that had produced a
  422 naming the characters of a fiscal period a day earlier. Decoding now happens in one place
  there, and anything unparseable becomes `[]`, which the guard reads as "declare nothing,
  accept nothing": a corrupt declaration fails closed.

## Consequences

- Registration works for every verb that declares a slot, and the projected property is
  inconsistent with its decoded neighbours **on purpose**. The inconsistency is the readable
  half of a constraint that is otherwise invisible until a write fails.
- `slots` is **not queryable in Cypher**. A JSON string cannot be filtered on, so slot-level
  graph queries are not available and are not meant to be.
- A request document in this repo may be a correction document. That is now a thing to expect:
  the banner is the contract and the struck-through body is kept so the rejected design cannot
  be independently re-proposed.
- The acceptance of the request still stands — the ask was right, only its implementation was
  wrong. Nothing here reopens whether `mesh_slots` should be projected.

## Alternatives considered

- **Decode to a list of dicts, as requested.** Rejected by measurement: rejected by the graph
  for the only shape that matters. This is the alternative the document exists to record.
- **One `:Slot` node per parameter, edged to the verb.** Recorded in the document as the
  properly modelled shape and **noted for later, not done**: it would be queryable in Cypher,
  which the JSON string is not, but the consuming router always wants the whole list rather than
  a filtered subset, and it is a far larger graph-schema change. The shape to reach for if
  slot-level Cypher ever becomes a requirement.
- **Drop the row and let the key keep being dropped.** Not considered: the silent drop was the
  reported defect.
