# Report — lane 7f, 2026-10-27: the 2683 banner is MALFORMED, not absent, and the only side that never moved to the 10-21 ruling is the contract

cc on the P0 (`PCN-2683`, sha `af5bfad3f934`, "915 rows carry an evidence_ref
that cannot be read"). Items 1–4 are lane 01's and item 1 is the one that
settles it — **I have not seen the wire, and nothing below claims to have.**
What follows is the producer side, which is mine, plus two readings taken from
object databases rather than working trees.

---

## 1. The banner names which half of the problem it is, and it is not the half I expected

Cortex has **two** evidence banners, not one
(`cortex-ui/src/components/ApprovalTask/PromotionReviewCard.tsx`):

| line | counter | wording |
|---|---|---|
| 619–621 | `absentEvidence` | "N rows carry no evidence_ref: nothing to check" |
| 625–627 | `malformedEvidence` | "N rows carry an evidence_ref **that cannot be read**." |

The screenshot is **line 627** — `malformedEvidence`. So `evidence_ref` is
**present** in the payload the card received and fails a check inside the
reader.

That eliminates the first thing I went looking for. doc-tools writes the key
**`wire_evidence_ref`**, not `evidence_ref`
(`doc_tools/utils/sustainment_merge.py:_review_item`). Had nothing mapped that
name across, every row would be **absent** and the banner would be line 621.
It is not. Something is serving an `evidence_ref`.

## 2. What doc-tools actually puts on the wire — literal bytes, not a reading of code

Run on the venv interpreter from PowerShell, through
`merge._review_item` with the sealed fixture provenance:

```
one box       {"page": 3, "bbox": [0.131176, 0.416818, 0.388824, 0.433182]}
two boxes     {"page": 3, "bbox": [0.131176, 0.416818, 0.532353, 0.433182], "note": "2 boxes"}
no page_dims  {"page": 3, "bbox": null, "note": "no page dimensions: the geometry could not be made unit-free, so no box is claimed"}
```

Keys are `page`, `bbox`, and `note` when there is one. **`page_dims` is never a
key in any of the three** — omitted, not nulled, deliberately, because that
presence is the form discriminator. `page` comes from
`enumerate(pdf.pages, start=1)` (`doc_tools/plugins/sustainment.py:429,852,1315`),
so it is 1-based and satisfies the reader's `posInt` (`>= 1`).

That is the ruled shape and it is what cortex's fraction branch accepts.

## 3. The reader, confirmed at their master — not at the branch I first read it on

I first read `readEvidence` in the `cortex-ui` checkout, which sits on
`disposition-card-standard`. Per the lesson #181 cost us this week, a working
tree measures nothing, so I re-read it from `origin/master` (`7023b333`):
**byte-identical.** The classification holds at master.

Its shape, in the order the checks run:

- `evidence_ref` missing/null → **absent**
- not an object → malformed
- `bbox` absent or null, `page` good → **ok** (page-only). So a null bbox is
  *not* a cause; three of my own rows above would read fine.
- **`page_dims` absent or `undefined`** → the ruled fraction branch: needs
  `isFractionBox(bbox)` (4 finite numbers, `0 <= x0 < x1 <= 1`, same in y)
- **`page_dims` present in any other state** → the pt/px branch, which begins
  `!isObj(d) → malformed`

The last two lines are the ones that matter. `Object.hasOwn(e, "page_dims")` is
**true for a null**, and `null` is not an object, so a `page_dims: null`
reaching the reader is **malformed on every row** — regardless of the `via`
method and regardless of whether the bbox is a perfectly good fraction box.

The screenshot shows 915 of 915 unreadable across **two different `via`
methods** (`text_layer_cell` and `inherited_doc_level`). A per-path geometry gap
cannot do that. Something global to the payload shape can.

## 4. The measured divergence: the contract never moved

`docs/api/cortex-bff.openapi.json` lives in **`invincible-agent`** (the packet's
path is right; `cortex-ui` carries a pinned mirror at
`src/api/openapi/cortex-bff.openapi.json`, pinned by `SOURCES.json` to
`b59e4a0f`). Read from the object database at `origin/master` — **`ecf73dae`**,
which is where the platform is now, 1 pin ahead of what #181 pins:

```
"EvidenceRef": {
  "additionalProperties": false,
  "description": "Where on the page an extracted value was read (units pt for a cell match, else px).",
  "properties": { "bbox", "bboxes", "page", "page_dims", "quality", "units" },
  "required": [ "page", "bbox", "bboxes", "page_dims", "units", "quality" ]
}
```

- **`page_dims` is REQUIRED.** So is `bboxes`, `units`, `quality`.
- **`note` is not a declared property at all**, under
  `additionalProperties: false`.
- The description is still the **pre-ruling** pt/px sentence.
- `ExtractionRow.evidence_ref` is `anyOf [EvidenceRef, null]`, and
  `evidence_ref` is in `ExtractionRow.required`.

So every row doc-tools emits violates that schema **twice**: it omits four
required keys and carries one undeclared one. The same shape appears at the
pinned `b59e4a0f` and at master `ecf73dae`, so this conclusion does not depend
on which of the two you read.

**Item 2, "which side moved":** doc-tools moved to the ruling (`d9e6118`
dropped `page_dims` and converted the boxes in one write; the wire ref landed in
`b08468f`/#145). Cortex moved — its reader takes both forms and documents the
10-21 one. **The contract did not move.** It still describes the world as it was
before 2026-10-21.

By item 3's own branch — *"if the contract itself is wrong, the contract PR
comes first and both sides follow"* — that is the first PR, and it is lane 01's
tree.

## 5. Item 3's seal already exists in two of its three legs, and the P0 is sitting in the missing one

This is not new work. `tests/test_row_fraction_seal.py` in this repo says so in
its own docstring, written 2026-10-21:

> *"with Lane 1 adding a third leg proving a fixture row leaves their route
> byte-equal and with no `page_dims`. So the span is converter -> BFF -> reader
> and the three legs cover it; this file is the first."*

- **Leg A** — `tests/test_row_fraction_seal.py`, here, green on every commit.
- **Leg B** — `cortex-ui/src/lib/rowFractionSeal.test.ts`, theirs, exists.
- **Leg C** — the BFF leg, proving a fixture row leaves the route byte-equal
  with no `page_dims`. **Measured as absent**, and the contract above is why: a
  schema that requires `page_dims` cannot pass a byte-equality test against a
  row that has none.

So item 3 is not "add a seal across three repos" from nothing. It is **land the
third leg that was assigned on 10-21 and never shipped**, and fix the contract
it would have failed against. The docstring already names the span's middle as
the part neither existing leg can see — and that is exactly where this P0 lives.

If it helps, #181's mechanism is the ready-made vehicle for the cross-repo half:
a pinned sha in `tests/pins/`, fetched by CI, with a missing fetch **failing**
rather than skipping. It is already wired for `invincible-agent` in this repo's
`tests` job.

## 6. The two candidate wire shapes, and how the screenshot tells them apart

Offered for item 1 to confirm or kill in one paste. **Both are predictions, not
measurements** — I have not seen the route's output.

| if the BFF emits | reader's verdict | banner | highlighting |
|---|---|---|---|
| `page_dims: null` (a serializer filling a required key) | **malformed, every row** | line 627 | none |
| `page_dims: {width, height}` of the real page, bbox left in fractions | **ok** | none | a box ~0.13 pt wide — invisible |

The report has a banner *and* no highlighting, which is the first row. The
second would be silent. Either way the fix is the same shape of fix; the first
is the one consistent with what Chris is looking at.

## 7. Ruled out, so nobody re-walks it

- **The deployed image is not too old.** `v0.2.2` contains
  `_row_wire_evidence_ref` (3 occurrences); `v0.2.1` has 0. It landed in
  `b08468f` (#145), confirmed an ancestor of `v0.2.2`.
- **A null bbox is not the cause.** It is contract-legal on our side and reads
  **ok** in cortex's own reader.
- **`page` is not the cause.** 1-based from `enumerate(..., start=1)`, which is
  what `posInt` wants.
- **A name mismatch on the key is not the cause** — it would show the *absent*
  banner (§1).
- **It is not a per-path geometry gap.** `parts_text_list.py:90` hardcodes both
  `text_layer_page_dims` and `text_layer_bbox` to `None`, so that salvage path
  yields *no box*, not an unreadable one; `table_text_layer.py:993,1105` sets
  real `page_dims`. And the symptom spans two `via` methods anyway.

## 8. For cortex's parallel item — the exact strings we already emit

Cortex is asked to log *which* check failed per row instead of "cannot be read".
Our rows already carry a `note` saying why, in these four wordings and no others
(`doc_tools/utils/provenance.py:140-181` plus the union branch):

- `no page dimensions: the geometry could not be made unit-free, so no box is claimed`
- `bbox lies outside the page, or has no area, so there is no box to draw`
- `bbox extended past the page edge and was clamped` (a box *is* still emitted)
- `N boxes` (the row's boxes were unioned into one outline)

`note` is the key the contract does not declare — so if the BFF is validating,
this is also the diagnostic that is being thrown away at the boundary.

## 9. Also measured, for #181

The platform's `origin/master` moved `4a4cf47c` → **`ecf73dae`** today, but the
`course` overlay row **still has no `render.pages`**
(`passes: [core.baml::ExtractOutline, training.baml::ExtractConcepts]` at
`ecf73dae`). So #181 stays a **draft**, and the pin is not bumped — moving it to
a sha that still lacks the row buys nothing and would still be red. The ruling's
one-line PR is lane 01's, after their dry-run fix.

## 10. What 7f is not doing

Not touching the producer. Our emitted shape matches the 10-21 ruling and
cortex's reader accepts it; changing it to satisfy a contract that predates the
ruling would be moving the wrong side. If the ruling is re-opened and
`page_dims`/`units`/`quality` come back, that is a producer change here and we
will take it — but it goes after the contract PR, per item 3.

— lane 7f
