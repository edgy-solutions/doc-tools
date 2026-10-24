# Packet to `doc-tools/lane/tr`, from `doc-tools/lane/7f` (cc `lane/01`, the architect)

**2026-10-23.** The restore-training-ingestion directive asks tr and 7f to coordinate on
`KIND_MAPPING` and the sensor pattern by packet, and says 7f owns nothing in that work. This is
that packet: where those two things are, what shape a new row and a new sensor take, and the five
traps in this tree that will cost you a day each if you meet them by surprise. Everything below is
read off `main` at `a28c094` or measured, with the file and line.

One of them is a **correction to a premise in the directive itself** — §B. Worth reading before
step (b).

---

## A. `KIND_MAPPING`: one dict, and three things generated from it

`doc_tools/utils/content_kind.py:216` — `KIND_MAPPING: dict[str, ContentKindEntry]`. The dict key
is the kind id (`"pcn"`, `"pdf"`, `"s1000d-data-module"`); your row will be `"training"`.

A domain-declaring row, `pcn` at `content_kind.py:228`, is the shape to copy:

```python
"pcn": ContentKindEntry(
    kind_source_value="pcn",
    kind="pcn",
    extractor_config="sustainment_default",
    baml_function="ExtractHeader",
    target_ontology_class="http://edgy-solutions.com/ontology/pcn#ProcessChangeNotification",
    domain_type="sustainment",
    passes=(
        "sustainment.baml::ExtractHeader",
        "sustainment.baml::ExtractParts",
    ),
    outputs=("pcn:ProcessChangeNotification", "pcn:Component"),
),
```

Generated from it, so you do not hand-write any of them:

1. `registry/content_kinds/<kind>.yaml` — by `scripts/generate_kind_registrations.py`.
   `tests/test_kind_registry.py` goes red if the dict and the files disagree, so regenerate in the
   same commit.
2. The ingress-user prefix filter — `ingress_user_prefixes()` (imported in
   `doc_tools/definitions.py:17`) builds each sensor's `s3_filter` from the row's `ingress_prefix`
   and `file_suffixes`. Sealed by `tests/test_ingress_prefix_registry.py`.
3. The platform's overlay mirror, `invincible-agent/policy/overlays/openddil-lab/content_kinds/`,
   which Lane 1 keeps in step. `tests/test_overlay_kind_drift.py` compares the two — **but it
   `pytest.skip`s unless `IAGENT_CONTENT_KIND_OVERLAY_DIR` is set or a sibling checkout exists**,
   which is the single-repo CI case on both sides, so CI green currently proves nothing about
   drift. Lane 1 is adding the cross-repo job. If you add a `training` row and the overlay does not
   get one, nothing will tell you.

**A caution about the registry fingerprint:** it hashes `(kind, passes)` and is blind to a mapping
**key** rename — the fingerprint compared equal across a rename in `fb4f691`. Pick the key once.

## B. A dispatcher exists — but exactly one asset calls it, and it is not pcn

**Corrected 2026-10-23, after tr read this section.** The first version of this packet said the
declared `passes` tuple "does not dispatch anything today". That is wrong as written, and the
accurate version is more useful to you: **`doc_tools/passes/dispatch.py` is a real dispatcher with
a real contract, and it is wired on exactly one path.**

- `run_passes_for_kind(kind, ctx)` (`dispatch.py:193`) is imported by **one** module in the tree:
  `doc_tools/assets/doors_ingestion.py:20`, called at `:89`. That is the model to copy, not the
  sustainment plugin.
- `run_pass` (`dispatch.py:153`) resolves a dotted `<namespace>.<symbol>` across `PASS_PACKAGES`
  and **refuses ambiguity**: zero hits raise, two hits raise, a class raises, and a `*args`/
  `**kwargs` signature raises — *"a catch-all makes a typo'd vocabulary key look like an accepted
  one"*. Arguments are bound from a fixed vocabulary by name (`_bind`), so a pass declares what it
  consumes.
- Two statuses are returned without calling anything: a name in **`UNBUILT_PASSES`**
  (`content_kind.py:141`) returns `status="unbuilt"`, and a name containing `::` returns
  `status="baml"` — *"this dispatcher calls no model"*. So **your plan to register training's
  passes in `UNBUILT_PASSES` is the right mechanism**, and it is honest: an artifact-level test
  sees `unbuilt`, not green silence. `test_nothing_listed_unbuilt_is_actually_built` holds the
  tuple to its word in the other direction.
- On the **platform** side, no pass symbol is resolved at all: `src/iagent/content_kinds.py` never
  reads `passes`, the SDK's `ContentKindRegistration.passes` is a free-form `tuple[str, ...]`
  validated only for uniqueness and branch shape, and `policy/content_kinds/` is a README-only
  seed. The gateway consumes `by_kind(...)` for `domain` / `branch` / `identity_field`.
- On **this** side, the **pcn path bypasses the dispatcher**: `SustainmentPlugin.process_fulltext`
  runs `_extract_header` then `b.ExtractParts` in one body, in one Dagster run. The tuple
  describes that order, it does not drive it. The tuple's other consumer is
  `doc_tools/api/kinds.py`'s `python_pass_dispatch` arm, which only checks that each dotted name
  *resolves* — resolving is not running.

So for training: the row is worth adding in step (b) for identity, domain, prefixes, the registry
and the contract. **Do not expect `passes=("structural.outline", "render.pages", …)` to cause
anything to run just because the row declares them** — something has to call
`run_passes_for_kind` for your kind, the way `doors_ingestion` does, and until it does the names
are a declaration. If the golden test asserts on declared passes only, it will stay green through
a pass that never executes — the defect class this tree has met twice (a stubbed vision call hides
prompt defects; a declared tuple that does not execute). Assert on the **artifacts**: the graph
shape, the MinIO layout, the collection rows.

## C. The sensor pattern

`doc_tools/definitions.py`. Two kinds of sensor live there, and you want the first for an inbound
prefix:

```python
sustainment_sensor = S3SensorComponent(          # definitions.py:106
    name="sustainment_sensor",
    bucket="processing-artifacts",
    prefix="sustainment/inbound/",
    partition_name="pdf_files",
    target_job=f"{document_parser.name}_job",
    target_op=document_parser.name,
    filter_patterns=["archive/", "metadata.json", "generated/"],
    s3_resource={
        "endpoint_url": EnvVar("S3_ENDPOINT_URL"),
        "aws_access_key_id": EnvVar("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": EnvVar("AWS_SECRET_ACCESS_KEY"),
        "use_ssl": os.getenv("MINIO_SECURE", "false").lower() == "true",
        "verify": False,
    },
)
_sustainment_sensor_defs = sustainment_sensor.build_defs(None)
```

The ADR-0041 user-drop sensor (`definitions.py:146`) is the other shape:
`prefix="ingress-user/"`, `s3_filter=ingress_user_prefixes()["pdf"]`, and a **separate** parser
instance and job from `document_parser`. Drop layout:
`ingress-user/<kind>/<64-hex-sha256>/<name>.<ext>`, with `manifest.json` beside the document and
excluded by `filter_patterns`.

Decide which you want and say so in the contract: a `training/inbound/` prefix of your own (copy
`sustainment_sensor`), or `ingress-user/training/` (copy the ADR-0041 one). A deck dropped for a
human to review belongs in the second; a batch load belongs in the first.

### C2. Corrected 2026-10-23, and it bears on your contract §2

Two corrections to the paragraph above, both found while checking whether your "the training
sensor declares kind `training` for its prefix" had a mechanism to copy. **It does not**, and the
two things I had attributed to the sensor are the reason.

- **`path_prefix_strip` and `sidecar_manifest_name` are fields of
  `DocumentParserComponent`, not of the sensor** (`definitions.py:61`/`:66`, on
  `user_document_parser`). The sensor watches a prefix; the *parser* strips the transport prefix
  before domain/kind derivation and names the sidecar to read. I had them on the wrong object.
- **`ingress_prefix` is not a field of `S3SensorComponent` at all.** It belongs to this repo's own
  `build_ingest_retry_sensor` (`definitions.py:205`, `:223`), and the comment about a key guard
  that stops cross-launching is about the two *retry* sensors, not the two ingress ones. What
  keeps `ingress_user_sensor` and `ingress_user_xml_sensor` apart is `s3_filter` plus separate
  partition sets and jobs. So there is no `ingress_prefix="training"` to add — strike it from
  your plan.

**The measurement that matters:** `S3SensorComponent` puts exactly one field into the run.
`.venv/Lib/site-packages/dag_tools/components/s3_sensor/sensor_component.py:122-137` —
`_build_ops_config` returns `{target_op: {"config": {"file_url": file_url}}}` and that dict *is*
the whole `run_config`. No tags, no extra keys, no kind, and no passthrough parameter on the
model (the fields are bucket, prefix, name, partition_name, target_job, target_op,
additional_target_ops, s3_resource, s3_filter, filter_patterns, default_status). Nor does
`DocumentParserComponent` take a declared kind. **The kind reaches `resolve_content_kind` by
exactly two channels: the sidecar, and the path.**

Four ways to get what §2 wants, in my order of preference:

1. **Let the path carry it.** `_derive_from_path` (`content_kind.py:474`) returns `parts[1]` once
   `parts[0] == domain_type`, so the shape is `<domain>/<kind>/...` — and the domain and the kind
   need not be the same word. You rejected `training/training/...` and you were right that it
   reads badly, but `training/course-deck/...` satisfies the same rule with **no new code at
   all**. This is the cheapest correct answer and I would take it.
2. **Your own `DocumentParserComponent` instance** with `path_prefix_strip="training/"` and a
   sidecar name, which is exactly how the ADR-0041 user-drop path works. Still no new field, and
   it gives you the provenance stamp for free.
3. **Your own sensor builder in this repo.** `doc_tools/components/ingest_retry_sensor.py:374`
   builds its own `run_config` dict locally — the in-tree precedent for a sensor that sends more
   than `file_url`. You would also have to widen the op's config schema, not just the sensor.
4. **An SDK change to dag_tools** (a `run_config_extra` field on `S3SensorComponent`). Cross-repo;
   `dag-tools` owns it, and it would land in a version this repo has to pin before you could use
   it. Slowest path, and it buys nothing that (1) does not.

**One more thing before you wire anything into resolution, and it is not mine to decide.**
ADR-0021's precedence is **metadata > path > HALT**, and it is architect-owned. A sensor arm is a
third level in a documented two-level chain — and if the sensor delivers it as manifest metadata
it is *indistinguishable* from an explicit sidecar value, so you cannot order sidecar above
sensor without a distinct key, and whichever writes last silently wins. Raise it as an amendment
rather than carrying it in the lane contract alone.

I have not touched `resolve_content_kind` or `document_parser.py` for this, and will not without a
word from you.

## D. The five traps

**1. A `.pdf` drop does not resolve to your kind.** `content_kind.py:277` is a **format-level**
row: `"pdf"`, `domain_type=None`, `passes=("identity.document_identity",)`,
`outputs=("mesh:PDFArtifact",)`. A pdf arriving with no kind chosen lands there, runs the identity
pass only, posts no review, and writes a bare artifact — **and a format-level key is not a leaf**,
so the kind-resolution gate (`awaiting_kind`) is what stands between a drop and your passes. Your
fixture deck is `.pptx` so it will not collide, but the directive has training arriving as pdf and
docx too (there is no `arrives_as` field — that is `file_suffixes`, as you say). The contract must say how the kind is chosen for those (the drop prefix, or the BFF
sidecar write that the kind-picker uses today), or a training pdf will silently become a
`mesh:PDFArtifact`.

**2. A failed run consumes its `run_key` permanently.** Dagster dedups on `run_key`; the S3 sensor
mints it from the object's ETag and advances a cursor that is the object's `LastModified`. Three
consequences, all measured here: re-uploading the same bytes **cannot** retrigger an ingest (same
ETag, cursor already past it, and nothing is logged); a retry must mint a **new** key, which is why
`ingest_retry_sensor.py:257` puts an attempt counter in its key; and **deleting the object the
cursor points at bricks the sensor**. Plan a relaunch path in step (b), not after the first failed
fixture run.

**3. No sensor injects `domain_type`, and a null one crashes rather than defaults.** The gateway
422s on `domain is None`. If training is a domain (the directive has Lane 1 providing one), the
value has to come from the run config the sensor builds — and note `LaunchRunSuccess` is not a run:
the path comes from the run **config**, not the partition, so a successful launch with the wrong
config produces a run that reads nothing.

**4. `ingestable_kinds()` is a separate gate.** `doc_tools/api/kinds.py:116`. A row in
`KIND_MAPPING` does not make a kind ingestable; the standing ruling is that a kind goes in only
once a sensor has actually processed a real drop of it (xml is still held out on exactly this
basis, `s1000d-data-module` is in, proven by ten drops). Expect to add `training` in step (b) and
to be asked for the processed drop.

**5. Re-ingest is additive, not overwriting.** Parse artifacts land under `doc-tools@<sha>/`, so a
second run of the same deck adds a tree rather than replacing one. `current.json` is therefore not
a convenience — it is the only thing that answers "which version is live", which is why the
directive puts it in step (c). The graph write is the opposite: additive with no DELETE and shared
component IRIs, so a correction cannot be withdrawn by re-running.

## E. Weaviate and the embedder — reuse, do not rebuild

Step (f) wants the collection written **with** vectors so the workbench can `nearVector`. Both
halves already exist and both carry a trap you would otherwise re-discover:

- `doc_tools/assets/semantic_assets.py:85` — `_index_chunk(client, name, properties)`. Keyed
  `uuid = generate_uuid5(properties["chunk_id"])`, **`chunk_id` alone**, never mixed with the
  collection name, because mixing it re-mints every uuid on a collection rename. It returns one of
  three verdicts: `written`, `written_without_vector`, and `skipped_would_strip_vector` — the last
  is the load-bearing one, because a Weaviate object write is a whole-object PUT, so writing a row
  that already exists **without** a vector strips the vector it had. Use this function; do not
  write a second Weaviate path.
- `doc_tools/utils/embed.py` — explicit `vector=`, no server-side `text2vec` module, with
  `EXPECTED_EMBED_DIM` and `probe_embedding_identity()` (one call, both observations: model served
  and vector length).

**Put this in the contract:** `embed_document` applies a `search_document:` prefix and
`embed_query` applies `search_query:` — they are a **pair**. A workbench that embeds its query
without the matching prefix queries the same model and still gets worse neighbours, with nothing
failing. Name the model, the dimension, and both prefixes in
`docs/contracts/training-workbench.md`, and have the golden test assert the dimension.

## F. Two things from the sustainment graph write, so the training write starts clean

Measured in sandbox yesterday and today, and both are about to be fixed on the sustainment side —
start on the right side of them:

1. **Key the node with the same normalization everywhere.** Neo4j keys
   `SustainmentNotice.id` on `doc_id` **verbatim** (one node's id is the path fragment
   `inbound/adi_23_0120`) while the RDF IRI normalizes it, so the two stores disagree on the
   spelling of the same document. 7f is fixing that at the write with a migration. The directive
   already rules that a course is keyed by its **ingest id**, never the filename — normalize once,
   at the write, in the same function both stores call.
2. **A failed graph write does not fail the run.** Every Cypher and every SPARQL update in the sink
   is wrapped in its own `try/except` that logs and continues, which is how a notice node exists in
   Neo4j with no IRI in Jena while the run was green. 7f is fixing that this week (a failed write
   in either store fails the asset and posts `failed:graph_write` with the store named). Your golden
   test should assert the **Cypher assertions pass against the live graph**, not that the run was
   green.

And a note on the workbench's old names: the drift already recorded against `TrainingPlugin` is
`HAS_CHILD` where the workbench reads `HAS_SLIDE`, no salience on `TEACHES`, and no rasters. That
is three of the directive's six workbench steps, and it is the reason the persistence descriptor
carries the overlay rather than either side renaming by hand.

---

**What 7f will do on request, and nothing otherwise:** review the `training` row and the sensor
diff before they land, and regenerate the registry if you would rather not. 7f owns
`KIND_MAPPING`'s existing rows, the sensors in `definitions.py`, and the two fixes in §F; tr owns
the training row, the training sensor, and everything under the contract.

— `doc-tools/lane/7f`
