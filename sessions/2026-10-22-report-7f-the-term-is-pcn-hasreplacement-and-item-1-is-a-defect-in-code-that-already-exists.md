# The term is `pcn:hasReplacement`, and item 1 is a defect in machinery that already exists

to: invincible-agent/seat/architect (cc invincible-agent/lane/01, cortex-ui/master)
from: doc-tools/lane/7f, via Chris
date: 2026-10-22

## 1. The vocabulary question, answered: no ruling needed

**`pcn:hasReplacement` exists.** It is emitted today at
`doc_tools/plugins/sustainment.py:2149` and asserted by
`tests/test_plugin_graph_queries.py:210`:

```
<http://internal/components/{affected}> pcn:hasReplacement <http://internal/components/{replacement}> .
```

So use that term. **One caveat to price in before item 2 promotes it:** the
triple is written on a **shared component IRI** and carries **no reference to
the asserting notice** — unlike `pcn:subjectToNotice`, which does. Writes are
additive with no DELETE. So a replacement relation asserted by HEMCG2-2683 is
indistinguishable from one asserted by any other notice, and **a wrong one
cannot be withdrawn by re-ingesting.** That is a known shape here, not a new
one, but item 2 is what will start writing these at volume.

## 2. Item 1 is already built. What you found is a defect in it, not a gap

Worth knowing before Lane 1 and cortex scope items 2 and 3, because it changes
how much is left to do:

| the piece | where it already is |
| --- | --- |
| `replacement_mpn` on the row | `PartImpact` and `PartRow` in `baml_src/sustainment.baml` |
| the paired-column rule | `table_text_layer.pair_columns` — and it handles N pairs per row, not just one |
| a replacement column in the vision arm | `GridColumnRoles.replacement_col` |
| `replacement_mpn` on the review route | `sustainment_merge.py:383-397`, with its own provenance |
| the graph relation | `sustainment.py:2149` |

"Emit ONE row per pair, affected left, replacement right, same row" is the
behaviour `pair_columns` was written for. HEMCG2-2683 did not miss a feature; it
**defeated** one.

## 3. Root cause, reproduced on the real header

`AFFECTED_HEADERS` and `REPLACEMENT_HEADERS` are substring vocabularies, and
**the replacement wording contains the affected wording.** Murata's header is
`Part Number | Alternative Part Number`, and "alternative part number" matches
"alternative" *and* "part number". Run against the real function:

```
'Part Number'              affected=True  replacement=False
'Alternative Part Number'  affected=True  replacement=True
pair_columns -> [(0, None), (1, None)]      <- TWO AFFECTED COLUMNS, no pair
printed part rows: 22   emitted rows: 44   with a replacement: 0
```

44 is 22 x 2, and **not one of them carries a replacement** — the emitter loops
`for a_col, r_col in pairs`, so a second unpaired affected column emits that
whole column again as discontinued parts.

**This is not a Murata quirk.** Every term in `REPLACEMENT_HEADERS` spelled the
ordinary way a notice spells a column — `<term> Part Number`, `<term> Part No`,
`<term> Device` — matched both vocabularies. That is **24 header spellings**,
each one an instance of this defect waiting for a document to print it.
HEMCG2-2683 is the first one measured, not the only one there is.

The module had already met this exact problem one level down and fixed it there:
`ALIAS_HEADERS` vetoes **both** vocabularies and is tested first, with the
comment *"the alias wording CONTAINS them"*. The same precedence was never
established between replacement and affected.

## 4. Why "replacements never inherit `ltb_date`" is a live defect, not a precaution

Your rule reads like a guardrail. It is a description of what is happening now.
Each of those 22 replacement MPNs is an `affected_mpn` today, so it goes through:

- `reconcile_ltb` (`sustainment_merge.py:135`) — a part with no per-row date
  **inherits the document-level LTB date**, flagged `ltb_date_inherited`;
- then `sustainment.py:2144` — `pcn:hasLastTimeBuyDate` on its component IRI,
  plus `pcn:subjectToNotice` pointing at HEMCG2-2683.

So the notice's last-time-buy date is asserted on 22 parts Murata is **offering
as replacements**, and per §1 the date triple names no notice, so **if this
notice was promoted, that cannot be withdrawn by re-ingesting it.** Worth
checking whether HEMCG2-2683 reached the graph before the fix rolls — a Lane 1
read, not mine.

## 5. Fixed, and the scoping is the interesting part

`pair_columns` now gives **replacement precedence** over affected for a column
that matches both. Murata becomes `[(0, 1)]` — 22 rows, 22 replacements, with
the affected cell keeping the row/col provenance.

**The veto is scoped to `pair_columns` and deliberately NOT put in
`_is_affected`,** which is where it looks like it belongs. `find_title_row` also
calls `_is_affected`, on *captions*, and Diodes PCN 2683 pages 4 and 5 are
captioned *"...and No Replacement Parts"*. Measured:

```
'Table 4 - EOL Devices and No Replacement Parts'  affected=True  replacement=True
   -> a global veto makes find_title_row return None: the table DECLINES
```

A global veto would have fixed 22 parts and lost **144 genuine EOL devices**.
The suite's own `_CAPTION` constant contains "Replacement Parts" too. A header
cell and a caption read the same words to opposite ends, so the fix has to know
which one it is looking at. There is a test pinning this, named as the scoping
guard, so the tempting simplification fails loudly rather than quietly.

**8 suites, 212 tests, green.** 6 new tests, including the 24-spelling
generalisation and the caption guard.

One thing I recorded rather than changed: with a customer column between them
(`Part Number | CUSTOMER PART NUMBER | Alternative Part Number`) the replacement
pairs with the **customer** part number, because the pre-existing rule gives a
replacement to the nearest affected column on its **left**. It reproduces with a
plain `Replacement` header, so the precedence did not introduce it. That is the
deferred Customer-Part-Number question in its live form, and I have not closed
it by side effect — it needs your ruling on whether a customer column is an
affected column at all.

## 6. The fixture: blocked on the document, and it moves the gate

Two things stand between me and "HEMCG2-2683 as a corpus fixture with the 22
pairs":

**(a) I do not have the document, and ground truth forbids inventing it.** A
notice entry is `{count, mpns, malformed, source, manifest}`, and the file's own
construction rule is *"an MPN enters ground truth only if it is VERBATIM PRESENT
in the source PDF's text layer."* I will not write 22 MPNs I have not confirmed
against the bytes. **Please point me at HEMCG2-2683 — the MinIO manifest path or
the PDF** — and the fixture is quick.

**(b) It is a gate-affecting change.** HEMCG2-2683 is not one of the 10 scored
notices, so it adds an 11th and moves the parts denominator off 522, which is
currently met exactly. That belongs with the corpus measurement, after the dry
run, not ahead of it.

**And one limit worth knowing before you count on the fixture:** `pcn_score.py`
scores **affected-MPN identity only** — there is no replacement arm in the
scorer or in the ground-truth schema. The fixture therefore *does* catch this
defect, because the 22 replacements score as **spurious** pre-fix and the gate
reds. But a run that paired nothing and simply dropped all 22 replacements would
score **identically green**. If you want the pairing itself measured rather than
just the doubling, ground truth needs a `pairs` field and the scorer a
replacement arm — a scorer change, which I would rather do as its own piece than
smuggle into a fixture.

## 6b. The other arm has the same defect by omission, and I have not measured it

Column roles are decided by **two arms**, and only one of them is the substring
vocabulary above. The grid-forwarding arm asks the vision model, and its prompt
(`prompts/sustainment_grid_columns_instructions.md`) defined `replacement_col`
as *"a recommended replacement / substitute part number"* — it **never named
alternative, alternate or successor**, the three wordings your ruling lists. So
on Murata's header that arm was being asked about a vocabulary that does not
include the word actually printed on the page.

I have added those wordings, plus an explicit statement that an "Alternative
Part Number" column is a replacement column and never a second affected one.

**Flagging this as unmeasured, deliberately.** A prompt change here cannot be
verified without a real vision fire, which the freeze holds until after the dry
run — and a green test suite says nothing about prompt text in this repo. Treat
it as the two arms made to agree on paper, with the measurement owed. Which arm
actually produced HEMCG2-2683's 44 rows I cannot tell from here; the text-layer
arm's defect is proven by construction, and this one is a gap I can see but have
not shown firing.

## 7. Status

The extraction fix is **committed on my branch and not rolled**, per *"after the
dry run"*. It has not been measured against the corpus: that needs a fire, which
the freeze holds until after the dry run. Nothing here touches 204.

— doc-tools/lane/7f
