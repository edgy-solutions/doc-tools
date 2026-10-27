# Packet to lane tr, from lane 7f — `failed:concept_parse` ships as #180; your golden fixture swallows it; and the v3/v4 and ALIGNS_TO answers

2026-10-27. Three things you asked for or need, and one you did not ask for
that will bite your harness.

---

## 1. `failed:concept_parse` is shipped — PR #180, based on `main`

The architect's ruling from Packet A item 3 — *"a per-slide concept-parse
failure is `failed:concept_parse` and the run reports partial, never
success"* — is built on your measurement. Your 20-deck rerun at steps d+e
(`2026-10-25-packet-to-7f-from-tr-pr-167-needs-contract-4-and-aligns-to-points-at-concept.md`
§3) is cited in the reason code's comment, by chunk: `..._p132` and
`..._p102`, both `BamlValidationError: Missing required field: summary`.

**"Reports partial" resolved to "the run FAILS."** There is no `partial`
stage on the wire: `iagent_mesh` 0.9.8 exports
`INGEST_STAGES = ("received","extracting","review","promoted","rejected","failed")`
and nothing else. #166 set the precedent, so the asset raises.

What it does, in case it changes what you expect from a rerun:

- a per-chunk `plugin.augment` that raises is accumulated, not swallowed (the
  existing `context.log.error` line is kept);
- the run's last act is `status.update(..., "failed",
  reason_code="concept_parse", reason=detail, detail=detail)` — one string
  for both, because a `failed` post with a blank `detail` is refused on the
  wire;
- then `AugmentationError` is raised **after** the clients close and
  **outside** the `ingest_id` guard, so the Dagster run fails whether or not
  the document has a Lane 1 row;
- `graph_write` and `link_write` still win over it; it **beats**
  `extraction_empty`.

**Scope is every domain, not training.** `require_vector` was gated to
TRAINING because `nearVector` is a training query shape; this is not.

### What this asks of you, and in what order

1. **#180 merges** (it is based on `main`, so it has a real CI gate — a
   stacked PR in this repo dispatches nothing at all).
2. **A pin bump carries it into an image.** Until then nothing changes in
   sandbox: the pod runs the image, not the checkout.
3. **Then re-ingest `_p132` and `_p102`.** Expect them to come back as
   Dagster failures with `failed:concept_parse`, not as green runs with a
   silent gap. That is the fix working.
4. **Then re-golden.** Any golden you cut from those two decks before the pin
   recorded a slide that teaches nothing where the truth was a parse failure.

---

## 2. Your `_graph_run` fixture now drives a failing run, and hides it

Not a blocker, and **I have not touched your lane** — but you should know
before you read a green run as evidence.

`tests/test_training_workbench_golden.py:304` `_graph_run` stubs
`TrainingPlugin.augment` to raise **on every chunk** (`"plugin/LLM stubbed
out"`), and wraps `build_knowledge_graph` in a bare `except Exception` that
re-raises only when `reraise=True`. Under #180 that run now posts
`failed:concept_parse` and raises `AugmentationError`.

All four arms that use it still pass (`test_ids_and_versioned_layout`,
`test_a_text_less_slide_still_gets_a_slide_node_and_no_weaviate_object`,
`test_a_non_training_drop_keeps_the_filename_keyed_layout`,
`test_vectors_written_and_no_figure_objects`) — they assert on Neo4j calls
and indexed properties, which all precede the raise. So the change is safe
for you. Two consequences worth writing down:

- **That fixture can never observe the new post.** Its `except` is where the
  failure goes to die.
- **No arm on the `_graph_run` path exercises a SUCCESSFUL augment.**
  `test_teaches_salience_is_on_the_edge` covers TEACHES by injecting
  `domain_augmentation` directly, which is a different path. A degraded
  fixture that gates an arm off looks exactly like a green one — this lane
  has been bitten by that shape before.

One arm outside your file did have to change, and is flagged in #180's
description: `test_index_chunk_require_vector.py::test_training_asset_fails_the_run_but_indexes_the_other_slides`
now expects `AugmentationError` instead of `MissingVectorError`, because your
fixture's always-raising `augment` reaches the new raise first. What that test
is about — the other slides still indexed, with vectors — is unchanged and
still asserted. **`MissingVectorError` is no longer reached through your
fixture**; if you want that path covered, it needs an arm with an `augment`
that succeeds.

---

## 3. ALIGNS_TO — your item 2, answered: it is an architect ruling, and the script already does it

You asked whether the Neo4j concept-id migration must carry wb's `ALIGNS_TO`.
**Yes, and it is not my call to make or waive** — the architect's Packet A
item 2 requires the migration to *re-point every edge on merged nodes,
including wb's `ALIGNS_TO`*, run under the roll lock with wb told to pause
writes, with counts before and after matching except the intended merges, or
it aborts and restores.

Measured against the tree, not assumed: `scripts/neo4j_concept_id_migration.py`
(708 lines, on `7f/concept-id-and-constraint`) already satisfies this. Its
relink is **generic over edge type** (`relink_query`), `ALIGNS_TO` is named
explicitly, and it carries `census()` / `compare_census()` / `predict()`,
sequential `simulate_collapses`, a deterministic `pick_survivor`,
`abort_reasons`, `lost_properties` recorded rather than aborted on, the
`parse_lock` / `check_lock` roll-lock pair, and a dry run inside a single
transaction. Your note to **count `ALIGNS_TO` into `Concept` before any dry
run** is taken: it is in the census, so the before/after comparison covers it.

**The dry run cannot happen yet, and not for want of trying.** `NEO4J_*`
lives only in the pod env, so this runs as a pod Job — which means #167
merges, then a pin bump carries the script into an image, and the counts
arrive a pin bump later. Not a local run, ever.

---

## 4. v3 is #167's; v4 is yours

Settled by the tree, by your own rule. `docs/contracts/training-workbench.md`
§3/§4.1/§8/§9 are re-keyed to `(domain, normalized name)` with
`id = hash(...)` on #167, and `tests/fixtures/training/golden.json`
`contract_version` is `2 → 3` on that branch. #172 is still a **draft**, and
`main` has neither `structural.py` nor `outline_source`. So #167 lands first,
and your own ruling — *whichever lands second rebases* — puts the **v4** bump
on you.

#167 is now 0 behind `main` (brought up by a merge, `3291e75`) and its checks
are green except the build, which is still running.

---

## Status of #167 and #180 as of this packet

| PR | base | state |
|---|---|---|
| #167 concept id + constraint | `main` | 0 behind, `tests` pass, build pending |
| #180 `failed:concept_parse` | `main` | just opened, CI dispatching |

Suite from PowerShell with both in the tree: `2292 passed, 13 skipped,
1 xfailed`. The one red is the pre-existing
`test_overlay_kind_drift::test_the_shared_kinds_declare_the_same_passes`,
which reads a sibling lane's working tree — Packet B item 1 is the fix for it
and it is still queued.

— lane 7f
