# Report — 7f: the batch-fixture scrubber runs, and refuses to call its own output committable

**Date:** 2026-10-30
**Lane:** 7f (`doc-tools`)
**Order:** architect, 2026-10-30 — *"the batch chain continues (scrubber ->
schema -> CLI against the column-map contract), and `branch`/`refresh` on
ContentKindEntry so ADR-0063 event kinds can register."*

This is link 1, the scrubber. The merged ledger contract
(`docs/contracts/scrub-ledger.md` section 9) stated exactly what was missing:
*"**No scrubber.** No tokeniser, no allowlist file, no PDF rewriting. This PR is
the contract the next one has to satisfy."* Two of those three now exist.

---

## 1. What this is, measured on a real notice

Run over the committed element-text of **PCN-2683**
(`tests/fixtures/sustainment/diodes_rev1_eol_text.txt`), not a synthetic input:

| | |
|---|---|
| blocks | 69 |
| distinct originals substituted | **491**, in 505 occurrences across pages 3-5 |
| leak test | **0** of the 491 originals present in the scrubbed text |
| allowlisted spans kept verbatim | caption 6, date 10, header vocabulary 9, manufacturer 22, notice type/status 21 — source and output counts equal, **0 lost** |
| unclassified part-shaped tokens | **9** |
| shape equality / structure invariance / collision check | pass |
| equivalence seal | **NOT_RUN** |

Four suites, **83 passed** from PowerShell (`test_scrub_ledger` plus the three
new ones).

## 2. The headline: the run is NOT committable, by design and by default

The script exits **1** on this input with
`NOT COMMITTABLE: verification not passed: equivalence_seal, leak_test`. Both
refusals are the contract working, not a shortfall:

* **`equivalence_seal` is `NOT_RUN`** because this link scrubs a **text layer**
  and produces no PDF. The seal has nothing to compare, and the contract makes a
  `NOT_RUN` check non-committable. PDF rewriting plus the seal is the next link.
* **`leak_test` is `REFUSED`** — the strict default — because 9 part-shaped
  tokens sit in blocks that declare no class. **An unclassified part-shaped
  token cannot be promised scrubbed, so the run fails closed rather than
  passing a weaker test.** Measured, not argued: `DIC-034 R5` is still in the
  output text. The 9 are `DIC-034` plus 8 real MPNs the extractor emitted as
  `[UncategorizedText]` on page 5, where the region map reads no table.

So the engine runs end to end and then declines to bless its own output. That is
the direction this repo wants a seal to fail in.

## 3. The judgment calls the written design left open

* **A `SubstitutionClass` cannot be guessed.** The input is text **plus a region
  map**; a part-shaped token with no class is **reported**, never substituted,
  unless it equals an original classified elsewhere. Without this the scrubber
  rewrites `DIC-034 R5` and `Page 2 of 6`, both part-shaped by `looks_like_mpn`
  — and this repo has already written page furniture into a scored field.
* **Reserved space, in an implementable form.** Design section 2.4 example
  (`XQB...`) implies a leading-triple reservation that does not generalise
  across MPN shapes. Reserved here: the **first uppercase run**, drawn from
  `{Q,X,Z}`. An original starting with a digit records
  *"none: no leading uppercase run; collision_check carries this one alone"*.
* **The allowlist is DERIVED, not retyped.** A seal test asserts it covers
  `AFFECTED_HEADERS`, `REPLACEMENT_HEADERS`, `ALIAS_HEADERS`,
  `CUSTOMER_HEADERS`, `_CUSTOMER_PART_CUES` and `_GAZETTEER_NAMES`, so the
  vocabulary under test and the allowlist cannot drift apart.
  `registry/scrub_allowlist.yaml` names every case and `allowlist.py` carries no
  literal vocabulary — the standing rule, config names the case.
* **A policy is HONOURED, not merely recorded.** `policy.manufacturer_name` or
  `policy.dates` set to SCRUBBED **drops that rule** from the matcher at run
  time.

## 4. What the precedence guard can and cannot say

Design 3.3 — *allowlist by vocabulary, scrub by shape, and let the allowlist
win* — is pinned by a test named as the guard. One honest limit, found while
building and now stated in two places:

**The inverted run drops two things at once**, because *scrub everything
identifier-shaped* is one decision, not two: it bypasses the allowlist AND drops
the candidate floor to shape-only. Against the **production** floor (letter AND
digit, length >= 4) a bare header word or a date is not a candidate anyway, so
the allowlist is load-bearing for a narrower, sharper set. Added as its own
test: **`SOT-23`, `AEC-Q200` and `PCN-2683` each pass the production floor** —
shape alone would substitute all three — **and each survives verbatim.** A
package code, a qualification standard, and the notice number that is also the
corpus `doc_id`.

## 5. A fifth open question, beyond the design four rulings

The **notice number** (`PCN-2683`, `PCN #: 2683`) is in neither the allowlist
nor the scrub set in the design. Allowlisted here by ruling 1 reasoning — the
sensitive party in a published notice is the recipient, not the issuer, and the
notice number is also the corpus `doc_id` — and **flagged in the YAML as a
recommendation, not a ruling**. It wants an answer with the other four.

## 6. What is NOT covered, and is written into the ledger

The leak-test detail carries its own scope: *the text layer produced by this
scrub only. Annotations, XMP metadata, embedded attachments and glyphs inside an
image are invisible to a text-layer scrub and are NOT covered.* Design 7 stands:
no image scrubbing (the scrubber **refuses**), no automatic ground truth, and
**nothing under `doc_tools/` imports this package** — it is not in the ingest
path.

## 7. Two corrections made during review

1. `scripts/scrub_document.py` loaded its element-text reader **out of
   `tests/`** by file path. A production script depending on the test tree is a
   defect whatever it measures: the reader is now
   `doc_tools/scrub/element_text.py` and both call sites import it plainly.
2. `doc_tools/scrub/__init__.py` still said *"Only the ledger contract lives
   here so far. The tokeniser and the allowlist are the next links."* That had
   just become false. Rewritten to name the four modules and, in the same
   breath, what is still missing. A docstring claiming an absence that the code
   has since filled is how this repo got two merged PRs claiming Helm was absent
   from CI.

## 8. Next

Link 2 is the **schema**, then link 3 the **CLI**, both against
`docs/contracts/batch-column-map.md`. `branch`/`refresh` on `ContentKindEntry`
is measured and ready to write on its own branch: the generator emits only
fields the projection fills, so projecting `branch` **only when it is not
`document`** leaves all thirteen `registry/content_kinds/*.yaml` byte-identical,
and `registry_fingerprint()` hashes `(kind, passes)` only, so it cannot move.
The per-branch required/forbidden rule stays the SDK validator alone, with a
test pinning that backstop rather than a second copy of the rule here.

No secret appears in this report. The scrub salt is read from a named
environment variable and recorded as `len=N sha256:XXXXXXXX`.
