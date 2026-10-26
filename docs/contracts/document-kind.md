# Contract: the `document` kind — our own manuals, procedures and specs

**Status:** declared in doc-tools, **not yet routable end to end**. One external
dependency blocks the drop path: Lane 1's door must offer `document` as a kind
candidate (§9). Everything below §9 is measured in this tree at
`7f/document-kind`; §9 is owed.

**Order it answers** (architect, 2026-10-25, overnight item 2), verbatim:

> *"Our own documents": a drop of a general document (manual, procedure, spec)
> that is not a PCN/PDN/S1000D should ingest as kind `document` with
> review_shape `document`, chunk to Weaviate with page refs, and land in the
> graph as Document → Section → Chunk so ask-the-manual can cite page +
> heading. Define the kind in the registry, the passes, a synthetic fixture
> (write a 6-page procedure yourself), golden, and the ledger.*

The consumer this exists for is **ask-the-manual**: a question answered with a
citation of the form *page N, heading H*. Every decision below is downstream of
that one sentence, and the recurring reason for the strict choices is that **a
citation that moves between runs on the same bytes is worse than no citation,
because it is checkable and wrong.**

---

## 1. What the kind declares, and what it is NOT

`document` is a statement about **origin**, not about file format: *this PDF is
one of ours*. That distinction is load-bearing, because the 2026-10-02 ruling
made format-level rows (`pdf`, `xml`) carry **no** domain — a PDF can come from
anywhere, so it cannot claim a domain from its bytes alone.

`document` does not reopen that ruling. It sits beside it: the `pdf` row still
resolves no origin, and `document` is what a drop becomes once something has
*declared* the origin.

| field | value | why |
| --- | --- | --- |
| `kind` | `document` | |
| `domain_type` | `document` | **Required, measured.** A row with `domain_type=None` reaches the `origin_unresolved` return in `semantic_assets.py` — *no domain graph, no Neo4j label, no chunks, no triples* — before any resource client is fetched. A domain-less `document` row would satisfy the registry half of the order and silently drop the half the order is for. Sealed by `test_the_row_declares_a_domain_because_a_domainless_one_writes_nothing`. |
| `passes` | `identity.document_identity`, `document.document_outline` | Both deterministic. No BAML function, no extractor config. |
| `outputs` | `mesh:GeneralDocumentArtifact` | A **phantom** (§9). Not `mesh:KnowledgeDocument`: that is a presentation `mesh:Archetype` whose own `rdfs:comment` says it is *"never a payload shape itself"*. |
| `ingress_prefix` | `None` | **Deliberate** (§2). |
| `file_suffixes` | `.pdf` only | A `.docx` has no pages, so a page citation off one would be invented. Claiming the suffix would hand a whole manual one synthetic section. |
| `review_shape` | **not emitted here** | §7. |

`processable_kinds()` and `ingestable_kinds()` both advertise `document`
automatically — both passes are real callables and the kind is not held out. No
further edit was needed for that, and the test asserts it rather than assuming.

## 2. The drop: how a document arrives

**There is no new seam, and no new sensor.** The route already exists:

1. A PDF lands at `ingress-user/pdf/<sha256>/<name>`.
2. The format-level `pdf` row resolves **no origin** → `origin_unresolved`.
3. The **leaf-grant** branch asks Lane 1's door, which may answer
   `content_kind="document"`.
4. The asset adopts the grant only `if granted is not None and granted.domain_type:`
   — which is precisely why `document` had to declare a domain, and why a
   domain-less row would have been refused *by the very door meant to route to it*.

**No `ingress_prefix`, deliberately.** A prefix is a user-drop seam, and a seam
needs a retry sensor behind it: `ingress_user_prefixes()` builds one pattern per
declaring row, and `definitions.py` wires sensors for `pdf` and `xml` only.
Declaring `ingress-user/document/` would advertise a drop path that nothing
drains — the same defect the standing order holds `xml` out of
`ingestable_kinds()` for. `ingress_user_key_pattern()` raises for this row, and
the test asserts that it raises.

## 3. Identity

`identity.document_identity` over the page texts, region `title_block`. It reads
`Label: value` lines and **nothing else**: `document_number`, `revision`,
`cage_code`, `contract_number`. Every field is either present with the source
line and page it came from, or named in `refused`.

A field with no labelled line is a **refusal**, not a gap and never a guess. On
the fixture: `document_number=TP-204`, `revision=B`, `cage_code=1ABC3`,
`refused=("contract_number",)` — a procedure has no contract number.

> Measured while building this: the fixture's first cover page printed
> `Revision B` with no colon, and the arm therefore refused **all four** fields
> while the pass still reported `ok`. The golden pinned only the outline, so it
> could not tell a working identity arm from a totally refusing one. The fixture
> now carries a labelled title block and the golden pins the identity read.

## 4. The outline

`document.document_outline` builds `Document → Section` deterministically, with
**no model call**. Three recognizers, in order:

1. **`element_title`** — the pipeline's own `[Title] 3.2 Torque sequence`
   rendering. Highest confidence: it is the only signal produced by something
   that saw the font and the position. `Header` is **excluded** — a running head
   would open a section on every page.
2. **`numbered`** — `^(\d+(?:\.\d+)*)\.?\s+(\S.*)$`. Where an author printed the
   numbering, **the numbering IS the hierarchy**: `2.1` is level 2 under `2`.
3. **`caps`** — the last resort and the most constrained (≤48 chars, all caps).
   It is why `APPENDIX A` is read.

Excluded from heading candidacy: **page furniture** (`Page N of M`, bare digits,
rev/issue stamps, `CONFIDENTIAL`/`DRAFT`, `continued`, effective/issued/approved
dates) — the same class of text that
`clause-1-writes-page-furniture-as-a-manufacturer` records being read as a
manufacturer. **Admonition labels** (`WARNING`, `CAUTION:`, `NOTE`) are excluded
**in the caps arm only**: a six-page procedure can print `WARNING` four times,
each one capturing the pages beneath it. `2.1 WARNING` (numbered by the author)
and `WARNINGS AND CAUTIONS` (a real S1000D section) still count.

**The one invariant:** a section's `heading_source` must be a **verbatim
substring of its own page's text**, or `document_outline` raises `OutlineError`.
A heading that is not on the page it cites is the failure this whole design
exists to prevent.

**A heading-less document gets ONE section, `method="synthetic"`, and
`outline.synthetic=True`** — marked, never silent. An empty heading that looks
read is indistinguishable from one that could not be read
(`a-ruled-none-is-indistinguishable-from-a-missing-one`).

Section ids are path-encoded: `TP-204_s3_s1`. A parent's page span **contains**
its subsections'. `section_for_page(page)` returns the **deepest** covering
section, tie-broken on `(-level, -start_page)`.

## 5. Neo4j: Document → Section → Chunk

Written by `DocumentPlugin.to_graph_queries`. Labels come from the **domain**,
not the kind: a `document` drop would otherwise inherit the `pdf` component's
`WorkInstruction`/`Page` labels, and writing a manual as `:WorkInstruction`
makes *"which of these is a work instruction"* unanswerable by label.

| tier | label | key |
| --- | --- | --- |
| document | `:Document:DOCUMENT` | `id` = `doc_id` |
| section | `:Section:DOCUMENT` | `id` = e.g. `TP-204_s3_s1` |
| chunk | `:Chunk:DOCUMENT` | `id` = `<doc_id>_p<page>` |

Section properties: `heading`, `number`, `level`, `page_start`, `page_end`,
`method`, `synthetic`. Edges: `(:Document)-[:HAS_SECTION]->(:Section)` for a
top-level section, `(:Section)-[:HAS_SUBSECTION]->(:Section)` otherwise, and
`(:Section)-[:HAS_CHUNK]->(:Chunk)` with `heading`/`section_id` set on the chunk.

Two guarantees that are tested rather than described:

* **The chunk is `MATCH`ed, never `MERGE`d.** The asset's own page loop creates
  it; this only attaches it. A `MERGE` here would mint an **empty** chunk node if
  that loop had not run, and coverage counted off an empty node is worse than a
  missing edge.
* **Another document's outline writes nothing.** `to_graph_queries` returns
  empty if `doc_id` disagrees with the held outline. Attributing page 3 of one
  manual to section 2.1 of another is a defect that reads as correct.

## 6. Weaviate: the page ref

Collection `DocumentChunk` (`config.vector_collection_name`). A page chunk is
indexed with:

```
text, doc_id, chunk_id, domain, page, heading, section_id
```

`page`, `heading` and `section_id` are **new in this change, and they are the
order's actual deliverable.** Before it, `_index_chunk` carried only the first
four; the page number existed solely in the `chunk_id` suffix and in Neo4j, so
ask-the-manual could retrieve a chunk and had nothing to cite.

* `page` is `DataType.INT`. A page number stored as text sorts 10 before 2.
  `_page_property()` coerces a clean integer and returns `None` for anything
  else, so a stray `"iii"` cannot take the whole chunk write down.
* **An existing collection gains the three properties.**
  `_ensure_weaviate_collection` created its properties **only if the collection
  did not exist** — and `DocumentChunk` exists on every deployed cluster, so the
  function was a no-op there and the new properties would never have appeared.
  Correct in the tree, absent in the pod: the shape this repo has met before.
  There is now an explicit `add_property` branch, and a test asserts it.
* **The figure-chunk call site is deliberately untouched.** Its page convention
  comes from a filename and is not a measured contract.
* `_chunk_citation(node)` is duck-typed on purpose, so the asset's shared page
  loop does not depend on one domain's plugin type; it returns `{}` for a plugin
  that attributes nothing.

## 7. What doc-tools does NOT emit

* **`review_shape: document`** — the order asks for it, and it cannot be emitted
  from here. `ContentKindRegistration` at our SDK pin (**v0.9.8**) has
  `model_config extra="forbid"` and no such field; it arrives in **v0.9.11**.
  Emitting it today would **raise at registry load**. Under #161's split
  (*the platform owns what a kind IS, doc-tools owns what it RUNS*) it belongs in
  the overlay regardless. Asked of Lane 1 in §9.
* **SPARQL.** `to_graph_queries` returns an empty SPARQL arm while
  `mesh:GeneralDocumentArtifact` is a phantom: emitting triples against an
  undeclared class writes data no shape can validate. Not because the domain has
  no use for them.
* **Mock content of any kind.** `DocumentPlugin` has no prompts, no BAML and
  **no `except ImportError` fallback**. Its siblings substitute invented content
  so tests pass without BAML; that pattern has produced a whole green graph of
  placeholder text in this repo. Asserted at source level.
* **The `else` branch.** `document` has its **own** plugin branch in the asset.
  The plugin selector's `else` is **not a default** — it is `TrainingPlugin`, so
  an unbranched new domain extracts course concepts from a procedure and looks
  like it worked. **Any next new domain must add its own branch.**

## 8. Fixture and golden

| file | what it is |
| --- | --- |
| `tests/fixtures/document/make_procedure.py` | Generates a 6-page procedure in raw PDF syntax — base-14 Helvetica, constant `/ID`, no date, **no new dependency**. Byte-deterministic. `--check`, `--verify`. |
| `tests/fixtures/document/procedure_fixture.pdf` | 3122 bytes, sha256 `dcdbd939…6604f`. |
| `tests/fixtures/document/make_golden.py` | Builds the golden **through the dispatcher**, so it records what the registry row actually runs. Imports `doc_tools` → **run from PowerShell on the venv interpreter**. `--check`. |
| `tests/fixtures/document/golden.json` | Pins the fixture sha, the row shape, both pass statuses, the identity read, the 9-section outline and the 6 page citations. |
| `tests/test_document_kind_golden.py` | 35 assertions. |

`fixture.pdf_sha256` pins the **input**: re-running the generator yields
identical bytes, so a changed sha means the fixture's *content* changed — a
contract change, not a re-pin.

There is deliberately **no `nondeterministic` block**, unlike the training
golden. Nothing on this path is model-derived, and that is the point of the kind.

The pinned citations:

| page | section | heading |
| --- | --- | --- |
| 1 | `TP-204_s1` | TORQUE PROCEDURE TP-204 |
| 2 | `TP-204_s2` | PURPOSE |
| 3 | `TP-204_s3_s1` | Lockout and tagout |
| 4 | `TP-204_s3_s2` | Residual pressure check |
| 5 | `TP-204_s4_s1` | Stage one - 30 Nm |
| 6 | `TP-204_s4_s2` | Stage two - 60 Nm |

## 9. Owed by Lane 1 (the one blocker)

1. **`document` as a kind candidate in `allowed_leaves`, with a label.** Without
   it the door cannot grant the leaf, and §2 step 3 never fires. **This is the
   blocker; everything else here is live without it.**
2. **The overlay row mirroring `passes`** — `["identity.document_identity",
   "document.document_outline"]`. Per #161 the overlay mirrors doc-tools, never
   the reverse. (Note: `test_overlay_kind_drift` currently fails on
   **`doors-export`**, a pre-existing #161 red unrelated to this change; the
   drift test compares only *shared* kinds, so `document` is not implicated
   until the overlay declares it.)
3. **`review_shape: document`** at the v0.9.11 pin (§7).
4. **`mesh:GeneralDocumentArtifact`** as a TTL leaf under `mesh:PDFArtifact`,
   beside `EngineeringDocumentArtifact` and `DoorsExportArtifact`. Until then it
   stays in `PHANTOM_OUTPUTS` and no triples are written.

## 10. Known gaps

* **Sub-page section boundaries cannot be attributed.** Chunks are page-granular,
  so a page carrying two headings cites the deeper/later one. On fixture page 6,
  which prints both `3.2 Stage two` and `APPENDIX A`, `section_for_page(6)`
  returns `TP-204_s4_s2`. That is a true statement about a page-sized chunk, not
  a defect — but a reader asking about Appendix A on page 6 will be cited to
  §3.2. Fixing it means sub-page chunking, which is a separate change.
* **`domain_type="document"` is an assumption flagged for the architect.** It is
  forced by measurement (§1), but it does create a new domain, and the new-domain
  hazard is the `TrainingPlugin` fallback (§7).
* **`.pdf` only.** A `.docx` manual is not ingestable as `document` today.
* **No user-drop prefix** (§2). A document arrives through the `pdf` seam.
* **The `document` row is not exercised by any live fire yet** — the golden is
  the only evidence, because the door does not yet grant the leaf.

## 11. Changing this contract

The outline, the ids and the page citations are what a consumer quotes back to a
reader. Changing a recognizer, the furniture list, the tie-break in
`section_for_page`, or the section-id encoding **moves existing citations** and
is a contract change: regenerate `golden.json` deliberately, say so in the PR,
and packet the consumer. A changed `fixture.pdf_sha256` is likewise a contract
change and not a re-pin.
