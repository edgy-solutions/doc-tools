# 7f — the narrowing holds on the corpus; the tenth `mfr` is an aborted header pass, not a precedence defect

**Order:** *"Fix on #162 before it merges, re-fire, and add mfr ground truth for all ten corpus notices — a gate that reads clean on 3 of 10 isn't reading."* Parts 1, 2 and 4 landed earlier today (`5d766c0`, `b5a4bca`). This is part 3, the re-fire, and the `mfr` field reported across the ten — now scored on ten rather than three.

## What was fired

| | |
|---|---|
| branch | `7f/header-identity-precedence` at `b5a4bca` |
| dispatch run | [40155057765](https://github.com/edgy-solutions/doc-tools/actions/runs/40155057765) — `build-and-push` **success** |
| pushed index digest | `sha256:ba9147b1b4b27dca75a97d3631e08ffb30a558f3c9451460c1a080ef87366ec2` |
| pod `imageID` | `ghcr.io/edgy-solutions/doc-tools@sha256:ba9147b1b4b27d…66ec2` — **identical**, read off `containerStatuses[0].imageID`, not `.image` |
| job | `mfr-fire-7f` in `sandbox`, derived from `cronjob/doc-tools-corpus-gate` in memory only (its env is inline and carries three live credentials), `backoffLimit: 0`, deleted after the read |
| artifacts | `/tmp/mfr-fire/{corpus_f1,score_f1,seal_f1}.json` + `fire1.log`; no publisher and no `--out-dir`, so `docs/corpus-gate/latest.json` is untouched |
| result | `rc=0`, one fire, 03:16Z → 04:06Z (50 min) |

The run's overall conclusion is `failure`, and that is **not** this branch: the only red job is `corpus-gate-verdict`, which reads the *published* authority report (blocking on fire 2 of a much older run). `tests`, `corpus-gate`, `verify-image-pin` and `telemetry-contract` are green.

## The narrowing, measured on the ten

`document_tier` and `document_displaced_model` are the fields `5d766c0` added. This is the whole point of the commit in one table:

| document | written `mfr` | origin | document arm | tier | displaced the model | model | agrees |
|---|---|---|---|---|---|---|---|
| `ADI_PDN_23_0120.pdf` | `Analog Devices, Inc.` | model | — | — | False | `Analog Devices, Inc.` | — |
| `Diodes_PCN_2683_Rev1_EOL.pdf` | `Diodes Incorporated` | model | — | — | False | `Diodes Incorporated` | — |
| `EOL-36_BYV34-400,-BYV34-500.pdf` | `SEMELAB` | **document** | `SEMELAB` | **gazetteer** | **True** | `SEMELAB` | True |
| `IDT_PDN_OV-19-05.pdf` | `Integrated Device Technology, Inc.` | model | — | — | False | same | — |
| `PCN23-002.pdf` | `Mini-Circuits` | model | — | — | False | `Mini-Circuits` | — |
| `PCN24-029.pdf` | **`Mini-Circuits`** | model | **`QUESTIONS`** | heuristic | **False** | `Mini-Circuits` | False |
| `TI_PCN_20210316000.pdf` | `TEXAS INSTRUMENTS` | model | — | — | False | `TEXAS INSTRUMENTS` | — |
| `TYC-PCN-24-210412.pdf` | `TE Connectivity` | model | — | — | False | `TE Connectivity` | — |
| `onsemi_Generic_IPCN25300X.pdf` | **none** | — | — | — | False | `""` (pass aborted) | — |
| `onsemi_Generic_PD26044X1.pdf` | **`onsemi`** | model | **`Europe`** | heuristic | **False** | `onsemi` | False |

The two clause-1 defects the last fire found are fixed, and fixed in the shape the ruling specifies rather than by suppressing the arm:

- `PCN24-029` — the arm still reads `QUESTIONS` off `[Title] QUESTIONS?`. It is `heuristic`, so it **does not displace**; `Mini-Circuits` is written, `agrees: False`, `needs_review` with both values in the reason.
- `onsemi_PD26044X1` — the same with `Europe` off `[UncategorizedText] Europe:`; `onsemi` is written.
- `EOL-36` — `SEMELAB` is a **gazetteer** reading, so it keeps primacy and `document_displaced_model: True`. The one notice that *should* be document-primary still is.

Last fire wrote `QUESTIONS` and `Europe` into the graph as manufacturers. This fire does not.

## The header score, now reading ten notices

```
HEADER SCORE 13 / 16 established fields exact, over 10 of 10 notices with ground truth
```

13 `exact` + 1 `alias` + 1 `correctly_absent` = **15 of 16 pass**. `notices_with_gt` 3 → 10, `fields_scored` 9 → 16, exactly as `b5a4bca` intended.

| status | field |
|---|---|
| `exact` ×13 | ADI, Diodes, EOL-36, IDT (`mfr`+`pub_date`+`doc_level_ltb_date`), PCN23-002, PCN24-029, TI `pub_date`, TYC (`mfr`+`pub_date`+`doc_level_ltb_date`), onsemi_PD26044X1 |
| `alias` (PASS) | `TI:mfr` wrote `TEXAS INSTRUMENTS`, canonical `Texas Instruments Incorporated` — the logo wordmark, read verbatim |
| `correctly_absent` (PASS) | `TI:doc_level_ltb_date` |
| **`absent` (FAILURE)** | **`onsemi_Generic_IPCN25300X:mfr`** — nothing written, page says `onsemi` |

So the header block is `clean: false` on this fire. **That is the instrument working, not a regression**: no `mfr` ground truth existed for this notice until `b5a4bca`, and the previous fire — which wrote `onsemi` here from the model — reported `clean: true` while writing page furniture on two other notices.

## The one failure is clause 3, not clause 1

`onsemi_Generic_IPCN25300X` wrote no `mfr` because **the header pass died**:

```
2026-10-25T03:35:45.903 [BAML WARN] Function ExtractHeader:
    Operation cancelled: Operation cancelled
header trust: the header pass failed and the text layer yields no value for:
  doc_level_ltb_date, mfr, pub_date — absent, not defaulted
header.mfr not written: the header pass returned none and the document does not name one itself
```

`model_value: ""`, `document_value: null`, `origin: null`, `needs_review: True`, `doc_id` still `IPCN25300X` from the text layer. That is clause 3's prescribed shape, and the narrowing is not implicated: with **no** model value the narrowing does not apply, and there was no document reading to write either.

Why no document reading on a page that prints the name: the arm needs a **standalone element of an accepted type**. This notice prints `onsemi` only inside prose (`onsemi is notifying it customers…`, `onsemi Sites External Foundry/Subcon Sites`) and as the garbled logo alt `[Image] ONSEM.`. Neither is a reading the arm will take, which is also why ground truth declares `ONSEM.` a distractor.

The cancel carries no duration and no prompt in the log block, and nothing in the persisted record carries a time either — `stats` held no header timing at all, and the reason string is the time-free `header pass failed: AbortError`. **CORRECTED 2026-10-24: this is our own 90 s `AbortController`, not an instant abort.** I first read it as instant because the warning sits beside the notice banner — and that banner line carries no timestamp. By subtraction: the last timestamped line before it is `03:34:15.694` (the previous notice's `ExtractParts`), the cancel is `03:35:45.903`, a **90.209 s** gap against `HEADER_TIMEOUT_MS_DEFAULT = 90_000`. Not a client disconnect, not a sibling task-group cancel, not a shared token — see #165, which records the elapsed, the bound and a classified origin on every pass and retries a cancelled one once. It is intermittent: the 2026-10-24 fire on the previous image answered `onsemi` for this notice. **A single fire cannot distinguish a cut from a recall miss**, and the gate takes three fires for exactly that reason.

## The rest of the fire

- **Parts: 522 / 522 exact** over 10 notices, 0 spurious, 0 missing, 0 malformed. `needs_review` 10 of 10, `crops_failed` 0, `text_layer_degraded` 3 of 10 (TYC, TI, IDT — unchanged).
- **Crop seal:** 37 tables, 2 stored cut (TI, IDT), 17 cut words, 0 repaired, 0 errors. The known stochastic clipping; `rc=0`.

## What this does and does not establish

- The narrowing behaves as ruled on all ten, and the two measured defects are gone. **Parts 1–4 of the order are complete.**
- It does **not** establish a clean header gate. One of ten notices lost its `mfr` to an aborted header pass on this fire, and the gate needs three fires to rule on whether that is instability or recall.
- `_identity_values_agree` still compares `mfr` on `_name_key` equality, so `TEXAS INSTRUMENTS` vs `Texas Instruments Incorporated` reads as a disagreement and spends a `needs_review` the score calls a PASS. Reported, not fixed; `mfr_agreement.readings_agree` is the right instrument.

Artifacts kept out of the tree, under `scratchpad/`: `n2_corpus_f1.json`, `n2_score_f1.json`, `n2_seal_f1.json`, `n2_fire1.log`, `n2_report.md`.