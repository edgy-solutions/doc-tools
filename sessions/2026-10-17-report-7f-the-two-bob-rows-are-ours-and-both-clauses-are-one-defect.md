# Report: the two bob rows are ours, the bytes are a valid PDF, and clauses 1 and 4 are one defect

doc-tools/lane/7f, 2026-10-17 (packet 5, clauses 1 and 4)

Both clauses addressed to this lane turn out to be the same structural fault,
and it is not where either clause points. Measured before writing any code.

## 1. The two rows, found and identified

`fa231498` and `0096a523` are ours, and the full ids are
`sha256:fa231498f527921fc547cb97009a7d98fb45927bdaf7237028ea1cb60305e9bb` and
`sha256:0096a523a94d6d848c939250e17d7892520bb9a6c52ad14b2efc573a30d51c9b`.
Both are user drops (`obtained_via: user-drop`, `standing: supervised`,
`content_kind: pcn`), both named `PCN23-002.pdf`, both parsed twice — at
`doc-tools@89e914e` and `doc-tools@dd23c758`.

| | `fa231498` | `0096a523` |
|---|---|---|
| source bytes | **606**, `%PDF-1.4` | **606**, `%PDF-1.4` |
| `ContentType` | `binary/octet-stream` | `binary/octet-stream` |
| pages rasterized | 1 | 1 |
| elements (`extracted_count`) | **2** | **2** |
| `review_items` | **0** | 3 |
| **part rows Lane 1 serves** | **0** | **0** |
| `needs_review` | True | **False** |
| why | `header pass failed: BamlValidationError … failed to coerce` | `no Table element detected — parts pass skipped (header-only)` |

## 2. Clause 3's premise is wrong, and the answer is favourable to the door

Clause 3 is Lane 1's, but I can answer half of it from the producer side and it
changes the question: **the bytes are a valid PDF.** `%PDF-1.4`, 606 bytes, one
page, and both rasterized. The door was right to admit them. There is nothing
to explain about Oct 12 — a 606-byte single-page PDF is a well-formed PDF.

Two things *are* wrong with them, and neither is the magic number:

- **`ContentType` is `binary/octet-stream`, not `application/pdf`.** A browser
  will not render that inline, which is very likely the "source can't be
  rendered" condition clause 2 asks Cortex to disable PROMOTED on. That is a
  stored-metadata defect at the door, not a bytes defect.
- They are **smoke-test PDFs**: 606 bytes yielding two elements, one
  `NarrativeText` and one `UncategorizedText`. Two different files with the
  same length and the same first sixteen bytes.

## 3. `rows=0` is confirmed — and `extracted_count` would not have caught it

Computed exactly as the deployed route does (`review_items` whose `field_path`
matches `parts[i].field`, counting distinct indices): **0 rows for both, under
both pipeline versions.** The premise of clause 1 holds.

But the seal cannot be written on the field a reader would reach for first.
Both rows carry **`extracted_count=2`** and **`extracted_total=1`**, so
`extracted_count == 0` catches **neither row**. `extracted_count` is
unstructured elements, `extracted_total` is rasterized pages, and the row count
is in `review.json` — three different numbers, and only the third is "rows".

`0096a523` is the worse of the two: `needs_review` is **False**. A zero-row
extraction with no flag raised looks *clean* to the queue.

## 4. Why clause 1 cannot be a conditional at the POST site

The `review` POST is made at `doc_tools/components/document_parser.py:721`.
`review.json` is written at `doc_tools/assets/semantic_assets.py:732` — by the
**downstream** asset, and only `if review_nodes:`. So at the moment the POST is
made, the row count does not exist yet, and for a document whose nodes carry no
`review` block it never will.

Since Lane 1 files `document_promotion` **on** that POST, a later `failed` POST
cannot satisfy "never files document_promotion" — the task is already filed.
The POST itself has to happen where the count is known.

It can: `document_parser.py:792` puts the parse asset and the graph asset in
**one job** (`define_asset_job(selection=[self.name, self.downstream_graph_asset])`),
and the graph asset receives the manifest itself (`manifest = process_document_artifact`),
which carries `ingest_id`. The status resource is not a Dagster resource — the
parser just constructs `IngestStatusResource()` inline — so moving the POST adds
no resource wiring.

Two fields have to be **declared** in the manifest for the POST to move without
path surgery, in the doctrine `source_key` and `pipeline_version` already
follow: `manifest_key` (so `extraction_ref` can name the versioned manifest) and
`element_count` (the downstream site cannot recount elements).

**And the seal must not fire on a domain that has no row contract.** A
manufacturing or S1000D-via-PDF drop produces no part rows at all; sealing on a
count it never produces would fail every one of them. The discriminator is
domain-generic and already available — whether this document's augmentation
declares a `review` block at all — not a hardcoded domain name.

## 5. `retryable` cannot be sent, and that is Lane 1's half

The deployed `IngestStageUpdateRequest` (`origin/master:src/iagent/gateway.py:11160`)
accepts `stage`, `extracted_count`, `extracted_total`, `detail`,
`extraction_ref`, `reason_code`, `reason`, `step`, `run_id`, `pin_digest` —
**and nothing named `retryable`**. This side can name the code; whether
`extraction_empty` is retryable is a property of Lane 1's queue, and it has to
be registered there or the seal produces a dead row instead of a retryable one.

`extraction_empty` also did not exist in our vocabulary (`REASON_CODES`,
`doc_tools/utils/ingest_failure.py:25`). It is being added.

## 6. Clause 4 is three fallbacks, and the file's own comment is the contract

The notice id Lane 1 serves comes from our manifest:
`"notice_id": str(manifest.get("doc_id") or "").strip() or row.get("notice_id")`.
Our `doc_id` is the basename minus extension. So for these two rows the queue
showed notice id **`PCN23-002`** — read off the filename, while the header pass
that was supposed to extract it had **failed**.

The contamination is in our plugin, at three sites in
`doc_tools/plugins/sustainment.py`:

| line | what it does |
|---|---|
| 1348 | `empty_header(doc_id)` seeds the **pipeline** `doc_id` as the notice id when the header pass raised |
| 1350 | `if not header_d.get("doc_id"): header_d["doc_id"] = doc_id` — the key fallback |
| 1795 | `"doc_id_raw": header_d.get("doc_id_raw") or header_d.get("doc_id") or doc_id` — the review payload |

Line 1350 is **legitimate and stays**: `doc_id` is a KEY — the workflow id, the
MinIO prefix, the graph IRI (`<http://internal/sustainment/doc/{safe_notice_id}>`)
and the provenance index all key on it, and a null key breaks all four.

The defect is that the *display* field inherits the key's fallback.
Line 1356 sets `doc_id_raw` from `header_d["doc_id"]` **after** line 1350 has
already overwritten it, and line 1795 adds two more fallbacks — under a comment
that reads, one line above, *"the raw printed notice number ('PCN # 23-002')
for DISPLAY"*. A filename is not a printed notice number. The field violates
its own documented contract, and `doc_id_raw` has exactly these three sites and
no test anywhere.

The fix keeps the key and repairs the display: capture the extracted id
**before** the key fallback, and let `doc_id_raw` be `None` when nothing was
extracted.

**`mfr` needs no change.** `empty_header` sets `"mfr": ""` — a blank sentinel,
never the filename — and `0096a523`'s own review reason says so: *"header.mfr
not written: the header pass returned none and the document does not name one
itself."* Clause 4's "same for manufacturer" is already satisfied. It is now
pinned by a test so the correct half cannot regress.

## 7. The two clauses do not subsume each other

Worth stating, because the seal looks like it makes clause 4 moot: it does not.
After the seal, a zero-row row never reaches the queue, so its notice id stops
mattering. But a notice whose **header pass fails while its parts extract fine**
has rows > 0, reaches review legitimately, and still shows a filename as its
notice id. Both changes are needed.

## 8. One more finding, not in any clause: a rejection strands every filed ref

All 13 objects for each row now sit under `rejected/sha256:<id>/` with
`LastModified` 2026-10-18 01:20Z — a single relocation, twenty seconds apart for
the two rows, minutes before this measurement. The prefix they came from,
`ingress-user/pdf/<sha>/`, now holds **0 objects**.

Their manifests still say `source_key: ingress-user/pdf/<sha>/PCN23-002.pdf` and
`text_location: ingress-user/pdf/<sha>/generated/…`, and the `extraction_ref`
already filed with Lane 1 names the same dead prefix. So
`/ingest/{id}/extraction` for these two rows now resolves to nothing — the
artifacts exist, under a key no filed reference names. Whoever owns the reject
relocation should either leave the objects in place or rewrite the refs; a
rejection should not make an extraction unreadable.

## 9. What is shipping, and what is owed by whom

**This lane** — `extraction_empty` in the reason-code vocabulary; the `review`
POST moved to where the row count exists, refused at zero rows for a
row-contract domain; `manifest_key` and `element_count` declared in the
manifest; a `failed:extraction_failed` stamp from the graph asset so a moved
POST cannot leave a row at `extracting`; and the notice id extraction-only with
`mfr` pinned.

Two ordering decisions inside that, both deliberate:

- **The POST sits after the extraction is persisted, not after the sinks.** A
  steward reviews the extraction, and `review.json`/`extraction.json` are
  written by then. Gating `review` on the Neo4j/Weaviate/Jena writes would make
  a good notice un-reviewable whenever Weaviate is down, and Weaviate does fail
  here.
- **The `failed` stamp is conditional on no stage having been posted.** A
  failure *before* the POST leaves the row at `extracting` and must be stamped,
  or it waits for Lane 1's watchdog. A failure *after* it must not be stamped:
  `failed` over `review` is a backwards move on a row a steward may already
  hold, and the thing that failed is downstream of what they are reviewing. The
  asset still fails loudly in Dagster either way — only the stage overwrite is
  suppressed.

**Lane 1** — register `extraction_empty` as retryable in the queue (this side
cannot say it on the wire), and stop reading `notice_id` from `manifest.doc_id`:
read the extraction-only field, and fall back to the drop id for the title.
Clause 3's bytes question is answered in §2 above. Placed as a packet.

**Not mine** — clause 2 is Cortex's, and "reject as not_a_notice" is a steward
action on the queue. Both rows were in fact relocated to `rejected/` at 01:20Z,
so that step appears to have happened already.
