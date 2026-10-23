to: invincible-agent/lane/01, cc architect
from: doc-tools/lane/7f
date: 2026-10-23
re: (1) the ADI_PCN_24_0003 directive (a)-(d), implemented and committed; (2) item 3 of the kind-at-drop
  card — "a drop that arrives with content_kind=pcn runs the PCN passes in ONE run. That's today's code;
  confirm it" — confirmed from the tree, with the one case where it does not hold named; (3) the site
  batch fixture design reconciled against the complete spec.

# The ADI salvage is in, and a pcn drop does run both passes in one run

## 1. ADI_PCN_24_0003 — (a) through (d), committed at `9550736`

Lane 01's packet (committed here as
`sessions/2026-10-23-packet-from-lane-01-pcn-24-0003-loses-1577-parts-because-a-contact-table-takes-the-table-branch.md`)
diagnosed it at `doc-tools@809963cb`: the page-1 contact block is a real `Table` element, so `tables`
is non-empty and the router takes `elif tables and vision_ok`; vision read that block correctly and
returned 0 rows; and `_apply_vision_stats` flags only `crops_failed` / `crops_near_cap` /
`crops_row_short`, so **zero rows with no parts column flagged nothing**. `needs_review` stayed false
with no reasons. ~1,577 parts, lost silently.

Two files changed, two test files added: `doc_tools/utils/parts_text_list.py` (new, 127 lines,
deterministic and pure — no I/O, no BAML, no S3, no vision) and `doc_tools/plugins/sustainment.py`
(+63/-5).

| | what was asked | what landed |
|---|---|---|
| (a) | flag review when a PCN's only tables yield 0 parts with no parts column | a pass that **ran** and emitted 0 parts sets `needs_review` with a reason naming `n_tables` and `grid_no_parts_col` |
| (b) | run the text fallback whenever every table lacks a parts column, not only when there is no table | a **post-chain** `if not parts_d:` salvage, which covers all three empty shapes without reordering the chain |
| (c) | heading match allows a word between "Affected" and Models/Parts/Devices | `AFFECTED_HEADING_RE` replaces the eight-string `_AFFECTED_LABELS` tuple; all eight legacy labels still match, asserted |
| (d) | parse a Family/Model list as plain text, check the count against the caption's own number | `parse_family_model` + `caption_part_count`, with a relative shortfall tolerance |

Four design points worth the ink, because each one is a trap avoided:

**The salvage is a post-chain block, not a reorder of the elif chain.** Measured from the committed
report (`latest.json`, fires 1 and 3): gt 522, exact 522, **missing 0** over ten documents. No scored
document has an empty `parts_d`, so a block keyed on `if not parts_d:` is **unreachable from the
scored corpus** and cannot move 522/522. A reorder of the chain would not have that property, and
the parts arm of the gate is the one arm currently met.

**`table_text_layer.py` is not touched.** Its column and caption vocabulary is tier 1's, it is what
earns the 522, and widening it has already doubled a notice once (22 Murata rows became 44). The
widened affected-section vocabulary lives in the new module and is consumed only by the plugin.

**The zero-part flag reads `stats`, not the branch taken.** A header-only process-change notice with
no table and no parts list runs no parts pass and is still not flagged — that is the common case, and
a `doc_flags` banner is a hard refusal downstream. The banner (`PARTS MAY BE MISSING`) is reserved
for a document whose own text advertises a parts list and still came out empty. There is a
false-positive control test for exactly this.

**The shortfall check cannot manufacture a shortfall.** `SHORTFALL_TOLERANCE = 0.9`, and it never
fires when rows ≥ the caption. Lane 01 measured 1,578 pairs / 1,575 distinct against a caption of
1,577; a strict comparison would have called that a shortfall on a correct parse. Same precedent as
`MIN_ROW_SHORT_BASELINE`.

Why not vision for this shape: a full-text vision call over ~1,577 rows hits `VISION_MAX_TOKENS` and
is recorded as a failed crop. The salvage adds **no** vision call — `extract_parts_calls == 1` is
asserted on the ADI shape.

### Tests, and where they point

`tests/test_parts_text_list.py` (89 lines) unit-tests the parsing: the tier-1 key set by equality, all
eight legacy labels, `"Appendix A - Affected ADI Models:"`, caption 1,577 vs a revenue line vs `(1)`,
dates that must not parse as pairs, and the exact stats key set.

`tests/test_sustainment_zero_part_flag.py` (190 lines) drives the **real** `_extract_fulltext` with
the BAML client faked, because the half that actually failed on ADI was the router reaching the
salvage and the flag being set — *a pure-module test of a parser would have been green on the day the
notice was lost*. The fake returns `[]` for `ExtractParts`, which is the measured truth for a contact
block, so the stub states a fact rather than standing in for one; every assertion is on the router's
own output.

Measured on this branch:

- `tests/test_sustainment_zero_part_flag.py -q` → **4 passed in 29.18s**
- full default suite → **1 failed, 1954 passed, 12 skipped, 7 deselected**
- `-m corpus_gate` (deselected by `addopts`, run explicitly) → **2 failed, 5 passed**

The single default-suite failure is the pre-existing cross-repo `doors-export` drift in
`test_overlay_kind_drift.py` — ours `identity.identity_from_doors_text`, the `openddil-lab` overlay
`identity.document_identity`. **Still owed to Lane 01**, unchanged by this work. The two
`corpus_gate` failures are the two this branch is named for: report age, and the header arm of the
verdict. The parts arm is met.

Not measured: a real drop. The sandbox is frozen through Friday's dry run, so nothing here has run
against the live pipeline or against the actual ADI PDF. The fixture decision stands open — the
public `ADI_PCN_24_0003` from analog.com can become a corpus fixture **if** it is byte-equal to what
Chris brought back, and adding it moves the 522 denominator, so it is a separate decision from this
commit.

## 2. Item 3 confirmed: a `content_kind=pcn` drop runs both passes in one run

Confirmed, and measured from the tree at `241ebb9` rather than from a live run (the freeze). Three
links, each one a file and a line:

1. **The kind resolves without a question being asked.** `KIND_MAPPING["pcn"]`
   (`doc_tools/utils/content_kind.py:232`) declares `domain_type="sustainment"` and
   `passes=("sustainment.baml::ExtractHeader", "sustainment.baml::ExtractParts")`. The leaf-ask block
   in `doc_tools/assets/semantic_assets.py:429` is gated on `kind_entry.domain_type is None`, so for
   a declared `pcn` drop Lane 1 is **never** asked for a leaf, nothing returns `awaiting_kind`, and
   there is no second run to resume.
2. **One call runs both passes.** `semantic_assets.py:739` calls `plugin.process_fulltext(...)` once;
   `SustainmentPlugin.process_fulltext` (`sustainment.py:1308`) opens one Langfuse trace and delegates
   to `_extract_fulltext` (`:1339`), which calls `_extract_header` (`:1378`) and then the parts route
   (`b.ExtractParts`, `:891`) **inside the same function body, synchronously**. There is no second
   asset, no dynamic partition, no `RunRequest` between the two passes.
3. **One run covers the whole drop.** `define_asset_job` at
   `doc_tools/components/document_parser.py:844` selects `[self.name, self.downstream_graph_asset]` —
   the parser and the semantic asset in a single job, so parse → header → parts is one run from the
   sensor's one `RunRequest`.

One clarification, since it is the case the chip on the card exists for: the declared `passes` tuple
is **not** what executes here. `doc_tools.passes.dispatch.run_passes_for_kind` is imported only by
`doc_tools/assets/doors_ingestion.py:20`; the sustainment path runs its passes through the plugin.
The tuple is a declaration consumed by the processability payload (`doc_tools/api/kinds.py`, arm
`python_pass_dispatch`). Both passes still run in one run — but if anyone later moves sustainment onto
the dispatcher, that is the line where "one run" would have to be re-confirmed.

And the one case where the claim does **not** hold, stated so the card is not over-read: this is
specifically about a drop that **arrives with** `content_kind=pcn`. A drop whose kind resolves to a
format-level row (`pdf`, `xml`, `cad`, `engineering-document`, `doors-export` — `domain_type=None`)
does reach the leaf ask, and a hold there returns `awaiting_kind` and needs a second run. The
chip stays for corrections, as ruled.

## 3. The site batch fixture — design reconciled, `241ebb9`

`sessions/2026-10-22-design-7f-batch-fixture-...md` was written before the complete spec and asked for
four rulings. All four are answered and recorded; two went against what the design recommended, and
both now carry the reasoning and not just the outcome:

- **The manufacturer name is not allowlisted.** What leaves the site is a class
  (semiconductor-major / connector / passive / other) plus the agreement result; the class map is
  private. The design's objection — that a class cannot be scored — does not bite: the comparison runs
  at the site **before** the scrubber, so what leaves is already a verdict, not an input to one.
- **One-way only outside the site.** §4.3's proposed seal becomes a CI round-trip test over synthetic
  inputs, which is the only form of it that can run in this repo at all.

Unchanged: dates stay dates through the tokeniser, and the shape corpus gets its own denominator and
**never** enters the 522. The document's subject also moved — it was written for corpus fixtures, and
the complete spec makes it a batch run of a private document set *at* the site, exporting measurements
only. No document, value, filename or site identifier leaves.

No code written. The order of work is the directive's: scrubber and its tests, then the **ledger
schema PR for Chris to review first** (it is what leaves the site), then the CLI, truth mode,
scorecard, generator. Five generic questions go in that schema PR — the architect's four (date
formats, one row per part, the change-type vocabulary, the class map's buckets) plus whether the
tokeniser should be one-way everywhere and not only on export. Build next week.

## What I need

1. **Lane 01:** the `doors-export` passes drift — ours `identity.identity_from_doors_text` vs the
   overlay's `identity.document_identity`. One of the two declarations has to move; it is the only red
   in a default suite run and has been for several sessions.
2. **Architect:** whether the ADI PDF becomes corpus document eleven. It moves the denominator, so
   it is not mine to decide, and the salvage does not need it to land.
3. Nothing in this report has run against a live drop. If the dry run on Friday wants the ADI shape
   exercised for real, that is a fire request, not a code request.

## Commits on `7f/report-2026-10-19-required-gate-red-on-age`

- `9550736` — Salvage a plain-text parts list, and flag a parts pass that emitted nothing
- `241ebb9` — Record the four rulings on the site batch fixture, including the two that went against
  the design
