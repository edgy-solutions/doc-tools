# PCN/PDN tier-2 baseline — what the product actually emits on the 5 zero-recall notices

**Date:** 2026-09-22. Answers the "measure before building" item in
`docs/pcn-corpus-validation-2026-09-21.md` §4: for the 5 notices where tier 1
(`table_text_layer.py`) returns zero parts, what does the *full* pipeline
(tier 1 → tier 2 vision fallback → merge) actually emit, compared against the
source PDF read by hand?

> **This is the before-picture, and it is separate history.** Measured on pod
> `doc-tools-7d5f466995-vwrf6` — the **pre-roll** image, before the
> continuation-table extractor fix was deployed and before any cap change. Do
> not read its numbers as current. The day's argument runs
> baseline → cap → three fires:
> this file, then `pcn-product-baseline-2026-09-22.md` (post-roll at the 2048
> default), `pcn-vision-cap-sizing-2026-09-22.md` (2048 → 4096 → 32768), and
> `pcn-vision-cap-8192-three-fires-2026-09-23.md` (the deployed 8192).

## Method

- Pod: `sandbox/doc-tools-7d5f466995-vwrf6` (confirmed running via
  `kubectl get pods -n sandbox` at the start of this session).
- All commands run via the PowerShell tool; scripts copied in with `kubectl cp`
  from `C:\Users\cnogr\AppData\Local\Temp\claude\...\scratchpad` and executed
  with `kubectl exec ... -- python /tmp/<script>.py`. No stdin piping. No file
  in this exercise was named `inspect.py`.
- Bucket: `processing-artifacts` (`$DAGSTER_STORAGE_BUCKET` default). Keys were
  **listed first**, not assumed: `extraction.json` sits next to `text.json`
  under `<prefix>/generated/<name>_pdf/extraction.json`, confirming the task
  brief's correction (it is *not* at `sustainment/inbound/<name>/extraction.json`).
- Emitted parts pulled from `extraction.json`'s
  `augmentations[0].notice.impacted_parts[]` (`affected_mpn`, `replacement_mpn`,
  `*_source`), per the shape in `doc_tools/plugins/sustainment.py`'s
  `PartImpact`/`SustainmentNotice` and written by
  `doc_tools/assets/semantic_assets.py:397` (`_extraction_payload`, `:85-90`).
  `augmentations[0].stats` (`n_tables`, `crops_failed`, `crops_truncated`,
  `vision_used`, `text_layer_used`) gives the tier/router state for that run,
  read directly off the artifact rather than inferred.
- Ground truth pulled by opening each source PDF with `pdfplumber`
  (`extract_tables()` / `extract_text()`) directly in the pod and reading the
  actual rows.
- Diff (missed / invented / mis-transcribed) computed programmatically
  (exact-string set comparison, `difflib.get_close_matches` for near-miss
  checking on anything invented), not by eye, for the three notices where a
  usable run existed.

### A data-hygiene problem found along the way — named, not silently resolved

Three of the five notices (`PCN23-002`, `PCN24-029`, `onsemi_Generic_PD26044X1`)
have exactly one `extraction.json` each, all dated 2026-09-18, at the plain
path `sustainment/inbound/generated/<name>_pdf/extraction.json`. Those are used
directly below.

The other two do **not** have a single canonical run:

- **`onsemi_Generic_IPCN25300X`**: no `sustainment/inbound/onsemi_Generic_IPCN25300X.pdf`
  exists at all. Instead there are **8 separate re-processing attempts** from
  2026-07-23/08-09, each in its own ad hoc subfolder (`onsemi_ipcn/`,
  `onsemi_run2` … `onsemi_run6`, `onsemi_truthkey/`), plus stray `review.json`-only
  folders (`ceremony_complete/`, `ceremony_final/`, `ceremony_first/`,
  `postfix_supervised/`, `record_witness/`) that carry no extraction and were
  not used for anything below. The 8 real attempts disagree with each other:
  `doc_id` is wrong in 6 of them (e.g. `"inbound/onsemi_run3"` — the header pass
  didn't resolve a real notice number), and part counts across attempts are
  **0, 2, 2, 2, 2, 19, 19** depending on whether a vision crop happened to
  time out that run (see verdict). None of these names ("truthkey" included)
  should be read as an authoritative label — they are not; I picked the most
  recent **clean** run (`onsemi_run6`, 2026-07-23 20:52 UTC, 0 crops failed) as
  the representative "tier 2 succeeded" case, and separately report the spread
  across all 8 attempts, because the spread is itself the finding.
- **`ADI_PDN_23_0120`**: 3 attempts. `adi_23_0120` (03:21 UTC) failed outright
  on an infrastructure error (litellm DNS resolution, HTTP 503) — not a parts
  logic failure, excluded. `adi_run2` has manifest/text/images but **no
  `extraction.json` at all** (the run never reached persistence — treated as
  "no stored extraction," not as zero parts). `adi_run3` (03:45 UTC) is the
  only complete, successful run and is used below.

Neither notice has a run dated alongside the September corpus (the three clean
ones above, or the 2026-09-21 validation doc). Treat the numbers for these two
as "what tier 2 does on this document," not "what today's deployed image would
do right now" — I did not re-run the pipeline live (out of scope: read-only,
no MinIO writes).

## Per-notice results

| Notice | Ground truth | Emitted | Missed | Invented | Mis-transcribed |
|---|---|---|---|---|---|
| `PCN23-002.pdf` | 18 (p2, single-column MPN list) | 0 | 18 | 0 | 0 |
| `PCN24-029.pdf` | 1 (`TC4-1TX+`, labeled "MODELS AFFECTED", no table at all) | 0 | 1 | 0 | 0 |
| `onsemi_Generic_PD26044X1.pdf` | 25 (10 on p1 + 15 on p2) | 25 | 0 | 0 | **0** |
| `onsemi_Generic_IPCN25300X.pdf` | 19 (17 on p3 + 2 on p4) | 19 (clean run) / 2 (4 of 8 runs) / 0 (1 of 8 runs) | 0 (clean run) up to 19 (worst run) | 0 | **0**, on every run checked |
| `ADI_PDN_23_0120.pdf` | 1 (`AD7873ACPZ` → `AD7873ARUZ`) | 1 | 0 | 0 | **0** |

Every affected-MPN string that tier 2 actually emitted, across all three
directly-comparable notices (25 + 19 + 1 = 45 parts, verified by exact string
match), matched the ground truth **character for character**. No
mis-transcription — the hypothesis this exercise was built to test — was found
anywhere in the corpus.

### Detail: `PCN23-002.pdf`

Tier 1 declines (single-column, no header). Vision *is* invoked (`n_tables=1,
vision_used=True`), but its one crop hits the 2048-token output bound
(`crops_truncated=1`) — an 18-row single-column table is dense enough to
overrun the cap — so the whole crop's partial output is discarded by design
("truncation is a failure, not a partial success," per the code comment) and
0 parts are emitted. `needs_review=True`, correctly flagged. This is a
**drop**, not a transcription error — the model never got a chance.

### Detail: `PCN24-029.pdf`

Ground truth is a single labeled MPN (`TC4-1TX+`) under "MODELS AFFECTED," not
a table — `unstructured` detects zero Table elements on this page (confirmed:
`n_tables=0` in stats, and independently in pdfplumber), so the router takes
the header-only branch and never calls vision at all. This is a genuinely
different failure mode from the other four: it is a **router/detection gap**
(no table shape to hand to either tier), not a tier-1-vs-tier-2 question.

### Detail: `onsemi_Generic_PD26044X1.pdf`

Clean run, `needs_review=False`, `crops_failed=0`. All 25 affected MPNs across
both pages emitted verbatim, in document order. The document's own replacement
column is the sentinel `#NONE` (with supplier `#NA`) for every row — the model
correctly emitted `replacement_mpn=None` rather than transcribing the literal
string `#NONE`, which is the right call, not a miss.

### Detail: `onsemi_Generic_IPCN25300X.pdf`

Ground truth is 19 affected parts (17 continuing on p3 under a "Qualification
Vehicle" column — not a true replacement-part column, despite the task brief's
framing — plus 2 more on p4's headerless continuation, same qualification
string). All 19 rows share one qualification-vehicle value:
`SNSR01F30NXT5G, NSR20F40NXT5G`.

Across 8 recorded attempts on this document, the *affected*-MPN side is either
complete-and-exact (19/19, verbatim, 2 attempts) or catastrophically absent
(2/19 or 0/19, 6 attempts) — determined entirely by whether the vision crop
covering the dense p3 table (17 of the 19 rows) times out that run. When it
times out, only the p4 continuation crop survives, yielding exactly the 2 p4
rows. **In every attempt, whatever rows did come through were verbatim
correct** — including the task brief's cited pair:

```
NSR01F30NXT5G | SNSR01F30NXT5G, NSR20F40NXT5G
NSR01L30NXT5G | SNSR01F30NXT5G, NSR20F40NXT5G
```

emitted exactly this way (both `affected_mpn` and `replacement_mpn` fields)
whenever the p4 crop succeeds — which is every attempt. No character is wrong
in any attempt.

The qualification-vehicle field is a separate, secondary drop: even the
best-case clean run (`onsemi_run6`) captures it only for the 2 p4 rows and
emits `None` for the other 17, which do carry the same value in the source.
That is a **missed field**, not a wrong one — nothing invented in its place.

### Detail: `ADI_PDN_23_0120.pdf`

Single-row notice. `adi_run3` emits `AD7873ACPZ → AD7873ARUZ`, matching the
document exactly, including the `Model`-headed affected column that §4 flags
as absent from tier 1's `AFFECTED_HEADERS` vocabulary. Vision reads the column
correctly from the image regardless of tier 1's header-vocabulary gap.

## Verdict

**Tier 2 is not mis-transcribing these parts.** Zero character-level
transcription errors were found anywhere in this corpus — the hypothesis in
§4 ("MPNs are precisely the strings a vision model gets wrong by one
character") did not reproduce on these 5 notices. Whatever tier 2 emits is
right.

The real gap is **recall, not accuracy**, and it has two distinct causes:

1. **Vision truncation/timeout on dense tables** drops whole crops
   wholesale (`PCN23-002`: 18/18 lost to a token cap; `onsemi_Generic_IPCN25300X`:
   0–17 of 19 lost depending on run, non-deterministically, to crop timeout).
   This is exactly the failure mode §4's redesign targets, and the measurement
   confirms it is real and not hypothetical — but it manifests as **silence**,
   not corruption.
2. **Router non-detection** drops a document entirely before vision is ever
   called (`PCN24-029`: a single non-tabular labeled MPN, no Table element,
   never reaches either tier).

So: **already getting it right when it runs, unreliable about whether it runs
at all.** The §4 redesign (tier 1 hands forward a declined grid; tier 2 only
classifies columns, never re-reads MPN strings from pixels) is best understood
as a **robustness and determinism improvement**, not a correction to a
transcription-accuracy bug — because there isn't one to correct, on this
evidence. It would still be the right fix: it removes the token-cap/timeout
failure mode entirely (tier 1's grid is already complete; only column meaning
is missing) rather than leaving recall dependent on whether a vision crop
happens to converge before its token budget runs out.

## Caveats

- N = 45 emitted parts checked across 3 clean-run notices; this is not a
  large sample, and it is entirely this-vendor's-document-formats — it shows
  zero transcription errors were found here, not that vision transcription is
  reliable in general.
- The `onsemi_Generic_IPCN25300X` and `ADI_PDN_23_0120` numbers come from
  July/August one-off runs, not a run matching the September corpus or
  today's deployed image — named explicitly above, not glossed over.
- `PCN24-029`'s gap is a router/table-detection issue, outside the tier-1↔
  tier-2 handoff that §4 addresses; noted so it isn't miscounted as evidence
  for or against that redesign.
