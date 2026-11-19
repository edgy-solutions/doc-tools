# ADR-0001: Memory-Bounded hi_res PDF Ingestion

- **Status:** Draft / Proposed
- **Date:** 2026-06-10
- **Deciders:** (TBD)
- **Related:** `doc_tools/components/document_parser.py`, `doc_tools/utils/extraction.py`,
  `doc_tools/assets/semantic_assets.py::build_knowledge_graph`

## Context

PDF ingestion is the most memory-intensive path in `doc-tools`. A ~16GB PDF OOM-kills the
`process_document_artifact` pod (default `DOC_PARSER` request/limit `6Gi`), with observed peak
RAM > 10GB.

What we established by tracing the path:

- **The file bytes are not the driver.** The source PDF is downloaded to a temp file on disk
  (`document_parser.py` `download_file(..., Filename=...)`), not into memory.
- **`unstructured` `hi_res` is the dominant consumer.** `document_parser` always calls
  `extract_text_and_metadata(..., extract_images=True)`, which forces `strategy="hi_res"` plus
  `infer_table_structure=True` (`extraction.py`). For every page this:
  - renders the page to a high-DPI bitmap (poppler/pdf2image → large PIL images),
  - runs layout detection (detectron2/yolox via onnxruntime), table-structure inference, and
    Tesseract OCR — a ~2–3GB resident **model baseline** (loaded once per process, then cached
    globally by `unstructured_inference`),
  - accumulates every emitted element in one in-memory list for the whole document.
  **Peak memory therefore scales with page count × DPI, not with file size.**
- **The document text is then copied several times.** `json.dumps(elements)` in
  `document_parser`, then in `build_knowledge_graph`: a full `json.load`, a `pages` copy, a
  `full_text` join, and the plugin's `md_elements` markdown conversion — multiple full-document
  copies held live at once.

### Hard constraint

**`hi_res` is mandatory.** Image and table fidelity are required for manufacturing work
instructions, so downgrading large documents to the `fast` strategy (text-only, no rendering,
no models) is **not acceptable**. The design must keep `hi_res` and still bound memory.

## Decision

Make peak memory **independent of total page count** by processing each PDF in **bounded page
batches**, keeping `hi_res` throughout.

### 1. Page-batch splitting (primary)

In `process_document_artifact`, before extraction:

1. Open the on-disk PDF with a lightweight library (`pypdf`/`pikepdf`) — metadata/structure
   only, **no rendering**, negligible RAM — and read the page count.
2. Split into fixed-size page ranges of `PAGE_BATCH_SIZE` (config/env, default ~25; tunable per
   resource budget).
3. For each batch: write the page range to a temp PDF, run `unstructured` `hi_res` on that
   batch, **append** its elements to the output stream, then **release the batch's elements and
   page rasters before the next batch**.
4. **Stream** elements to `text.json` incrementally (write per batch / via a file handle) rather
   than building one `json.dumps(elements)` string for the whole document.

Because `unstructured_inference` caches the vision/OCR models as process-global singletons, the
~2–3GB model baseline is **loaded once and reused across all batches** — batching does not
multiply model RAM. It bounds only the *variable* part (page rasters + the element list), so:

```
peak ≈ model_baseline (fixed) + PAGE_BATCH_SIZE × per_page_cost
```

which is independent of document size. Choose `PAGE_BATCH_SIZE` so the variable term fits the
pod budget with headroom.

### 2. Global consistency across batches (required)

- **Page numbers** reset to 1..N inside each split PDF; restore global numbering by offsetting
  by the batch start (or pass `starting_page_number` to the pdf partitioner per batch).
- **Element/section IDs** and ordering must remain globally unique and monotonic across batches.
- **Boundary-spanning tables/figures:** a table or figure straddling a batch boundary may be
  split. Mitigate with a small page **overlap** between batches (and de-dup), or a
  boundary-aware split that avoids cutting mid-structure. Document the residual risk.

### 3. Per-page DPI cap (complementary)

Batching bounds page *count*, not per-page *size* — a single page with a massive embedded raster
can still spike at `hi_res`. Expose `pdf_image_dpi` (env/config, sensible default below
`unstructured`'s ~200) to cap per-page raster footprint, accepting a modest OCR-accuracy cost on
dense pages.

### 4. Downstream copy reduction (`build_knowledge_graph`)

Avoid holding `text_elements` + `pages` + `full_text` + `md_elements` simultaneously: stream
elements from `text.json` (e.g. `ijson`) and convert/chunk lazily, releasing processed elements.
Secondary to (1) but removes the second OOM surface.

### 5. Memory headroom (margin, not fix)

Keep `DOC_PARSER` request/limit sized for `model_baseline + one batch + downstream copies` with
margin. Raising the limit alone is explicitly **not** the fix (it only moves the cliff); it is a
safety margin once memory is bounded by (1).

### 6. Pre-flight observability / guard

Log page count and the chosen batch plan at the start of ingestion. Optionally enforce a
hard page-count ceiling (or route oversized inputs to a dedicated high-memory / async worker)
so the failure mode is an explicit, actionable error rather than an OOM kill.

## Consequences

**Positive**
- Peak RAM is bounded and predictable; arbitrarily large PDFs (16GB / many-thousand-page) become
  feasible within a fixed pod size, **with `hi_res` preserved**.
- Removes both OOM surfaces (extraction and the downstream full-document copies).
- `PAGE_BATCH_SIZE` / `pdf_image_dpi` give operators a direct memory↔throughput dial.

**Negative / cost**
- Added complexity: a splitter, a batch loop, incremental `text.json` writes, and global
  page/ID reconciliation.
- Tables/figures on a batch boundary risk being split (mitigated by overlap; residual risk).
- Per-batch partition calls add wall-clock overhead (models are reused, so no per-batch model
  reload, but each batch re-enters the partition pipeline).
- A pathological single oversized page is only mitigated by DPI tuning, not batching.

## Alternatives considered

- **A — Size-gate to `strategy="fast"` for large PDFs.** *Rejected:* violates the `hi_res`
  hard constraint (loses image/table fidelity).
- **E — Just raise pod memory.** *Rejected as a fix:* unbounded — only moves the OOM cliff.
  Retained as a margin once (1) bounds memory.
- **Per-page-range Dagster sub-partitions** (each batch a partition, processed/retried
  independently). A viable variant of (1) with stronger isolation and retry granularity, at the
  cost of heavier orchestration and cross-partition assembly. Worth revisiting if batches need
  independent retry/scale.
- **Offload extraction to a dedicated autoscaled high-memory worker.** Ops-level alternative;
  complements rather than replaces memory bounding.

## Open questions

- Default `PAGE_BATCH_SIZE` and `pdf_image_dpi` for the `6Gi` budget — derive empirically from
  the threshold testing already underway.
- `pypdf` vs `pikepdf` for splitting (license, speed, robustness on malformed PDFs).
- Overlap size vs. boundary-aware splitting for spanning tables/figures.
- Whether to adopt the sub-partition variant now or keep batching in-asset.
