# Report — lane 7f, 2026-10-25: the `document` kind ships (PR #168), and the page ref it adds would have been inert in every pod

**Order:** architect, overnight item 2, verbatim:

> *"Our own documents": a drop of a general document (manual, procedure, spec)
> that is not a PCN/PDN/S1000D should ingest as kind `document` with
> review_shape `document`, chunk to Weaviate with page refs, and land in the
> graph as Document → Section → Chunk so ask-the-manual can cite page + heading.
> Define the kind in the registry, the passes, a synthetic fixture (write a
> 6-page procedure yourself), golden, and the ledger. Packet Lane 1 with the
> door change needed (kind candidate `document` in allowed_leaves with label).*

**Status: complete and delivered, one item declined as impossible at our SDK pin
(§3), one asked of Lane 1 as a blocker (§6), one gap reported not fixed (§7).**

- **PR #168** — `7f/document-kind` (`b102032`), cut from `main` `3418171`, **not
  stacked**, so it dispatched a CI run.
- **Ledger:** `docs/contracts/document-kind.md`.
- **Packet:** `sessions/2026-10-25-packet-to-lane-01-from-7f-the-document-kind-needs-one-leaf-candidate-and-three-things-only-you-can-declare.md`.
- **Suite:** 2131 passed, 12 skipped. The one red is the pre-existing #161
  `doors-export` overlay drift, which this change does not touch.

---

## 1. The decision the order left open, settled by measurement

Does `document` declare a `domain_type`? It has to.

`semantic_assets.py` has the branch
`if kind_entry is not None and kind_entry.domain_type is None:` which returns
**no domain graph, no Neo4j label, no chunks, no triples** — before any resource
client is fetched. A `document` row with `domain_type=None` would therefore have
satisfied the registry half of the order and silently dropped the half the order
exists for.

There is a second, sharper consequence I did not expect: the **leaf-grant**
branch adopts a grant only `if granted is not None and granted.domain_type:`. A
domain-less `document` row would have been refused **by the very door meant to
route to it**. The two halves had to agree, and they now do.

`domain_type="document"` **does not reopen the 2026-10-02 format-level ruling**,
and the row's own comment says why: that ruling is about file **formats** — a PDF
can come from anywhere, so it cannot claim a domain from its bytes — whereas
`document` is the declaration *"this is one of OURS"*, a statement about
**origin**, made at Lane 1's door. **Flagged as an assumption for the architect:
it creates a new domain.**

## 2. The route in already existed

No new sensor, no new `ingress_prefix`, no new seam:

1. A PDF lands at `ingress-user/pdf/<sha256>/<name>`.
2. The `pdf` row resolves no origin → `origin_unresolved`.
3. The leaf-grant branch asks Lane 1's door, which may answer `document`.
4. The grant is adopted because the row declares a domain (§1).

**No `ingress_prefix`, deliberately.** A prefix is a user-drop seam and a seam
needs a retry sensor behind it: `ingress_user_prefixes()` builds one pattern per
declaring row, and `definitions.py` wires sensors for `pdf` and `xml` only.
Declaring `ingress-user/document/` would advertise a drop path nothing drains —
the same defect the standing order holds `xml` out of `ingestable_kinds()` for.
`ingress_user_key_pattern()` raises for this row, and the test asserts the raise.

## 3. `review_shape` — declined here, and it is not a judgment call

The order names it. **It cannot be emitted from doc-tools.**
`ContentKindRegistration` at our SDK pin **v0.9.8** has
`model_config extra="forbid"` and **no `review_shape` field**; it arrives in
**v0.9.11**. Emitting it today does not warn — it **raises at registry load**,
taking every kind down. Under #161's split it is a platform field regardless, so
it is asked of Lane 1 rather than deferred.

## 4. What was built

- **`doc_tools/passes/document.py`** — the outline, deterministic and LLM-free.
  Three ordered recognizers: `element_title` (the pipeline's own
  `[Title] 3.2 …` rendering, the only signal produced by something that saw the
  font and the position; `Header` excluded, because a running head would open a
  section per page), `numbered` (where an author printed numbering, the numbering
  IS the hierarchy), and `caps` as the most constrained last resort. Page
  furniture is excluded — the same class of text that
  `clause-1-writes-page-furniture-as-a-manufacturer` records being read as a
  manufacturer. **One invariant:** a section heading must be a verbatim substring
  of its own page's text, or the pass raises.
- **`doc_tools/plugins/document.py`** — no prompts, no BAML, **no mock
  fallback**. It runs the row's tuple **through the dispatcher**, so the registry
  declaration is what executes; `doors-export` was until now the only row in
  production that actually dispatched its tuple. The chunk edge is `MATCH`ed,
  never `MERGE`d, and handed another document's outline it writes nothing.
- **`semantic_assets.py`** — its own plugin branch, its own graph labels
  (`:Document`/`:Chunk`, not the pdf component's `WorkInstruction`/`Page`), the
  page ref, and a per-iteration `citation` rebind.
- Fixture (6-page procedure, raw PDF syntax, byte-deterministic, no new
  dependency), golden built through the dispatcher, and 35 assertions.

## 5. Three things found while building, each of which looked green

**(a) The Weaviate page ref would have been inert in every pod.**
`_ensure_weaviate_collection` created its properties **only if the collection did
not exist** — and `DocumentChunk` exists on every deployed cluster, so the
function was a no-op there and `page`/`heading`/`section_id` would never have
appeared. Correct in the tree, absent in the pod; the shape this repo has met
before. There is now an explicit `add_property` branch, and a test asserts it.

**(b) The plugin selector's `else` is not a default — it is `TrainingPlugin`.**
An unbranched new domain runs course-concept extraction over a procedure and
looks like it worked. Fixed for `document` with an explicit branch, and recorded
in the row comment because **the next new domain will meet it too.**

**(c) A declared pass can report `ok` and contribute nothing.** The fixture's
cover page printed `Revision B` without a colon; `identity.document_identity`
reads `Label: value` and nothing else, so it **refused all four fields** while
still reporting `ok` — and a golden pinning only the outline could not tell that
from a working arm. The fixture now carries a labelled title block
(`document_number=TP-204`, `revision=B`, `cage_code=1ABC3`,
`refused=("contract_number",)`) and the golden pins the read. The outline did not
move.

Also fixed in my own freshly written code before commit: a cross-iteration leak
in the asset's page loop (`node` is assigned inside a `try`, so a page whose
augmentation raised would have carried the **previous** page's heading), and a
false-positive class in my own caps recognizer (every bare `WARNING` becoming a
section — a six-page procedure can print four of them, each capturing the pages
beneath it).

## 6. The one blocker, with Lane 1

Packeted. Four items, one blocking:

1. **`document` as a kind candidate in `allowed_leaves`, with a label** —
   **blocking.** Without it §2 step 3 never fires.
2. The overlay row mirroring my `passes` (per #161). Note for them: the drift
   test is already red on `doors-export`, and adding a `document` row without
   mirroring takes it from one kind to two.
3. `review_shape: document` at the v0.9.11 pin (§3).
4. `mesh:GeneralDocumentArtifact` as a TTL leaf under `mesh:PDFArtifact`. Until
   it lands the output stays in `PHANTOM_OUTPUTS` — the **seventh** entry, and
   unlike its six predecessors it backs a **domain-declaring** row — and I write
   **no SPARQL at all**, because triples against an undeclared class write data
   no shape can validate. I checked before inventing a class:
   `mesh:KnowledgeDocument` is a presentation `mesh:Archetype` whose own
   `rdfs:comment` says it is *"never a payload shape itself"*.

## 7. Reported, not fixed

**Sub-page section boundaries cannot be attributed.** Chunks are page-granular,
so a page carrying two headings cites the deeper/later one. On fixture page 6,
which prints both `3.2 Stage two` and `APPENDIX A`, `section_for_page(6)` returns
`TP-204_s4_s2`. The tie-break is `(-level, -start_page)` and is documented in the
pass. This is a true statement about a page-sized chunk rather than a defect —
but a reader asking about Appendix A gets cited to §3.2, so **ask-the-manual's
wording must not promise more precision than a page.** Fixing it means sub-page
chunking, a separate change.

## 8. Item 3 cannot start yet

It is **Sunday 05:55Z**, inside the forbidden 05:45Z–09:35Z window, and Lane 1's
roll is at 09:35Z. The three header-gate fires also require **PR #165 merged and
carried by a pin**, or they do not test the cancel fix at all. So item 3 waits on
both the window and the pin, and item 4 (the batch fixture scrubber → schema PR)
is the next thing that can proceed without a cluster.

— doc-tools/lane/7f
