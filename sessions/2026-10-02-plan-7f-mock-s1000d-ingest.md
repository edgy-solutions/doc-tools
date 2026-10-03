# Plan — ingesting the mock S1000D publication (7f)

**Status: PLAN ONLY. Nothing implemented, nothing uploaded, no credentials
handed over.** Written for architect review. Every claim below was read out of
the tree at `main` + `pcn/gate-per-notice-and-log-preservation` on 2026-10-02;
file:line references are given so you can check any of them cheaply.

The other agent's report is largely accurate and the bug it found is real. But
three of its load-bearing claims are wrong in ways that change the plan, and
the first of them voids its headline result. Those come first.

---

## 1. Three corrections to the report

### 1.1 The parser they validated is not on the ingest path — their result does not describe what the sandbox would produce

There are **two** S1000D parsers in `doc_tools/parsers/`:

| module | classifies? | on the ingest path? |
|---|---|---|
| `s1000d_ingest.py` (`extract_facts`) | yes — `classify_data_module` at `:129` | **no** |
| `s1000d_rdf.py` (`S1000dGraphBuilder`) | **no** | **yes** |

- `doc_tools/assets/xml_ingestion.py:11,131` imports `S1000dGraphBuilder` from
  `s1000d_rdf.py` and routes `'s1000d'` to it.
- `extract_facts` is called at exactly one site — `s1000d_ingest.py:335`, inside
  its own module. **No asset imports `s1000d_ingest`.** Their `check.py`
  imported the module that nothing in the pipeline calls.
- `s1000d_rdf.py` is 122 lines and its only data-module type triple is
  `s1000d_rdf.py:65` — `self.graph.add((dmc_uri, RDF.type, self.MIL.DataModule))`.
  `classify_data_module` is never called in that file.

**Consequence:** the "5 of 6 correct, 1 generic" result is not the pipeline's
behaviour. On the real path **all six** modules land as generic
`mil:DataModule` — the descriptive/procedure/fault-isolation/IPD distinction
does not exist downstream at all. The 320 info-code miss is not an outlier;
it is the only case where the unused parser and the used one happen to agree.

This is the single most important thing for you to rule on, because it decides
whether the exercise is "ingest a mock pub" or "the S1000D path has no
classification and a mock pub is how we found out."

### 1.2 The `disassyCode` fix is not one line, and the real fix carries a URI migration

The bug they found is genuine: `s1000d_rdf.py` reads only `disasCode` /
`disasCodeVariant` (the short names), so S1000D 4.x documents using
`disassyCode` silently drop that segment, and two modules differing only in
that code collide on one `dmc-` URI.

But adding the fallback does **not** make the two parsers agree, because
`s1000d_rdf.py:45-66` reimplements the join that `s1000d_ingest.py:105`
explicitly says not to reimplement:

| | `assemble_canonical_dmc` (`dmc_canonicalizer.py:180-207`) | `s1000d_rdf.py` inline join |
|---|---|---|
| case | uppercases every segment | as-authored |
| empty segments | **preserved** (fixed positions) | **dropped** (`if p`) |
| shape | 8 hyphen groups, `ssc+sssc`, `dis+dvar`, `info+ivar` concatenated | 11 flat segments |

Worked example on the same inputs: `AE--32--00-00A-520A-A` (canonical) vs
`AE-32-00-00-A-520-A-A` (inline). The fallback alone leaves them different IDs.

The correct fix is to call `assemble_canonical_dmc` from the RDF builder. That
changes the URI shape, which **rewrites every existing S1000D DMC URI in Jena,
Neo4j and any Weaviate row keyed on one.** That is a migration, and it is your
call, not a drive-by.

### 1.3 rdflib is installed — the triple count is measurable now, with no upload

They reported rdflib absent and gave a ~32-33 triple estimate read off the
source. `py -c "import rdflib"` does fail, but `py` is the **system** python.
The project venv `.venv\Scripts\python.exe` has **rdflib 7.6.0 and lxml**.

So the real builder can be run against their XML on this workstation, right
now: no MinIO, no credentials, no cluster, no sandbox write. That turns the
estimate into a measurement and — more to the point — it is how 1.1 gets
demonstrated rather than argued.

Two mechanical notes for whoever runs it:
- `doc_tools/__init__.py` ends with `from .definitions import defs`, so any
  `import doc_tools.parsers.*` pulls in the entire Dagster `Definitions`. That
  is their import hang; it is not a bug. Load `s1000d_rdf.py` by file path
  (`importlib.util.spec_from_file_location`) and it is a plain lxml+rdflib
  module. `doc_tools/parsers/` has no `__init__.py`, which makes this clean.
- Run it from **PowerShell**, not the Bash tool
  ([[doc-tools-local-suite-hangs-on-libmagic]]).

---

## 2. Findings that are ours, not theirs

These are defects in doc-tools that the mock pub surfaced. None is caused by
their document.

1. **The 3xx fallthrough is silent against an explicit contract.**
   `mil_info_code_map.py` maps first digits `0,2,4,5,7,9` and omits `1,3,6,8`;
   `classify_data_module` returns `DATA_MODULE_ROOT` via `.get(..., default)`
   with no log and no counter. Its sibling `mil_40051_classifier.py:13-14`
   quotes the standing rule — *"Fallthrough to mil:DataModule must log/count
   when it fires (no silent absorption)"* — and honours it, raising on an
   unenumerated root (`:57-61`). Same contract, two different answers.
2. **A docstring documents a warning that does not exist.**
   `mil_info_code_map.py:81` claims *"an explicit warning logs — surfacing
   rather than hiding the gap."* It is the only occurrence of "warning" in the
   file and it is prose. The same docstring also carries
   *"⚠ Confirm the info-code ranges against the actual S1000D issue in use"* —
   still unconfirmed, and 1/3/6/8 are where that bites.
3. **Zero test coverage of the classifier.** Nothing in `tests/` imports
   `classify_data_module`. The only two S1000D fixtures
   (`test_parsers_rdf.py:29`, `test_xml_ingestion.py:15`) both use
   `infoCode="520"` — a *mapped* code, so neither fixture can ever exercise a
   fallthrough. Their mock is the first input that does.
4. **`mil:part-{pn}` and `mil:fig-{fig_id}` are document-independent subjects.**
   `s1000d_rdf.py:82,91,108` coin global URIs from the raw part number and the
   raw `figure/@id`. A mock document's parts and figures **MERGE onto the same
   nodes real publications use**, and `fig_0`-style ids collide trivially. This
   is the same hazard already recorded in
   [[component-iris-are-shared-so-delete-by-subject-is-destructive]], one repo
   over. It is the reason §4.3 recommends what it does.
5. **Minor:** tools and spares share the `part-{pn}` prefix (`:82` and `:91`),
   so one part number appearing in both `reqSupportEquip` and `reqSpares`
   yields a single subject typed both `mil:Tool` and `mil:Part`.
6. **The fault → procedure → parts walk is a feature gap, not a bug.** Their
   assessment is right. A 122-line builder emits `DataModule`, `Tool`, `Part`,
   `Figure` and four predicates. There are no fault-code nodes, no
   cross-reference edges between modules, and no parts-list item structure.
   Nothing about their document causes this and no fix to their document
   changes it.

---

## 3. Proposed phase order

Deliberately ordered so that **every one of their three asks is answered by
evidence collected before it has to be answered.** Phase 0 needs nothing from
you.

**Phase 0 — measure locally (no decisions, no upload, no credentials).**
Run `S1000dGraphBuilder` over all six of their modules with the venv python,
by file path. Report: triple count, the full set of `RDF.type` objects emitted,
every `dmc-` URI, and every `part-`/`fig-` URI. Expected outcome — and the
thing to confirm or refute — is six `mil:DataModule` and zero classified
kinds (§1.1), plus a collision list for §2.4. One file, committed under
`sessions/`. **This is the deliverable that makes the rest decidable.**

**Phase 1 — your rulings (§4).** Nothing proceeds past here without them.

**Phase 2 — fixes, if you authorise them.** Candidates, each independently
shippable, smallest first:
- (a) `mil_info_code_map.py`: log/count the fallthrough, and delete or fulfil
  the false docstring at `:81`. Pure observability; no URI change; no
  migration. Safe regardless of everything else.
- (b) Tests for `classify_data_module`, including an unmapped first digit.
  Currently zero.
- (c) The `disassyCode` fallback **plus** the `assemble_canonical_dmc` call,
  with a migration for existing URIs. Bundled on purpose: shipping the
  fallback alone changes IDs *and still* leaves the two parsers disagreeing,
  which is the worst of the three states.
- (d) Call `classify_data_module` from `S1000dGraphBuilder` so the kind
  distinction reaches the graph at all. This is the §1.1 repair and it is a
  behaviour change to a live path.
- (e) The fault/xref/parts-list edges (§2.6) — a feature, scoped separately.

**Phase 3 — route, if you authorise an ingest.** See §4.1.

**Phase 4 — ingest and verify.** Single document, verified by reading the graph
back, with the cleanup from §4.3 established *before* the write, not after.

---

## 4. The three asks — your decisions

### 4.1 Route: widen the sensor, add a sibling, or launch by hand?

Their framing is right; the options are not equal.

- **Hand launch of `xml_graph_sync_job`** (GraphQL, explicit bucket+key).
  *Recommended for a first pass.* No code change, no build, no deploy, no
  standing trigger. Note the known trap: a re-upload cannot retrigger an
  existing partition ([[reupload-cannot-retrigger-an-ingest]]) — launch the
  partition explicitly.
- **Sibling `S3SensorComponent` with `prefix="s1000d/"`.** The clean permanent
  answer. `definitions.py:143-166` is the pattern; the comment at `:154-158`
  already anticipates it.
- **Widening the existing `prefix`.** *Not recommended.* The comment at
  `definitions.py:130` records that the narrow `40051/` prefix is what stops
  the sensor looping on its own outputs. Widening re-opens that.

Either code route needs a deployed image, and **a green `build-and-push` on a
PR publishes nothing** — the push step is gated on `event_name`
([[green-build-and-push-on-a-pr-pushes-no-image]]). Deploying means a merge to
`main` or a `workflow_dispatch`.

### 4.2 MinIO credentials

**I will not supply these, and the answer is that nobody should hand them over
in chat.** The mechanism is already env-driven — `definitions.py:43-46` reads
`S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and
`MINIO_SECURE`. If that agent needs to write to MinIO it should get its own
values through the same env path, out of band. Two standing rules apply: never
`kubectl -o jsonpath` a Secret ([[a-jsonpath-typo-dumps-the-whole-secret]]),
and a credential pasted into a transcript is disclosed and must be rotated.

Phase 0 needs none of this, which is most of the point of ordering it first.

### 4.3 Writing into the shared corpus — recommend NO for the first pass

Three independent reasons:

1. **Synthetic content becomes indistinguishable from real tech manuals.**
   `xml_ingestion.py:24` sets `_XML_INGEST_DOMAIN = "MAINTENANCE"`, and
   `_apply_post_sync_domain_labels()` stamps `:MAINTENANCE` on every imported
   Resource node. Downstream agents filter by exactly that label. There is no
   synthetic-vs-authoritative marker on this path.
2. **The DMC shape is about to change** if §1.2(c) ships. Anything written now
   is orphaned URIs after the migration.
3. **Part and figure subjects are global** (§2.4), so the write is not confined
   to the document's own graph even though the document's triples are.

Isolation and rollback, accurately: the XML path's Jena write **is** scoped to
`urn:doc:{s3_key}` (`semantic_assets.py:605`), so Jena is a clean
`DROP GRAPH`. Neo4j is **not** equally clean — the wipe is keyed on the root
URI, while `mil:part-*` / `mil:fig-*` nodes may be shared, so a delete-by-
subject there is the destructive move the memory above warns about. Weaviate
`DocumentChunk` rows would need a delete-by-`doc_id` filter. So "we can just
remove it" is true for one of the three stores and needs care in the other two.

**Recommendation:** Phase 0 locally; if an ingest is wanted, point it at a
throwaway Fuseki/Neo4j first ([[the-default-graph-seal-drops-production-graphs]]
is the precedent for why a seal run gets its own target). The open question of
whether this content is generic enough to be public is yours and is unaffected
by anything here.

---

## 5. Decisions needed from you

1. Does §1.1 reframe this as "fix the S1000D classification path" (Phase 2d)
   rather than "ingest a mock pub"?
2. Authorise Phase 0 unconditionally? (No code change, no upload, no creds.)
3. Phase 2(a)+(b) — the fallthrough log and the missing tests — as their own
   PR, independent of everything else?
4. Phase 2(c): is the DMC canonicalisation + URI migration in scope now, or
   deferred with the `disassyCode` bug documented and left open?
5. Route: hand launch, sibling sensor, or hold?
6. Shared-corpus write: hold, or throwaway target, or proceed?

My answers if you want defaults: yes to 1; yes to 2; yes to 3; **defer** 4 with
the bug filed; hand launch for 5; **hold** for 6.

---

## 6. Not in scope / explicitly not done

- Nothing implemented. No file changed by this plan.
- No credentials read, echoed, or supplied.
- Their `infoCode="320"` choice is **not** a fault to correct. It is the only
  reason §2.1 and §2.3 are visible. Changing the document to a mapped code
  would hide the defect.
- Unrelated carry-forward is untouched: #43 is `MERGEABLE/UNSTABLE` and
  deliberately unmerged pending your call; #28 is held red awaiting `lane/ca`.
