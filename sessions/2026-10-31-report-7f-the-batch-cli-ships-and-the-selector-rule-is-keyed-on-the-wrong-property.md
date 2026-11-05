# report — 7f — the batch CLI ships, and §4's selector rule is keyed on the wrong property

Lane: `doc-tools/lane/7f`. Date: 2026-10-31. PR: **#200** (`7f/batch-export-cli` → `main`).
Order: *"the batch chain continues (scrubber → schema → CLI against the column-map contract)."*
This is **link 3**, the last of the chain. Link 1 was #196, link 2 was #198.
Built off `main`, not stacked: a stacked PR runs no CI gate in this repo.

## What shipped

| Path | What it is |
| --- | --- |
| `doc_tools/batch/cli.py` | `python -m doc_tools.batch.cli`: a validated profile plus saved extraction responses in, CSV rows out. Reads files only — no network, no credentials, no fetch mode. |
| `tests/test_batch_cli.py` | 14 arms: one per contract rule, one per decision below, and a parametrised date table. Synthetic extractions only. |

Exit codes, because a wrapper will read them: **0** rows written; **1** a block,
`row_ambiguous`, a corrections refusal, a catalogue resolution error or an
unreadable input; **2** the profile was refused at validation. On any exit but 0
**no file exists at `--out`** — the write goes to a temporary path and is renamed
only after the last row. The test asserts the path's absence, not merely the code.

## The thing that did not need asking: the wire shape was already in the tree

A catalogue entry carries `wire: {container, name}`, which names a container and
not a path, and **the nesting of those containers is not in the catalogue.** The
obvious move was a packet to lane 01 and a wait.

It was unnecessary. `tests/fixtures/cortex_bff_extraction_pin.json` is the pinned
extract of invincible-agent's `docs/api/cortex-bff.openapi.json` at `5522d8d2`
that the catalogue's own `seal.contract_leg` already asserts against. It gives
the whole shape: `Extraction` at top level, `Notice` at `doc["notice"]`,
`ExtractionRow` in `doc["rows"]`, `EvidenceRef` at `row["evidence_ref"]`, with
all thirteen `Extraction` keys and all eleven `ExtractionRow` keys required.

**The seal that proves the catalogue honest is also the document that makes it
usable**, and it was committed here on 2026-10-28. One read saved a round trip.

## The finding: §4 requires a selector on the wrong condition

§4 requires `row_field` when a field's **wire name is shared**, and refuses it
when it is not. That rule exists because five fields share `extracted_value`.

Building the row extractor shows the condition is the wrong one. What decides
whether a column needs a selector is not whether the wire name is shared — it is
whether **the value varies from row to row within one part**. Those are different
sets, and measured from the catalogue:

- **18** served row-scope fields;
- **11** of them cannot carry a `row_field` at all, because their wire name is
  unshared and §4 *refuses* a selector there;
- **9** of those 11 vary per row: `row.source_snippet`, `row.needs_review`,
  `row.match_confidence`, `row.obtained_via`, `row.review_reason`,
  `row.row_index`, and all three of `row.evidence_ref.{page,bbox,note}`.

So a profile may name `row.source_snippet` — the validator accepts it, the field
is served — and **there is no way for it to say which row's snippet it means.**
Only `row.mpn` and `row.part_index` are safe, being the part identity repeated on
every row.

**What the CLI does about it, and what it refuses to do.** It takes the first row,
because there is nothing else to take, and it **reports a disagreement on stderr**
naming the column, the part and how many distinct values the part's rows carried.
It does not pick quietly. A positional pick that nobody sees is exactly the class
of defect this lane keeps finding: a wrong value that looks like a measured one.

The fix belongs in the contract, not here — §4's condition should be derived from
whether a field is row-varying, which the catalogue does not currently record.
That moves `contract_version` to 3, so it is **named and not filed today.**

## A second gap, lane 01's, also not filed

Their 10-28 packet: *"`on_unresolvable` is refused on a column without `format`.
No non-date column can be unresolvable, and a key that can never fire is a guard
that cannot fire."* §5 says **every** column may declare it, the schema permits
it, and the validator does not check it. Also version 3 work.

## Two rules of lane 01's single export that bind a batch of the same data

Both are implemented, and neither was in the contract:

- **two rows of one part with the same `row_field` → `row_ambiguous`, and the
  export never picks one.** Same data, same answer.
- **`corrected_by` non-null → `export_corrections_not_applied`, nothing written.**
  The route serves review.json's values, so a corrected promotion would export
  the **uncorrected** ones. A batch of those is worse than one, not better.

## Dates: the rule as first specified would have landed an unambiguous date

`format: iso8601` normalises only what the input **forces**: ISO `YYYY-MM-DD`
(a time suffix truncated); a named or 3-letter English month; and `N/N/YYYY`
only where the day/month roles are forced. Everything else lands **byte for
byte** in the landing column. No dateutil, no pandas: a parser that succeeds on
an ambiguous date is the defect §6 exists to prevent.

The rule as first written said "only when exactly one component is > 12", which
lands `05/05/2023` — and that date is **not** ambiguous: 5 May under either
reading. Equal components choose nothing, so they normalise. One arm of the date
table is that case.

Also measured and reported, not hidden: a selected row with
`obtained_via: "inherited_doc_level"` is a **doc-level** LTB date repeated onto a
part row. The value is emitted — a profile can name `row.obtained_via` for
itself — and the run prints a count per column, so a column of part LTB dates
cannot quietly read as all-row-level.

## Measured

- `40 passed in 6.79s` — `tests/test_batch_cli.py` (14 functions, 25 cases: the
  date table is parametrised over 12) + `tests/test_batch_profile.py` (15).
- **Whole suite: `2452 passed, 13 skipped, 16 deselected, 1 xfailed` in 110.55s**, from PowerShell against `.venv/Scripts/python.exe`.
- **No new dependency.** `csv`, `json`, `argparse`, `datetime`, `re` from the standard library; `yaml` and `jsonschema` arrive through `doc_tools.batch.profile`, declared in #198.

## Not done, and named

- The two `contract_version: 3` items above: §4's selector condition, and
  `on_unresolvable` without `format`.
- Lane 01's catalogue answers 1–3, still held: answer 1 (`header.pub_date` served
  as `notice_date`) contradicts the catalogue, and the 10-31 packet disputes it.
  They move the 33/25 counts, so they will be **re-measured**, never hand-edited.
- Nothing imports `doc_tools.batch` from the pipeline. There is still no
  scheduled or triggered export; this is a tool a human runs.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
