# Report to 7f — grid forwarding built, PR #17 OPEN (held, not merged)

Dispatch: "Tier 1 returns a declined-grid record (exact cells, reason) instead of [];
tier 2 receives the grid plus the image and labels columns only; part strings come from
the grid, never pixels. Branch, sealed on PCN23-002's SYTX9 row read from the grid with
the crop deliberately re-cut. Corpus must stay 898/898. PR open, not merged."

- Branch `pcn/grid-forwarding`, one commit `dc97752`, based on `f3daa3b` (includes the
  merged #15 digest pin). PR: https://github.com/edgy-solutions/doc-tools/pull/17 — OPEN,
  MERGEABLE, **not merged**.
- Suite: **520 passed, 9 skipped** (from PowerShell; the Bash tool still hangs on libmagic).

## What shipped

| Path | Change |
|---|---|
| `doc_tools/utils/table_text_layer.py` | decline record carries `grid` (exact cells) beside reason/n_rows/n_grid_rows; exports `is_part_row` so the MPN-bearing count and the forwarded rows share one predicate |
| `baml_src/sustainment.baml` + `doc_tools/baml_client/*` | new `GridColumnRoles` / `LabelGridColumns` (indices only), image LAST in a user message per the vLLM-gemma NOTEs |
| `doc_tools/plugins/sustainment.py` | declined page → `LabelGridColumns`, not `ExtractParts`; part strings read verbatim from grid cells; out-of-range index or a raising call falls back to the pixel path; `stats["text_layer_declines"]` projected WITHOUT `grid` |
| `prompts/sustainment_grid_columns_instructions.md` | canonical prompt (`PROMPT_SOURCE=file`) |
| `tests/test_grid_forwarding_seal.py` | 7 tests: the seal + the rendering contract |

The grid rides **in-process only**. That dict is persisted into `extraction.json` and read
as a corpus manifest by `scripts/pcn_corpus_run.py`, so forwarding it whole would have put
every declined table's full cell content into the stored manifest.

## The seal, mutation-checked both ways

Real PCN23-002 ground truth — 18 MPNs in printed order, `SYTX9-122HP-1+` last. Asserts all
18 verbatim from the grid with `ExtractParts` **never called**; identical output whether the
image is absent or present-but-re-cut; fallback on a raising label call and on an
out-of-range `affected_col`; persisted declines omit `grid` while the forwarded list keeps it.

Not just green — reddened on purpose. Sourcing the strings from pixels reds 2 of 5 including
the primary test. Restoring the old row rendering reds the two rendering-contract tests.

## The defect no test could reach

`_grid_to_text` rendered the row index as a bare `str(i)` leading field — a table whose
first column is the row number, inviting the model to answer `1` for the FIRST data column.
That off-by-one hands back the **replacement** column as `affected_col` and mispairs every
row, silently. The suite cannot see it: `LabelGridColumns` is stubbed everywhere, so the
defect lives only in the wording the model sees.

Fixed by printing every index the model must return — columns HEADED `c0 c1 …`, rows
labelled `[row N]` — and rewriting the prompt to "read the N off the heading, do not count
columns", with `[row N]` named as a row, never a column. The guard is now on the rendered
TEXT, the only place it can be. The subagent's implementation did not have this; it was
found by reading what the model would receive.

## Two things not proven, said plainly

1. **898/898 is NOT provable from this branch.** The corpus harness scores the STORED
   manifests, produced by whatever ran at ingest. This change is inert until build → pin →
   re-ingest (`docs/pcn-reingest-runbook.md`). Owed at the next pin bump. What IS shown:
   no behavioural change on any page tier 1 did not decline.
2. **Grid forwarding never engages where tier 1 emitted any parts** — the router
   short-circuits at `if tl_parts: parts_d = tl_parts`. A mixed document (some tables read,
   one declined) keeps the pixel path for its declined table. Pre-existing, out of scope,
   and a real bound on reach — the first thing to check if a notice with a declined table
   still comes up short.

Also: `scripts/check_drift.py` counts an unfetchable prompt as drift, so the new prompt file
will report drift until it exists in Langfuse under `LANGFUSE_PROMPT_LABEL`. It is wired into
no workflow, and the runtime default serves the committed file.

## CI

All four checks green on `dc97752`: `tests`, `changes`, `telemetry-contract`,
`build-and-push`. The first `build-and-push` attempt failed at 15m30s in the **arm64**
leg — HuggingFace returned `504 Gateway Timeout` for
`microsoft/table-transformer-structure-recognition` in the model-prebake layer, which no
file in this PR touches. A re-run of the failed job alone passed (33m36s), confirming the
504 was transient. **Not evidence about the image's contents** — a green build proves an
image exists, not what is inside it.
