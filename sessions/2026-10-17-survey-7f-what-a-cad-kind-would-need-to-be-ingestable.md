# Survey — what a `cad` kind would need to be ingestable

doc-tools/lane/7f, 2026-10-17. Day 2 item: **survey only, no code.** No code was
written and no registry row was touched.

## The short answer

**The `cad` row already exists**, architect-authorised 2026-10-13, with its
target ontology class and its declared pass. So this is not "add a kind". It is
**six specific gaps between that row and a drop that lands a parse artifact**,
and only one of them is the pass everybody thinks of first.

One prerequisite is already met and worth saying so: **`mesh:CADArtifact` is
declared** (`invincible-agent/setup/ontologies/mesh_system.ttl:808`). It is
**not** in `PHANTOM_OUTPUTS`, unlike `mesh:EngineeringDocumentArtifact`,
`mesh:DoorsExportArtifact` and `mesh:XMLArtifact`, which are still owed by
Lane 1. A cad kind would not be blocked on an ontology commit.

## The row as it stands, measured

```
cad    prefix=None  suffixes=()  domain=None  passes=('cad.cad_document_identity',)
                    target_ontology_class = mesh:CADArtifact
                    extractor_config = ""   baml_function = ""
```

and the exclusion the registry itself reports:

```
{'kind': 'cad', 'reason_code': 'unbuilt_pass',
 'pass': 'cad.cad_document_identity',
 'detail': "listed in UNBUILT_PASSES: declared but not built"}
```

Compare the two rows that do declare routing, which is the whole shape of the
gap:

| kind | ingress_prefix | file_suffixes | domain_type |
|---|---|---|---|
| `pdf` | `"pdf"` | `(".pdf",)` | None |
| `xml` | `"xml"` | `(".xml",)` | None |
| **`cad`** | **None** | **()** | **None** |

## The six gaps, in the order a drop would hit them

### 1. No sensor watches a cad prefix — and this is first for a reason

`definitions.py:155` wires the user-drop sensor with
`s3_filter=ingress_user_prefixes()["pdf"]` — **one** prefix, singular. A drop
into `ingress-user/cad/{sha256}/{file}` is never seen. This is the same shape
already measured for XML: ten MRAD drops arrived in `ingress-user/xml/` and no
sensor fired, because the declared prefix is not a watched one.

So gap 1 is a **decision, not a line of code**: widen that sensor's filter to
the registry's prefixes, or add a second sensor per prefix. Widening means one
sensor's partition set spans formats with different parsers; a second sensor
means a second cursor to go stale. Both are live choices with precedent
problems in this repo, and whoever rules on it should know that a watched
prefix's cursor is a LastModified watermark whose backing object must never be
deleted.

### 2. The row declares no prefix and no suffixes

Nothing can generate a key pattern for a cad drop, because
`ingress_user_prefixes()` only includes rows where `e.ingress_prefix` is
truthy. Two fields on one row, but they are what makes gap 1 implementable at
all.

### 3. The pass does not exist, and it must not be a class

`cad.cad_document_identity` is in `UNBUILT_PASSES`; nothing resolves for
namespace `cad` (no `cad*.py` in any pass package). When built it must be a
**module-level callable**, because dispatch refuses a class by contract — the
registry proves it by reporting `s1000d-data-module` excluded with
`reason_code: pass_is_a_class` even though ten `s1000d-data-module` drops
completed all five stages through the *other* arm.

The row's own comment already specifies the contract, and it is the right one:
read part number, revision, CAGE and contract/program identifiers out of **CAD
metadata** — a STEP header's `FILE_NAME`/`FILE_DESCRIPTION` entities, a DWG/DXF
header block, or a native CATIA/SolidWorks part's product-data attributes — with
the entity or attribute that produced each value as its source, and **refuse
rather than guess**. It is explicitly *not* a title-block OCR of a drawing
sheet: a sheet exported to PDF is a `pdf` drop and already has a pass.

### 4. Nothing produces that metadata today — the real work

This is the gap the row cannot describe away, and it is larger than the pass.
The declared pass needs CAD metadata as its **input**, and no stage produces
it. `extractor_config` is empty, and the parse stage runs a text/page-oriented
extractor: a STEP or DWG payload has no page text at all. So an ingestable cad
kind needs a **new extractor** that opens the model file and yields structured
header entities, before the identity pass has anything to read.

That is also the gap with a real dependency question behind it: STEP is
parseable with a modest amount of code, DXF with a library, and native
CATIA/SolidWorks essentially not at all without a vendor toolkit. **A `cad`
kind is not one kind of work** — it is one row covering formats whose
tractability differs by an order of magnitude. If this is to be scoped, scope
it per format and say which formats the first cut refuses.

### 5. `domain_type` is None, so the write path short-circuits

The row declares no domain, and the comment is explicit that the write path
short-circuits at "origin unresolved" before any pass would run. Under the
2026-10-02 ruling the domain comes from the registered content kind and never
from a run tag, so this is a row field someone must choose. A CAD model is
plausibly `maintenance` or a new domain of its own; it is not obviously either,
and picking it also picks which graph the instances land in.

### 6. `cad` means two different things, and one guard already knows it

`document_parser.py:221` **raises** when a sidecar's `domain_type` is `"pdf"`
or `"cad"`, because in Lane 1's `POST /ingest` the first path segment is a
**file FORMAT** (`ingest_status.KINDS`), not a semantic domain:
`ingress-user/{kind}/{sha256}/{filename}`.

So the string `cad` is already live in this system as a *format prefix*, and the
content kind `cad` would be a *semantic* label with the same spelling. The guard
exists precisely to stop the format leaking in as the domain. Anyone wiring this
must keep them apart: the drop path may say `cad`, and the sidecar's
`domain_type` must not. Worth a packet to Lane 1 before, not after.

## What this means for sequencing

Gaps 2, 3 and 5 are small and local to this repo. Gap 1 is a ruling. Gap 4 is
the actual project, and it is per-format. Gap 6 is a cross-lane contract note.

**Recommendation:** do not open a cad lane on the strength of the row existing.
The honest first increment is **STEP only** — a real extractor for STEP header
entities, the pass built as a callable over it, the row given a prefix and a
domain, the sensor ruling taken, and DWG/DXF/native explicitly refused with a
reason code until someone asks for them. That is a measurable end-to-end drop.
Anything broader buys a vendor-toolkit dependency before the first artifact
exists.

## One thing the survey turned up that is not about cad

`processable_kinds()` returns `work-instruction` (**singular**) while the
`KIND_MAPPING` key is `work-instructions` (**plural**). That is the documented
secondary index doing its job — the registered `kind` differs from the
`kind_source_value` — but it means a consumer diffing the advertised list
against the table's keys sees a spurious mismatch on that one row. Not a defect;
a trap worth knowing before someone files it as one.
