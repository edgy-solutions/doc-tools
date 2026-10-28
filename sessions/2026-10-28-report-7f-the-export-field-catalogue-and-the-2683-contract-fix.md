# Report — lane 7f, 2026-10-28: the export field catalogue ships, and the 2683 contract fix landed upstream while it was being written

Two things, one of which was not asked for and matters more than the other.

- **Item 2 of the export packet is delivered**: `registry/export_field_catalogue.json`,
  57 fields, sealed by `tests/test_export_field_catalogue.py` (14 legs) against a
  pinned contract extract.
- **The `PCN-2683` P0 is closed on the contract side.** Lane 01 landed it today,
  and their commit subject confirms the mechanism I had labelled a prediction.

---

## 1. The P0: fixed, and the prediction was right

`invincible-agent` `origin/master` moved `ecf73dae` → **`5522d8d2`** while I was
measuring. Three commits on `docs/api/cortex-bff.openapi.json`:

| commit | subject |
|---|---|
| `7281603b` | `feat(contract): EvidenceRef is 7f's wire shape {page, bbox, note?} (architect 10-28)` |
| `ac77ef61` | `fix(extraction): serve 7f's wire_evidence_ref as is, no page_dims` |
| `9723df35` | `fix(contract): note?: string, never null; cortex's OLD_REF refused by the published schema` |

`ac77ef61` is the confirmation. Yesterday I wrote, and labelled a **prediction**,
that the route was filling the then-required `page_dims` with a null, which
`Object.hasOwn` lets through cortex's guard and `!isObj(null)` then refuses —
malformed on every row, independent of `via`. Their own subject line is *"serve
7f's wire_evidence_ref as is, **no page_dims**"*. The route was synthesising it.

The schema at `5522d8d2`:

```
EvidenceRef: additionalProperties false, required ["page"]
  page  integer, minimum 1
  bbox  anyOf [4 numbers each 0..1, null]
  note  string, pattern "\S"
description: "7f's wire_evidence_ref, served as is (architect rulings 2026-10-21
  and 2026-10-28). ... A null bbox means 'on this page, no box' (ruling 205).
  Nothing else is served: no bboxes, page_dims, units or quality."
```

**Our producer is contract-legal with no change, measured, not assumed.** We emit
`{page, bbox, note?}`; `page` is 1-based from `enumerate(pdf.pages, start=1)`, so
it satisfies `minimum: 1`; fractions are clamped to 0..1; and
`_row_wire_evidence_ref` writes the note key under `if note:`, so a null or empty
`note` — which `9723df35` now refuses — is unreachable from here. §8 of
yesterday's report said we would change nothing in the producer. That holds, and
it is now the contract that says so.

**Not measured, so not claimed:** whether leg C of the three-leg row seal now
exists on their side. The contract no longer blocks one. Do not assume the fix
shipped a seal with it.

## 2. Item 2, delivered

Three new files, all on `7f/gate-triggers-suspend-nightly`:

| file | what |
|---|---|
| `registry/export_field_catalogue.json` | 57 fields, the registry a profile references |
| `tests/fixtures/cortex_bff_extraction_pin.json` | the pinned contract extract, `ref 5522d8d2…`, 7 schemas + the route description |
| `tests/test_export_field_catalogue.py` | the seal, 14 legs, unmarked so it runs in a default `pytest` |

Each entry carries 11 fixed keys: `name, scope, type, nullable, producer,
review_json, wire, served_by, vocabulary, evidence, notes`. Scopes are `notice`
(26), `row` (17), `steward_edit` (11), `provenance` (3).

### The load-bearing column is `served_by`, and half of them are null

**29 of 57 fields are reachable on `GET /ingest/{id}/extraction`. 28 are
produced by doc-tools and not served at all.** A profile cannot emit what the
route does not carry, so this is the column item 1 has to read first. The
unserved set includes `header.doc_type`, `header.revision`, `header.pub_date`,
`header.categories`, `header.summary`, **`header.doc_level_ltb_date`**, and the
whole `*_source` family except one.

`header.doc_level_ltb_date` is the one that bites. It is the value unsourced
part-level LTB rows *inherit*. A per-part export that omits it loses the only
source those dates have, while the rows themselves still show a date — so the
export looks complete and is not.

### Header evidence exists and cannot be exported

Header review items carry a `wire_evidence_ref`. The wire's `Notice` object has
exactly four properties (`mfr`, `mfr_parent`, `mfr_source`, `notice_date`) and no
`evidence_ref`, under `additionalProperties: false`. The route serves only the
`parts[i].*` items as rows. So header evidence is produced and unreachable.

## 3. Two name collisions, either of which would silently export the wrong thing

**`obtained_via`.** On the wire, `ExtractionRow.obtained_via` is the **match
method** — `unique`, `region_preferred`, `ambiguous`, `not_found`,
`text_layer_cell`, `text_layer_word`, `inherited_doc_level`, `derived`, from two
families, and the schema declares **no enum** so that list is measured rather
than guaranteed. In ADR-0041, `obtained_via` is the **trust rung**: `None` or
`user-drop`, with `authoritative_source` and `standing` beside it, and a `None`
means *no provenance stamp is written at all* rather than "rung unknown".

The packet asks for the **provenance rung**. That is the ADR-0041 one, and it is
**not served on this route**. Cataloguing the wire field under that heading would
have exported match methods as provenance. Both are in the catalogue, under
`row.obtained_via` and `provenance.obtained_via`, with the collision stated on
each.

**`mfr_source`.** The producer's `header.mfr_source` is a **verbatim source
substring** (BAML: *"Verbatim source substring for mfr — MANDATORY whenever mfr
is non-null"*), one of a family with `pub_date_source`, `mfr_parent_source`,
`doc_level_ltb_date_source`. The contract's `Notice.mfr_source` is a **closed
enum `{header, identity}`** naming which arm produced the value. Two unrelated
fields, one name. Catalogued as `header.mfr_source` and `notice.mfr_source`.

Measured aside: `sustainment_header_trust.py` sets `header["mfr_source"] = None`
on at least two paths, despite BAML calling it mandatory whenever `mfr` is
non-null.

### Two mappings I did not assert

- `notice.notice_date` ← `header.pub_date`. The contract gives `notice_date` no
  type and no description, and nothing in doc-tools writes that name. Recorded as
  **unverified**, because a date transform in a profile needs the format settled
  and because `pub_date` is a **print stamp**, not an effective date.
- `notice.mfr_source` ← unknown. The enum values name our two header arms, but no
  doc-tools field carries those values. Lane 01 derives it somewhere.

## 4. A steward can only ever correct `mfr`

`HeaderEdit.field` is a closed enum `{mfr, notice_id, notice_date}`. The producer
writes four header review items: `pub_date`, `mfr`, `mfr_parent`,
`doc_level_ltb_date`. **The intersection is `{mfr}` alone.**

So an export column of "steward-corrected header fields" can never differ from
extraction on anything but `mfr`, and nobody can correct an `mfr_parent` or a
doc-level LTB date at all. `RowEditCounts.header` is therefore bounded above by 3
by that enum, not by how many header fields exist.

## 5. Three part values share one wire column

`affected_mpn`, `replacement_mpn` and `ltb_date` all arrive as
`extracted_value`, picked out by `row.field`. A column list needs the **selector**,
not just a name — which is the clearest single argument for the mapping language
item 1 describes.

The `replacement_mpn` and `ltb_date` rows are emitted **only when the part has
one**. A part with no replacement has two rows, not three. A per-part profile
must tolerate an absent row rather than expect a null. Catalogued as
`part.affected_mpn`, `part.replacement_mpn`, `part.ltb_date`, each naming its
selector.

That gap was caught by the seal, not by me: the first draft catalogued the three
only generically, and leg 7 failed because `replacement_mpn` and `ltb_date` were
claimed by no entry. The implementer stopped on it rather than relaxing the
assertion, which is the behaviour that makes the seal worth having.

## 6. What the seal covers, and the hop it does not

`tests/test_export_field_catalogue.py`, 14 legs, all green:

- **catalogue → pinned contract**: every `wire` entry exists in the pinned schema.
- **pinned contract → catalogue**: every property of the 7 pinned schemas is
  claimed, with exactly two declared exemptions (`Extraction.rows`,
  `Extraction.notice` — the structural containers), and the exemption set itself
  is asserted so it cannot quietly grow.
- **enums**: walked generically; every schema enum must match a `closed`
  vocabulary. Bites on `Extraction.leaf`, `Extraction.leaf_source`,
  `Notice.mfr_source`, `HeaderEdit.field`.
- **`EvidenceRef`**: `additionalProperties false`, `required == ["page"]`,
  properties exactly `{page, bbox, note}`, `page.minimum == 1`, `note` a string
  with no null branch.
- **producer**: `build_review_items` is called and its emitted `field_path` set
  and item key set are asserted exactly; no emitted `wire_evidence_ref` may carry
  a key the pinned schema refuses — **including `page_dims`** — and no `note` may
  be null or empty. That is yesterday's P0, sealed from our side.
- **BAML**: the header and impacted-part `_properties` sets are parsed out of
  `type_builder.py`; all 13 header names must be claimed. A BAML regen that moves
  a field reds the catalogue.

**The hop it does not cover, named deliberately:** that the platform still serves
the pinned shape. The extract is a frozen copy, so a platform-side change does
not red this repo until the pin is re-taken. That freshness leg is #181 and #181
is a draft. This is the same trap as the 2683 P0 — two green legs are not a
covered span — and it is written into the catalogue under `seal.NOT_sealed`.

## 7. Two premises of the packet that are not true in the tree

Stated plainly rather than worked around, because both are measured and both are
item 1 and item 3 dependencies.

1. **There is no batch column-map vocabulary to reuse.** `column_map` and
   `column-map` have **zero** occurrences in `doc_tools/`, `registry/` and
   `docs/`. Item 1 tells lane 01 to *"reuse 7f's batch column-map vocabulary so
   one mapping language serves both"*; it does not exist yet. It is the
   four-ruling batch fixture chain from Packet B item 2, which is unbuilt and is
   queue item 4 here.
2. **`change_type` and `effective_date` are not extracted at all.** Zero
   occurrences in `sustainment_merge.py` and `plugins/sustainment.py`. Two of
   those same batch rulings name them, so no profile can reference them today,
   and the ISO-8601-with-`date_ambiguous` normalisation the ruling calls for has
   nothing to normalise.

Neither blocks the catalogue, which is why it shipped. They block the
**transform and date-format half** of the mapping language, and they block any
profile column over those two fields.

## 8. What 7f needs, and what it is not doing

Needed from lane 01, in this order:

1. Whether `notice.notice_date` is `header.pub_date`, and where
   `notice.mfr_source` gets `header`/`identity` from. Both are one line each and
   both are currently `unverified` in the registry.
2. Whether item 1 wants the 28 unserved fields widened onto the route, or whether
   profiles are scoped to the 29 that are served. A profile language that can
   name a field the route cannot carry is a 422 waiting to happen.
3. Whether the batch fixture chain is still 7f's to build, given item 1 now
   depends on its vocabulary.

Not doing: inventing the column-map vocabulary unilaterally, or adding
`change_type`/`effective_date` to the catalogue as if they were promoted fields.

## 9. Suite state

Full local suite from PowerShell on the venv interpreter:
**`1 failed, 2279 passed, 13 skipped, 16 deselected, 1 xfailed in 114.60s`**.

The one failure is `test_overlay_kind_drift.py::test_the_shared_kinds_declare_the_same_passes`
on **`doors-export`** — pre-existing, unrelated, and the known false red from the
unpinned seal reading the sibling working tree that sits ~149 commits behind.
That is exactly what #181 replaces. Nothing in this work touches it.

## 10. Addendum, same day: the inbox had two things that changed this work

Checked `invincible-agent/sessions/` before closing the block. Three packets
dated today touch the export directive; two of them changed what shipped.

**1. `bbox` is now always present, and we already comply.** cortex relayed the
architect: *"A ref without `bbox` is not legal; the shape is {page, bbox,
note?}."* Nullable, but the key is always there — which reverses the 205 note
that omitting it equalled null. **Measured:** both our emitters write the key
unconditionally (`sustainment_merge._row_wire_evidence_ref` initialises
`{"page": page, "bbox": None}`; `leaf_read.wire_evidence_ref` writes
`list(bbox) if bbox else None`), and both were already sealed to it —
`test_row_wire_evidence_ref.py` asserts `set(out) == {"page", "bbox"}` exactly
and `test_leaf_read.py:262` asserts the whole dict. **Nothing in the producer
changes.**

What did change: the catalogue seal no longer derives the floor from the pin.
My pinned extract reads `required: ["page"]` (the schema at `5522d8d2`, before
lane 01 regenerates), so the seal now asserts `{"page", "bbox"} ⊆ keys`
**itself**, citing the ruling, and the registry records it under
`seal.stricter_than_the_pin`. **Deliberately stricter than the pin** — holding
to the ruling now rather than finding the gap when they re-pin onto
`required: [page, bbox]` and cortex turns an absent key malformed. That is the
2683 shape of failure, declined in advance.

**2. `scope` is a third collision, and it is worse than the two in §3.** Both
proposed shared profile headers use the key, and they already disagree:

| source | `scope` means | values |
|---|---|---|
| this catalogue | which **field scope** a field belongs to | `notice`, `row`, `steward_edit`, `provenance` |
| cortex, route 1 | the **row granularity** of the export | `row`, `notice` |
| lane fin, CDRL header | a **program-level** profile | `program` |

The first two **collide on the literal tokens `row` and `notice` while meaning
different things**. Here `scope: row` is *one value per (notice, part, field)*;
there it is *the profile emits one row per (notice, part)*. A profile carrying
`scope: row` beside a column list whose entries carry a `scope` reads wrong and
looks right. And fin asked lane 01 explicitly to flag a differing `scope`
vocabulary before `policy/exports/` merges — there are now two. Recorded as the
third `collisions` entry, `severity: high`. **Not renamed unilaterally**: fin
and cortex are both proposing headers against lane 01's, so the rename is
theirs to pick (`granularity` on the header, or `field_scope` here).

**3. Item 2 does not block cortex.** Their §4: the picker chooses profiles by
name and does not read the catalogue for this slice. So the answers §8 asks for
gate item 1 and the column-list half of the mapping language, not cortex's
buttons.

Seal after both changes: `14 passed`; with both evidence-ref suites,
`97 passed in 9.97s`.

— lane 7f
