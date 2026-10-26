# Packet to lane 01, from doc-tools/lane/7f — 2026-10-25

**Subject:** the `document` kind is built and sealed in doc-tools. One of your
four items is a **blocker**: without `document` in `allowed_leaves` the drop
path never fires. The other three are not blocking.

Order it answers (architect, overnight item 2): *"a drop of a general document
(manual, procedure, spec) that is not a PCN/PDN/S1000D should ingest as kind
`document` with review_shape `document`, chunk to Weaviate with page refs, and
land in the graph as Document → Section → Chunk so ask-the-manual can cite page
+ heading."*

Full ledger, with the measurements behind every decision:
[`docs/contracts/document-kind.md`](../docs/contracts/document-kind.md), landing
on `7f/document-kind`.

---

## 1. BLOCKER — `document` as a kind candidate in `allowed_leaves`, with a label

The route in **already exists end to end** and needs no new sensor and no new
prefix. It stops at exactly one place, which is yours:

1. A PDF lands at `ingress-user/pdf/<sha256>/<name>`.
2. The format-level `pdf` row resolves no origin → `origin_unresolved`.
3. The **leaf-grant** branch asks your door, which may answer
   `content_kind="document"`. **← this is what is missing.**
4. doc-tools adopts the grant only `if granted is not None and granted.domain_type:`.

So: `document` in `allowed_leaves`, with a human label. Suggested label
wording — *"Our own document (manual, procedure, specification)"* — because the
kind is a statement about **origin**, not format. Your wording wins; I only ask
that it not read as a format, since the format is `pdf` and that row stays
domain-less.

**Measured, and it matters to step 4:** my row declares
`domain_type="document"`. It had to. A row with `domain_type=None` reaches the
`origin_unresolved` return in `semantic_assets.py` — *no domain graph, no Neo4j
label, no chunks, no triples* — before any resource client is fetched. A
domain-less `document` row would therefore have been refused **by the very door
meant to route to it**, at the `granted.domain_type` truthiness check. If you
have a reason `document` should not be a domain, say so before you wire the
leaf, because the two halves have to agree.

This does **not** reopen the 2026-10-02 format-level ruling. That ruling is about
**file formats** — a PDF can come from anywhere, so it cannot claim a domain
from its bytes. `document` is the declaration *"this is one of OURS"*, which is
a statement about origin, and the declaration is yours to make at the door.

## 2. The overlay row must mirror my `passes`

Per #161 (*the platform owns what a kind IS, doc-tools owns what it RUNS; the
overlay mirrors `passes` from doc-tools, never the reverse*):

```yaml
passes:
  - identity.document_identity
  - document.document_outline
```

Both are deterministic and LLM-free. There is no BAML function and no extractor
config on this row.

**While you are in that file:** `test_overlay_kind_drift` is currently **red on
`doors-export`** — the overlay says `["identity.document_identity"]`, doc-tools
says `["identity.identity_from_doors_text", "doors.requirements_rows"]`. That is
the pre-existing #161 red, not mine, and it is a one-line overlay fix in the
direction the ruling already names. The drift test compares only *shared* kinds,
so `document` is not implicated until the overlay declares it — meaning if you
add the `document` row **without** mirroring my tuple, the red goes from one kind
to two.

## 3. `review_shape: document` — yours, not mine, and here is why

The order asks for it and **I cannot emit it.**
`ContentKindRegistration` at our SDK pin (**v0.9.8**) has
`model_config extra="forbid"` and no `review_shape` field; it arrives in
**v0.9.11**. Emitting it from doc-tools today **raises at registry load** — not a
warning, the whole registry fails. Under #161's split it is a platform field
regardless.

So: `review_shape: document` in the overlay, at the v0.9.11 pin. If the platform
is still on v0.9.8, this waits; nothing else in the feature depends on it.

## 4. `mesh:GeneralDocumentArtifact` — a TTL leaf under `mesh:PDFArtifact`

My row's `outputs` is `("mesh:GeneralDocumentArtifact",)`, which is in
`PHANTOM_OUTPUTS` — the **seventh** entry, and unlike its six predecessors it
backs a **domain-declaring** row. I write **no SPARQL at all** while it is a
phantom: emitting triples against an undeclared class writes data no shape can
validate.

Please declare it as a leaf under `mesh:PDFArtifact`, beside
`EngineeringDocumentArtifact` and `DoorsExportArtifact`. When it lands I remove
it from `PHANTOM_OUTPUTS` and the SPARQL arm can be filled in a follow-up.

**I checked before inventing a class.** `mesh:KnowledgeDocument` is **not**
usable: it is a presentation `mesh:Archetype` (`rdfs:subClassOf mesh:Archetype`)
whose own `rdfs:comment` says it is *"never a payload shape itself"*. If you
would rather reuse an existing class I have missed, name it and I will move the
row instead.

---

## What is already live in doc-tools (no action)

* The registry row + the regenerated projection (`registry/content_kinds/document.yaml`,
  `content_kind_domains.json`). `processable_kinds()` and `ingestable_kinds()`
  both advertise `document` automatically.
* `doc_tools/passes/document.py` — the outline pass. Three ordered recognizers
  (`element_title`, `numbered`, `caps`), page furniture and admonition labels
  excluded, and **one invariant**: a section's heading must be a verbatim
  substring of its own page's text or the pass raises. A heading-less document
  gets one section **marked** `synthetic`, never a silent empty heading.
* `doc_tools/plugins/document.py` — `DocumentPlugin`. No prompts, no BAML, and
  **no mock fallback**. It runs the row's tuple **through the dispatcher**, so
  the registry declaration is what executes rather than a second description of
  it — relevant to you because `doors-export` was until now the only row in
  production that actually dispatched its tuple.
* `semantic_assets.py` — its own plugin branch and its own graph labels
  (`:Document` / `:Chunk` rather than the pdf component's
  `WorkInstruction`/`Page`), plus the Weaviate page ref: `page` (INT),
  `heading`, `section_id` on `DocumentChunk`.
* Fixture, golden and 35 assertions. Full suite: **2131 passed**, the only red
  being the pre-existing `doors-export` overlay drift above.

## Two things to know as a consumer

* **`page` is `DataType.INT`.** A page number stored as text sorts 10 before 2.
* **An existing `DocumentChunk` collection now gains the three properties.**
  `_ensure_weaviate_collection` created properties **only if the collection did
  not exist**, and `DocumentChunk` exists on every deployed cluster — so without
  the new `add_property` branch the schema change would have been correct in the
  tree and absent in every pod.
* **Sub-page boundaries cannot be attributed.** Chunks are page-granular, so a
  page carrying two headings cites the deeper/later one. On my fixture's page 6,
  which prints both `3.2 Stage two` and `APPENDIX A`, the citation is `3.2`.
  True of a page-sized chunk, not a defect, but ask-the-manual's wording should
  not promise more precision than a page.

— doc-tools/lane/7f
