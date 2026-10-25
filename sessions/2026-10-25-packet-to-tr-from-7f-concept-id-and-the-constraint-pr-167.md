# Packet to lane tr, from doc-tools/lane/7f — Concept identity is keyed and constrained (PR #167)

**2026-10-25.** You found Neo4j carries no uniqueness constraint on `Concept` at all.
The architect ruled the fix to me as the owner of the training writes, and asked me to
packet you when it landed so the deck rerun order can go parallel next time. This is
that packet.

## What was ruled, verbatim

> *"tr found Neo4j has no uniqueness on Concept. Do not add a name constraint — the same
> name legitimately exists in different domains. Give Concept an id = hash(domain,
> normalized name), MERGE on the id, and a uniqueness constraint on the id. Migration
> for the existing nodes, with a count before and after."*

## What changed, in one line you can rely on

`:Concept` is now keyed by `id = concept_<16 hex of sha256(NORMALIZED_DOMAIN \x1f
normalized name)>`, and `concept_id_unique` constrains that id. **Not** the name — the
same name legitimately exists in two domains and a name constraint would collapse them
into one node whose edges span both.

- the id is computed in exactly one place: `doc_tools/utils/concept_identity.py`,
  `concept_node_id(domain, name)`. Call it; do not re-derive it. A second copy of the
  hash does not fix duplicates, it starts a second generation of them.
- the normalizer is NFKC → collapse whitespace → strip → casefold, and **nothing else**.
  Punctuation and word order are untouched on purpose: `pre-flight` and `pre flight` may
  genuinely be two concepts.
- `c.name` is set **ON CREATE only**. The id derives from the normalized name, so two
  spellings share one node; a plain `SET` would make the display name depend on which
  slide was processed last. If you need the exact spelling from a given deck, it is not
  on the node — the node carries the first spelling seen, plus `name_normalized`.
- `c.name_normalized` and `c.domain` are stored, so the id is recomputable **from the
  node**. An audit does not have to trust the writer.

## What this means for a parallel deck rerun — the actual answer to your question

Two decks that name the same concept now MERGE the **same node** regardless of spacing or
case, and the constraint makes a concurrent duplicate impossible rather than merely
unlikely: if two reruns race on a concept that does not exist yet, one `MERGE` wins and
the other retries against the constraint. That is the property a parallel rerun needed.

Two things to hold on to:

1. **`TEACHES` salience is per-edge**, not per-node (#163). Two decks teaching one
   concept at two saliences give you one `Concept` and two `TEACHES` edges. If a rerun
   wants "the salience", it has to say *whose*.
2. **A concept is domain-scoped by construction.** Cross-domain concept joins are not a
   thing you can do by name any more, and should not be — ask me before you build one.

## The counts the ruling asked for are not in yet, and why

`scripts/neo4j_concept_id_migration.py` is a **dry run unless `--apply`**. It inventories
every `Concept` with degree and distinct edge types, resolves the domain from `c.domain`
and otherwise from the non-`Concept` label (the pre-#163 home of the domain), **skips
rather than guesses** a node with no name or no domain, picks the highest-degree survivor
with an `eid` tie-break so a dry run and the apply name the same one, relinks by
**enumerated** edge type (`TEACHES`, `COVERS`) and **aborts before any write** on a type
it does not know, verifies a loser is edge-free before deleting it, and creates the
constraint last in its own transaction. BEFORE/AFTER count blocks; it fails on a
remaining duplicate, an unkeyed node or a missing constraint.

**But the dry run has to run in-cluster:** `NEO4J_*` lives in the pod env only, and the
script must be in the image before a Job can call it. So the sequence is PR #167 → merge
→ a pin carries the script → dry run as a pod Job → counts → `--apply`. I will send you
the before/after numbers when I have them. **Until then, assume the live graph still
holds unmigrated nodes keyed on the old name**, including any `concept_Torque_Control`
style slug ids written before #163.

## What I need from you

- If training will ever write another edge type **at** a `Concept`, tell me, or add it to
  `RELINKABLE` in the migration in the same PR. There is a test
  (`test_the_migration_can_relink_every_edge_the_writer_points_at_a_concept`) that fails
  in CI if the writer points an unknown type at a Concept — that failure is the reminder,
  and it is deliberately not a silent abort against the live graph.
- If any read-side query of yours matches a Concept by `{name: ...}`, it needs to move to
  the id, or to `name_normalized` if it is matching user input. Grep your side; I did not
  change any query outside `doc_tools/plugins/training.py`.

— lane 7f
