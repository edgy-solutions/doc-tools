# ADR-0160 — a `Concept` is keyed on a hash, because Neo4j carries no uniqueness on name

**Status:** built
**Date:** 2026-10-24 (architect's ruling, shipped as `#167`) · recorded 2026-11-18
**Deciders:** the architect, relayed by Chris — after lane tr found the missing constraint
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `doc_tools/plugins/training.py:453-470` — a code comment, which with
`doc_tools/utils/concept_identity.py:1-37` was the **only** written statement of the *why*
before this record; the ruling is quoted verbatim at
`scripts/neo4j_concept_id_migration.py:5-12` and `tests/test_concept_id_and_constraint.py:4-9`;
the shape is contract `docs/contracts/training-workbench.md` §3
**Related:** [ADR-0161](ADR-0161-teaches-edges-are-replaced-in-one-write.md) (the edge the key
made safe to prune), [ADR-0162](ADR-0162-a-concept-no-slide-teaches-is-not-aligned.md),
[ADR-0163](ADR-0163-alignment-direction-and-who-creates-a-canonical.md),
[ADR-0234](ADR-0234-the-training-workbench-seam.md)

## Context

Lane tr measured the live graph and found that **Neo4j carries no uniqueness constraint on
`Concept` at all**. Nothing in the database refused a second node for a concept that already
existed, and two earlier key choices had each left their own residue:

- the pre-`#163` MERGE key was `{id, name, salience}`. Salience is a per-slide number, so one
  concept named on two slides with two saliences became **two nodes**, and `TEACHES` carried no
  salience at all.
- `#163` moved the key to `{name}`, which fixed that and honoured the contract's "one
  `Concept:TRAINING` per name across courses" — but left the key **unnormalized and
  unconstrained**. `Torque control` and `Torque  Control` were two nodes, and nothing refused a
  third.

The failure is not cosmetic. `TEACHES` from slides, the alignment pass's components
([ADR-0163](ADR-0163-alignment-direction-and-who-creates-a-canonical.md)) and the workbench's
user edges all key on the Concept. A duplicate splits a course's teaching evidence across two
nodes and neither one is wrong, so nothing surfaces as an error.

A global name constraint — the obvious repair — is **worse than no constraint** here: `Torque
Control` in a TRAINING course and `Torque Control` as a MANUFACTURING concept share a label, and
`REQUIRE c.name IS UNIQUE` would collapse them into one node whose edges span two domains.

## Decision

**A Concept's identity is `(domain, normalized name)`, and `id = hash(domain, normalized name)`
is that identity's single-property key. MERGE on `id`; constrain `id`; never constrain `name`.**

- `concept_node_id(domain, name)` is `concept_` + the first 16 hex of
  `sha256(normalize_domain(domain) + "\x1f" + normalize_concept_name(name))`
  (`doc_tools/utils/concept_identity.py:80-89`). The `\x1f` unit separator is a character
  neither a domain label nor a concept name can contain, so no input pair reassembles into
  another pair's digest input.
- `normalize_concept_name` is NFKC, whitespace collapse, strip, casefold — and **deliberately
  nothing else**: punctuation is not stripped and words are not reordered, because `pre-flight`
  and `pre flight` may genuinely differ and a guessing normalizer merges concepts nobody asked
  it to (`concept_identity.py:56-71`). It is sized for the failures actually seen in slide
  text — stray double spaces, a trailing space, inconsistent capitalisation.
- The domain is *inside* the id, so the same name in two domains stays two concepts. That is
  precisely why the constraint (`concept_id_unique`) is on `id` and **not** on `name`.
- `name` is written `ON CREATE SET` only (`training.py:483`, under the `MERGE … {id: $concept_id}`
  at `:482`), so of two spellings that normalize
  alike the node keeps whichever was written first. A plain `SET` would make a node's display
  name depend on slide order.
- `name_normalized` is stored on the node, so the id is recomputable **from the node** without
  trusting that whatever wrote it used this module.
- The writer and `scripts/neo4j_concept_id_migration.py` compute the id through **the same
  module**. A migration with its own copy of the hash does not fix duplicates; it starts a
  second generation of them.

## Consequences

- One property carries a two-fact identity, which is what makes a Neo4j constraint possible at
  all. Show `name`; match on `id`.
- The id is 64 bits, deliberately: a domain's vocabulary is thousands of names at the outside,
  and the full digest buys noise in every log line and graph browser
  (`concept_identity.py:48-51`).
- **Changing `normalize_concept_name` re-keys every Concept node** and therefore needs a
  migration. `CONCEPT_ID_VERSION` exists as the thing to grep for and compare; it is stored on
  nothing yet.
- The migration is the risky half: re-keying exposes duplicates that must be merged, and the
  merge must **re-point every edge** on the merged nodes — including the workbench's
  `ALIGNS_TO`, which is user data. The follow-up ruling at
  `scripts/neo4j_concept_id_migration.py:14-21` requires it to run under the roll lock with the
  workbench paused, with before/after counts per edge type that must match except for the
  intended merges, aborting and restoring otherwise, and a sandbox dry run first.
- Order is load-bearing and the script enforces it: the constraint is created **last**, in its
  own call. Creating it first fails on any existing duplicate pair; creating it between the id
  assignment and the merge fails on the pair the assignment just made collide.
## Alternatives considered

- **A uniqueness constraint on `name`.** Rejected explicitly by the ruling: *"Do not add a name
  constraint — the same name legitimately exists in different domains."* It is tested **as a
  prohibition**, not merely as a different design
  (`tests/test_concept_id_and_constraint.py::test_the_constraint_is_on_the_id_and_not_on_the_name`).
- **Keep merging on `{name}`** (`#163`'s shape). Rejected: it is the state that was broken.
- **Key on `{id, name, salience}`** (the pre-`#163` shape). Rejected: salience in the key meant
  one node per salience.
- **A readable slug id, `concept_Torque_Control`.** Rejected, and the comment says why it is
  wrong in both directions at once: names differing only in the characters a slug drops
  (`Torque/Control`, `Torque Control`) slug **identically**, while `Torque control` and
  `Torque Control` slug **differently**.
- **A lookup table instead of a hash.** Rejected: the writer MERGEs one concept at a time with no
  view of the rest; a hash is stable across runs and re-ingests without one.
