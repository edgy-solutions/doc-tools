# 7f — ExtractHeader IS the fleet model, and header identity has no text-layer primary

to: the architect, via Chris
from: doc-tools/lane/7f
date: 2026-10-19 (cluster timestamps are UTC, so the nightly evidence reads 10-19/10-20)

## Answer in one line

Yes. `mfr`, `doc_id`, `pub_date` and `revision` come from a model call on the
fleet header endpoint, as the **primary and only** source. The ruling is
currently implemented for exactly one header field, `doc_type`.

## 1. The call

| layer | what it is |
|---|---|
| BAML function | `ExtractHeader(doc: string, system_instructions: string) -> NoticeHeader`, `baml_src/sustainment.baml:73`, declared `client LLM`. Its own comment: *"Pass 1: header fields, text-only, on gpt-oss (client LLM)"* |
| runtime client | `_header_call_opts()` (`doc_tools/plugins/sustainment.py:395`) registers `HeaderBounded` as provider `openai-generic` and calls **`cr.set_primary("HeaderBounded")`** — the declared `LLM` block is overridden at call time, not in the `.baml` file |
| endpoint / model | `LLM_BASE_URL` + `LLM_MODEL`; measured in the logs as **`gpt-oss-128k:120b`** |
| sampling | `temperature = HEADER_TEMPERATURE = 0` (`:238`), no seed, optional `num_ctx` passthrough |
| call site | `_extract_header()` (`:536`), one call per notice; the prompt is the dynamic prompt plus `render_candidate_block(ltb_candidates(full_text))` |

It is a **text-only** pass (no image), so this is not the vision client. It
returns the whole `NoticeHeader` class — `doc_id`, `doc_type`, `revision`,
`pub_date`, `mfr`, `mfr_parent`, `categories`, `summary`,
`doc_level_ltb_date`, `impacted_parts`. **The identity half `(mfr, doc_id)` is
two of its fields.** So the timeout and the cross-fire instability are the same
event, which is what the 10-18 run showed.

## 2. The timeout

| | value | source |
|---|---|---|
| configured | **600 000 ms** | `AbortController(timeout_ms=int(os.getenv("LLM_REQUEST_TIMEOUT_MS", "600000")))`, `:413` |
| set by env | **nothing** | no key containing "timeout" in the serving Deployment or the `doc-tools-corpus-gate` CronJob; the literal has read `600000` since `58fc658` |
| observed cut | **300 001 – 300 008 ms**, then `---ERROR (Timeout (408))---` | 10-18 authority run, 9 occurrences |
| healthy p100 | **36 300 ms** | 10-19 nightly, 15 of 15 calls completed, range 19 274 – 36 300 ms |
| fire budget | **2 794 – 3 201 s** per fire | 10-19 per-fire table |

So the effective bound is **not** the configured one, and it is **not** well
under the fire budget: 300 s is ~8x the healthy worst case and ~10 % of a whole
fire. Nine of them on 10-18 is ~2 700 s — about one fire's entire runtime spent
waiting on calls that returned nothing. **Which layer imposes the 300 s is
still not measured** (baml_py's `openai-generic` default and the gateway in
front of `LLM_BASE_URL` are both live candidates); it needs a probe against the
endpoint, not a code read. The same ceiling was previously measured on the
vision client, so a shared layer is the leading hypothesis.

**There is no retry.** Every notice in the visible log window shows exactly one
`Function ExtractHeader:` call per fire.

## 3. Which notices hit the fallback

**10-18 authority run — 9 fallbacks:**

| notice | fire 1 | fire 2 | fire 3 |
|---|---|---|---|
| PCN24-029 | 408 | 408 | 408 |
| onsemi_Generic_IPCN25300X | 408 | 408 | 408 |
| TI_PCN_20210316000 | 408 | 408 | ok |
| IDT_PDN_OV-19-05 | ok | 408 | ok |
| onsemi_Generic_PD26044X1 | ok | ok | ok |

**10-19 nightly — zero.** 15 of 15 header calls completed in 19–36 s, and the
log contains **no** `header pass failed` / `header extraction failed` line at
all. The endpoint was healthy by then.

### What the fallback does

`ExtractHeader` 408 -> `except Exception` (`:1344`) appends
`header pass failed: ...`, appends a doc flag, and sets **`needs_review = True`**
-> `header_d = empty_header(doc_id)` (`utils/sustainment_merge.py:53`) ->
`mfr ""`, `pub_date ""`, `revision None`, `doc_id_extracted None`, and
**`doc_id` seeded from the pipeline doc_id** (the filename-derived key).
`written_header` then maps `""` to `None`.

So half the ruling already holds — **the fallback does mark `needs_review`** —
and half is inverted: the fallback does not fall back to the text layer, it
writes a **filename** into the identity triple, where a consumer cannot tell it
from an extracted notice number.

## 4. Where the ruling stands against the code

Measured, field by field. The header pass is followed by a trust pipeline
(`:1503-1527`), so "the model is primary" needs the detail:

| field | text-layer primary today? | what actually decides it |
|---|---|---|
| `doc_type` | **YES** | `header_trust.doc_type_from_titles(headline_candidates(elements))` — a genuine text-layer derivation with a source |
| `mfr` | no | model; then `refuse_field_label_echoes`, `refuse_unsourced_header_values`, `require_mfr_witness_agreement` |
| `doc_id` | no | model; filename on fallback |
| `pub_date` | no | model; refusals only |
| `revision` | no | model; refusals only |
| `doc_level_ltb_date` | partial | `ltb_candidates(full_text)` extracts candidates from the text layer, but they are rendered into the **prompt** as a candidate block — the model still chooses |

Two structural points for the ruling:

1. **The post-passes fix precision, not recall.** They refuse, withdraw and
   corroborate. None of them can *produce* an `mfr` the model did not return —
   so a 408 cannot be repaired downstream.
2. **The one supplier arm is vision, not the text layer, and it is gated off on
   a healthy document.** `supply_header_from_regions`
   (`utils/sustainment_header_trust.py:578`) returns immediately unless
   `text_layer_degraded` **and** a region witness exists, and its readings come
   from image crops. On the 10-18 timeouts the text layer was *fine*, so the arm
   was inert by design. It is also itself a model call, on the client that took
   the only 408 in the 10-19 run.

**So implementing the ruling is new work, not a reordering**: there is no
text-layer extractor for `mfr`/`doc_id`/`pub_date`/`revision` in this repo to
promote. `ltb_candidates` is the shape to copy for a real text-layer extractor
with offsets and a source, and `doc_type_from_titles` is the shape to copy for a
derivation that already carries its own provenance.

## 5. The nightly corpus-gate pod Error — same instrument, different cause

`doc-tools-corpus-gate-29873220-hntrx`, `Error`. **The Error is the instrument
reporting a red**: the gate exits non-zero on a non-pass verdict, so a red
verdict always leaves a `Failed` Job and an `Error` pod. Not a crash.

Different cause from 10-18:

- **No absences.** Every notice was measured; the agreement table is complete.
- **No header timeouts.** 15/15 calls completed, 19–36 s, zero fallbacks.
- All three fires **exit 0**, **522/522 parts, 0 spurious, 0 missing, 0
  malformed**, 2 794 / 3 014 / 3 201 s. The parts gate is still met.
- Measured digest `sha256:ac853308...`, **matches pods**.
- The single `Timeout (408)` in the entire run is **`VisionBounded` /
  `TranscribePage` on page 2** — `[SustainmentPlugin] TranscribePage failed on
  page 2: ... this page will not corroborate any header value`. That is the known
  voided-witness path, on the vision client, not the header client.
- **The blocker is one condition:** `TYC-PCN-24-210412.pdf` written header does
  not match ground truth — *fire 3: mfr (absent), pub_date (distractor)*. The
  needs_review exemption covered the header **disagreement** and the
  **identity-half instability**, and did **not** cover **correctness** — the
  narrowing working as intended.

Note what that TYC line means given section 3: fire 3 had **no** header timeout,
so TYC's `mfr` came back absent from a call that **succeeded**. That is a recall
miss on a damaged text layer (TYC is the notice whose text layer drops `ti`),
and its page-2 witness was the 408 — so the one arm that reads TYC correctly was
voided in the same fire. Two independent faults landing on the same notice.

## 6. What I did not measure

- **Which layer cuts at 300 s.** Needs a direct probe against the endpoint with
  a request known to exceed it. Not inferable from this repo.
- **Whole-fire header tallies.** The gate echoes only the **last 262 144 bytes**
  of each ~440 KB fire log, so every per-fire count here covers the visible
  window (the last 5 notices per fire), not all 10. **This corrects a number in
  last night's report**: the "15 calls = 5 notices x 3 fires" figure is 15 calls
  *in the echoed window*, not 15 in the run. The no-retry finding is unaffected —
  a retry would appear as a second call on a notice that is visible.
- Whether the 300 s ceiling is per-request or per-connection.

## Next, in the order I would take it

1. **Probe the 300 s layer** and reconcile the bound, then set an explicit header
   timeout well under the fire budget. A bound nobody set is not a bound.
2. **Decide the header-timeout contract.** Today a 408 writes a filename into
   `doc_id`. Refusing the field (leaving it null and marked) is strictly better
   than inventing one, and is a small change; a retry is the other option.
3. **Then the text-layer primary** for `mfr`/`doc_id`/`pub_date`/`revision`,
   modelled on `ltb_candidates` + `doc_type_from_titles`, with the model demoted
   to a marked fallback. This is the ruling, and it is net-new extraction code.
4. Point the agreement check at `corpus_f{n}.json`'s `written_header` and make
   `compare` enumerate the declared corpus (the two instrument defects from last
   night; they change ABSENT into DISAGREE, a reporting-contract change).

**No pin bump** — condition 3 of the P1 is still unmet, and the live verdict is
red on TYC correctness. **No re-fire**: 10-19 already supplied the
healthy-cluster comparison a re-fire would have been run to get.
