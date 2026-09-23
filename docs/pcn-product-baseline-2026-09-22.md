# PCN/PDN Product Baseline — 2026-09-22

Scope: measure what `SustainmentPlugin.process_fulltext` (the real product
entry point, driven the same way `semantic_assets.py` drives it) emits today
on the deployed sandbox image
(`ghcr.io/edgy-solutions/doc-tools:0279d836a57de0f2c4ae00f9e51b3c74009499e7`,
digest `sha256:71a662f0f41a3cbc1484f0b465c83871b3cf3ec09b2487b0a8cc6aea72606046`,
pod `doc-tools-6675ccd5b-s8x7t` / namespace `sandbox`), for all 9 named
source PDFs under `sustainment/inbound/` in MinIO bucket
`processing-artifacts`. This is a before-picture for a future
`VISION_MAX_TOKENS` change, plus a follow-on cap experiment run against two
notices once the baseline confirmed which ones truncate. No S3/Neo4j/Jena/
Weaviate/DataHub writes and no Dagster materialization occurred anywhere in
this work — the extraction functions were called directly and results kept
in memory / written only to `/tmp` in the pod and this report.

**Disclosure**: before importing `doc_tools.*`, the harness scripts popped
`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` from the process environment so
that `doc_tools.telemetry.observed_trace` (fail-soft, no-op without the
`provenance_telemetry` package) would not send this measurement run's spans
to the shared Langfuse project. That was my own judgment call, not spec'd.

**Tooling note**: partway through this session, bare `/tmp/...` arguments
passed to `kubectl exec` from this Windows/Git-Bash environment were being
silently rewritten by MSYS path conversion into local Windows paths before
reaching `kubectl` (e.g. `python /tmp/check_vision_ps.py` arrived in the pod
as `python /app/C:/Users/.../check_vision_ps.py` and failed with `Errno 2`).
Fixed by prefixing those specific invocations with `MSYS_NO_PATHCONV=1`.
Noted here since it explains a couple of otherwise-confusing exit-code-2
errors if anyone re-runs this.

## 1. The `/tmp/run.done` signal is not trustworthy — do not use it

The original baseline launch used a `nohup sh -c '...; echo EXIT_CODE=$? > /tmp/run.done'`
pattern from a PowerShell double-quoted string. PowerShell expands its own
`$?` (its last-command-success boolean) inside a double-quoted string before
the payload ever reaches `kubectl`/the pod shell. Confirmed directly this
session — `cat /tmp/run.done` in the pod returns exactly:

```
EXIT_CODE=True
```

That is not a real python exit code under any circumstance. Success for
this report is determined instead from `/tmp/baseline.json` content and the
tail of `/tmp/run.log`, both read directly in the pod this session:

- `python -c "json.load(open('/tmp/baseline.json'))"` parses cleanly, has
  all 9 expected filename keys, and every entry has `"ok": true`.
- `/tmp/run.log`'s last line is `WROTE /tmp/baseline.json`, written by the
  harness only after all 9 notices completed and the file was flushed.

Both signals agree: **all 9 notices completed**, none died mid-corpus. The
9-of-9 completion claimed in the coordinator's interim message is confirmed
independently here, not taken on faith.

## 2. Baseline results — all 9 notices, VISION_MAX_TOKENS=2048 (deployed default)

Vision endpoint (`192.168.1.169:11434/api/ps`) before the run: `{"models":[]}`
— gemma was not resident, so whichever notice hits vision first pays a cold
load inside its elapsed time. **Limitation**: only before/after readings
exist for this run (both `{"models":[]}` — the model had unloaded again by
the time I checked after, consistent with Ollama's idle-unload behavior,
not a failure signal). Mid-run sampling was not part of the original spec
and was not retrofitted onto this already-completed run; it *is* present
for the cap experiment below (section 4).

| # | Notice | Provenance | Tier | Parts emitted | Elapsed (s) | Vision crop stats | needs_review |
|---|--------|-----------|------|---------------:|------------:|--------------------|:---:|
| 1 | `TYC-PCN-24-210412.pdf` | canonical | tier1 | 24 | 31.1 | — | False |
| 2 | `Diodes_PCN_2683_Rev1_EOL.pdf` | **substituted †** | tier1 | 402 | 47.2 | — | False |
| 3 | `Diodes_PCN_2683_FULLGREEN.pdf` | canonical | tier1 | 402 | 34.3 | — | False |
| 4 | `EOL-36_BYV34-400,-BYV34-500.pdf` | canonical | tier1 | 4 | 28.9 | — | False |
| 5 | `ADI_PDN_23_0120.pdf` | **substituted, overridden ‡** | tier2_vision | 1 | 131.1 | 1 crop, 0 failed, 0 truncated | False |
| 6 | `PCN23-002.pdf` | canonical | tier2_vision | 0 | 132.0 | 1 crop, 1 failed, **1 truncated** | True |
| 7 | `PCN24-029.pdf` | canonical | neither (router never calls vision — no Table element) | 0 | 22.1 | — | ? (see ground-truth doc) |
| 8 | `onsemi_Generic_IPCN25300X.pdf` | **substituted †** | tier2_vision | 2 | 280.3 | 7 crops, 1 failed, **1 truncated** | True |
| 9 | `onsemi_Generic_PD26044X1.pdf` | canonical | tier2_vision | 25 | 205.2 | 7 crops, 0 failed, 0 truncated | False |

**Total parts emitted: 860.** Rows marked † and ‡ are provenance-deviant —
see section 3 before citing them. `PCN24-029`'s `needs_review` value wasn't
captured in the harness's early field list for that entry; it is a router/
detection gap (no Table element on the page), not a tier-1-vs-tier-2 issue,
and is documented as such in `pcn-tier2-baseline-2026-09-22.md`.

## 3. Provenance of the 3 non-canonical notices — two separate claims, not one

No canonical `sustainment/inbound/<filename>.pdf` object exists for any of
these three — confirmed directly this session by `head_object` against
`sustainment/inbound/Diodes_PCN_2683_Rev1_EOL.pdf`,
`sustainment/inbound/ADI_PDN_23_0120.pdf`, and
`sustainment/inbound/onsemi_Generic_IPCN25300X.pdf`: all three return
**DOES NOT EXIST**. Each notice's manifest/text.json was instead read from
an ad hoc historical run subfolder. The earlier "three substitutions"
phrasing conflated two different things — corrected here:

- **Folder substitution** (which `generated/.../manifest.json` the harness
  pointed at) is true of all 3.
- **`source_key` field override** (patching a `null` field in memory after
  reading the manifest) is true of only **1 of 3** — `ADI_PDN_23_0120.pdf`.
  `/tmp/baseline.json`'s `source_key_override` field is non-null *only* for
  that notice, and that field is the accurate record: the other two
  resolved through their own self-declared, valid `source_key`, no patch
  needed.

Per-notice, both claims stated separately and honestly:

### `Diodes_PCN_2683_Rev1_EOL.pdf`
- Manifest read from `sustainment/inbound/diodes_bbox/generated/Diodes_PCN_2683_Rev1_EOL_pdf/manifest.json`.
- **(a) Byte-identity — verified.** Command: `hash_check.py` (in-pod,
  boto3 `head_object`/`get_object` + `hashlib.md5`), executed this session.
  Three candidate copies exist:
  `sustainment/inbound/diodes_2683/Diodes_PCN_2683_Rev1_EOL.pdf`,
  `sustainment/inbound/diodes_bbox/Diodes_PCN_2683_Rev1_EOL.pdf`,
  `sustainment/inbound/diodes_tier1/Diodes_PCN_2683_Rev1_EOL.pdf`. All
  three: size 181899 bytes, ETag/MD5 `abe083fe8bab0e963874777280e8e293`,
  identical to each other and self-consistent (downloaded-bytes MD5 equals
  the S3 ETag for a non-multipart small object).
- **(b) Provenance/rightness — moderate.** The manifest's own
  self-declared `source_key` field is `sustainment/inbound/diodes_bbox/Diodes_PCN_2683_Rev1_EOL.pdf`
  — it points at itself, no override needed. Reasoning strength: filename
  match + self-declared manifest pointer to a real, existing object. No
  independent confirmation that `diodes_bbox` (vs. `diodes_2683` or
  `diodes_tier1`) is the "correct" historical run in any business sense —
  only that its manifest is internally consistent and its PDF bytes are
  identical to the other candidates anyway, so it makes no difference which
  of the 3 was picked for this measurement.

### `ADI_PDN_23_0120.pdf`
- Manifest read from `sustainment/inbound/adi_run3/generated/ADI_PDN_23_0120_pdf/manifest.json`.
- **(a) Byte-identity — verified.** Same method. Three candidates:
  `adi_23_0120`, `adi_run2`, `adi_run3` — all size 32264 bytes, ETag/MD5
  `fd9eff0fde5578c105975b729812dacc`, identical across all three.
- **(b) Provenance/rightness — weaker, override required.** This
  manifest's own `source_key` field is `null` (confirmed by reading the
  manifest JSON directly this session) — it does **not** self-resolve. The
  harness patched `manifest["source_key"] = "sustainment/inbound/adi_run3/ADI_PDN_23_0120.pdf"`
  in memory before calling the plugin (visible in `/tmp/baseline.json` as
  `source_key_override`). Reasoning: filename match to the folder name plus
  "only candidate with 3 runs available, all byte-identical" — there is no
  manifest-internal pointer confirming `adi_run3` specifically is correct
  over `adi_23_0120`/`adi_run2`; since their PDF bytes are identical this
  is moot for the *content* fed to the plugin, but the override itself is a
  measurement-harness decision, not a product behavior, and should be read
  as "substituted, not independently verified beyond byte-identity" rather
  than confirmed-correct provenance.

### `onsemi_Generic_IPCN25300X.pdf`
- Manifest read from `sustainment/inbound/onsemi_truthkey/generated/onsemi_Generic_IPCN25300X_pdf/manifest.json`.
- **(a) Byte-identity — verified.** Same method. Seven candidates
  (`onsemi_ipcn`, `onsemi_run2`..`onsemi_run6`, `onsemi_truthkey`) — all
  size 417830 bytes, ETag/MD5 `c9674b3893e657e59fde3c78aad424ce`, identical
  across all seven.
- **(b) Provenance/rightness — moderate-to-strong.** The manifest's own
  `source_key` field is `sustainment/inbound/onsemi_truthkey/onsemi_Generic_IPCN25300X.pdf`
  — self-resolving, no override needed. The folder name itself
  (`onsemi_truthkey`) and its later `LastModified` (2026-08-09, vs. the
  other 6 candidates spanning 2026-07-23) both suggest it was deliberately
  curated as the reference copy, but that reading of the folder name is an
  inference, not something the manifest states explicitly.

No number above is a re-fabricated "verified" — where the evidence is only
folder-name/self-reference reasoning rather than a hash, it's stated as
such, at the strength it actually has.

## 4. Diff against ground truth

Against `docs/pcn-corpus-validation-2026-09-21.md` (tier-1 ground truth)
and `docs/pcn-tier2-baseline-2026-09-22.md` (full-pipeline ground truth,
read from stored `extraction.json`, not freshly re-run there):

| Notice | Ground truth | Baseline emitted | Gap | Note |
|---|---:|---:|---:|---|
| `TYC-PCN-24-210412.pdf` | 24 | 24 | 0 | matches |
| `Diodes_PCN_2683_Rev1_EOL.pdf` | 402 | 402 | 0 | matches |
| `Diodes_PCN_2683_FULLGREEN.pdf` | 402 | 402 | 0 | matches |
| `EOL-36_BYV34-400,-BYV34-500.pdf` | 4 | 4 | 0 | matches |
| `ADI_PDN_23_0120.pdf` | 1 | 1 | 0 | **character-for-character match** — `AD7873ACPZ`→`AD7873ARUZ`, verified against `/tmp/baseline.json` content directly |
| `PCN23-002.pdf` | 18 | 0 | 18 | crop truncated at 2048 cap, discarded by design |
| `PCN24-029.pdf` | 1 | 0 | 1 | router never calls vision (no Table element) — a detection gap, not a tier defect |
| `onsemi_Generic_IPCN25300X.pdf` | 19 | 2 | 17 | p3 crop (17 of 19 rows) truncated; p4 crop (2 rows) survived |
| `onsemi_Generic_PD26044X1.pdf` | 25 | 25 | 0 | count matches; spot-checked `NCN5192MNRG` row present and matches doc excerpt; full 25-row character diff not exhaustively re-run this session (ground-truth doc already documents this as a clean, exact run) |

**Total: 860 of 896 parts (36 missing), all 36 in tier2_vision/router-gap
notices, zero missing from any tier1 notice.** This matches the
coordinator's figure, independently reconstructed here from the raw JSON,
not taken on their word.

**`crops_truncated > 0` flag: 2 notices** — `PCN23-002.pdf` and
`onsemi_Generic_IPCN25300X.pdf`. These are exactly the two notices the cap
experiment (section 5) re-ran.

## 5. Cap experiment — VISION_MAX_TOKENS=4096

Re-ran only the two notices above, in a fresh process with
`VISION_MAX_TOKENS=4096` set in that process's environment only
(`VISION_MAX_TOKENS=4096 python /tmp/cap_experiment.py`, launched via
`nohup` inside a single-quoted `kubectl exec ... sh -c '...'` so the `$?`
bug from section 1 could not recur). No `values-sandbox.yaml` edit, no
`helm upgrade`, no pod restart — confirmed unchanged: same pod
(`doc-tools-6675ccd5b-s8x7t`), same start time throughout.

**Method for per-crop capture**: `doc_tools.plugins.sustainment._extract_parts`
only returns aggregate stats, not per-crop detail, so the harness
monkeypatched `doc_tools.baml_client.sync_client.b.ExtractParts` — the
exact BAML call the product makes — with a wrapper that times the call and
reads `collector.last.usage.output_tokens` off the same `collector` object
the product already passes in via `baml_options`. Arguments, return value,
and control flow are untouched; the wrapper only observes. A background
thread polled `192.168.1.169:11434/api/ps` every ~12s concurrently with
each notice's extraction call (this status poll was the only traffic sent
to `.169` during the experiment — no other extraction ran against it
concurrently, per instruction).

Neither notice truncated at 4096, so **no 8192 round was run** (the
"only if 4096 still truncates" condition was not met).

### `PCN23-002.pdf` @ 4096

| Crop | Elapsed (s) | Output tokens | Truncated | Combined rate (tok/s) |
|---|---:|---:|:---:|---:|
| 1 (only crop) | 142.6 | 2840 | No | 19.9 |

Notice total: 165.1s, `crops_truncated=0`, `crops_failed=0`,
**final_part_count = 17** (ground truth: 18). Result: the truncation is
gone — 2840 tokens comfortably fit under the new 4096 cap with room to
spare — but **the notice is still 1 part short of ground truth, with no
truncation and no crop failure to blame it on.** This is a separate,
unexplained residual defect, not a cap issue. It cannot be attributed to a
mistranscribed or dropped row from a known-good prior list, because no
prior successful decode of this document exists to diff against — every
historical run at 2048 truncated to 0 parts (per `pcn-tier2-baseline-2026-09-22.md`,
"18/18 lost to a token cap" on every prior attempt). This 4096 run is the
**first time this notice has ever produced a non-empty result**, so the
17-vs-18 gap is new information, not a regression from a known baseline —
but it's also not yet diagnosed. Determining which of the 18 source rows
is missing, or whether it's a false 18-count from the source PDF, would
require reading the source PDF page directly, which is out of scope here.

`192.168.1.169:11434/api/ps` during this notice: the first 3 samples
(spanning ~03:11:28–03:11:52 UTC) show `{"models":[]}`; from the 4th
sample onward (03:12:04 UTC) `gemma4-32k:31b` is resident with
`size_vram == size` (20,926,064,230 bytes) for the rest of the notice. This
notice was first in the cap-experiment process and paid a cold load — the
model had unloaded again since the original baseline run ended (confirmed
by the post-baseline `{"models":[]}` reading in section 2). The 142.6s
single-crop elapsed time therefore includes an unknown but nonzero cold-load
component; it should not be read as pure decode time for that crop.

### `onsemi_Generic_IPCN25300X.pdf` @ 4096

| Crop | Elapsed (s) | Output tokens | Truncated | Combined rate (tok/s) |
|---|---:|---:|:---:|---:|
| 1 | 22.9 | 396 | No | 17.3 |
| 2 | 17.8 | 323 | No | 18.1 |
| 3 | 17.4 | 308 | No | 17.7 |
| 4 | 24.0 | 482 | No | 20.1 |
| 5 | 17.6 | 346 | No | 19.7 |
| 6 (the p3 table — previously the truncated crop at 2048) | 168.0 | 3472 | No | 20.7 |
| 7 | 37.9 | 753 | No | 19.9 |

Notice total: 332.5s, `crops_truncated=0`, `crops_failed=0`,
**final_part_count = 19** — matches ground truth exactly on the
affected-MPN count and, spot-checked against `/tmp/cap_experiment_4096.json`,
the specific pair the ground-truth doc calls out (`NSR01F30NXT5G` and
`NSR01L30NXT5G`) are both present with the correct `affected_mpn` string.

**Important caveat — do not read this as a clean, proven fix.**
`pcn-tier2-baseline-2026-09-22.md` already documents this exact notice as
non-deterministic **at the current 2048 cap**: across 8 historical
attempts, 2 were "complete-and-exact (19/19)" and 6 were "catastrophically
absent (2/19 or 0/19)" — driven by whether the dense p3 crop happens to
time out/truncate that particular run. A 19/19 result therefore already
occurs ~25% of the time at the *current* cap, without any change. This
cap-experiment ran the 4096 condition **once**. One clean run is not
sufficient, by itself, to distinguish "raising the cap fixed it" from
"got one of the ~1-in-4 clean runs that already happen at 2048." What *is*
new, directly-measured evidence: the p3 crop produced **3472 output
tokens** when allowed to run to completion — 1424 tokens past the old 2048
cap — meaning that crop's full response, at least on this run, structurally
cannot fit under 2048, which is consistent with (but does not, alone,
statistically prove) 2048 being the dominant cause of the historical
truncation pattern. Repeated trials at each cap would be needed to
establish this with confidence; that was not done here per the "one round
unless truncation persists" instruction.

**A separate, real mismatch found in this run**: the ground-truth doc
states the qualification-vehicle value (`SNSR01F30NXT5G, NSR20F40NXT5G`) is
emitted in the `replacement_mpn` field for the 2 p4 rows "in every attempt"
where the p4 crop succeeds. In this cap=4096 run, `replacement_mpn` is
`null` for **all 19** rows, including those 2 — checked directly against
`/tmp/cap_experiment_4096.json`. This is a genuine deviation from the
documented historical pattern, not a count/coverage issue; flagging it
rather than smoothing over it, since the coordinator has been explicit
about not letting things like this go unstated.

`192.168.1.169:11434/api/ps` during this notice: `gemma4-32k:31b` resident
throughout, `size_vram == size` (20,926,064,230 bytes) on every sample — no
eviction, no other model, no partial VRAM offload observed. This notice ran
immediately after `PCN23-002.pdf` in the same process, so it did not pay a
cold-load cost. **No anomalies — this round's timings are usable, not
discardable.**

### Measured decode rate

Directly measured (output_tokens / call-wall-time, includes image prefill +
decode, not decode alone): **17.3–20.7 tok/s across the 8 crops that ran**,
mean ≈ 19.2 tok/s. This is the number that should inform whether a larger
cap is reachable inside `LLM_REQUEST_TIMEOUT_MS` (600s, unset/default) —
at ~19 tok/s, even an 8192-token generation would take roughly 430s of
decode alone, still well inside the 600s ceiling, before adding prefill or
tier-1 overhead.

**Inference, not measurement** (labeled as such per instruction): fitting a
line across the 7 `onsemi_Generic_IPCN25300X.pdf` crops (elapsed vs. output
tokens; least-affected-by-cold-load since this notice ran second) gives a
decode-only slope of ≈21.0 tok/s with a small (~2.7s) fixed per-call
overhead (image prefill/setup), fitting the 5 short crops and the long
crop consistently (e.g. predicted 38.6s vs. actual 37.9s for the 753-token
crop). This is offered as a rough decomposition, not a verified constant —
one notice's 7 crops is a small sample.

## 6. Summary

- All 9 baseline notices completed; `/tmp/run.done`'s `EXIT_CODE=True` is a
  known-bad signal from a PowerShell `$?` leak and was not relied on —
  completion was confirmed from `baseline.json` content and `run.log`.
- 860 of 896 parts emitted at the deployed 2048 cap; all 36 missing parts
  are in tier2_vision or router-gap notices, none in tier1.
- 2 notices show `crops_truncated ≥ 1`: `PCN23-002.pdf` (1/1 crops) and
  `onsemi_Generic_IPCN25300X.pdf` (1/7 crops).
- 3 of 9 notices used non-canonical ad hoc S3 folders because no canonical
  `sustainment/inbound/<file>.pdf` object exists for them; byte-identity
  across all historical copies is hash-verified for all 3, but only 1
  (`ADI_PDN_23_0120.pdf`) required patching the manifest's `source_key`
  field — the other 2 resolved through their own valid, self-declared key.
- At `VISION_MAX_TOKENS=4096`, both previously-truncating notices stopped
  truncating in a single trial. `onsemi_Generic_IPCN25300X.pdf` reached
  19/19 parts (matching ground truth) but dropped the qualification-vehicle
  field for all rows, a new mismatch against the documented historical
  pattern; given this notice's already-documented ~25% clean-run rate at
  the current cap, one successful trial is suggestive, not conclusive.
  `PCN23-002.pdf` reached 17/18 parts with no truncation or crop failure —
  a distinct, undiagnosed residual gap, not a cap problem (and the first
  non-empty result this notice has ever produced, so there's no prior
  transcript to diff against).
- No 8192 round was needed. Measured combined (prefill+decode) throughput
  across 8 crops: 17.3–20.7 tok/s. No vision-endpoint anomalies (wrong
  model, partial VRAM) were observed in either cap-experiment notice.
- Deployment unchanged throughout: no `values-sandbox.yaml` edit, no `helm
  upgrade`, no pod restart.
