# Widening the PCN corpus from the inbound bucket — the widening set is empty

**Date:** 2026-09-30. **Question asked:** every inbound notice not already in the nine —
ground-truth it by identity, report the new denominator, and name any unseen formats
(scans, multi-notice PDFs, non-English).

**Answer: there are none.** Sandbox MinIO holds no notice that the corpus does not
already score. The denominator is unchanged. This is settled by complete enumeration of
every object in every bucket, not by inference from the inbound prefix.

---

## 1. What was enumerated

All 6 buckets, **4061 objects**, listed exhaustively via the S3 API from inside the
doc-tools pod (`sandbox/doc-tools-6466b8bfd9-x8mxc`, `S3_ENDPOINT_URL=http://iagent-minio:9000`):

| bucket | objects |
|---|---|
| `dag-lake` | 3 |
| `doc-pages` | 12 |
| `iagent-data` | 13 |
| `ontologies` | 29 |
| `processing-artifacts` | 3960 |
| `publog-lake` | 44 |

Scripts: `scratchpad/analyze_all_pdfs.py` (the PDF sweep), `scratchpad/ls_ext_census.py`
(every extension, plus every doc-like object outside the sustainment tree) and
`scratchpad/sust_ext.py` (every extension *under* a sustainment prefix). They are
read-only `list_objects_v2` / `get_object` calls.

## 2. The PDF sweep: 58 keys, 19 PDFs, 8 documents

58 keys end in `.pdf`. **39 of them are not PDFs.** They are Dagster IO-manager asset
values under `dagster-artifacts/{build_knowledge_graph,process_document_artifact}/`,
111–3804 bytes, whose *partition key* happens to end in `.pdf`. A sweep that counted
keys would have reported 58 candidate notices and 39 phantom widenings; they separate
cleanly by prefix, and by size.

The remaining **19 are real PDFs, and every one is under `processing-artifacts/sustainment/inbound/`.**
By ETag they resolve to **8 distinct contents**:

| md5 (ETag) | bytes | filenames carrying it |
|---|---|---|
| `c9674b3893e657e59fde3c78aad424ce` | 417830 | `onsemi_Generic_IPCN25300X.pdf` ×7 |
| `abe083fe8bab0e963874777280e8e293` | 181899 | `Diodes_PCN_2683_FULLGREEN.pdf`, `Diodes_PCN_2683_Rev1_EOL.pdf` ×3 |
| `fd9eff0fde5578c105975b729812dacc` | 32264 | `ADI_PDN_23_0120.pdf` ×3 |
| `0e754e2c30b2bb9713a75e720dc1215e` | 163821 | `EOL-36_BYV34-400,-BYV34-500.pdf` |
| `7593ca5333b7a6207d46e1118c7a58fa` | 108301 | `PCN23-002.pdf` |
| `cc3e45064219561ff48f87febeb0cd80` | 48750 | `PCN24-029.pdf` |
| `30954fcb867feb9355b762750860fed5` | 145603 | `TYC-PCN-24-210412.pdf` |
| `40d244f23763eb4887d80405e6ff0bbe` | 206441 | `onsemi_Generic_PD26044X1.pdf` |

Two facts follow, and both directions matter:

- **Every distinct content sits under a basename already in `TARGETS`.** Zero unseen
  documents.
- **Every `TARGETS` basename has a PDF object behind it.** No target is scored against a
  file that is no longer there.

The multiplicity is re-ingest history (`diodes_bbox`, `onsemi_run4`, `adi_run3`, …), not
new documents. `scripts/pcn_corpus_run.py::PREFER` already pins which manifest each
target scores from, for the three notices with non-equivalent copies.

## 3. Unseen formats: there is no object that could be one

The PDF sweep can only support "no unseen *PDF*". A notice arriving as `.docx`, `.tif` or
`.html` would have been invisible to it, so every extension in every bucket was tallied:

```
.json 1825  .jpg 1361  .png 307  .g4 238  .bmp 85  .pdf 58  .gif 51  .csv 33
.ttl 22  .xml 18  .pcx 17  .parquet 13  .md 12  .rdf 6  (none) 5  .avro 4
.cgm 4  .owl 1  .iads 1
```

**Absent entirely:** `.docx .doc .rtf .odt .html .htm .xhtml .tif .tiff .webp .xls
.xlsx .pptx .ppt .txt .eml .msg .zip .7z .rar .gz`. A notice in one of those formats is
not merely unscored — no such object exists.

Of the extensions that *are* present, every doc-like one outside `sustainment/inbound/`
is accounted for and none is a notice:

| what | count | where | what it is |
|---|---|---|---|
| `.bmp` + `.gif` | 136 | `processing-artifacts/40051/army/aviation/**/images/` | MIL-STD-40051 tech-manual figures (MAINTENANCE) |
| `.pdf` | 39 | `dagster-artifacts/**` | the IO-manager asset values of §2 |
| `.csv` | 33 | `publog-lake/_raw/**` | FLIS/CAGE reference tables, listed twice under two prefix orderings |
| `.md` | 12 | `doc-pages/docs/pages/**` | engineering walkthrough pages |

`.g4`, `.pcx` and `.cgm` (259 objects) are raster/vector figure formats, all in the same
40051 tech-manual tree; `.xml` (18) and `.iads` (1) are tech manuals in that tree too.
None is under a sustainment prefix — checked directly rather than assumed. Under **any**
key containing `sustainment`, the extensions present are `.jpg` 239, `.json` 88,
`.pdf` 58, `.ttl` 8, `.rdf` 1, and every non-PDF non-sidecar among them is an ontology
file in the `ontologies` bucket (`pcn_extension.ttl`, `S3000L.ttl`, `IOF_Core.rdf`, …) —
vocabulary, not notices.

The inbound prefix itself holds **346 objects**: 19 `.pdf`, 88 `.json` (22 of them
`manifest.json`) and 239 `.jpg` page renders. The JSON and JPG are ingest *outputs* of
the 19, not further inputs.

**Scans, multi-notice PDFs, non-English:** no new document arrived to carry any of these,
so none is newly in scope. The one text-layer pathology the corpus does hold is TYC's
dropped `ti` ligature, which is already detected and routed to a second witness.

## 4. The denominator, unchanged

| quantity | value |
|---|---|
| `TARGETS` entries (harness rows) | **9** |
| distinct documents | **8** |
| harness parts (`GT_TOTAL`) | **898** |
| distinct parts | **496** |

The 9-vs-8 and 898-vs-496 gaps are one thing: `Diodes_PCN_2683_Rev1_EOL.pdf` and
`Diodes_PCN_2683_FULLGREEN.pdf` are byte-identical (md5 `abe083fe8bab…`, 181899 bytes),
so the Diodes document is scored twice at `gt=402`. That is **not** a defect to fix here
— the pair is the corpus's only `identical` case and it is what pins
`notice_identity.classify_pair`'s bytes-before-keys ordering
([the contract, §6.4](notice-identity-contract.md)). But a rate quoted over 898 weights
Diodes at 89% of the corpus, and any recall claim should say which denominator it used.

Reports dated before 2026-09-24 quote 896; the two extra parts are two TYC cells that had
been glued together in ground truth.

## 5. What would change this

The widening set is empty **today**. It is not empty by construction — the moment a new
notice lands in `sustainment/inbound/`, it is a widening candidate. To re-check, re-run
`scratchpad/ls_ext_census.py` from the pod; the two things to look for are a `.pdf` whose
ETag is not in §2's table, and any extension not in §3's tally. Ground-truthing a new
notice means part numbers in `scripts/pcn_ground_truth.json` plus a `TARGETS` row, and
`check_ground_truth()` makes a disagreement between the two fatal.
