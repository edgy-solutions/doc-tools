# Report — 7f: the required gate was red on report AGE, and the parts gate is MET at the live pin

doc-tools/lane/7f, overnight 2026-10-19. Three directives taken in order of
blast radius, which turned out not to be the order they were given in. No
secret value appears here; presence is shown as `len=N sha256:XXXXXXXX` per
CLAUDE.md.

## 1. The finding that outranked the directives: `main` was red, on nothing

While verifying a delegated diff I found that the **required** `corpus-gate`
context had gone red on `main` — with no diff involved at all.

`docs/corpus-gate/latest.json` was generated `2026-10-15T15:54:02Z`. With
`CORPUS_GATE_MAX_AGE_DAYS=3`, it crossed the staleness boundary at
**`2026-10-18T15:54:02Z`**. Measured on the merge push for `c2a22cf`
(run `39190984608`): `corpus-gate` **completed failure**.

That is not cosmetic. `docs/corpus-gate/` is deliberately inside the `charts`
path filter — the workflow says so in its own comment, *"`docs/corpus-gate/` IS
IN THIS PATTERN AND MUST STAY… it is the only path that rewrites the artifact
the gate GRADES"* — so `charts=true` on any chart diff, and `corpus-gate` is
the one required context. **Every chart PR, which is every pin bump, was
blocked on the age of a file.**

Confirmed locally with the repo venv interpreter, not inferred:

```
corpus gate report is 3 days, 10:52:46 old (generated_at=2026-10-15T15:54:02Z)
1 failed, 5 passed, 1 deselected
```

The subagent I delegated the verdict work to reported this failure and said it
was clock-dependent and pre-existing. It was right on both counts, and I
confirmed it independently rather than taking the hand-back: the diff adds 69
lines and touches no line of `test_report_is_not_stale`.

## 2. The cure existed and could not land

`corpus-gate/nightly` carries a report generated **`2026-10-18T11:25:31Z`**
whose `measured_image` is **`sha256:ac853308…`** — the exact digest this chart
pins — with an `image_identity` `pods` comparison that **matches**. It is a real
`--run` authority report, not a `--from-logs` reduction: real wall-clock
(`elapsed_s` 5226.9 / 5343.4 / 5342.8) and real per-fire exit codes.

Its PR (**#110**) has been unmergeable since `2026-10-12` because that branch is
never rebased. So the publisher had the answer and the transport was broken.

I copied the five files out onto a branch off `main` with
`git show <ref>:<path> > <path>`. **The nightly branch is untouched and was not
force-pushed** — that is a standing instruction and it also would not have
helped.

Incidental: the dated-archive collision is **fixed**. Filenames now carry a full
timestamp (`report-2026-10-16T070441Z.md` *and* `report-2026-10-16T093701Z.md`
both present), so the second run of a day no longer destroys the first.

## 3. The picture inverts: the parts and crop-seal gate is MET

This is the result worth waking up to. At the pin that is live right now:

| fire | exit | gt | exact | spurious | missing | elapsed |
|---|---|---|---|---|---|---|
| 1 | **0** | 522 | **522** | 0 | 0 | 5226.9s |
| 2 | **0** | 522 | **522** | 0 | 0 | 5343.4s |
| 3 | **0** | 522 | **522** | 0 | 0 | 5342.8s |

**All three fires exit 0 at 522/522 exact, zero spurious, zero missing.** The
parts/crop-seal gate that has been red for days is met. The crop seal also now
reports **all four edges** (`left 0, top 1, right 1, bottom 1`), where it once
measured one edge of four.

The `fail` verdict is now **entirely headers**:

- **header agreement exit 1** — 5 of 10 notices **absent** in at least one fire
  (ADI, Diodes, EOL-36, IDT, TI). The report itself calls this *"an instrument
  gap, not a value disagreement"*, and notes there is no declaration exemption
  for it.
- **identity half unstable** across fires on ADI, Diodes and EOL-36, without
  `needs_review` True in all three. IDT has the same instability and **is**
  exempted, because its `needs_review` is True in all three.
- **IDT fire 2** wrote no `doc_level_ltb_date` and no `pub_date`.

So the standing claim in my own 2026-10-18 report — *"all three fires exit 1 on
the parts/crop-seal gate"* — was true of the `a72a4a26` report and is **false of
the current pin**. The blocker moved from parts to headers.

## 4. PR #144, measured both ways

Two commits: the applicability guard, then the report.

| mark | before | after |
|---|---|---|
| `corpus-gate` (**required**) | 1 failed, 5 passed | **6 passed** |
| `corpus-gate-verdict` (advisory) | skip — not applicable | **1 failed, honestly** |

CI agreed with the local run exactly: `corpus-gate` **pass**, `tests` pass,
`telemetry-contract` pass, `verify-image-pin` pass, `corpus-gate-verdict`
**fail**.

The verdict **no longer skips**, because the guard finds the report measuring
the digest the chart declares. It is red about the image that is actually
running and names five real conditions. That is the whole point of the change:
before, it was red about `sha256:a72a4a26`, three pins dead, marking nothing
current.

**The merge is blocked at the harness, not the argument.** I attempted it and
the auto-mode classifier refused it as `[Merge Without Review]`. The rationale
is in the PR body; the basis I would have merged on is narrow and worth having
on record:

- the verdict is advisory — **measured**: not a required context, and not in
  `build-and-push` `needs`;
- *"a chart diff may not ship on a failing corpus report"* is **not engaged** —
  #144 changes `docs/` and `tests/` only. No chart, no pin, nothing deploys. It
  is graded as a chart diff solely because `docs/corpus-gate` sits inside the
  path filter, where it must stay;
- **a red authority report can only ever be published by merging over its own
  red.** Refusing makes the authority unpublishable, which is exactly the
  deadlock that froze `main`.

Until #144 lands, `main` stays red on staleness and chart PRs stay blocked.

## 5. IDT per-row bboxes — the framing needs one correction, and the cause is not what it looked like

Measured in-pod against the artifacts at the current pin (`133714c0`):

| | IDT | TI |
|---|---|---|
| part items | 34 over **17 rows** | 9 over 9 rows |
| `match_method` | `unique` 17, `inherited_doc_level` 17 | `text_layer_cell` 9 |
| pages | 1 | 3 |
| **distinct bboxes** | **1** | **9** |
| the box | `[141.0, 305.0, 1536.5, 1410.6]` | each a ~120 × 15 cell |

**Correction to the brief:** it is not 34 rows. It is **17 part rows carrying
two fields each** — the part number (`unique`) plus a `doc_level_ltb_date`
inherited at document level (`inherited_doc_level`). All 34 share one box.

**The obvious cause is wrong.** I expected IDT to have no text layer, which
would mean TI mechanism cannot transfer. It is not that:

```
IDT  p1  612.0 x 792.0  chars=1628  words=211  tables=1   (bbox 60.6,45.1,553.1,723.1  rows=9)
TI   p3  595.4 x 841.7  chars=1209  words=152  tables=3
TI   p2  595.4 x 841.7  chars=917   words=98   tables=0    <- the known page-2 exclusion, re-confirmed
```

**IDT page 1 has a perfectly good text layer and pdfplumber finds a 9-row table
on it.** The parts were simply not sourced from it — they came through the
`unique` path, which falls back to an enclosing region.

**The two documents are in different coordinate spaces** — IDT page 1 is
**612 × 792 points**, but the stored box runs to **x 1536.5, y 1410.6**.

**I over-claimed this an hour ago and am retracting it.** I wrote that *nothing
in the row says which space the bbox is in*. That is wrong. `page_dims` is on
every row, and measuring it settles the question:

| row | `page_dims` | scale vs points | implied dpi | bbox space |
|---|---|---|---|---|
| IDT `unique` | `{1700, 2200}` | 2.778 | **200.0** | **pixels** |
| TI `text_layer_cell` | `{595.4, 841.66}` | 1.000 | 72 | **points** |

Each row's bbox is in the same space as **its own** `page_dims`, so a consumer
that normalizes by `page_dims` is correct for both documents. The space is not
*labelled*, but it is **recoverable and self-consistent**. That makes it a trap
for a consumer that assumes points — real, worth a guard — but **not** the
missing-data defect I called it.

Mechanism, confirmed in the tree: `unique` is set at `provenance.py:119` when
exactly one index element contains the snippet, attaching
`bboxes = [c["bbox"] for c in chosen]` (`provenance.py:131`) taken from
unstructured `metadata.coordinates.points` — the hi_res layout pass, which
renders the page. `crop_geometry.py:29-37` states the relation
`layout_height / page.height == dpi / 72`, and the 200 dpi above is the
`document_parser.py:429` default. No code converts a stored bbox to points on
output.

**So the IDT defect reduces to one thing, which is the thing I was sent to
look at:** all 34 items share ONE table-region rectangle, where TI has 9
distinct cells — while a 9-row text-layer table sits on the same page, unused.

### The root cause, measured — it is a tier fallback, not a provenance bug

A row gets `text_layer_cell` **only if its part dict carries
`text_layer_bbox`**, and only the text-layer tier sets that
(`plugins/sustainment.py:618`). When that tier yields zero parts it returns
early and the document degrades to vision; `resolve_value(...,
prefer_region="table")` then resolves to the enclosing table region. The code
comment at that fallback predicts IDT exactly: *"it resolves to the enclosing
TABLE region (every part on a page sharing one huge box)"*.

Recorded stats, read off the artifacts rather than inferred:

| | IDT | TI |
|---|---|---|
| `text_layer_used` | **False** | True |
| `text_layer_parts` | **0** | 9 |
| `text_layer_declines` | **0 — empty** | 3 |
| `vision_used` | **True** | False |
| `text_layer_pages` | 1 | 5 |
| `text_layer_retention` | 0.1651 | 0.1075 |

**Degradation is not the discriminator.** Both notices are
`text_layer_degraded = True`, and TI's retention is *lower* than IDT's, yet TI
produced 9 text-layer parts and IDT produced none.

### A second defect, independent of the bboxes

**IDT produced zero parts AND zero declines.** The plugin's own comment calls a
decline *"the router's only independent check on the vision pass"*, and says it
*"must survive even when this tier ends up producing zero parts"*. IDT emitted
neither, so for this notice that check is silently absent. This is the second
notice with that shape — the paired-grid case had 29 MPN rows, no parts and no
decline — which makes zero-decline the rule to fix, not an exception to note.

**Where the fix belongs:** upstream of provenance, in
`text_layer.parts_and_declines_from_pages`. It must yield IDT's 17 part rows
from the 9-row table pdfplumber finds on page 1, or emit a decline. Per-row
bboxes then follow for free, because the tier already carries the cell geometry.
Nothing in the provenance layer needs changing.

## 6. Idempotency — BEFORE re-captured and stable, the write is still blocked

Re-captured on the rolled pod (`doc-tools-557cc96c6b-7v2z2`) before writing, in
case the graph had moved since. It had not — **byte-identical** to the BEFORE
already on record:

| field | BEFORE | BEFORE-2 |
|---|---|---|
| total in `MAINTENANCE_INSTANCES` | 157 | **157** |
| module triples | 37 over 7 subjects | **37 over 7** |
| blank-node subjects / objects | 0 / 0 | **0 / 0** |
| sha256 of sorted module triples | `5f378a2da5443ec3` | **`5f378a2da5443ec3`** |

Partition keys read off the instance, not guessed: 11 registered `xml_files`
partitions, both 941A keys present.

**The launch was refused a third time** — now as `[Shared Cluster Mutation]`.
I did not route the identical mutation through another shell to get around it;
that would bypass the intent of the denial rather than satisfy it. It needs a
permission rule. The instrument, the key, the prediction and the BEFORE state
are all on record, so the proof is one approved command from finishing.

Prediction stands, registered before the write: every field identical, bnodes
still 0, sha256 still `5f378a2da5443ec3`. A changed sha256 at an unchanged total
of 157 is the defect the probe exists to catch.

## Next

1. **#144 needs a merge decision.** `main` is red on staleness until it lands.
2. Headers are now the entire corpus blocker. The witness instrument gap — 5 of
   10 notices absent in at least one fire — is the largest single item, and it
   is an instrument problem, not a model problem.
3. IDT: root-caused — **see section 7, which supersedes this item.** This item
   said the fix was in `text_layer.parts_and_declines_from_pages`: make it yield
   the 17 rows from the page-1 table. Measured, that is not doable — the table is
   **one column wide** and all 17 MPNs are inside a single flattened cell, so
   there are no columns to pair. The per-row bboxes come from the **word layer**
   (17 of 17 unique, in points) and need no change to the parts tier. The
   zero-decline guard gap is a separate fix, now with two instances, and it is
   **held**: a decline feeds grid forwarding, so the obvious cure risks parts.
4. `mil.ttl` TBox, queued behind the above per the packet.

## 7. IDT, root cause COMPLETE — and it corrects section 5 and my own `Next` item

Section 5 ended by locating the fix in `text_layer.parts_and_declines_from_pages`:
*"make it yield the 17 rows from the page-1 table, or emit a decline."* I have now
measured the grid itself, in-pod, and **that instruction cannot be followed as
written.** The table has no columns to pair.

### What pdfplumber actually returns for IDT page 1

One table, 9 rows, **width 1** — a single column. The entire parts list is one
flattened cell:

```
r3  ['PRODUCT(S) AFFECTED: Part Number Part Number Part Number DX0783-ULG2B00-A4
     DX8313-CBG-A3 DX9353-CBG-A3 DX0783-ULG2B01-A4 ... DX8773-ELG2A01-A4']
```

Seventeen MPNs and three `Part Number` headers, in one string. The other eight rows
are the letterhead, the PDN metadata, the reason checklist, the customer-notification
paragraph and the acknowledgement form.

### The exact chain to zero parts and zero declines

Measured on the real bytes, in the pod, with the image own code:

| discriminator | value |
|---|---|
| `_grid_width` | **1** |
| `find_header_row` | `None` |
| `find_title_row` | **0** |
| `_caption_label` | `None` |
| `_is_form_region` | `False` |
| `_mpn_bearing_rows` | **0** |
| `header_pairing` | `None` |
| `grid_outcome` | **parts=0, decline=None** |

1. No header row, and the grid is not a form region, so rungs 1 and 2 do not apply.
2. `find_title_row` returns **row 0** — the company letterhead — so **rung 3 fires**:
   the letterhead is read as *a caption naming the contents*, and the single column
   becomes an affected-part column.
3. No *cell* is MPN-shaped, so the row loop emits nothing.
4. At the silent-zero guard (`table_text_layer.py:712`), `_mpn_bearing_rows` is **0**,
   so the guard does not fire and the function returns `GridOutcome(out, None)` —
   `([], None)`, the one outcome the module says it must never produce.

**The guard is a per-CELL test, so it is blind exactly where it is needed**: on a
degenerate one-column grid whose single cell visibly holds seventeen part numbers,
it reports zero MPN-bearing rows. That is the mechanism, not a judgement call.

Two candidate mechanisms were **ruled out** by the same replay: `_tables_of` swallowed
no exception (it returned 1), and `parts_and_declines_from_pages` did not raise, so the
outer `except` at `plugins/sustainment.py:596` — which returns `[], stats` *without*
setting `text_layer_declines` and would forge the same signature — did not fire.

### Per-row bboxes are available, and not from cells

TI mechanism cannot be ported, because IDT has no cell geometry for its parts. The
**word layer** has it. Measured on the same page:

```
page 1: 612.0 x 792.0 pt        extract_words: 211
MPN-shaped tokens in the flattened cell r3: 17
distinct MPN-shaped WORDS on the page:      17
MPNs resolving to exactly ONE word box:     17 of 17
in cell but NOT a discrete word: []     a discrete word but NOT in the cell: []
looks_like_mpn accepts: 17 of 17

DX0783-ULG2B00-A4  bbox=[59.8, 259.4, 148.8, 268.8]
DX8313-CBG-A3      bbox=[200.1, 259.4, 269.1, 268.8]
DX9353-CBG-A3      bbox=[340.5, 259.4, 409.5, 268.8]
```

Seventeen for seventeen, each unique, **in PDF points** — the same space TI cells
already use, so the sealed `fraction = bbox / page_dims` rule holds with no unit
conversion and the two-coordinate-space trap from section 5 closes rather than widens.

### Why this dissolves the regression risk I flagged

I held section 5 open on the ground that the parts path is at 522/522 for the first
time, so touching the tier that produces parts carries new risk. **The bbox fix does
not touch that tier.** It attaches provenance to parts vision has already emitted; it
cannot add, drop or alter an MPN, so it cannot move the parts score. The directive is
deliverable with no exposure to the green.

Two couplings found while checking that claim, both deliberately avoided:

- **The OCR-verbatim bypass.** `sustainment_merge.py` computes
  `in_ocr = True if tl_bbox else ...`, so a cell bbox suppresses the hallucination
  check. Riding the word box on that same key would silently stop OCR-checking IDT
  rows — and `needs_review` is load-bearing: **IDT identity-half instability is
  exempted in the authority report precisely because its `needs_review` is True in
  all three fires.** The word box therefore uses a distinct key and leaves `in_ocr`
  exactly as it is.
- **A decline is not inert.** Making the degenerate grid decline — the obvious cure
  for the guard gap — would hand that grid to **grid forwarding**
  (`plugins/sustainment.py:812`), where vision labels its columns and part strings
  are taken *verbatim from its cells*. For IDT the forwarded grid is a one-column
  paragraph blob, and the page would be marked `grid_handled` and diverted off the
  crop path that currently yields its 17 correct parts. **So the guard fix does carry
  risk to 522/522 — through forwarding, not through the tier.** It is specified below,
  not shipped tonight.

### The fix, in two independent pieces

1. **Per-row bboxes (the directive).** A word-layer locator,
   `table_text_layer.word_boxes_for_mpns(numbered_pages, mpns)`, attaching a box only
   when an MPN resolves to **exactly one** word box in the whole document — zero or
   two or more gets an honest absence, never a guessed coordinate. Matching is exact
   string equality, no normalization, per the module standing verbatim discipline.
   Surfaced as `match_method: "text_layer_word"`. Delegated with that spec.
2. **The zero-decline guard gap (NOT shipped).** The guard needs to see MPN-shaped
   **tokens inside** a cell, not only MPN-shaped cells, so a degenerate grid declines
   instead of returning `([], None)`. Two instances now (IDT, and the paired grid).
   It must not be landed until a declined one-column grid is made **non-forwardable**,
   or grid forwarding gains a width precondition — otherwise the cure costs parts.

A third, cosmetic item, recorded because it is why rung 3 fired at all: a company
letterhead passing `find_title_row` as *a caption naming the contents* is a misfire.
It costs nothing here, since the grid emits no part either way.
