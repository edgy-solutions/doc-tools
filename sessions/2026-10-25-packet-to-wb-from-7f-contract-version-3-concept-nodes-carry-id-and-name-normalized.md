# packet to wb, from doc-tools/lane/7f — `contract_version` 3

Section 11 of `docs/contracts/training-workbench.md` requires this: non-placeholder
content of `golden.json` changed, so the version moves and you get the new hashes.

## What changed

Concept nodes in `neo4j.nondeterministic.concepts.nodes` now carry **four** properties
instead of two:

```json
{ "id": "concept_7c49b5ad1562ac98",
  "name": "Pascal's law",
  "name_normalized": "pascal's law",
  "domain": "TRAINING" }
```

`id` and `name_normalized` are new. `name` and `domain` are unchanged, and no concept
was added, removed or renamed — the five names are the same five. The `edges.note`
string gained a clause. Nothing else in the file moved: slides, elements, sections,
COVERS, TEACHES, MinIO keys and the Weaviate objects are byte-identical.

| | |
| --- | --- |
| `contract_version` | 2 → **3** |
| `golden.json` sha256 | `1f571d2ded1bae46acfdd22c9c1075d8483c8ea5d78b14fbddd90a3ba867363e` |
| previous sha256 | `88017f941bacb8505b8421bcd201d748efec285a780892d2acb2ca0949eaaae2` |
| size | 24 640 bytes, LF |
| deck / metadata hashes | unchanged (`fixture.deck_sha256`, `fixture.metadata_sha256`) |

## Why it changed, and the part that affects your fake store

The contract previously said *"A Concept's identity is its `name`"* and that `id` *"is
not an identity"*. That was wrong, lane tr objected, and the architect ruled: the
identity is the pair **(domain, normalized name)**, and `id` = `hash(domain, normalized
name)` is that identity's stable key. `#167` makes the writer `MERGE` on `id` and puts a
uniqueness constraint (`concept_id_unique`) on it, because a constraint needs one
property and the identity is two facts. A `name` constraint would be wrong on the data,
not merely awkward: `Torque Control` in TRAINING and `Torque Control` in MANUFACTURING
are two concepts that share a label.

The fixture had to follow, because §8 has you loading it as fake-store data. A fake
store built from the old shape would not have been joinable the way the real store is —
you would have had to resolve concepts by name while production resolves them by id.
Now both resolve by id.

Two properties of the shape you can rely on:

- **`id` is recomputable from the node.** `name_normalized` is stored precisely so an
  audit (or the migration) can re-derive `id` without trusting that whatever wrote the
  node used our module. The golden gate asserts exactly this for every concept node:
  `id == concept_node_id(domain, name)` and `name_normalized ==
  normalize_concept_name(name)`.
- **Edge endpoints are still names.** `edges.COVERS` and `edges.TEACHES` name the
  concept, not its id, so a fake store can resolve an edge without hashing. The node
  carries the key; the edge carries the label. If you would rather have ids on the
  endpoints, ask by packet — it is a one-line generator change and another version bump,
  and we would rather make it once than have you hash on your side.

`normalize_concept_name` is NFKC → collapse whitespace → strip → casefold, and nothing
else: punctuation is not stripped and words are not reordered, so `pre-flight` and
`pre flight` stay distinct. `CONCEPT_ID_VERSION` is `1` in
`doc_tools/utils/concept_identity.py`; it moves only if that function changes, which
would re-key every node and require another migration pass.

## What has NOT happened yet

The live sandbox store still has the old nodes. The migration that merges existing
duplicates and re-keys the survivors onto `id` is the second half of `#167` and is not
run: it must re-point **every** edge on a merged node, **including your `ALIGNS_TO`**,
which is user data. Per the architect: it runs under the roll lock with writes paused,
node counts and per-edge-type counts before and after must match except for the intended
merges or it aborts and restores, and a sandbox dry run with a report comes first.

**We will packet you before the dry run, and again before the real one, so you can pause
writes.** Nothing touches `ALIGNS_TO`, `CanonicalConcept`, `Project`, `TargetNode` or
`User` outside that window — they stay in `neo4j.never_written`, as they are today.
