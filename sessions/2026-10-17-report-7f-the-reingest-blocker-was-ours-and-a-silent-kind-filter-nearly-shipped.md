# Report: the MRAD re-ingest blocker was ours, the cad row already exists, and a silent `kind` filter nearly shipped

doc-tools/lane/7f, 2026-10-17 (overnight, Day 2 continued)

Four PRs merged this segment: **#133** (report), **#134** (cad survey), **#135**
(the xml retry sensor, two commits). Two packets placed uncommitted in the peer
tree. One pin rolling.

## 1. Day 2 cad survey — the premise was wrong, and that was the finding

Merged as **#134**. The packet asked "what would a cad kind need to be
ingestable". The answer is not "a kind": **the `cad` row already exists**
(architect-authorised 2026-10-13) with `target_ontology_class =
mesh:CADArtifact` and `passes = ("cad.cad_document_identity",)`. So the survey is
**six measured gaps**, and the unbuilt pass everyone thinks of first is not the
largest.

In the order a drop hits them: no sensor watches a cad prefix; the row declares
no `ingress_prefix` and no `file_suffixes`, so no key pattern can be generated;
the pass is in `UNBUILT_PASSES` and must be a module-level **callable** (dispatch
refuses a class by contract, proven by `s1000d-data-module` /
`pass_is_a_class`); **nothing produces CAD metadata for the pass to read**, which
is the actual project and is **per-format** (STEP tractable, DXF a library,
native CATIA/SolidWorks a vendor toolkit); `domain_type = None` short-circuits
the write at "origin unresolved"; and `document_parser.py:221` **raises** on a
`domain_type` of `cad`, because `cad` is already live as Lane 1's **file-format**
prefix and must not leak in as a semantic domain.

**Not a gap:** `mesh:CADArtifact` **is** declared (`mesh_system.ttl:808`) and is
**not** in `PHANTOM_OUTPUTS`, unlike the three sibling output classes Lane 1
still owes. A cad kind is not blocked on an ontology commit.

Recommendation on the record: **STEP only** for a first increment, with
DWG/DXF/native refused by reason code, so no vendor-toolkit dependency is bought
before the first artifact exists.

**I corrected this survey after writing it** (`0b022c8`), because code I wrote
the same night disproved one of its gaps — see section 3.

## 2. #135 — the re-ingest blocker was OURS

Lane 1 placed a packet saying the MRAD re-ingest could not run, and they were
right, and the cause was in this repo. `build_ingest_retry_sensor` was wired
**once**, with the PDF triple, so a retry row for an xml drop finds no
`user_pdf_files` partition carrying its digest and is refused on every tick.
Writing the rows first would have bumped ten `attempt` counters and achieved
nothing.

Merged as **#135** (`89e914e`): `ingest_retry_sensor_xml` →
`xml_graph_sync_job` / `extract_rdf_from_xml` / `xml_files`. A **separate**
sensor, not a widened one, for the reason already written into
`definitions.py:225` — a sensor has ONE `target_job`.

**The hazard that shaped it.** `object_key` comes from `row["source_object_key"]`
when present, and only otherwise from the partition set. **The partition lookup
was the only thing telling a PDF row from an xml one, and `source_object_key`
bypasses it entirely.** Two unfiltered sensors would have cross-launched —
`xml_graph_sync_job` on a PDF key, the mirror image of the D2 defect the xml
sensor's own comment exists to prevent. So `ingress_prefix` is now a required
keyword, its registry key pattern is compiled at **build time** (an unknown
prefix raises; a sensor that silently refuses every row for ever is the worse
failure, and this repo has shipped inert sensors before), and the resolved key is
matched against it **whichever branch produced it**.

**Lane 1's `kind` claim did not hold here.** They reported that
`GET /ingest/retries` carries `kind` (`pdf`/`xml`) per entry. **Measured: `kind`
appears nowhere in this repo** — not in the sensor, not in its docstring, not in
the only fixture. The queue has also been empty on 109 of 109 ticks, so no real
row has ever been observed on this side. Not a contradiction of their API; it
means we cannot verify it, so the guard does not depend on it.

Verified: **22 passed** in the sensor file, full suite **1751 passed, 17 skipped,
7 deselected**, both sensors load and register `RUNNING`, and the `run_config`
shape is identical to what `S3SensorComponent` emits with no
`additional_target_ops` on the xml sensor, so a single-op config is correct.

## 3. The near miss, which is the most useful thing in this report

I first wrote the `kind` pre-filter as **"skip any row whose `kind` differs from
my prefix"**. Reviewing it against Lane 1's own population stopped it: those
rows are content kind **`s1000d-data-module`**, not `xml`.

So that filter would have made **both** retry sensors skip **all ten rows in
silence** — no refusal, no warning, the queue draining to nothing with no log
line saying why. **Strictly worse than the cross-launch it sat beside**, because
a cross-launch leaves a failed run and this leaves no evidence at all. It would
have presented to Lane 1 as "7f says the sensor is live and nothing happens".

Fixed before it shipped (`cd611b7`): the silent skip now requires the `kind` to
name **another registered ingress prefix**. Anything else — `s1000d-data-module`,
an empty string, a missing field — falls through and is judged on its key.
Pinned by a test that **launches** an `s1000d-data-module` row carrying a legal
xml key.

**The reusable shape:** a filter written against a field whose values you have
never observed will silently discard the exact population it was built for. The
safe form is to skip only values you positively recognise, and let everything
else fall through to a guard that fails **loudly**.

This also corrected #134's gap 1, which had called the per-kind-sensor question
an open ruling. It is not: the repo has decided it twice now, and the reason is
in `definitions.py:225-229`.

## 4. Lane 1's second ask: confirmed, and deliberately not written

Their measurement is right. `IngestStatusResource.update` is called **only** from
`document_parser.py` (:330, :357, :722, :770), and `extract_rdf_from_xml`
(`doc_tools/assets/xml_ingestion.py:165`) never references the resource. **The
xml path is row-silent**, which is why ten rows read `failed:timeout` on 10-13
while the drops actually completed all five stages and wrote instances. A
relaunched run repeats it: the graph write lands, the watchdog fails the row.

We should post the stages, and I have not, because **`review` files a
`document_promotion` task** and an s1000d module has no PCN/PDN card to vet
against the review standard. That is a ruling, not a fix — so it went to the
architect rather than into a pin.

## 5. What was placed, and what is owed

Two packets placed uncommitted in `invincible-agent/sessions/`:

- **to Lane 1** — the sensor is built; "live" means **rolled, not merged**, so do
  not write the rows until I name the pin; the exact legal key shape
  (`^ingress-user/xml/[0-9a-f]{64}/[^/]+\.xml$`, so an `archive/` path or a
  capital `.XML` is refused loudly); that omitting `source_object_key` falls back
  to the partition set; that `attempt` must be an int >= 2; that `xml`,
  `s1000d-data-module` or no `kind` all launch and only `pdf` is skipped; and a
  small correction — the PDF retry sensor's job is
  `process_user_document_artifact_job`, not `user_document_parser_job`.
- **to the architect** — **five rulings** now blocking this lane, collected in one
  file: the promotion-task question above; ten rows versus six for the re-ingest
  (ten writes both byte-versions of four modules, and two pairs disagree: 720A 19
  vs 14, 520A 14 vs 9); the two evidence-gate questions (derived fields exempt?
  does a `region`-quality bbox count?); and the `mesh:universalReferent` seal,
  which cannot be met as written because Cypher `SET c.prop = null` **removes**
  the property, so an absent flag never reads as `false`.

Still blocked on Lane 1's retries, now behind our own roll: the
`MAINTENANCE_INSTANCES` count and the Day 2 idempotency proof. The expectation of
"112" was set at the pin **before** #131, so it needs re-deriving, not asserting.
`mrad.ttl` regeneration is still owed in invincible-agent (99 → 146 triples after
#131).
