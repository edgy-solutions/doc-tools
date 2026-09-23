# Sizing VISION_MAX_TOKENS: 2048 → 4096 → unbounded, measured

    image     ghcr.io/edgy-solutions/doc-tools@sha256:71a662f0f41a3cbc1484f0b465c83871b3cf3ec09b2487b0a8cc6aea72606046
    pod       doc-tools-6675ccd5b-s8x7t   (helm release doc-tools rev 11)
    endpoint  C — 192.168.1.169:11434, gemma4-32k:31b, sole resident
    method    process env only. No values change, no deploy, no image build.

All three runs are on the **same image**, back to back, so the extractor fix and
the cap are not confounded. Baseline detail: `docs/pcn-product-baseline-2026-09-22.md`.

## Result

| cap | corpus total | `PCN23-002` (GT 18) | `IPCN25300X` (GT 19) |
|---|---|---|---|
| **2048** (code default) | **860 / 896** | 0 | 2 |
| **4096** | *(2 notices only)* | 17 | 19 |
| **32768** (effectively unbounded) | **894 / 896** | 17 | 19 |

The four tier-1 notices returned 24 / 402 / 402 / 4 in every run — identical.
Tier 1 does not touch the vision model, and the cap does not perturb it.

**The caution I gave was wrong.** I wrote that getting from 2 to 19 on
`IPCN25300X` "does not obviously close," reasoning that a bigger budget lets the
model write more, which is not the same as writing it correctly. It closed, and
it closed exactly, twice. The correctness question was the right one to ask; the
pessimism attached to it was not, and the answer came from the diff below rather
than from the part count.

## Why 8192, and why it is not an arbitrary round number

Running at **32768** — three times the largest table in the corpus needs — is
what makes this a measurement of the model rather than of the cap. Offered a
budget it cannot exhaust, the densest crop still emitted **2,723 tokens**:

| tokens | elapsed | tok/s | notice |
|---|---|---|---|
| **2,723** | 131.2s | 20.75 | `PCN23-002` |
| 2,687 | 128.8s | 20.87 | `IPCN25300X` |
| 1,661 | 78.9s | 21.04 | `ADI_PDN_23_0120` |
| 1,572 | 79.4s | 19.79 | `PD26044X1` |
| 1,269 | 62.6s | 20.28 | `PD26044X1` |

15 crops, max 2,723. The 4096 run's max was **3,472** on the same notice — so
emission length varies run to run by roughly 20%, and **3,472 is the largest
ever observed at any cap**. That variance is the reason not to size to the
observed maximum.

    8192  =  2.4x the largest emission ever observed (3,472)
          =  3.0x the largest observed when the cap could not bind (2,723)

The upper bound is the per-call timeout, not the context window. At the measured
~20 tok/s, 8192 tokens is ~400s against the 600s `LLM_REQUEST_TIMEOUT_MS`
default. Going much higher trades a **detected** truncation for an **undetected**
timeout, which is strictly worse: truncation raises `PARTS MAY BE MISSING`.

**No runaway decode occurred at 32768.** The longest single crop was 131.2s,
well inside the timeout. The "dense tables decode forever" failure the 2048
default was chosen to prevent does not reproduce on this hardware.

Decode is **19.6–21.0 tok/s** on crops above ~700 tokens. A 255-token crop
measured 10.92 tok/s — that figure is combined prefill+decode, so a short output
is dominated by fixed prefill and is not a slower model.

## Correctness: the part count is not the evidence

Character-level diff of emitted strings against the source PDF text layer.

**`PCN23-002`** — identical at 4096 and at 32768:

    exact matches     17 of 17
    spurious          0
    duplicates        0
    emitted in page order   yes
    missing           SYTX9-122HP-1+

The missing part is **the last row of the table on p2**, immediately above:

    SYDC-25-92VHP1+
    SYTX9-122HP-1+
    PCN23-002 Rev.: A M135112 (01/16/12) File: PCN23-002 ...

Reproduced at 4096 **and** at 32768, where the crop used 2,723 of 32,768
available tokens. This is a **last-row boundary effect where the table abuts the
page footer**, and it is now proven rather than inferred: no cap value reaches it.

It is also **silent**. `needs_review=False`, no review reason, nothing in
`crops_failed` or `crops_truncated`. Truncation is detected and surfaced;
this class of loss has no detector at all. That is the more important finding here.

**`IPCN25300X`** — 19 of 19, and all 19 distinct MPN tokens appear **verbatim in
the PDF text layer**. Zero fabricated strings. This settles the open question
about `SNSR01F30NXT5G` looking like a corrupted `NSR01F30NXT5G`: both strings are
really in the document, and the leading `S` is the notice's, not the model's.

## The qualification-vehicle column did not regress

`IPCN25300X` emits no qualification-vehicle field, and the historical runs that
did were recording a pre-normalizer value. There is no such field to lose:
`PartRow` — the vision pass's schema — carries only `affected_mpn`,
`replacement_mpn`, `ltb_date`. Its `replacement_mpn` description ends
"Qualification / evaluation vehicles are NOT replacements," and
`sustainment_normalize.clean_replacement` nulls any comma-separated value on the
grounds that a genuine replacement is exactly one part.

`tests/test_sustainment_extraction.py:148` asserts this against the exact string
this corpus produces:

    assert norm.clean_replacement("SNSR01F30NXT5G, NSR20F40NXT5G") is None

So the model emitted the qualification vehicles into `replacement_mpn`, as it
always has, and the normalizer dropped them by design. Working as intended.

## New instrument: crops_near_cap

Truncation is only observable **at** the cap, by which point rows are already
gone. A crop that emits close to the cap is the last observable state before
that, and the ratio is the only early warning available. Crops emitting
≥ `VISION_NEAR_CAP_RATIO` (0.85) of the bound now increment `crops_near_cap`,
log the ratio, and set `needs_review`.

It deliberately does **not** raise the `PARTS MAY BE MISSING` doc flag: nothing
is known to be missing, and spending that banner on a complete extraction trains
reviewers to ignore it when it means something.

At 8192 this **will not fire on the current corpus** — 2,723 is 33% of 8192.
That is correct: it is armed for a document denser than anything yet seen, which
is precisely the case that would otherwise fail silently.

**Known gap:** neither the existing truncation detector nor this new flag has
test coverage — `crops_truncated` appears nowhere under `tests/`. Exercising the
path needs BAML-client and collector mocking. Not added here rather than added
unrun.

## What is still missing, by name

Two parts of the original 36, neither attributable to the cap:

1. **`SYTX9-122HP-1+`** — the last-row drop above. Silent. Undiagnosed.
   A cheap partial detector: when a crop's row count is below the table's
   visible row count from tier 1's grid, set `needs_review`. That is the
   declined-grid-forwarding design from `pcn-corpus-validation-2026-09-21.md` §4
   paying for itself a second time.
2. **`PCN24-029`'s single part** — a different defect. Tier `neither`: 0 crops,
   vision never invoked, because the router finds no Table element. No cap value
   can reach it.

## Strength of the evidence

`IPCN25300X` has a documented ~25% clean-run rate at 2048 (2 of 8 historical
attempts), so a single good run is suggestive rather than conclusive. What makes
this more than luck is the **mechanism**: a 2,687–3,472-token emission against a
2,048-token ceiling explains every historical failure, and both raised-cap runs
returned 19/19 with `crops_truncated: 0` rather than surviving a truncation.

It is still two runs. **Three fires at 8192 after the upgrade** are what settle
it, and those results belong in a follow-up dated report, not this one.
