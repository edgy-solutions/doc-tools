# Contract: the batch column map — the one vocabulary a batch export profile is written in

**Status:** the **contract only**. There is no column map in code. `column_map`,
`column-map` and `columnMap` have zero occurrences in `doc_tools/`, `registry/`,
`docs/`, `charts/` and `scripts/`, on this lane and on `origin/main`. Two of the
four rulings this file encodes name fields the extractor **does not produce at
all** (§7, §9) — that is recorded here rather than worked around, because a
profile that names an unproducible column must fail at validation time, not
surprise someone at runtime.

**Order it answers** (architect, 2026-10-28), verbatim:

> *"the column-map vocabulary is yours, not Lane 1's: write it as one file in
> doc-tools (granularity, source selector for shared `extracted_value`, landing
> for unresolvable values, the ruled date/change_type/manufacturer rules); Lane 1
> reviews against the ledger route."*

This reversed an earlier ask of mine, in which I had asked Lane 1 to propose the
vocabulary on the reasoning that nothing of mine existed. The four things the
ruling names are exactly the four gaps a measured read of the tree had found, so
nothing was lost by the reversal.

It is the next link in the batch fixture chain that
[`scrub-ledger.md`](scrub-ledger.md) belongs to, and it is **reviewed** against
Lane 1's ledger route — reviewed, not owned there.

**contract_version: 1**

---

## 1. The one rule this vocabulary exists to enforce

**A profile names columns; the map resolves every column to a doc-tools field
before the export runs, or the profile is refused.** Nothing is resolved at
runtime, nothing is guessed, and no column silently emits a blank because its
source could not be found.

That rule is the whole reason the vocabulary is more than a `{output: source}`
dictionary. Three of the four sections below exist because a bare field name
cannot express what this data actually looks like on the wire.

## 2. `granularity`, on the profile header — and why it is not `scope`

    granularity: notice_part | notice      # required, closed

| value | one row per |
|---|---|
| `notice_part` | (notice, part) |
| `notice` | notice |

**The key is `granularity` and not `scope`, deliberately.** `scope` is already a
three-way collision across the repos, recorded at `severity: high` in
`registry/export_field_catalogue.json`:

| source | `scope` means | values |
|---|---|---|
| our field catalogue | which **field scope** a field is in | `notice`, `row`, `steward_edit`, `provenance` |
| cortex's listing route | the export's **row granularity** | `row`, `notice` |
| lane fin's CDRL header | a **program-level** profile | `program` |

The first two **collide on the literal tokens `row` and `notice` while meaning
different things**, so a profile carrying `scope: row` beside a column list whose
entries each carry a `scope` reads wrong and looks right. This file takes the
unambiguous name and leaves the catalogue key alone; renaming the catalogue
`scope` to `field_scope` is still available and is still Lane 1's to call, since
two other lanes are proposing headers against theirs.

## 3. The row rule, including the notice that has no parts

At `granularity: notice_part`:

- one row per (notice, part);
- a notice with **no parts** emits **one** row carrying `no_parts: true`.

**Not zero rows, and not a null part column.** Zero rows makes a notice that was
processed indistinguishable from a notice that was never ingested; a null part
column makes it indistinguishable from a part whose MPN was lost.

**One naming caution, measured.** `no_parts` as a row flag is a *new* token on
the export side, but `no_parts` already appears in this tree as a substring:
`grid_no_parts_col` (a per-page counter for a grid column that holds no parts)
and a `_no_parts_decline` test helper. **A table with no parts column is not a
notice with no parts** — nearly the same words, unrelated facts. Anyone grepping
for prior art will find the counter; it is not this.

## 4. The source selector — because three values share one property

**This is the section a bare field name cannot express.** Three different part
values — `affected_mpn`, `replacement_mpn` and `ltb_date` — arrive on the
extraction wire as the **same** property, `extracted_value`, distinguished only
by `row.field`. A mapping entry that names a source *field* and nothing else
cannot address two of the three.

So the source side of a column is an object, never a bare string:

    source:
      field: extracted_value       # required: the wire property
      row_field: replacement_mpn   # required WHEN `field` is shared; else omitted
      absent_row: empty_cell       # closed: empty_cell (default) | block

`row_field` is **required** whenever `field` names a shared property, and
**refused** when it does not — a selector that over-specifies is as wrong as one
that under-specifies, because it silently matches nothing.

**`absent_row` is load-bearing and is why this key exists at all.** The
`replacement_mpn` and `ltb_date` rows are emitted **only when the part has one**,
so a part with no replacement yields two rows, not three. The vocabulary must be
able to say that an **absent row means an empty cell**, not a null value:
otherwise every no-replacement part becomes either a KeyError or a blank that
reads downstream like a measured null. `empty_cell` is the default because it is
the common and correct case; `block` exists for a column where absence really is
a defect.

## 5. Landing for a value that cannot be resolved

Every column may declare where an unresolvable value goes:

    on_unresolvable: land | blank | block    # closed, required for date columns
    landing: date_ambiguous                  # required when on_unresolvable == land

| value | effect |
|---|---|
| `land` | the raw value is written to the `landing` column; the mapped column is left empty |
| `blank` | the mapped column is left empty and the value is dropped |
| `block` | the export fails, naming the notice, the part and the column |

**`blank` and `land` are not interchangeable.** `blank` discards evidence;
`land` keeps it where a human can see what could not be resolved. A column that
chooses `blank` is asserting that the unresolved value is not worth keeping, and
that assertion belongs in the profile where it can be reviewed.

A profile that declares `on_unresolvable: land` without a `landing` column, or a
`landing` that is not itself a declared column, is refused at validation.

## 6. Dates: ISO-8601, and an ambiguous date lands rather than being guessed

Ruled. A date column declares:

    format: iso8601                 # the only accepted value
    on_unresolvable: land
    landing: date_ambiguous

**A printed `05/12/2023` is 5 December or 12 May depending on the vendor
country**, and resolving it would trade a visible gap for a silent
off-by-seven-months error. So an ambiguous date is **not** normalised, **not**
guessed, and **not** dropped: it lands verbatim in `date_ambiguous`.

This is why a date column needs **two** things in the vocabulary and not one. A
profile that can only say `format: iso8601` has nowhere to put the ambiguous
case, and it will be silently guessed or silently dropped — the two outcomes the
ruling exists to prevent.

The extractor's own date handling is the same shape and is worth knowing while
reading a landed value: header dates are corroborated by *components* (year, day,
and month as a number or an English abbreviation), deliberately **not** parsed,
precisely so that `05/12` vs `12/05` is never decided by code.

## 7. `change_type`: a closed vocabulary, with free text alongside it

Ruled: a closed `change_type`, and any free text the document carries goes to
`change_type_note` — never into the closed column.

    change_type:       one of the closed set below
    change_type_note:  free text, verbatim, unnormalised

The closed set is the extractor's own `ChangeCategory`, which is already a closed
BAML enum and therefore not a new vocabulary to maintain in two places:

    Material | Process | Location | Discontinuation | Packaging | Testing

**STATUS: UNPRODUCIBLE TODAY, and a profile naming it must be refused.**
`change_type` and `effective_date` have **zero** occurrences in
`sustainment_merge.py` and `plugins/sustainment.py` — the extractor does not
produce either. `categories` (plural, a list) is what exists. So:

- a profile column over `change_type` fails validation with "declared, not
  produced", exactly as a column over a catalogue field with a null `served_by`
  does (§9);
- whoever builds it must decide how a **list** of categories becomes **one**
  `change_type`, and that decision is not made here. Picking the first element
  silently would be a guess of the kind §6 refuses.

## 8. Manufacturer class: buckets by name shape only

Ruled: manufacturer class buckets **by name shape only**.

"Name shape only" is the whole safety of the rule, and it is measured, not
stylistic. A gazetteer-backed or ownership-backed class would be wrong on this
corpus in both directions:

- the extractor's own `mfr` gazetteer arm **refused `Analog Devices` and
  `ON Semiconductor`** — two entirely real manufacturers;
- a parent or owning company is a **different claim** from the name printed on
  the page, and the one shape the refusal rules exist to stop is assembling a
  name out of a web address (a `ttelectronics.com` in a SEMELAB footer resolves
  character-for-character and is still not a company name).

So the class is read off the **printed string** and nothing else: no gazetteer,
no parent lookup, no network, no inference from the document domain.

**The bucket list is the one thing in this file I am proposing rather than
transcribing**, and it is the thing I most want reviewed:

| bucket | shape test |
|---|---|
| `suffixed_entity` | ends in a legal-form token (`Inc`, `Ltd`, `LLC`, `GmbH`, `Corp`, `KK`, `AB`, `SA`, `NV`, `Co`), punctuation at the edges stripped |
| `initialism` | all alphanumerics, 3 or fewer of them, no lowercase run |
| `multiword` | two or more whitespace-separated tokens, no legal-form suffix |
| `single_token` | one token, more than 3 alphanumerics |
| `unknown` | `mfr` is null — which is a **correct** answer here, not a failure |

`unknown` is in the list on purpose. A document that prints no manufacturer
anywhere has a null `mfr` by design, and a class vocabulary with no bucket for it
would force either a fabricated class or a dropped row.

## 9. The producibility gate: a profile is validated against the field catalogue

Every column `source.field` must name a field in
`registry/export_field_catalogue.json`, and:

- **a field whose `served_by` is null is a hard stop at profile-validation
  time.** 28 of the 57 catalogued fields are unserved. The catalogue is the
  superset of what doc-tools *produces*, not of what the extraction route can
  *serve*, and the difference must be caught when the profile is written, not
  when it runs.
- **the one that will hurt is `header.doc_level_ltb_date`**, unserved. It is the
  value every unsourced part-level LTB row *inherits*, so a per-part export that
  omits it loses the only source those dates have.
- **two catalogue mappings are marked `mapping_unverified`** —
  `Notice.mfr_source` and `Notice.notice_date`. A profile naming either is naming
  something whose derivation only the consumer knows.

## 10. A worked profile

    name: pcn-ltb-by-part
    granularity: notice_part
    columns:
      - output: "Notice"
        source: {field: doc_id}
      - output: "Affected MPN"
        source: {field: extracted_value, row_field: affected_mpn}
      - output: "Replacement MPN"
        source: {field: extracted_value, row_field: replacement_mpn,
                 absent_row: empty_cell}
      - output: "LTB Date"
        source: {field: extracted_value, row_field: ltb_date,
                 absent_row: empty_cell}
        format: iso8601
        on_unresolvable: land
        landing: date_ambiguous
      - output: "date_ambiguous"
      - output: "no_parts"

Read against §1: every column resolves to a catalogued field; the two shared
`extracted_value` columns are discriminated by `row_field`; the two optional rows
say that absence is an empty cell; the date column names where an ambiguous value
lands; and the landing column and the `no_parts` flag are declared columns rather
than implicit ones.

## 11. What is deliberately NOT decided here

1. **`change_type` from `categories`** (§7) — a list-to-one decision that must
   not be made silently.
2. **The manufacturer bucket list** (§8) — proposed, not ruled.
3. **Whether the catalogue `scope` is renamed to `field_scope`** (§2) — Lane 1
   call, not taken unilaterally.
4. **Header/footer rows and the `upper`/`trim`/`fixed` transforms.** Nothing in
   this tree does any of the three, so there is no prior art to encode and no
   measured shape to copy. The only header-rows-above-a-table convention in the
   tree is `doc_tools/parsers/doors_export.py`, which **reads** a `Key: Value`
   preamble above a header row written by somebody else's DXL script — offered as
   prior art only, and note it is an **inbound** parser despite the name.
5. **Where profiles are stored and how they are picked.** That is the ledger
   route, and this vocabulary is reviewed against it rather than specifying it.

## 12. External corroboration: LlamaIndex's Document Parsing Protocol

**Nothing in this contract binds to DPP.** This section cites an external draft
that independently reaches some of the same conclusions as the rulings above. It
adds no requirement, closes no vocabulary, and changes no validation. It is here so
that a reader asking "is this rule just our habit?" has an answer, and
`contract_version` is deliberately **not** bumped by its addition.

> *Document Parsing Protocol*, LlamaIndex — working draft 0.1, repo
> `run-llama/document_parsing_protocol` at commit `a9c49e2` (2026-10-27),
> <https://parseprotocol.com>. Licensed **CC BY 4.0**
> (<https://creativecommons.org/licenses/by/4.0/>). Rule text below is quoted
> verbatim and cited by the draft's own `rule_id`; the mapping to our sections, and
> the selection of which rules to quote, are our changes and our responsibility, not
> LlamaIndex's.
>
> DPP specifies a **document representation** (faithful Markdown/HTML per source
> document). This contract specifies a **field export**. The two overlap only on
> what a parsing stage must decide, which is why the citations below are partial by
> nature.

| this contract | DPP rule | what it corroborates |
|---|---|---|
| §1 (resolve or refuse), §9 (producibility gate) | `principles-never-drop-never-invent` | that an unresolvable column must be refused rather than filled. DPP's formulation: content is never invented to satisfy a shape. |
| §3 (a no-parts notice emits one flagged row, not zero rows) | `tables-header-only-tables` | that an absence must be *stated* rather than represented by nothing. DPP refuses an orphan header standing alone as a table for the same reason we refuse zero rows: nothing is indistinguishable from not-processed. |
| §4 (`absent_row: empty_cell`) | `tables-header-body-column-count-mismatch` — pad the short side with empty cells, and "MUST NOT be padded with a duplicated or invented value" | that the correct filler for a missing position is an **empty cell**, never a repeated neighbouring value. This is `absent_row: empty_cell` arrived at independently. |
| §5–§6 (an ambiguous date lands verbatim, is not guessed) | `principles-the-page-is-the-ground-truth` — text is transcribed verbatim, typos included; `forms-values-are-verbatim` | that the printed form is what survives. Our `landing` column is the place to put it; DPP has no landing concept, having no export, but its verbatim rule is the same commitment. |
| §6 (`format: iso8601` with a landing escape, never a normalised twin) | `tables-accounting-number-formats` — "The output MUST NOT carry a normalised twin of the value beside it, and MUST NOT replace the printed form with a normalised one." | that normalising in place is the error. Note we apply this to the *landed* value, while the mapped column is by design normalised — our two-column shape is the reconciliation, not an exception. |
| §7 (`change_type` closed, free text to `change_type_note`) | `tables-cell-text-fidelity` | that unparseable text keeps a home of its own rather than being forced into a closed vocabulary. |
| §8 (manufacturer class buckets by printed name shape only — no gazetteer, no parent lookup, no network) | `principles-the-page-is-the-ground-truth` | that the page, not an external register, is the authority on what the document says. |

**One divergence, recorded rather than reconciled.** `strip_enclosing_quotes`
removes a balanced enclosing quote pair from an MPN before it becomes a join key.
Under `tables-accounting-number-formats` that is non-conforming. We keep it: our MPN
is a key, not a transcription, and the un-stripped form (`"090-44310-31"`, quotes
included) matches nothing downstream. The full rule-by-rule comparison, including
the four misses found by running DPP's two example PDFs through our tier-1
extractor, is in
[`sessions/2026-10-29-report-7f-the-document-parsing-protocol-tabled-against-the-ten.md`](../../sessions/2026-10-29-report-7f-the-document-parsing-protocol-tabled-against-the-ten.md).
