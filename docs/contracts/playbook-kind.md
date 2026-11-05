# Contract: the `playbook` kind — markdown playbooks on the existing git source

**Status: SPEC ONLY. Nothing here is built.** This file is the measured design
that a build implements; it declares no row, adds no property and changes no
asset. Every statement about the tree below is measured at **`main@5c113ce`**,
and the four files it reads (`doc_tools/utils/content_kind.py`,
`doc_tools/utils/xml_chunks.py`, `doc_tools/assets/dds_ingestion.py`,
`doc_tools/assets/semantic_assets.py`) are byte-identical to `origin/main` at
the time of writing, so a reader can check it against `main` rather than against
a branch.

**The correction this absorbs.** The first proposal treated playbooks as a new
*source mechanism*. It is not one: it is **a new content kind on the path that
already ingests from git**. Cloning, auth and globbing do not change — that is
the whole point of the correction, and §2 measures what is already there.

**The consumer.** A playbook is read to answer *"how do we do this"* with a
citation of the form **repo + path + heading**. Every strict choice below is
downstream of that, and for the same reason
[`document-kind.md`](document-kind.md) gives: a citation that moves between runs
on the same bytes is worse than no citation, because it is checkable and wrong.

---

## 1. The kind row

`registry/content_kinds/*.yaml` is **generated** from `KIND_MAPPING` in
`doc_tools/utils/content_kind.py` by `scripts/generate_kind_registrations.py`,
with drift pinned by `tests/test_kind_registry.py`. So `playbook` is a mapping
entry and a regeneration — **never a hand-written registry file.**

| field | value | why |
| --- | --- | --- |
| `kind_source_value` | `playbook` | The key is the source value (the leaf), separate from the registered `kind`. `work-instructions` → `work-instruction` is the precedent for them differing; here they do not. |
| `kind` | `playbook` | |
| `domain_type` | `playbook` | **The one decision in this row** (§1.1). It MUST NOT be `None`: a row with `domain_type=None` reaches the origin-unresolved return in `semantic_assets.py` and writes *no domain graph, no Neo4j label, no chunks, no triples*. |
| `extractor_config` | `""` | Nothing here samples. |
| `baml_function` | `""` | Likewise. A heading split needs no model call. |
| `passes` | `playbook.playbook_outline` | New, and **declared unbuilt** (§1.2). |
| `outputs` | `mesh:PlaybookArtifact` | A **phantom**, owed by Lane 1 (§8). |
| `target_ontology_class` | the IRI of that class | |
| `ingress_prefix` | `None` | There is no user-drop seam for a playbook; it arrives by clone (§2). A prefix with nothing draining it is the defect the standing order holds `xml` out of `ingestable_kinds()` for. |
| `file_suffixes` | `(".md",)` | **Read this as the repo-scan filter, not a seam gate** (§1.3). |
| `branch` | `document` (default) | A playbook is a document to extract, not a workflow seed. |
| `review_shape` | **not emitted here** | §7. |

### 1.1 Why a new domain, and the trap that comes with it

Two options, both measured:

* **Reuse `domain_type="document"`** — gets `DocumentPlugin` for free, and writes
  every playbook into the DOCUMENT graph labelled `:Document:DOCUMENT`. That
  makes *"which of these is a playbook"* unanswerable by label, which is the
  exact argument `document-kind.md` §5 makes for not letting a `document` drop
  inherit the `pdf` component's labels.
* **Declare `domain_type="playbook"`** — answerable by label, and it creates a
  new domain.

Recommended: **`playbook`**, consistent with the precedent. The cost is a trap
that must be paid in the *same* change:

> **The plugin selector's `else` is not a default — it is `TrainingPlugin`**
> (`semantic_assets.py`, the `elif domain_type == "document"` chain). A new
> domain with no branch of its own does not get a generic plugin; it gets
> course-concept extraction run over a playbook, and **it looks like it worked**.
> So `elif domain_type == "playbook": plugin = PlaybookPlugin(domain_type)` lands
> with the row, or the row does not land.

### 1.2 The pass is declared unbuilt on purpose

The SDK model refuses `passes=()` (*"a kind with no pass is not a kind"*), so the
row must name one. `playbook.playbook_outline` does not exist until the chunker
is built, so it is listed in `UNBUILT_PASSES` in the same commit.

`tests/test_passes_registry.py` makes that self-enforcing: a declared pass must
resolve to a callable **unless** it is listed unbuilt, and anything listed unbuilt
must **not** resolve. So the pass cannot be built while still declared unbuilt,
and cannot be declared without being either built or listed.

The consequence is intended, and is **not** a defect to be reported later:
`_kind_exclusion` gives the row reason code `unbuilt_pass`, so `processable_kinds()`
and `ingestable_kinds()` both **omit** `playbook` until the pass is real. A kind
that is declared but not yet advertised is the correct intermediate state.

### 1.3 `file_suffixes` means something different on this path

With no `ingress_prefix`, suffixes elsewhere gate *that kind's own inbound sensor*
(`course` is the example). **The git path has no sensor and no seam at all.** Here
the tuple documents what the repo scan accepts, and the build must pass it to the
glob rather than hardcoding `**/*.md` the way the DDS asset hardcodes `**/*.idl`
(§2.3). Nothing about declaring it creates a drop path.

## 2. The source: what already exists, measured

`DDSIngestionConfig` (`doc_tools/assets/dds_ingestion.py`) and
`RabbitMQIngestionConfig` (`doc_tools/assets/rabbitmq_ingestion.py`) carry the
same six fields, **duplicated field for field**: `git_repo_url`, `git_branch`
(default `main`), `git_token`, `git_token_username` (default `x-access-token`),
`git_ssl_verify`, `schema_path_in_repo`.

The clone is built as `["git", "-c", "http.extraHeader=Authorization: Basic <b64>",
"clone", "-b", <branch>, "--single-branch", <url>, <tmpdir>]` in a
`TemporaryDirectory`. **The token never enters the URL**, so a failed clone's
stderr carries no credential — and the existing handler logs `e.stderr` and then
raises a scrubbed `RuntimeError("git clone failed (see logs)") from None`. A
playbook clone inherits that and must not re-shape it.

Three qualifications the build has to absorb:

### 2.1 These are not rows

They are per-asset Dagster `Config` classes whose defaults are env vars. **No
name, no labels, no registry.** So *labels-gate-who-asks* and
*token-in-a-Secret-by-name* have nowhere to live on this path: an env default is
global to the code location, not per source.

### 2.2 The ref is a mutable name and no run records what it got

`clone -b <branch> --single-branch`, and **no `rev-parse` anywhere**. Per-source
staleness defined as *measured ≠ recorded* is therefore not satisfiable today,
because the recorded ref always equals itself.

**One `git rev-parse HEAD` after the clone closes it**, and it is the smallest
change on this path. The resolved sha is what a run records; the branch name is
not evidence of anything.

### 2.3 The glob is half present

`schema_path_in_repo` is a configurable directory; the pattern (`**/*.idl`) is
hardcoded in the asset. A playbook scan needs the directory from config and the
pattern from the row's `file_suffixes` (§1.3).

## 3. The chunker — the one genuinely new component

The only chunker in the tree is `doc_tools/utils/xml_chunks.py` (graph → chunks).
**There is no markdown chunker and no heading splitter.** The build adds one:

* Split on **ATX headings** (`#`…`######`); one chunk per **leaf** heading, with
  the ancestor headings carried as the heading path.
* **Derive `chunk_id` from the heading path, not from position.** Mirror
  `xml_chunks.py`, which keys on `doc_id` + section + a 12-hex sha1 of the text
  precisely so a reordering re-parse cannot re-mint uuids:
  `f"{doc_id}_{heading_path_slug}_{sha1(text)[:12]}"`.
  This matters because our section ids are positional today, which is why a
  re-ingest merges a second outline instead of replacing the first.
* `_index_chunk` derives the Weaviate uuid as `generate_uuid5(chunk_id)`, so the
  `chunk_id` above is what makes a re-ingest **overwrite** rather than duplicate.
* **The invariant, taken from `document_outline`:** a chunk's heading must be a
  verbatim substring of the source file, or raise. A heading that is not in the
  file it cites is the failure this design exists to prevent.
* **A heading-less file gets one chunk, marked synthetic** — never silently.

`doc_id`: the existing convention on this very path is the DDS asset's
`f"{repo_name}.{repo_path}"`. A playbook `doc_id` should be built the same way,
from the repo name and the extension-stripped repo-relative path. A path-fragment
`doc_id` is an already-known shape in this repo, not a new one.

## 4. The citation shape — two properties, and a trap in the second half

`DocumentChunk` (`config.vector_collection_name`) declares, today:

```
text, doc_id, chunk_id, domain, page, heading, section_id
```

So **`heading` already exists.** The two to add are **`source`** and **`path`**,
both `DataType.TEXT`, and **neither belongs folded into `doc_id`**. `source` is
the repo URL — safe to store, because the token lives in `http.extraHeader` and
never in the URL (§2). `path` is the repo-relative file path.

`page` is left absent for a playbook: a markdown file has no pages, and
`_page_property()` already returns `None` for anything that is not a clean
integer, so nothing has to be special-cased to omit it.

> **The correction.** The earlier packet called this *live rather than inert*
> because `_ensure_weaviate_collection` has an add-missing-properties branch for
> a collection that already exists. That was too generous. The branch is real,
> **but its property set is a hardcoded literal**:
> `wanted = {"page": INT, "heading": TEXT, "section_id": TEXT}`.
>
> A property added **only** to the `create` list is therefore inert on every
> deployed cluster, because `DocumentChunk` already exists there and the create
> arm never runs — the defect recorded as *a Weaviate property added to the
> create path is inert on every deployed cluster*. **`source` and `path` must be
> added in BOTH places**, and a test must assert the second one.

Weaviate's auto-schema would add an unknown property on first write, but it
infers the type from the value, so declaring it is the point.

## 5. Neo4j

Tiers mirror `document`: `:Playbook:PLAYBOOK` → `:Section:PLAYBOOK` →
`:Chunk:PLAYBOOK`, written by the new plugin's `to_graph_queries`, with labels
from the **domain**, not the kind. Two guarantees to carry over verbatim from
`document-kind.md` §5, because both are defects this repo has already paid for:

* **`MATCH` the chunk, never `MERGE` it.** A `MERGE` mints an empty chunk node if
  the write loop did not run, and coverage counted off an empty node is worse
  than a missing edge.
* **Another document's outline writes nothing** — return empty if `doc_id`
  disagrees with the held outline.

## 6. What changes in the corpus/ingest job

1. Capture the **resolved sha** after the clone (§2.2).
2. Read the kind from **the row**, not from the asset.
3. Chunk markdown by heading (§3).
4. Write `source` and `path` beside `heading` (§4).

Nothing about cloning, auth or globbing changes.

## 7. What doc-tools does NOT emit

* **`review_shape`** — platform-owned under the 2026-10-24 ownership ruling
  (*the platform owns what a kind IS — kind, domain, `arrives_as`,
  `review_shape`, `label`; doc-tools owns what it RUNS*). A decline on ownership,
  not a deferral on shape; `tests/test_kind_registry.py` already pins the
  platform-owned fields absent.
* **`domain` in the registration row** — it rides beside the rows in
  `registry/content_kind_domains.json`, generated in the same pass.
* **SPARQL triples** while `mesh:PlaybookArtifact` is a phantom: emitting against
  an undeclared class writes data no shape can validate.
* **Mock content of any kind.** No `except ImportError` fallback that substitutes
  invented text. That pattern has produced a whole green graph of placeholder
  content in this repo.

## 8. Owed elsewhere

1. **`mesh:PlaybookArtifact`** as a TTL class, by the ontology owner. **Do not
   assume the `document` parent:** `mesh:GeneralDocumentArtifact` is a leaf under
   `mesh:PDFArtifact` because a `document` drop is PDF-shaped. A markdown file
   cloned from git is not, so the parent is the ontology owner's choice, not ours.
   Until it exists the output stays in `PHANTOM_OUTPUTS` and no triples are
   written.
2. **The overlay row** mirroring `passes`, and `review_shape` (§7). Per #161 the
   overlay mirrors doc-tools, never the reverse.
3. **No door grant is needed.** Unlike `document`, which is blocked on Lane 1
   offering the leaf, a playbook does not arrive through the user seam at all —
   it arrives by clone, so there is no leaf to grant and nothing here is blocked
   on the door.

## 9. Known gaps, and the one thing to rule

* **A chunk cannot be resolved to a commit.** The packet named two properties and
  this spec adds two; the resolved sha lands in the run metadata and on the
  document node, not on the chunk. So a retrieved chunk cites repo + path +
  heading, and the file at that path may since have changed. The fix is a third
  TEXT property (`ref`), and it is **not** taken here because it widens the shape
  the packet proposed.
* **Re-ingest leaves renamed headings behind.** A heading-path `chunk_id` makes a
  re-ingest overwrite the chunks that still exist, but a chunk whose heading was
  renamed keeps its old row: our re-ingest is additive. A doc-scoped delete before
  the write is the remedy and is safe here *because* every `chunk_id` is prefixed
  with its `doc_id` — unlike component IRIs, which are shared, where delete-by-
  subject is destructive.
* **`.md` only.** No `.markdown`, no `.rst`, no `.adoc`. Widening is a measured
  change, not a tuple edit.
* **No live fire.** Nothing exercises this until the build; the golden will be the
  only evidence, as it is for `document`.
* **TO RULE — making the two existing asset configs rows on a registry.** That is
  what would buy labels, overlay rows and Secret-by-name (§2.1), and it is a
  larger change than adding a kind: it re-plumbs two live ingests (DDS, RabbitMQ).
  **The recommendation is to land `playbook` on the mechanism as it stands and
  make the row migration its own item**, rather than re-plumbing two live ingests
  under cover of a docs feature. Retiring the mesh's hard-wired `docs/` source is
  the same decision. This spec assumes the recommendation; if it is ruled the
  other way, §2.1 and §2.3 are what change.

## 10. Fixture and golden the build owes

Mirroring `tests/fixtures/document/`: a byte-deterministic synthetic playbook
(markdown is trivially deterministic — no generator script needed, the file *is*
the fixture), a golden built **through the dispatcher** so it records what the
registry row actually runs, and a test pinning the fixture sha, the row shape, the
pass status, the heading tree and every `chunk_id`.

There must be **no `nondeterministic` block**: nothing on this path is
model-derived, and that is the point of the kind. The golden generator imports
`doc_tools`, so it is **run from PowerShell on the venv interpreter** — a system
interpreter blocks for ever at `python-magic` import.

## 11. Changing this contract

The heading tree, the `chunk_id` encoding and the `source`/`path` pair are what a
consumer quotes back to a reader. Changing the splitter, the slug, or the id
encoding **moves existing citations** and is a contract change: regenerate the
golden deliberately, say so in the PR, and packet the consumer.
