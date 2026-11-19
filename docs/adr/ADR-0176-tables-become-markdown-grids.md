# ADR-0176 — tables are converted to Markdown grids for the global pass

**Status:** built
**Date:** no ruling date is recorded; carried in `AGENTS.md` as standing guidance · recorded
2026-11-18
**Deciders:** `AGENTS.md` §Table Processing, this repo's standing guidance — no individual
ruling is on record
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:99-101`; implemented at
`doc_tools/utils/formatters.py:57-88` (the `Table` branch of
`convert_element_to_markdown`)
**Related:** [ADR-0173](ADR-0173-the-baml-prompt-layout-is-fixed.md) (what the converted text is
placed into), [ADR-0129](ADR-0129-a-customer-part-number-is-never-an-affected-part.md) (what a
grid's columns are allowed to mean),
[ADR-0222](ADR-0222-the-corpus-validation-is-the-authority.md),
[`docs/arch/components/extraction-pipeline.md`](../arch/components/extraction-pipeline.md)

## Context

The dense data in these documents is in tables: part number against replacement, step against
tooling, item against quantity. An `unstructured` `Table` element carries two representations of
that — `.text`, which is the cell contents flattened into a run of words with the row and column
structure gone, and `metadata.text_as_html`, which keeps the structure but spends a large part of
the context window on markup.

Handing the model `.text` loses the one thing a mapping needs: which value was in the same row as
which other value. A part-to-replacement table flattened to prose is a list of part numbers from
which no pairing can be recovered reliably, and the extraction does not fail — it returns
plausible, wrongly-paired rows. Handing it raw HTML keeps the pairing and pays for it in tokens,
at a point where the chunking budget is already derived from `LLM_NUM_CTX`
(`doc_tools/plugins/manufacturing.py:159-162`).

## Decision

**During the global pass, a table element is converted to a Markdown grid, and the grid is
emitted alongside the element's raw text rather than instead of it.**

- The conversion is `doc_tools.utils.formatters.convert_element_to_markdown`, called on every
  element before chunking — `manufacturing.py:86` and the equivalent in
  `doc_tools/plugins/maintenance.py:51` (inside `execute_global_pass`, `:37`). `AGENTS.md:100`.
- `metadata.text_as_html` is parsed with `pandas.read_html` and rendered with `to_markdown`
  (`formatters.py:68-76`). The frame is cast to `object` before `fillna("")` so an all-NaN or
  numeric column does not raise a pandas `FutureWarning` in place (`:73-75`).
- **The output is hybrid, deliberately** (`:84-88`): a
  `### TABLE STRUCTURE (SPATIAL) ###` section carrying the grid, then a
  `### TABLE CONTENT (SUPPLEMENTAL RAW TEXT) ###` section carrying the element's `.text`. The
  stated reason is recovery: if OCR missed cells in the HTML structure but captured them in the
  raw text, the model still sees them.
- Degenerate or empty table HTML is **non-fatal**: the conversion falls back to the raw HTML
  string and logs at debug level, so it does not emit one line per table per document
  (`:77-82`). With no HTML at all the structure section reads `Structure unavailable` and the
  raw text still ships.
- Non-table elements pass through unchanged (`:90-91`), apart from the figure-placeholder branch
  at `:18-55`, which is a separate concern.
- Pinned by `tests/test_formatters.py:20` (HTML converts to a grid, hybrid output), `:34`
  (object-form metadata), `:42` (no HTML marks the structure unavailable) and `:49` (missing
  cells fill without the pandas warning).

## Consequences

- Row-wise mapping survives into the prompt, which is what makes a part-to-replacement
  extraction possible at all.
- The grid costs fewer tokens than the HTML it replaces and more than the flattened text —
  and the **hybrid output sends both representations**, so a table's cost in context is the grid
  plus its own raw text. That is a deliberate purchase of recall with context budget, and it is
  the reason a table-dense document chunks into more pieces than its character count suggests.
- Duplicating every cell twice in one prompt is a real risk of its own: a model can read the
  supplemental text as a second table. No measurement of that effect is recorded.
- The fallback path means a table whose HTML will not parse still reaches the model, as raw
  HTML, with no error anywhere above debug level. A silently-degraded table is therefore
  possible and is not visible in a run's output.
- The conversion only applies where a `Table` element exists. A table that the parser never
  emitted as a `Table` is outside this decision entirely, and that is a separate, measured class
  of miss — see [ADR-0222](ADR-0222-the-corpus-validation-is-the-authority.md) for the authority
  on `table_text_layer`.
- `pandas` and its HTML parser are on the extraction path as a result, including in the pod
  image.
- Only `dfs[0]` is used (`:75`): an element whose HTML contains more than one table
  contributes its first one. No decision about multi-table elements is recorded.

## Alternatives considered

- **Send `.text` only.** This is the behaviour the rule replaced. Rejected because the row
  structure, which is the extractable content, is exactly what `.text` discards.
- **Send `text_as_html` only.** Not recorded as explicitly declined, but it is what the grid
  conversion exists to avoid: the markup is context the model does not need, and the chunk budget
  is finite. It survives as the **fallback** when parsing fails, which shows it was understood as
  usable but not preferred.
- **Send the grid only, without the supplemental raw text.** Rejected in the comment at `:85`:
  the raw text is the recovery path for cells the HTML structure lost to OCR.
- **Convert tables to a structured payload — JSON rows, or a typed grid passed outside the
  prompt.** Not recorded as considered. The sustainment path does something adjacent for grid
  forwarding (`baml_src/sustainment.baml:146-171`), but that is a different decision about a
  declined table, not about this pass.
