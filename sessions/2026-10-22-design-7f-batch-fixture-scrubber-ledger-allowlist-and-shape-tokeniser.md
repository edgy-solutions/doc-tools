# Batch-fixture scrubber: the ledger schema, the allowlist, and the shape tokeniser

to: Chris (schema review first), cc invincible-agent/seat/architect
from: doc-tools/lane/7f
date: 2026-10-22
status: **RULED 2026-10-23. All four rulings answered — see §5. No code written yet;
the hold is lifted and the order of work is the directive's (§5.6).**

> ### RULED, 2026-10-23 — the architect's complete site-batch-fixture spec
>
> A complete spec arrived on 2026-10-23 ("THE SITE BATCH FIXTURE — complete spec,
> supersedes anything partial") and it answers all four rulings §5 was holding code
> on. **§5 below is rewritten as the rulings as made, not as questions.** Three
> things in this document change substantively, and they are flagged where they
> occur:
>
> 1. **The manufacturer is NOT allowlisted.** §5.1 recommended allowlisting it; the
>    ruling is a **class plus an agreement result**, never the name. My objection
>    (that scrubbing `mfr` makes the mfr arm of the score measure the scrubber) does
>    not bite, and §5.1 now says why: the agreement is computed **at the site, before
>    the scrubber runs**, so what leaves is a verdict and not a value to re-score.
> 2. **The scrub is one-way outside the site.** §4.2's uncommitted mapping cannot
>    live in sandbox MinIO — a re-identification key in sandbox is a value leaving
>    the site, which the spec's first constraint forbids outright. §4.3's equivalence
>    seal moves from "audit the real fixture later" to "a round-trip test on
>    synthetic inputs, in the repo, run every time", which is strictly better: it is
>    repeatable by anyone with no access to anything.
> 3. **This fixture's subject changed.** The original scope was *corpus* fixtures
>    derived from the ten MinIO notices. The spec's subject is a **site batch run**:
>    a large private document set run through the live pipeline at the site, of which
>    only measurements leave. The shape fixture becomes a downstream artifact
>    (§5.5) rather than the point. The tokeniser (§2) and the allowlist (§3) are
>    unchanged and are still the load-bearing parts.

## 0. Why this exists, in one paragraph

A corpus fixture has to be a real document. Ground truth's own construction rule
is *"an MPN enters ground truth only if it is VERBATIM PRESENT in the source
PDF's text layer"*, so a fixture cannot be typed — it has to be derived from
bytes. But the corpus PDFs live in MinIO and not in git, which is why
HEMCG2-2683 is blocked on *"I do not have the document"* rather than on any
code. The scrubber's job is to turn a real notice into a **committable** one
without turning it into a different test.

## 1. The one hard constraint everything else follows from

**Extraction reads shapes, not meanings.** The header vocabularies are substring
matches; `_has_part_shaped_text` is a shape test; the grid pairing is positional;
the vision arm is shown an image of the same table. So:

- change a string's **shape** and the fixture stops testing the extractor and
  starts testing the scrubber;
- leave the string **as it is** and nothing was scrubbed.

Everything below is the consequence of needing both halves at once. The design
therefore has exactly three moving parts: a **tokeniser** that substitutes
shape-for-shape, an **allowlist** of what must never be substituted, and a
**ledger** that makes the result auditable and reproducible.

## 2. The shape tokeniser

### 2.1 The shape alphabet

A string is reduced to a shape by class, with punctuation and case kept literal:

| class | symbol |
| --- | --- |
| uppercase letter | `A` |
| lowercase letter | `a` |
| digit | `9` |
| anything else (`-`, `/`, `.`, space) | **itself** |

Examples:

```
GRM033R60J104KE19D   ->  AAA999A99A999AA99A
PCN24-029            ->  AAA99-999
HEMCG2-2683          ->  AAAAA9-9999
MAX4372HEUK+T        ->  AAA9999AAAA+A
```

### 2.2 Substitution

A replacement is any string with **the identical shape**, drawn per character
class. Two properties matter more than the alphabet:

**(a) Deterministic and injective within a batch.** The same original must map
to the same replacement everywhere it appears — the parts table, the body
paragraph, the revision history, the figure caption. A notice that says "GRM033…
is replaced by GRM155…" in prose and again in a table is the case that breaks a
naive per-occurrence scrub, and it is also exactly the case the replacement-pair
work is about. Proposal: `HMAC(batch_salt, original)` seeded into a per-class
character draw, so the mapping is stable without being reversible from the
fixture.

**(b) Shape-equal, not merely length-equal.**

```
GRM033R60J104KE19D   ->  XQB712T40M558BF23C   OK   same shape
GRM033R60J104KE19D   ->  XQB712T40M558BF23      NO  one char short
GRM033R60J104KE19D   ->  XQB7A2T40M558BF23C     NO  digit became a letter
```

### 2.3 What the tokeniser must deliberately NOT preserve

Character-level repeats and internal structure leak the original. `AA1111AA`
with "both letter pairs identical and the digits ascending" narrows a vendor
catalogue to a handful of parts. The draw is per position and independent; the
only invariant carried across is the shape.

### 2.4 The collision rule, which is a real risk and not a formality

A shape-preserving replacement **can land on a real part number belonging to
someone else**. A fixture that ships a stranger's live MPN as synthetic data is
worse than the original problem. Two options, and I want the ruling rather than
the choice:

- **(i)** draw from a reserved space (e.g. a leading letter triple that no
  vendor in the corpus uses), and record the reservation in the ledger; or
- **(ii)** check each replacement against the full corpus MPN set plus ground
  truth and redraw on a hit, recording the check and the number of redraws.

(i) is cheap and auditable; (ii) is stronger but only as strong as the corpus
it checks against. **My recommendation is (i) with (ii) as an assertion on top.**

## 3. The allowlist

The allowlist is **what must survive verbatim**, because the extractor's
correctness is defined against it. If any of these is substituted, the fixture
tests nothing.

### 3.1 Allowlisted — survives verbatim

| category | examples | why |
| --- | --- | --- |
| **column headers** | `Part Number`, `Alternative Part Number`, `Affected Part`, `Replacement`, `Customer Part Number`, `Last Time Buy` | this IS the vocabulary under test; the HEMCG2-2683 defect was a header-matching defect |
| **captions and table titles** | `Table 4 - EOL Devices and No Replacement Parts` | `find_title_row` reads these, and this exact wording is a known scoping trap |
| **dates, every printed spelling** | `2024-06-06`, `06-Jun-2024`, `June 6, 2024` | LTB and pub-date extraction is date-semantic; a shape-substituted date is not a date |
| **notice-type and status words** | `PCN`, `EOL`, `Last Time Buy`, `obsolete`, `not recommended for new designs` | routing and the status field read them |
| **units, packages, standards** | `0402`, `SOT-23`, `X7R`, `RoHS`, `AEC-Q200` | package/size strings are shape-identical to part fragments and must not be drawn into the substitution |
| **the manufacturer name** | `Murata`, `Diodes Incorporated`, `Texas Instruments` | **see §5, ruling 1 — this is the one I will not decide alone** |

### 3.2 Scrubbed — the sensitive set

| category | examples |
| --- | --- |
| manufacturer part numbers | affected, replacement, alias, every column |
| **customer** names and customer part numbers | the deferred Customer-Part-Number column is literally a column of someone else's internal identifiers |
| contact names, emails, phone numbers | including the footer block |
| addresses and site names | including fab and plant names where they identify a customer |
| internal order, quote, case and RMA numbers | |
| anything in a "distributed to" or "attention" block | |

### 3.3 The rule the allowlist needs to be written as

**Allowlist by VOCABULARY, scrub by SHAPE, and let the allowlist win.** A header
cell and a part number can be the same shape; a caption can contain the words a
header contains. So matching order is: allowlist first, substitution only on
what survives it. This is the same precedence problem as replacement-vs-affected
in `pair_columns`, and the same answer: **establish the precedence explicitly,
and pin it with a test named as the guard**, because the tempting simplification
(scrub everything part-shaped) silently destroys the headers.

## 4. The ledger — the part to review first

One ledger per fixture, committed beside it. Two artifacts, not one, and the
split is the point.

### 4.1 The committed ledger (redacted)

```json
{
  "ledger_version": 1,
  "fixture_id": "hemcg2-2683",
  "source": {
    "bucket": "<corpus bucket>",
    "key": "<prefix>/HEMCG2-2683.pdf",
    "sha256": "len=2184731 sha256:9f2c41ab",
    "pages": 3,
    "tables": 1
  },
  "scrub": {
    "tool_version": "scrubber-0.1.0",
    "run_at": "2026-10-24T13:02:11Z",
    "salt_ref": "<secret-manager key name, NOT the salt>",
    "allowlist_ref": "registry/scrub_allowlist.yaml@<sha>",
    "mapping_ref": "<bucket>/scrub-mappings/hemcg2-2683.json"
  },
  "substitutions": [
    {
      "class": "mpn_affected",
      "shape": "AAA999A99A999AA99A",
      "original": "len=18 sha256:3d81c7f0",
      "replacement": "XQB712T40M558BF23C",
      "occurrences": 2,
      "sites": [
        {"page": 2, "kind": "table_cell", "row": 4, "col": 0},
        {"page": 1, "kind": "body_text"}
      ]
    }
  ],
  "allowlisted": [
    {"text": "Alternative Part Number", "rule": "header_vocabulary", "count": 1},
    {"text": "2024-06-06", "rule": "date", "count": 3}
  ],
  "verification": { "...": "see 4.3" }
}
```

**The committed ledger carries NO original value.** Each original appears as
`len=N sha256:XXXXXXXX` — this repo's standing convention, and the reason for it
applies exactly: a ledger that lists the originals re-identifies the document it
exists to make committable, and a transcript is not editable. The `replacement`
is in the clear, because it is already in the fixture.

### 4.2 The uncommitted mapping

The full `original -> replacement` mapping lives in MinIO beside the source,
named by `mapping_ref`. It is what makes a re-scrub reproducible and what lets a
reviewer with MinIO access check the scrub was faithful. **It never enters git.**
Whether it may be kept at all is ruling 3.

### 4.3 The verification block, which must be measured and not asserted

A scrub that is merely *performed* is a claim. Proposed checks, each written
into the ledger with its result:

| check | what it catches |
| --- | --- |
| **leak test**: every substituted original is ABSENT from the scrubbed PDF's own text layer | the real failure — a value missed in a footer, a figure label, XMP metadata, an embedded attachment |
| **shape equality** per substitution | a replacement that changed the shape |
| **allowlist integrity**: count of each allowlisted string unchanged | the headers or dates got scrubbed |
| **structure invariance**: page count, table count, per-table row/col counts unchanged | the scrub moved the geometry the extractor reads |
| **equivalence seal**: run the extractor on the source and on the fixture; the outputs must be equal **after applying the mapping** | the only check that proves the fixture tests the same thing as the document |
| **collision check** per §2.4 | a replacement that is somebody's real part |

The leak test must run on the **rendered output's text layer**, not on the input
strings. A PDF carries text in places a string replacement does not reach:
annotations, XMP metadata, embedded attachments (MAR053's parts are in an
attached spreadsheet, per Lane 1's packet today), and the glyphs inside an
embedded image. **Image-borne text is the known hole** — a scrubber cannot see
it, and `ADI_PCN_24_0003`'s parts list may be exactly that case. Proposal: the
leak test fails CLOSED on any page whose text-layer retention is below a
threshold, i.e. the scrubber refuses a document it cannot read rather than
shipping one it did not scrub.

## 5. The four rulings, as made — 2026-10-23

The hold is lifted. Each ruling is recorded with what it changes here, because two
of the four went against this document.

### 5.1 The manufacturer — RULED AGAINST THIS DESIGN, and the ruling is better

**Not allowlisted.** It leaves as a **class** — `semiconductor-major` /
`connector` / `passive` / `other` — plus its **agreement result**, and never as a
name. The class map itself is private and stays at the site.

§5's original objection was that scrubbing `mfr` makes the mfr arm of the score
measure the scrubber rather than the extractor. **That objection does not apply to
this design**, and the reason is the whole trick: the comparison happens **at the
site, inside the CLI, before the scrubber runs**. What leaves is
`match | mismatch | missed | extra` — a verdict computed against the real value, by
the pipeline, on the real document. The scrubber never sits between the extractor
and the thing it is scored against. It sits between the *verdict* and the *export*,
where it has nothing left to distort.

What it costs: a mismatch can no longer be *diagnosed* off the export alone. We
learn that the mfr arm disagreed on N documents of class `connector`, not which
string it produced. The shape-tokenised mismatched pair (spec §C) is the mitigation
and it is enough to tell a misformat from a wrong vendor — which is exactly the
distinction the live `ti-mfr-misformats-5-of-6` finding turns on.

### 5.2 Dates — RULED AS DESIGNED

**Allowlisted, and compared as dates, not as strings.** A date keeps being a date
through the tokeniser (spec §D). LTB scoring therefore survives the scrub intact,
which is what §3.1 needed: `tyc-ltb` and the contested 2024-06-06/07 boundary stay
answerable from a scrubbed export.

### 5.3 The mapping — ONE-WAY OUTSIDE THE SITE

The spec's first constraint is absolute: *"No document, value, filename or site
identifier ever leaves."* A re-identification key in sandbox MinIO would be a value
leaving the site, so **§4.2's uncommitted mapping cannot live in sandbox.** Any
mapping exists only at the site, under the site's control, or not at all.

This is a real loss and it lands on §4.3: the equivalence seal cannot be re-run
later against the real bytes by anyone off-site. In exchange it becomes something
better — the spec requires *"a test [that proves] no raw value survives a round
trip"*, which runs in CI on **synthetic** inputs, every time, for everyone. A seal
that only one machine can verify once is weaker than a test anybody can run always.

**One generic question for the schema PR** (§5.7): does the site want a mapping
retained at the site at all, or should the tokeniser be one-way everywhere including
there? One-way everywhere is simpler and I would default to it.

### 5.4 The scored corpus — RULED AS DESIGNED

**A shape fixture never enters the 522.** Spec §F: the generated fixtures go in a
**separate shape corpus with its own denominator**. The parts denominator stays 522
over ten documents, which is what `scripts/pcn_ground_truth.json` asserts at
startup and what the gate reads.

### 5.5 What the complete spec adds beyond this document

Recorded here so the schema PR has one source. The spec is the authority; this is
the delta against the design above.

- **The CLI** is `scripts/pcn_batch.py --dir --truth --map --out`, dropping every
  PDF through the door as the `svc:batch` persona (Lane 1 provides it), waiting for
  each row to reach a terminal stage (`review` / `awaiting_kind` / `failed` /
  `promoted`) with a timeout, collecting the entry, and **running the scrubber
  last**. Re-runnable: already-ledgered documents are skipped unless `--rerun`.
- **The column map is config and is NOT committed.** The repo ships an example map
  with generic keys only (`part_number`, `manufacturer`, `notice_id`,
  `notice_date`, `effective_date`, `change_type`, `replacement`, `ltb_date`,
  `ignore: []`); the site's real map is a private overlay per ADR-0042 §C3/C4.
  **The scrubber refuses every field not on the allowlist, including everything on
  the `ignore:` list** — so a site-internal workflow column cannot leave even by
  being named in config.
- **The ledger entry** is one per document, keyed on the **sha256 of the bytes**
  (which reveals nothing), carrying: `file` (page count, bytes, text layer y/n,
  filename **shape** only), `kind` (declared / title / not_identified, with title
  candidates as shapes), `trail` (every stage with timestamp, attempts, final
  stage, `reason_code`, Dagster run status, traceback text), `review`
  (`needs_review`, `review_reasons`, flagged count, every `crops_*` rate, part
  count, bbox quality counts, `obtained_via` counts), `tables` (count; per table
  the column **header text**, row count, and whether parts came from
  table / text / image), `log` (the `[Sustainment]` lines, values shape-tokenised),
  `edits` (steward corrections as counts by op and field), and `truth`.
- **Truth mode** joins on `notice_id`, then part number within a notice, with a
  fallback join on the **PDF hash**. Compared: `mpn` (normalised the way instance
  resolution normalises), `mfr`, `notice_id`, `notice_date`, `ltb_date`,
  `replacement_mpn`. Outcome per field: match / mismatch / missed / extra.
  Mismatched pairs export as shapes.
- **Two roadmap gaps, recorded and not compared:** `effective_date` and
  `change_type` as a category. I owe a report on what the header pass would need to
  extract each — neither is in `ExtractHeader`'s output today, so both are a
  prompt-and-schema change, not a scoring change.
- **The site's own part identifier is ignored**, and noted as the future source of
  `customer_part_map`. Not compared, not exported.
- **The scorecard** (`scorecard.md`) reports counts by terminal stage and reason;
  precision and recall **per compared field, per manufacturer class, and per layout
  class** (ruled table / text columns / image table / attachment); the top ten
  failure reasons; and the roadmap gaps with counts.
- **The shape-fixture generator** is the LAST item, not the first: it takes a
  ledger entry and emits a synthetic PDF with the same layout — headings, table
  columns, token shapes, page structure — and fake values.

### 5.6 Order of work, as directed

1. **the scrubber and its tests** (including the round-trip proof of §5.3);
2. **the ledger schema — a PR Chris reviews first**, since it is what leaves the
   site;
3. the CLI; 4. truth mode; 5. the scorecard; 6. the generator.

Lane 1 in parallel: `GET /ingest/{id}/ledger` (trail + review fields + run status +
edits for one ingest, gated like `/extraction`) and the `svc:batch` drop persona.
**Build next week; Chris runs it at the site once the schema PR is merged.** The
ADI_PCN_24_0003 fixes are Monday's roll and come first.

### 5.7 Questions for Chris, in the schema PR, generic wording only

As directed, plus one of mine from §5.3:

1. **Date formats** in the record — what does the sheet actually print, and is it
   consistent across columns?
2. **One row per affected part, confirmed?** The join in §5.5 assumes it.
3. **The change-type vocabulary** — the closed set of values the column takes.
4. **The manufacturer class map's buckets** — are
   `semiconductor-major` / `connector` / `passive` / `other` the right four?
5. **Mine:** should the tokeniser be one-way **everywhere**, including at the site,
   or does the site retain a mapping locally? (§5.3)

## 6. Worked examples

### 6.1 The HEMCG2-2683 pair table (the case that started this)

Source:

```
Part Number          | Alternative Part Number
GRM033R60J104KE19D   | GRM155R60J104KE19D
GRM033R61A105KE15D   | GRM155R61A105KE15D
```

Scrubbed:

```
Part Number          | Alternative Part Number     <- allowlisted, verbatim
XQB712T40M558BF23C   | XQB884T40M558BF23C
XQB712T61A550BF24C   | XQB884T61A550BF24C
```

Both headers survive, so the replacement-precedence defect still reproduces on
the fixture. Both columns are shape-identical, so the pairing still pairs. The
two rows that share a prefix in the source share one in the fixture only as an
artifact of the independent draw — and per §2.3 that is not preserved
deliberately, which is a thing to notice: **a fixture testing "the two columns
differ by one family digit" would lose that property.** If any extractor rule
depends on affected/replacement *similarity*, it has to be named now, because
this design does not carry it.

### 6.2 A Diodes caption

```
Table 4 - EOL Devices and No Replacement Parts
```

Untouched. Allowlisted as a caption, and it is the exact string that proves a
global affected-veto would decline 144 genuine EOL devices.

### 6.3 A customer column

```
Part Number  | CUSTOMER PART NUMBER | Last Time Buy
PDC1234-A    | ACME-77-X             | 2024-06-06
```

```
Part Number  | CUSTOMER PART NUMBER | Last Time Buy   <- all three allowlisted
QFJ8392-K    | KZQR-14-B             | 2024-06-06      <- date verbatim
```

The customer part number is substituted *and so is its prefix* — `ACME` is the
customer's name inside a part number, which is the common real case and the
reason customer columns are in the scrub set rather than the allowlist.

## 7. What I am NOT proposing

- No scrubbing of images. The scrubber **refuses** a document whose parts table
  is image-borne rather than shipping it half-scrubbed (§4.3).
- No automatic ground-truth generation. Ground truth for a scrubbed fixture is
  the real ground truth **with the mapping applied**, never retyped, and the
  verbatim-presence rule is then re-checked against the scrubbed text layer.
- No scrubber in the ingest path. This is an offline tool that produces
  committed artifacts; nothing in `doc_tools/` imports it.

— doc-tools/lane/7f
