# Three fires at the deployed 8192 — the ruling on IPCN25300X

    release   doc-tools revision 12, 2026-09-23 08:07 CDT
    pod       doc-tools-7957657dc7-ql79d
    imageID   ghcr.io/edgy-solutions/doc-tools@sha256:71a662f0f41a3cbc1484f0b465c83871b3cf3ec09b2487b0a8cc6aea72606046
    cap       VISION_MAX_TOKENS=8192, read back from the running module (not just the manifest)
    endpoint  C — 192.168.1.169:11434, gemma4-32k:31b

This is the follow-up promised in `docs/pcn-vision-cap-sizing-2026-09-22.md`.
The sizing evidence there rested on two runs; the three-fires ruling applies to
a notice with a known-flaky history, so it applies here.

**No process env override.** These runs read the cap from the deployed
configuration, so what is measured is the deployment, not an experiment.

## Result: 3 of 3, both notices

| fire | notice | got / GT | elapsed | crops | largest crop | trunc | failed | needs_review |
|---|---|---|---|---|---|---|---|---|
| 1 | `PCN23-002` | **17** / 18 | 151.1s | 1 | 2,422 | 0 | 0 | False |
| 2 | `PCN23-002` | **17** / 18 | 160.2s | 1 | 3,040 | 0 | 0 | False |
| 3 | `PCN23-002` | **17** / 18 | 129.0s | 1 | 2,171 | 0 | 0 | False |
| 1 | `IPCN25300X` | **19** / 19 | 286.4s | 7 | 2,405 | 0 | 0 | False |
| 2 | `IPCN25300X` | **19** / 19 | 298.8s | 7 | 2,822 | 0 | 0 | False |
| 3 | `IPCN25300X` | **19** / 19 | 298.4s | 7 | 2,676 | 0 | 0 | False |

The emitted part sets are **byte-identical across all three fires** for both
notices — not merely equal in count.

Character-level diff against the source PDF text layer, all three fires:

    PCN23-002     17 exact, 0 spurious, missing SYTX9-122HP-1+   (identical each fire)
    IPCN25300X    19 distinct MPN tokens, 0 not found verbatim in the PDF

## The ruling

`IPCN25300X` had a documented **~25% clean rate at 2048** (2 of 8 historical
attempts). At a raised cap it is now **5 consecutive clean runs** — 4096, 32768,
and these three at 8192 — every one of them 19/19 with `crops_truncated: 0`.

That is no longer "suggestive". Combined with the mechanism — a 2,405–3,472
token emission against a 2,048-token ceiling explains every historical failure —
the cap is established as the cause and 8192 as an effective fix for this notice.

Worth stating precisely: these runs never truncated, rather than truncating and
surviving it. The failure mode being ruled out is absent, not tolerated.

## Emission variance is the reason 8192 is not 4096

The same crop on the same input, across every run at every cap:

    PCN23-002   single crop:  2,171  2,422  2,723  2,840  3,040     (40% spread)
    IPCN25300X  largest crop: 2,405  2,676  2,687  2,822  3,472     (45% spread)

Across the three fires: 24 crops, largest **3,040 tokens = 37% of 8192**.
Largest ever observed at any cap: **3,472**.

    8192  =  2.4x the largest emission ever seen
          =  2.7x the largest seen at the deployed cap

Sizing to the observed need would have put the ceiling inside that spread. The
output length wanders by 40% run to run on identical input — while the extracted
content does not, which is the more interesting half of this table: the model
varies how verbosely it emits, not what it finds.

## What did not change

Both residual defects reproduce exactly, at every cap, in every fire:

1. **`SYTX9-122HP-1+`** — missing from `PCN23-002` in all three fires, as at
   4096 and at 32768. It is the last row of the table, immediately above the page
   footer. Silent: `needs_review=False`, nothing in `crops_failed` or
   `crops_truncated`. Not a cap defect and no cap value reaches it. The proposed
   cheap detector — flag `needs_review` when a crop's row count is below the
   table's visible row count from tier 1's grid — is still unbuilt.
2. **`PCN24-029`** — not exercised here (these fires cover the two vision
   notices only). It remains tier `neither`: the router finds no Table element,
   so vision is never invoked.

## `crops_near_cap` was NOT exercised

The near-cap instrument merged in `b11323e` but is **not deployed**: it is code,
and `values-sandbox.yaml` still pins the image to `0279d83`. The running module
has no `VISION_NEAR_CAP_RATIO` — verified, not assumed. Deploying it needs a pin
bump to `b11323e` and the image build that comes with it.

It would not have fired in any case: 3,040 of 8,192 is 37%, well under the 0.85
threshold. That is the intended behaviour — it is armed for a document denser
than anything in this corpus, which is exactly the case that would otherwise
lose rows silently.

Neither that flag nor the pre-existing truncation detector has test coverage
(`crops_truncated` appears nowhere under `tests/`). Unchanged by this work.
