# Report — 7f REGION CROPS: the witness now supplies, and TYC is sealed

to: architect
from: doc-tools/lane/7f, 2026-10-01

---

## 0. Headline

**Sealed: TYC's three ground-truth fields, verbatim, on three fires.** `mfr`,
`pub_date` and `doc_level_ltb_date` all read correctly in fires 1, 2 and 3 at the
candidate code, against the live host.

Four things in the order's design turned out to need correcting, and all four are
load-bearing:

1. **DPI was a confound.** The crops read every field correctly **at 150 DPI** —
   the resolution the DPI report indicts. Framing is the whole effect; the page
   knob is not what fixed this and should not be swept again.
2. **Reading correctly was still 0/3.** The witness was wired as a corroborator,
   and a corroborator cannot reach either TYC defect. It had to become a
   **supplier**. That is beyond the order's literal wording and is, I believe,
   the evident intent of "per-field questions"; it is the single largest change
   here and the one most worth your objection if I have read it wrong.
3. **One fire in three lost the header crop to a host 400** and silently
   published the damaged text layer's own values. The crop was measured innocent
   (8/8 on byte-identical input), so the region read now retries once, and a
   region that stays lost is reported rather than left as a counter nobody reads.
4. **TYC's gate exemption does not self-close.** It was keyed on `needs_review`,
   which a degraded text layer sets permanently — so the exemption could never be
   revoked by any measurement. Narrowed; see §6. **This can newly block `main`.**

Evidence section for the DPI question:
`sessions/2026-10-01-report-7f-witness-diagnosis-it-is-the-image.md`.

---

## 1. The seal

Three fires, candidate tree at `fb8da71`, driven through the real plugin methods
(`_extract_header` → `_read_regions_witness` → `supply_header_from_regions` →
`refuse_unsourced_header_values`) over the real PDF on the live host.

| | fire 1 | fire 2 | fire 3 |
|---|---|---|---|
| `mfr` | `TE Connectivity` | `TE Connectivity` | `TE Connectivity` |
| `pub_date` | `2024-06-07` | `2024-06-07` | `2024-06-07` |
| `doc_level_ltb_date` | `2024-06-06` | `2024-06-06` | `2024-06-06` |
| verdict | **PASS 3/3** | **PASS 3/3** | **PASS 3/3** |
| regions read | 2 of 2 | 2 of 2 | 2 of 2 |
| retries used | 0 | 0 | 0 |
| region wall-clock | 53.7s | 54.7s | 56.5s |

Ground truth is `scripts/pcn_ground_truth.json`: `TE Connectivity`,
`2024-06-07` (NOT the portal print stamp `2024-06-10`), `2024-06-06`.

**The harness mirrors the plugin, and asserts that it does.** It locates the two
call sites in `sustainment.py` by source and fails if the supply call is not
before the refusal — so a future reordering in the plugin cannot leave this
measurement quietly measuring a path the product no longer runs. That guard
caught one of my own errors: its first version compared bare names and ordered a
docstring mention against real code.

---

## 2. The crops read right, and they do it at 150 DPI

What the two region crops return (verbatim, fire 1):

```
Manufacturer: TE Connectivity
Document Number: PCN-24-210412
Notice Date: 07-JUN-24
Current Date: 10-Jun-2024
```
```
Last Order Date: 06-JUN-2024
Last Ship Date: 07-JUN-2024
All Dates: Last Order Date (Obsolete Parts Only): 06-JUN-2024 | Last Ship Date of
Changed Items (Obsolete Parts Only): 07-JUN-2024
```

Every field right, including the one the whole-page witness has never once got
right: the notice date **separated from** the print stamp, both present, neither
confused for the other.

**And this works at 150 DPI.** Your control already implied it — same model, same
host, whole page wrong twice, crop right — and the crop runs confirm it. The
300-DPI page render is not what fixed this. I would leave
`DOC_PARSER_PAGE_RENDER_DPI` at 200 (it also feeds the parts crops, where it was
measured better than both 150 and 300) but stop treating it as any part of the
header story.

---

## 3. Why reading correctly was still 0 of 3

The first three fires had every answer above, correct, and scored **0/3**. The
witness was a **corroborator**: a filter over values the text layer produced. A
filter fixes precision. Neither TYC defect is a precision defect:

- `mfr`: the damaged text layer prints `TE Connecvity`, so it **corroborates its
  own misspelling**. The containment check passes on a wrong value.
- `pub_date`: `2024-06-10` is **genuinely printed on the page**. It is the
  portal's print stamp. No corroboration check rejects a value the page prints.

So the witness now **supplies**: on the degraded path it writes the field and
cites its own verbatim answer as the `*_source`, and
`refuse_unsourced_header_values` then runs over the result like any other value.
Nothing is exempt from the citation check — the supplied value simply has a
citation that can pass one.

Order matters and is commented at the call site: **supply, then refuse.**

### The two guards, because a date written from a crop is the risk

- **The distractor is asked separately and discarded.** `Current Date:` is a
  question whose only purpose is to not be used. If both questions come back with
  the same answer, the model read one stamp twice and **no date is supplied**.
  `currentdate` is deliberately absent from `REGION_FIELD_ANSWERS`.
- **`All Dates:` restates every `label: date` pair** and the last-order pairing is
  cross-checked against it. Disagreement **blocks** the supply; silence does not —
  absence from a witness is not evidence.

---

## 4. Three defects, found by tests rather than by fires

All three were in code written the same day, and all three were **silent**: each
left the feature looking present.

1. **`_all_dates_pairs` split on `=` only** — which is what the prompt asks for.
   The host answers with `:`. So the redundancy guard returned **zero pairs on
   real data**, and since silence does not block, it was inert while reading as
   implemented.
2. **`_iso_date('2024-06-07')` returned `None`.** Root cause is in
   `ltb_candidates._try_date`: it routes the month through `_month_num`, a **name**
   dictionary, so `_MONTHS.get("06")` is `None` and **every all-numeric date is
   invisible to `_find_dates`**. `_find_dates('06/07/2024') -> []` too. Latent, and
   **deliberately not fixed here** — it moves LTB candidate generation across the
   whole corpus, which is a measured change. `_iso_date` matches the unambiguous
   ISO form locally and still declines `06/07/2024` rather than guessing D/M.
3. **The supplier skipped a value that already agreed, and left its citation
   alone.** TYC's `doc_level_ltb_date` was **already correct** at `2024-06-06` and
   cited as `-2024`, a truncated snippet naming no date — so the refusal rejected
   it (`source_is_a_different_date`) and blanked a correct value. The citation is
   now repaired even when the value is untouched.

---

## 5. One fire in three lost the header crop — and the crop was innocent

Fire 2 of the first clean set scored **1/3**, with no code difference from the
fires either side of it. The header-block read had failed with:

```
400 Bad Request: Failed to load image or audio file
```

so `mfr` and `pub_date` fell straight back to `TE Connecvity` and `2024-06-10` —
exactly the two values this path exists to replace — and the only trace in the
record was `witness_regions = 1` instead of 2.

**Measured before fixing.** The header crop was built **once** and sent **eight
times**: byte-identical, one sha256, a valid JPEG that decodes locally at
2392x729, 275 KB. **8/8 succeeded**, ~10s each. A rejection that does not
reproduce on identical bytes is the host's.

Two changes follow:

- **One retry, same bytes.** A **timeout is not retried** — the ~300s ceiling is
  server-side and not configurable from this repo, so retrying into it buys the
  same answer for twice the wall clock.
- **A region that stays lost is reported**: a reason naming the region and the
  header fields that went with it, a `witness_regions_lost` counter, and the
  reviewer-facing banner. The banner is the structural half: a degraded text layer
  deliberately raises none, so before this a notice that lost its header witness
  looked exactly like a clean one.

That second part is the real lesson. The region stopped being a cross-check the
moment it became the supplier. Losing one no longer weakens a check — it
publishes a value from a text layer already known to be damaged.

---

## 6. TYC's exemption does NOT self-close — and this can block `main`

The order expects that after this lands, "TYC stops being an exemption and the
gate scores it like the other eight." **It does not follow, and I changed the
gate rather than report a false completion.**

The exemption in `check_header_correctness` was keyed on
`needs_review_in_all_fires`. `needs_review` is set **unconditionally** by
`_apply_text_layer_stats` whenever the text layer is degraded, and TYC's
degradation is a permanent property of that PDF. So TYC held an exemption **no
measurement could ever revoke** — an exclusion dressed as an exemption, over the
one notice whose header was measured wrong.

Narrowed: the exemption must now be earned by a reason that **names the header** —
a refused field, a failed header pass, a lost or unlocatable region — in **every**
fire, with `needs_review` still required alongside. Degradation alone no longer
qualifies, because the region witness reads header fields from crops the text
layer had no part in. When the witness genuinely fails, the plugin now says so
(§5) and that reason earns the exemption on its own merits.

**Review this one.** It can newly block `main`. TYC is the only notice it can
reach today, and only while the header is measured wrong. `strict_verdict`
counted this failure all along, so nothing changes about what was *true* — only
about what blocks.

---

## 7. State

- Branch `pcn/witness-page-dpi-200`, PR **#47**, **not merged**. The branch name
  is a misnomer now; the PR is retitled to the region-crop story.
- Commits: `a18de9c` region crops · `b0c6f4e` the supplier + the three defects ·
  `fb8da71` retry and loss reporting · `57f1806` the gate narrowing.
- Suite: **1014 passed**, 15 skipped. The 3 failures are the known
  `iagent_mesh.provenance` venv/SDK-pin mismatch (0.9.4 installed against the
  v0.9.5 pin), unrelated to this work.
- The DPI sweep is finished; nothing is running in the pod.

## 8. Not done, and why

- **The corpus is not re-scored.** This is candidate code measured on one notice.
  The render and the parse artifacts are written at **ingest**, so the nine-notice
  re-ingest (prior order item 1) is what turns this into a corpus number — and
  TYC's `current.json` still points at `doc-tools@fa19b85`, so the corpus is mixed
  vintage until it runs.
- **`ltb_candidates._try_date` is left broken** (§4.2), recorded in project memory
  rather than patched blind.
- **Prior order item 3** (#43, the `ingress-user/` sensor against Lane 1's live
  routes) is unstarted.

## 9. One clause of the order I could not implement as written

> "Whole-page transcription stays only for `text_layer_degraded` detection."

Degradation is not detected from an image. `text_layer_health.assess_elements`
measures it from **text statistics** (ligature retention), with no vision call at
all — which is why it is known *before* any witness is built, and is what decides
whether to build one. Implemented as the evident intent: the whole-page
transcription is retained for the degraded path's **parts** corroboration, where
it is still needed because part rows are spread over tables across the document
and a header crop contains none of them. It is no longer any header field's
source.
