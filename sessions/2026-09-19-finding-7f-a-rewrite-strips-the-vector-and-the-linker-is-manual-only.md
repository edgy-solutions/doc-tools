# FINDING — 7f: a re-write strips the vector, and the linker is manual-only

    to:        the architect · ia-74/lane/74 [bd26bdc1] · ia-01/lane/01 (orchestrator) · Chris
    from:      doc-tools :: lane/7f
    date:      2026-09-19 late
    measured:  at bee5b4c, the pushed head. READS ONLY — no store was contacted, nothing built.
    status:    UNCOMMITTED BY ORDER. Commit after the merge decision; a commit now moves the head
               and invalidates the sha PR #1's merge gate is about.

---

## 1. RULED — a re-write that strips an existing vector is a LOSS, not "a thinner row"

The architect's ruling, 2026-09-19 late, on the read below. **It is the first writer item after
the walks draw. Build nothing now, and keep it out of PR #1.**

This overturns a distinction the file itself draws. `ontology_assets.py`, in the Ruling-1 block,
sorts failures into ROW MISSING vs ROW PRESENT BUT THINNER, and puts a failed `embed_document`
firmly in the second bucket:

> *`embed_document` failure inside `sync_ontology_to_weaviate` writes the row without a vector and
> says so. BM25 still answers and a backfill can populate the vector later. Stays best-effort.*

That reasoning is sound for a row being written for the FIRST time — nothing existed, and a
BM25-answerable row beats no row. **It is false for a row that already had a vector.** There the
same code path does not write a thinner row; it destroys a vector that was present, and it does so
through a success path that logs a warning and returns green. The ruling names that what it is.

---

## 2. THE READ — which call runs on an existing uuid, and does it carry the vector

**The call is NOT a `.data.replace`.** `sync_ontology_to_weaviate` has exactly one write path, the
dynamic batch. At `bee5b4c`, `doc_tools/assets/ontology_assets.py`:

    :845   with collection.batch.dynamic() as batch:
    :848   deterministic_uuid = generate_uuid5(str(cls["uri"]))
    :881   add_kwargs: dict = { ... "uuid": deterministic_uuid }
    :895   if cls_vector is not None:
    :902       add_kwargs["vector"] = {"default": cls_vector}
    :904   batch.add_object(**add_kwargs)

**`:895` is the whole finding.** The `vector` key is not set to `None` on an embed failure — it is
OMITTED, so `add_object` takes its own default of `vector=None`.

The predecessor's two measured `.data.replace` sites (`aitool_linker.py:604`,
`collection_marker.py:155`) are **different collections and not on this path at all**. Their
"properties-only" measurement was correct and is not the reassurance it sounds like — see §4.

### Does it carry the vector? No. And it replaces regardless.

Two reads of the installed weaviate-client **4.21.3**:

1. `weaviate/collections/batch/batch_wrapper.py:246, 323, 398, 454` — the client's own docstring,
   at **all four** `add_object` entry points:

   > *"If the UUID of one of the objects already exists then the existing object will be
   > **replaced** by the new object."*

   Replaced. Not merged, not patched.

2. `weaviate/collections/batch/grpc_batch.py:78‑91` — the wire object is rebuilt from scratch on
   every send:

       vector_bytes=self.__single_vec(obj.vector),
       vectors=self.__multi_vec(obj.vector),

   With `obj.vector is None` both are `None`. **There is no "leave the existing vector alone"
   value in the wire format.** The batch object IS the whole object; absence is not "unchanged",
   it is "has none".

**And nothing recomputes it.** The collection is `self_provided` — doc-tools embeds via LiteLLM and
hands Weaviate a finished vector — so a row that arrives without one keeps not having one. *With a
server-side `text2vec` module this defect would self-heal on the next replace.* The same
`self_provided` choice that fix D was about is what makes this permanent.

### Therefore: last writer wins the whole row

A URI written twice gets whatever the SECOND writer had. If that writer's embed succeeded, the
vector is replaced with a fresh one and nothing is lost. If it failed, the row is left vectorless
and the first writer's vector is gone.

**This is a better fit for 74's shape than scattered failures are.** 74 measured *whole namespaces*
— 12 of the 13 BFO and IOF Core rows — not scattered rows. Scattered gateway failures produce
scattered rows. A gateway that is down for the duration of ONE partition's run produces exactly one
manifest entry's worth of vectorless rows, which is a namespace. With `IOF_Core` manifested twice
(fleet `prime_databases.py:174` and `:229`), the same URIs are written by two entries, and the
second entry's run conditions decide the vector for every URI they share — BFO included, since the
IOF Core file carries them.

**So this item and the `IOF_Core` double-manifest collision are ONE item, and it belongs to Lane 1's
held manifest work.**

---

## 3. THE SECOND READ — what triggers `aitool_linker` in the sandbox

**MANUAL ONLY. No schedule, no sensor.** Three independent confirmations, all in
`doc_tools/definitions.py` at `bee5b4c`:

| # | what | where |
|---|---|---|
| 1 | The AITool sensor is **commented out** — the component is imported but never constructed | `definitions.py:221‑226`, the block `# aitool_sensor = AIToolSensorComponent(` … `# _aitool_sensor_defs = aitool_sensor.build_defs(None)` |
| 2 | `Definitions(...)` takes `assets=`, `jobs=`, `sensors=`, `resources=` — **and no `schedules=` at all.** `grep -rn "schedules=\|ScheduleDefinition\|@schedule\|build_schedule" doc_tools/` returns **nothing, repo-wide** | `definitions.py:327‑336` |
| 3 | None of the five jobs selects the asset. `sync_aitool_predicate_to_neo4j` appears in exactly one selection anywhere — `components/aitool_sensor.py:55` — inside the component that item 1 never constructs | `definitions.py:261‑336` |

The retirement is deliberate and dated, and the file says why:

> *`# del _aitool_sensor_defs  # RETIRED 2026-06-13 — gateway v0.2 is sole writer; see ADR-0006
> §Addendum`*  — `definitions.py:382`

and, in the `Definitions()` call itself (`:328‑333`):

> *"The aitool_linker module (with sync_aitool_predicate_to_neo4j) is loaded via all_assets so the
> asset is still callable for one-off manual syncs through the Dagster launchpad. **The SENSOR is
> what's gone** — no automatic polling of DataHub for mlModel MCPs."*

The Weaviate write is reached only from inside that asset: `sync_predicate_to_weaviate` is defined
at `aitool_linker.py:544` and called from exactly one place, `aitool_linker.py:835`, in the body of
`sync_aitool_predicate_to_neo4j` (`:633`). The asset takes an `AIToolSyncConfig` — it cannot run
without someone supplying a `tool_urn`.

### What that means for the three Predicate rows at 00:52:00 UTC

**My linker can only have been that 00:52:01+77s update if a human launched it in the Dagster
launchpad inside that window, with the right `tool_urn`, by hand.** Nothing in this repo can fire it
on its own — there is no clock and no watcher.

**The linker is CLEARED**, per the architect: nothing in doc-tools could have written that update.

**WHAT THE SOURCE ACTUALLY IS — measured by cortex, not by me.** The desktop frontend posts its
whole capability menu on **every authenticated page load**, and carries a **second re-post path**.
Either shows up as an update seconds after the create. That is a measurement and it supersedes what
I had here.

**WHAT I HAD HERE, AND WHY IT IS GONE.** I wrote that a 77-second create→update gap "is the shape of
a saga's second step" — the gateway v0.2 saga being named in my own repo's comments as sole writer
of AITool predicate edges since 2026-06-13. I labelled it an inference and said I had not read the
gateway. The architect is not carrying it forward, and is right not to: **it was a shape argument
about a component I never opened**, offered where a measurement of a different component already
existed. 74 is reading that endpoint. Recorded rather than deleted because the failure mode is this
lane's recurring one — a plausible story about code you have not read, told confidently enough that
someone downstream repeats it without the label.

---

## 4. ONE ADJACENT HAZARD, UNASKED, BECAUSE "PROPERTIES-ONLY" READS AS REASSURANCE

`aitool_linker.py:602‑606`:

    if collection.data.exists(uuid=deterministic_uuid):
        collection.data.replace(uuid=deterministic_uuid, properties=properties)
    else:
        collection.data.insert(uuid=deterministic_uuid, properties=properties)

`data.replace` is documented in the installed client (`collections/data/executor.py:248‑257`) as
**"equivalent to a PUT operation"**, building a fresh object at `/objects/{class}/{uuid}`. Its
`vector` parameter defaults to `None` and this call site does not pass one. **Same whole-object
replacement, same stripping, on the `Predicate` collection.**

**It has NOT bitten.** 74 measured `Predicate: 135 rows, 0 without a vector`. It is a loaded gun,
not a wound — and it is loaded precisely because the call is properties-only. The predecessor's
measurement was right; the word "only" is what makes it sound safe.

**Not mine to touch.** It is the architect's ruling and it is held with the rest.

**AND IT IS SMALLER THAN IT LOOKED** (architect, same ruling). The path is still destructive, but
§3 establishes that it can only run when a **person launches the asset by hand** — there is no
clock and no watcher anywhere in this repo that can reach it. So it stays held with everything
else, and **nobody needs to guard against it tonight.**

---

## 5. MEASURED vs INFERRED

### MEASURED — read at `bee5b4c`, this session

| claim | where |
|---|---|
| the ontology leg's only write is `batch.add_object`, and the `vector` key is omitted on embed failure | `ontology_assets.py:845, 848, 881, 895, 902, 904` |
| batch add on an existing uuid REPLACES the object | weaviate-client 4.21.3 `batch/batch_wrapper.py:246, 323, 398, 454` |
| the wire object carries no "unchanged" vector state | `batch/grpc_batch.py:78‑91` |
| `data.replace` is a PUT and defaults `vector=None` | `data/executor.py:248‑257` |
| `aitool_linker`'s Weaviate write is reachable only from the asset | `aitool_linker.py:544` defined, `:835` called, `:633` the asset |
| the AITool sensor is constructed nowhere | `definitions.py:221‑226`, and `AIToolSensorComponent(` appears at that one commented line only |
| there is no schedule anywhere in `doc_tools/` | repo-wide grep, empty |
| no job selects the asset | `definitions.py:261‑336` |

### INFERRED — labelled, not findings

| claim | why it is a guess |
|---|---|
| a whole-partition gateway outage is what produced whole vectorless namespaces | fits 74's shape better than scattered failures; **the Dagster run logs would settle it** and I did not read them |
| ~~the 77-second gap is a saga's second step~~ | **WITHDRAWN.** Superseded by cortex's measurement of the desktop frontend (§3). It was a shape argument about a component I never opened |
| the server honours the client's documented replace semantics | I read the CLIENT's docstring, repeated at four call sites, plus the wire format. **I did not measure the server**, and I am not permitted to |

**That last row is the load-bearing one.** The conclusion rests on the installed artifact's own
statement about a server I did not touch. It is strong — four docstrings and a wire format that has
no third state — but it is a read of documentation.

**RULED (architect, 2026-09-19 late): NO SCRATCH COLLECTION TONIGHT.** The documentation read is
enough to hold the ruling, and **the writer fix will carry its own seal when it is built.** That is
the right place for the measurement: a seal that runs with the fix proves the behaviour on the
server the fix ships against, where a scratch experiment tonight would prove it on a server nobody
is deploying to.

---

## 6. STANDING

* Reads only. Zero store contact, this finding and the one before it.
* Nothing built. Both items are held: the writer fix until the walks draw, the `Predicate`
  hazard under the architect's ruling.
* Out of PR #1, by order.

Lane: doc-tools/7f
