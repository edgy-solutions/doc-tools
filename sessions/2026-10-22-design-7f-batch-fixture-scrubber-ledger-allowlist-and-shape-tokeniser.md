# Batch-fixture scrubber: the ledger schema, the allowlist, and the shape tokeniser

to: Chris (schema review first), cc invincible-agent/seat/architect
from: doc-tools/lane/7f
date: 2026-10-22
status: **DESIGN FOR REVIEW. No code written. Four rulings needed before any is.**

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

## 5. Four rulings I need before writing code

1. **Is the manufacturer name allowlisted or scrubbed?** `mfr` is one of the
   three scored header fields. Scrub it and the mfr arm of the score measures
   the scrubber. Keep it and the fixture names the vendor — which for a
   *published* PCN is arguably not sensitive at all, since the vendor published
   it. **My recommendation: allowlist the manufacturer, scrub the customer.**
   The sensitive party in a PCN is the recipient, not the issuer.
2. **Are dates allowlisted?** I have them allowlisted above because LTB
   extraction is date-semantic, and because `tyc-ltb` and the 2024-06-06/07
   contested boundary are live corpus questions. If a date is considered
   identifying, LTB scoring has to come off scrubbed fixtures entirely — say so
   and I will design for that instead.
3. **May the unredacted mapping be kept in MinIO, or is a scrub one-way?** A
   one-way scrub is safer and makes the equivalence seal (§4.3) unrepeatable
   after the fact. Keeping it makes the fixture auditable forever and puts a
   re-identification key next to the source.
4. **Does a scrubbed fixture enter the SCORED corpus?** It moves the parts
   denominator off 522, which is currently met exactly at `ac853308`. If the
   answer is yes, these land with the corpus measurement after the dry run, not
   before.

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
