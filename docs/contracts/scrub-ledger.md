# Contract: the scrub ledger — what a scrubbed fixture must declare about itself

**Status:** the **contract only**. There is no scrubber. `doc_tools/scrub/`
contains the ledger model and nothing else; the tokeniser and the allowlist are
the next links and are blocked on four rulings (§7). The ledger is not blocked,
because it *records* which answer a scrub ran under instead of choosing one.

**Order it answers** (architect, 2026-10-25, overnight item 4), verbatim:

> *4. Batch fixture: scrubber → schema PR, continue the chain.*

The design this implements is
`invincible-agent/sessions/2026-10-22-design-from-7f-batch-fixture-scrubber-for-chris-review.md`,
placed for Chris's review on 2026-10-22. Section numbers below in the form
*design §N* refer to it.

**The problem the whole chain exists for:** the corpus fixtures that measure the
extractor are customer documents. They cannot be committed, so the tests that
matter most run against documents nobody can check into git — and a fixture that
cannot be committed is a fixture that silently stops being run. A *scrubbed*
fixture can be committed, but only if two things are both true: it still tests
the extractor rather than the scrubber, and the scrub is auditable. The ledger is
the second half.

---

## 1. The one rule the module exists to enforce

**A committed ledger carries no original value.** Every original appears as
`len=N sha256:XXXXXXXX` — the repo-wide convention, which is in
[`CLAUDE.md`](../../CLAUDE.md) because a drift script in this repo once printed
three live credentials into a transcript, and **a transcript is not editable**.

A ledger that lists its originals re-identifies the document it exists to make
committable. The `replacement`, by contrast, is in the clear: it is already in
the fixture PDF, in print.

The rule is a type, not a comment:

```python
REDACTION_RE = re.compile(r"^len=(0|[1-9][0-9]*) sha256:[0-9a-f]{8}$")
Redacted = Annotated[str, StringConstraints(pattern=REDACTION_RE.pattern)]
```

so `Substitution.original` and `SourceRef.sha256` **cannot** hold a value.
`tests/test_scrub_ledger.py` rejects the plausible hand-edits as well as the
obvious one: a full 64-hex digest, a bare `len=18`, upper-case hex, nine hex
digits, a leading-zero length.

### 1.1 The limitation of a truncated digest, stated rather than glossed

`sha256:XXXXXXXX` is **32 bits over a known catalogue**. A reader who already
holds a list of candidate part numbers can hash the list and match. The
redaction stops a reader with no candidates; it does not stop one with the
catalogue.

That is accepted — the convention is repo policy, and a longer digest only raises
the cost of the same attack — but it has two consequences worth acting on:

* `len=N` is in **bytes**, which narrows the search space further. Also accepted:
  without it, a ledger entry for a multi-byte original is quietly shorter than
  the original.
* **The example fixture uses synthetic originals** (`SYN…`, `ACME-77-X`,
  `Northwind Components`), so no digest of a real catalogue part is committed
  into a file whose only job is to show the shape. `make_ledger_example.py` says
  so in its own docstring.

A ledger for a real fixture does commit such digests. That is the point of the
convention, and a reason a one-way scrub (§7 ruling 3) is the safer answer.

---

## 2. Two artifacts, and the split is the point

| | where | contains | enters git |
| --- | --- | --- | --- |
| the **ledger** | beside the fixture | digests, shapes, replacements, sites, counts, checks, policy | **yes** |
| the **mapping** | MinIO, named by `scrub.mapping_ref` | `original → replacement` in the clear | **never** |

A reviewer with MinIO access can check the scrub was faithful. A reviewer
without it can still check everything in §4 — shape equality, counts, allowlist
integrity, the verification block — because none of it needs the values.

`Substitution.covers(candidate)` and `ScrubLedger.substitution_for(original)`
are how a reviewer **holding** the mapping queries the ledger: they compare
`redact(candidate)` to the stored digest, so the value never enters the ledger
or its index.

---

## 3. The shape alphabet (design §2.1–2.3)

`shape_of()` reduces uppercase to `A`, lowercase to `a`, digits to `9`, and
**keeps everything else literally**. The literal punctuation is deliberate:
`SOT-23` and `PCN24-029` are told apart by where the hyphen sits, and the
extractor's own shape tests read exactly that.

| original | shape |
| --- | --- |
| `SOT-23` | `AAA-99` |
| `PCN24-029` | `AAA99-999` |
| `ACME-77-X` | `AAAA-99-A` |
| `Northwind Components` | `Aaaaaaaaa Aaaaaaaaaa` |

`shapes_equal(shape, replacement)` is **shape** equality, not length equality
(design §2.2b): a replacement of the right length and the wrong shape is read by
the extractor as a different kind of part number, and the fixture would then
measure the scrubber. `Substitution` rejects it at construction.

Character-level **repeats are deliberately not preserved** (design §2.3):
`AA00AA → XQ71BF` is acceptable. Preserving the repeat would leak structure of
the original. This is recorded as a test so a later "improvement" has to argue
with it.

---

## 4. What a ledger must declare, and what each entry is for

### 4.1 `substitutions`

```json
{
  "class": "mpn_affected",
  "shape": "AAA999A99A999AA99A",
  "original": "len=18 sha256:9d3ea4ef",
  "replacement": "XQB712T40M558BF23C",
  "occurrences": 2,
  "sites": [
    {"page": 2, "kind": "table_cell", "row": 4, "col": 0},
    {"page": 1, "kind": "body_text"}
  ],
  "reserved_space": "XQB",
  "redraws": 0
}
```

* **`occurrences` must equal `len(sites)`.** An occurrence not listed is one
  nobody checked was scrubbed.
* **A `table_cell` site carries `row` and `col`.** An unaddressed cell cannot be
  re-checked against the source table.
* **The two-site case above is the point of the example.** The same original in
  a cell *and* in a body paragraph is design §6.1 — the case a naive
  per-occurrence scrub gets wrong, and the replacement-pair case the fixture
  exists to test.
* **`reserved_space` and `redraws` are measurements.** `0` redraws is a
  measurement; the field being absent is not. The reserved draw space is design
  §2.4(i): replacements come from a space no vendor uses, and the corpus-MPN
  check sits on top as an assertion.
* **The mapping is injective in both directions.** Two substitutions with the
  same original must be merged into one with two sites; two originals sharing a
  replacement would conflate two parts into one. Both are rejected.

`SubstitutionClass` has twelve members, covering what a PCN carries beyond part
numbers: contact name, email and phone, address, site name, internal reference,
distribution block.

### 4.2 `allowlisted`

A string that survived verbatim, **with the count that proves it**. The count is
the whole entry: `Alternative Part Number` present but appearing twice where the
source had it three times means a header was scrubbed — and a fixture whose
headers have been scrubbed tests nothing, because the defect that started this
chain was a header-matching defect.

Design §3.3, which the model enforces: **"Allowlist by VOCABULARY, scrub by
SHAPE, and let the allowlist win."** A replacement that lands *on* an
allowlisted string inverts that precedence, so `ScrubLedger` rejects it.

### 4.3 `verification` — measured, not asserted

All six checks of design §4.3, each with a result and its measurements:

| check | what it catches |
| --- | --- |
| `leak_test` | the real failure — an original missed in a footer, a figure label, XMP metadata, an embedded attachment |
| `shape_equality` | a replacement that changed the shape |
| `allowlist_integrity` | the headers or the dates got scrubbed |
| `structure_invariance` | the scrub moved the geometry the extractor reads |
| `equivalence_seal` | the only check that proves the fixture tests the same thing as the document |
| `collision_check` | a replacement that is somebody's real part |

Three rules make the block non-decorative:

1. **Every check must be present.** `Verification` rejects a partial block with
   *"A missing check is not a default pass — record it as not_run with a
   reason."* This repo has been bitten by the opposite reading more than once.
2. **A `not_run` check must say why.** Recording a check as not-run is the
   honest option; recording it as not-run with no reason records nothing.
3. **`detail` cannot be empty on any result.** A PASS with nothing measured is
   an assertion wearing a measurement's clothes.

`ScrubLedger.committable` is `True` only when **every** check PASSED.
`refused` — the leak test's fail-closed case — is not a pass:

> The leak test must run on the **rendered output's text layer**, not on the
> input strings, and it **fails closed** on any page whose text-layer retention
> is below a threshold. The scrubber refuses a document it cannot read rather
> than shipping one it did not scrub.

**Image-borne text is the known hole.** A scrubber cannot see glyphs inside an
image, and a PDF whose parts list is an image is exactly the document
`committable` must say no to.

### 4.4 `scrub.salt_ref` is a NAME

The field that would hold a live secret if it were misused. `ScrubRun` rejects a
redaction pasted there (*"salt_ref is a secret NAME, not a value — even
redacted"*) and anything that looks like raw entropy (16+ hex characters, or a
base64-shaped blob). `run_at` must be a UTC instant.

---

## 5. Pydantic is the authority; the JSON Schema is its projection

`registry/scrub_ledger.schema.json` is **generated** by
`scripts/generate_scrub_ledger_schema.py` and pinned by a `--check` test, the
same idiom as `registry/content_kinds/` and `generate_kind_registrations.py`:
the table is the authority, the files are its projection, drift is pinned by a
test. No `jsonschema` dependency was added; `pydantic` was already here.

**What the projection cannot carry**, stated in the generated file's own
`$comment`: shape equality, `occurrences == len(sites)`, the mapping policy
agreeing with `mapping_ref`, injectivity, and the allowlist collision rule are
all cross-field invariants that live only in the model validators.

> *Validating against this file alone checks a ledger's shape, not its truth.*

A drifted projection is the quiet failure: a reviewer or a non-Python consumer
validating against permissions the loader refuses — or, in the worst case,
permitting an original in the clear.

---

## 6. Offline by construction

Design §7: *"No scrubber in the ingest path. This is an offline tool that
produces committed artifacts; nothing in `doc_tools/` imports it."*

A comment cannot enforce that, so
`test_nothing_in_the_ingest_path_imports_the_scrubber` walks every `.py` under
`doc_tools/` outside `doc_tools/scrub/` and fails on any import line mentioning
`scrub`. One import edge from an asset or a pass would put a tool whose whole job
is to touch original values into the pipeline that runs against live documents.

The module lives **inside** `doc_tools/` anyway, rather than in a top-level
package, for one reason: `include = ["doc_tools*"]` in `pyproject.toml` is what
CI installs, and a top-level `scrub/` would be importable in this tree and absent
from the wheel — a drift between what the suite seals and what ships, which is a
worse failure than the import cost. The §7 guarantee is enforced by the guard,
not by the directory.

---

## 7. The four rulings, and why they do not block this

Design §5 asks four questions that are **unanswered as of 2026-10-25**. Every
ledger records which answer its scrub ran under, in `policy`:

| field | ruling | recommendation placed for review |
| --- | --- | --- |
| `manufacturer_name` | 1. allowlisted or scrubbed? | **allowlisted** — the sensitive party in a *published* PCN is the recipient, not the issuer. Scrub it and the `mfr` arm of the score measures the scrubber. |
| `dates` | 2. allowlisted? | **allowlisted** — LTB extraction is date-semantic, and a shape-substituted date is not a date. Scrubbed means LTB scoring comes off scrubbed fixtures entirely. |
| `mapping` | 3. may the mapping be kept in MinIO? | **one_way** is safer; it makes the equivalence seal unrepeatable after the fact, which is the cost. |
| `enters_scored_corpus` | 4. does a scrubbed fixture enter the SCORED corpus? | **false** — `true` moves the parts denominator, which is currently met exactly at `ac853308`. |

`policy.authority` is a required free-text field, and the example's says
`RECOMMENDATION ONLY`. Every `policy` field is **required**, so a fixture states
its assumptions instead of inheriting them.

**This is the whole reason the schema could land first.** A ruling that lands
later invalidates exactly the fixtures whose `policy` disagrees with it — which
is a query, not an audit.

---

## 8. Files

| file | what it is |
| --- | --- |
| `doc_tools/scrub/ledger.py` | the models — the authority |
| `scripts/generate_scrub_ledger_schema.py` | the projection generator, with `--check` |
| `registry/scrub_ledger.schema.json` | generated; do not edit |
| `tests/fixtures/scrub/make_ledger_example.py` | builds the example **through the model**, with `--check` |
| `tests/fixtures/scrub/ledger_example.json` | a valid ledger, synthetic throughout |
| `tests/test_scrub_ledger.py` | 28 tests: the rejections, the helpers, the projection, the §7 guard |

The example is **built, not hand-written**, for a reason that showed up
immediately: a hand-written example carries invented digests, so `covers()`
fails for every candidate and the file teaches a shape that does not round-trip.
It also caught its author — the first hand-written customer-name replacement was
eight letters against the original's nine, and the shape-equality validator
refused to build the file.

---

## 9. What is NOT here

* **No scrubber.** No tokeniser, no allowlist file, no PDF rewriting. This PR is
  the contract the next one has to satisfy.
* **No `jsonschema` runtime validation.** Nothing loads the generated schema;
  it exists for reviewers and non-Python consumers.
* **No real fixture.** `ledger_example.json` is synthetic and describes a
  document that does not exist. The first real ledger needs rulings 1–4.
* **No image scrubbing, ever** (design §7): the scrubber refuses a document
  whose text it cannot read. See §4.3.

---

## 10. Changing this contract

Bump `LEDGER_VERSION` and say why in this file. A reader that guesses at an
unknown version is how a schema change becomes a silent misread, so
`ScrubLedger` rejects any version but the current one. Then regenerate both
projections and run the suite:

```powershell
& .\.venv\Scripts\python.exe scripts\generate_scrub_ledger_schema.py
& .\.venv\Scripts\python.exe tests\fixtures\scrub\make_ledger_example.py
& .\.venv\Scripts\python.exe -m pytest tests/test_scrub_ledger.py -q
```
