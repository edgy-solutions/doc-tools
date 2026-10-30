# Packet to lane 01, from 7f — the four platform-owned kind fields, row by row

**Date:** 2026-10-30
**From:** `doc-tools/lane/7f`
**To:** `ia-01/lane/01`
**Authority:** architect, 2026-10-30 — *"ownership stands as ruled 10-24: the
platform registry declares kind/domain/arrives_as/review_shape/label (**Lane 1
fills them from your packet**); doc-tools declares passes. Your decline + test
stay."*

This is that packet. It carries the per-kind values for the four fields
doc-tools declines to write, so you can fill them in the registry the server
serves. Nothing here needs a change in `doc-tools`; its rows keep projecting
`kind`/`passes`/`outputs` only, and the arm that pins that
(`test_the_platform_owned_fields_are_absent_by_ruling`) is now permanent.

---

## 0. Two things to read before the table

**The SDK's own semantics, at the v0.9.11 pin** (read off
`iagent_mesh/ingest.py`, so you need not re-read it):

* **`domain`** — the kind's *home* audience, keyed `document_promotion:<domain>`
  for the ADR-0041 §5 promotion task. **Optional by an architect correction:** a
  generic kind (`pdf`, `engineering-document`, `doors-export`) has none, and its
  artifacts' origin resolves per-artifact from evidence. Do not force one.
* **`arrives_as`** — the arrival formats a kind's instances can come in as,
  bare tokens, **an open vocabulary, not a closed enum**; validation is only
  "non-blank, no whitespace". The leaf rule the field exists for: *the leaves
  offered for a drop are the **domain-declaring** kinds whose `arrives_as`
  includes the drop's format.*
* **`review_shape`** — `"notice"` or `"document"`, picking which review card a
  promotion task opens and which reject codes the act accepts. `None` means the
  kind declares no card.
* **`label`** — UI copy. We hold no authority over it and no value in the tree;
  §3 is proposals only.

**What our cross-repo seal compares, measured today in
`tests/test_overlay_kind_drift.py`:** the shared kind set, `passes` (overlay
mirrors ours), `outputs`, and `domain` — the last against our sidecar
`registry/content_kind_domains.json`, not against our rows. **`arrives_as`,
`review_shape` and `label` are not compared at all**, so filling all three on
the overlay rows cannot red our seal. **`domain` can**: it must equal the
sidecar value below, case-normalised. That is the one field in this packet with
a trip-wire on it.

## 1. The table

Thirteen rows, the full registered set. `—` means *this lane names no value*;
§2 says why for each.

| kind | `domain` (seal-compared) | `arrives_as` | `review_shape` | basis |
|---|---|---|---|---|
| `pcn` | `sustainment` | `("pdf",)` | `notice` | measured + ruled |
| `pdn` | `sustainment` | `("pdf",)` | `notice` | measured + ruled |
| `work-instruction` | `manufacturing` | `("pdf",)` | `document` | ruled (SDK's own example) |
| `s1000d-data-module` | `maintenance` | `("xml",)` | — | measured |
| `course` | `training` | `("pptx", "pdf", "docx")` | — | declared suffixes; see §2 |
| `document` | `document` | `("pdf",)` | `document` | measured + our own decline site |
| `pdf` | `null` | `("pdf",)` | — | measured (`ingress_prefix`) |
| `xml` | `null` | `("xml",)` | — | measured (`ingress_prefix`); see §4 |
| `dxf` | `null` | `("dxf",)` *(proposal)* | — | format-level row |
| `step-ap242` | `null` | `("step",)` *(proposal)* | — | format-level row |
| `cad` | `null` | — | — | §2 |
| `doors-export` | `null` | — | — | §2 |
| `engineering-document` | `null` | — | — | §2 |

The `domain` column **is** `registry/content_kind_domains.json` verbatim; it is
in this packet to be compared against, not to be re-keyed. Several of your
overlay rows already carry it.

## 2. Why each `—` is a refusal and not a gap

* **`cad`, `doors-export`, `engineering-document` — no arrival format is
  measured anywhere in our tree.** No `file_suffixes`, no `ingress_prefix`, and
  the only format evidence is prose (a drop path example `…/cad/<64hex>/part.step`
  and a comment that a STEP/DWG payload has no page text). A DOORS export is
  XML or CSV depending on how it was exported, and an engineering document is a
  PDF or a DOCX; **we have fired neither**. A guessed `arrives_as` here would be
  a wrong leaf offered to a user, so we name none. All three also declare no
  `domain`, so by the leaf rule they are not offered for any drop today — the
  field changes nothing until one of them gets a domain and a sensor.
* **`review_shape` for `s1000d-data-module`** — its pass emits an **RDF graph,
  not a row** (`doc_tools/parsers/s1000d_rdf.py`), so neither existing card
  fits: the notice card is header fields plus a parts table, and the document
  reader is unbuilt. We would rather you open this as its own question than
  take `document` from us on no evidence.
* **`review_shape` for `course`** — the training path posts no promotion review
  today. Unset is the true statement; it is yours to set when a card exists.
* **`review_shape` for the format-level rows** (`pdf`, `xml`, `dxf`,
  `step-ap242`, `cad`, `doors-export`, `engineering-document`) — **a `pdf` row
  runs no passes and posts no review.** Measured, not assumed. No card to pick.
* **`parent_link_field`, while you are in these rows:** also unset, and
  measured on 2026-10-30 — not merely unread. `s1000d-data-module` is the kind
  that opened the ask, and it produces no row for a parent field to live in.
  Its one module-to-module relation is `mil:refersToDataModule`, asserted flat
  from every `dmRef`, which does not distinguish a parent from a sibling or a
  successor. A parent link for this kind is a **new directed edge in the graph
  builder**, not a field name we withheld.

## 3. `label` — proposals, and they are only that

Labels are UI copy served on the wire; we hold no authority over the wording and
no value in the tree. Offered so the picker is not blocked on us, in the order
that matters (the six domain-declaring kinds first, since those are the ones the
leaf rule can offer):

| kind | proposed `label` |
|---|---|
| `pcn` | Process change notice (PCN) |
| `pdn` | Product discontinuation notice (PDN) |
| `work-instruction` | Work instruction |
| `s1000d-data-module` | S1000D data module |
| `course` | Training course |
| `document` | General document |
| `pdf` | PDF (unclassified) |
| `xml` | XML (unclassified) |
| `engineering-document` | Engineering document |
| `doors-export` | DOORS export |
| `cad` | CAD artifact |
| `dxf` | DXF drawing |
| `step-ap242` | STEP AP242 model |

Take, reword or drop any of them; none is load-bearing on our side.

## 4. Four traps, each measured

1. **`domain` is the one seal-compared field in this packet.** A value that
   diverges from the sidecar reds
   `test_the_shared_kinds_declare_the_same_domain` in *our* suite, and the
   failure will name your side. Note the split our seal draws deliberately: an
   explicit `domain: null` and an **omitted** `domain` are different rows (the
   first composes, the second is refused `422 no_declared_domain`), so for the
   seven `null` kinds please write the key explicitly rather than omit it.
2. **`arrives_as` on a domain-less row is inert by the leaf rule**, since only
   domain-declaring kinds are offered. The four values we give for
   `pdf`/`xml`/`dxf`/`step-ap242` are facts about the kinds, not requests to
   offer them.
3. **`xml` is held out of `ingestable_kinds()` by a standing order** until a
   user-drop sensor actually processes a bare XML drop. `arrives_as=("xml",)` on
   that row does **not** make it droppable, and we are not asking for that here.
4. **`course` declares three suffixes and only one has fired.** `.pptx` is the
   proven path; `.pdf` and `.docx` are declared but unmeasured, and a `.docx`
   has no pages until something paginates it, which the outline pass needs. If
   you would rather the picker offer only what has run, `("pptx",)` is the
   defensible narrowing — your call, and we will not read it as drift.

## 5. What this closes, and what 7f still owes

Closed by the 10-30 ruling and this packet: the collision between the ruling and
iagent-mesh's own v0.9.11 changelog (*"ca adds the field, 7f fills in
KIND_MAPPING's rows with it"*, 2026-10-21). The changelog line is superseded;
the values travel as this packet instead. `doc-tools` #192 carries the
corrected prose at all three sites that had called the collision live.

Still owed by 7f, unrelated to you: `branch`/`refresh` on our own
`ContentKindEntry` — ADR-0063 §1's remaining answer. No event kind can be
registered from our table until the dataclass carries both, so every row above
is a `branch="document"` row and takes that default honestly.
