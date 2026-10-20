# Report — lane 7f — the five header absences are 300s `ExtractHeader` timeouts, and the mfr/doc_id instability is the same defect

2026-10-19. Answers the architect P1 of today, items 1, 2 and 3, from the
authority run published as `docs/corpus-gate/latest.json` (generated_at
`2026-10-18T11:25:31Z`, verdict `fail`).

---

## 1. Attribution: NOT the cluster window. An endpoint timeout on 10-18, turned into an unrecoverable absence by the instrument.

### When the fires ran

| fire | started (UTC) | elapsed | exit |
|---|---|---|---|
| 1 | 2026-10-18T07:00:18Z | 5226.9 s | 0 |
| 2 | 2026-10-18T08:27:25Z | 5343.4 s | 0 |
| 3 | 2026-10-18T09:56:28Z | 5342.8 s | 0 |

The last fire ended and the report was written at `11:25:31Z` on **10-18**. The
incident ia-74 measured (5-10x slow, 13/18 pipeline errors) began **00:06Z on
10-19** — about **thirteen hours after** the last fire finished. The absences are
not in that window.

### No fire lost a document

`rates_by_fire`, all three fires: `documents 10, errors 0, not_applicable 0`.
Every fire processed the whole corpus and exited 0. Nothing was lost in the
*run*; the loss is in the header *pass*.

### Which fire lost which notice — measured, not inferred

The gate echoes every fire log into its own stdout when the verdict is not
`pass`, and the Job pod for that run — `doc-tools-corpus-gate-29871780-x8dc8`,
phase `Failed` because a red verdict exits non-zero — still serves
`kubectl logs`. The echo is the **last 262144 bytes** of a ~430 KB log, so it
covers the final five notices, with **identical coverage in all three fires**
(PCN24-029 partially, then IPCN25300X, PD26044X1, TI, IDT). Within that window
the comparison is sound.

| notice | fire 1 | fire 2 | fire 3 | what the gate reported |
|---|---|---|---|---|
| PCN24-029 | **408** 07:40:45 | **408** 09:08:14 | **408** 10:41:12 | *nothing at all* |
| onsemi_Generic_IPCN25300X | **408** 07:46:22 | **408** 09:13:52 | **408** 10:46:49 | *nothing at all* |
| onsemi_Generic_PD26044X1 | ok 07:58:13 | ok 09:25:43 | ok 10:59:44 | `agree` |
| TI_PCN_20210316000 | **408** 08:05:47 | **408** 09:33:18 | ok 11:05:44 | `ABSENT` |
| IDT_PDN_OV-19-05 | ok 08:25:06 | **408** 09:52:11 | ok 11:21:25 | `ABSENT` |

Every `408` is `Function ExtractHeader:` logged at `[BAML WARN]` followed by
`---ERROR (Timeout (408))---`. Verified **two independent ways** that agree
exactly:

1. the BAML log level per call (`WARN` on the nine failures, `INFO` on the six
   that parsed), and
2. re-running the gate's own `headers_from_log` over each echoed slice: fire 1
   recovers IDT + PD26044X1, fire 2 recovers PD26044X1 only, fire 3 recovers
   IDT + TI + PD26044X1.

So **TI was lost by fires 1 and 2**, **IDT by fire 2**, and PCN24-029 and
IPCN25300X by **all three**.

### The ceiling is 300 s, and the configured bound is 600 s

```
2026-10-18T09:33:18.411 [BAML WARN] Function ExtractHeader:
    Client: HeaderBounded (<unknown>) - 300001ms
    ...
    model: "gpt-oss-128k:120b"   temperature: 0   options: {"num_ctx":8192}
    ---ERROR (Timeout (408))---
    Request timed out
```

Across the three echoed slices:

| client | calls | at the ceiling | max observed |
|---|---|---|---|
| `HeaderBounded` | 15 | **9** | 300008 ms |
| `VisionBounded` | 89 | 2 | 300003 ms |

**Nothing anywhere exceeds 300008 ms.** That is a hard 300 s cut — and it is not
what this repo configures:

- `_header_call_opts` (`plugins/sustainment.py:414`) sets
  `AbortController(timeout_ms=int(os.getenv("LLM_REQUEST_TIMEOUT_MS", "600000")))`,
  and that line has read `600000` since it was introduced in `58fc658`.
- `LLM_REQUEST_TIMEOUT_MS` is set in **neither** pod spec: no env key in the
  serving Deployment nor in the `doc-tools-corpus-gate` CronJob contains
  "timeout" (filtered on key names only).
- `charts/doc-tools/values-sandbox.yaml:1275` reasons explicitly *"against the
  600s `LLM_REQUEST_TIMEOUT_MS` default"*.

So **the configured 600 s bound is inert and the real ceiling is 300 s** — the
same shape already on record for the vision client, now measured for the header
client too. Which layer imposes the 300 s (baml_py's `openai-generic` client
default, or the gateway in front of `LLM_BASE_URL`) is **not** measured here;
what is measured is that nothing in doc-tools asks for 300000.

**15 calls = 5 notices x 3 fires, so there is exactly one header call per notice
per fire. There is no retry.** One 408 loses that notice for that fire outright.

### Onset: between the clean 10-17 run and 07:40Z on 10-18

The 10-17 09:32Z run **passed**, with all ten notices present in its agreement
table (TI and TYC `DISAGREE` on `mfr`, both exempted). 10-18 is the first
published run with any `ABSENT`. So the header endpoint degraded between
10-17 ~09:32Z and the first timeout at 10-18 07:40:45Z — **16 to 23 hours before**
ia-74's 00:06Z 10-19 window. Same kind of fault, earlier phase; not the same
window, and the fire times are the evidence.

### Three instrument defects convert a recoverable timeout into a lost measurement

1. **The gate blocks on a LOG parser, not on the structured record it already
   has.** `run_header_agreement` (`scripts/pcn_corpus_gate.py:254`) runs
   `pcn_header_agreement.py` over `fire*.log`, whose `main` (:388) calls
   `headers_from_log`. Every fire already records `written_header` per notice
   into `corpus_f{n}.json` (`pcn_corpus_run.py:396,463`), and the gate's own
   `headers_from_corpus` docstring calls the log path strictly inferior and
   enumerates its failure modes. A 408 leaves no `NoticeHeader` block in stdout,
   so the log path sees nothing — while the corpus JSON holds what was actually
   written.
   *This fix needs its eyes open:* per item 2, a timed-out fire writes
   `empty_header`, so pointing the check at the corpus JSON converts each
   `ABSENT` into a `DISAGREE` on `mfr`/`doc_id`. That is the correct and
   non-silent outcome — and still a red.
2. **No retry on the header pass.** One 408 is final for that notice in that
   fire.
3. **A notice lost by all three fires vanishes entirely.** `compare` builds its
   notice list as the **union** of the fires' recovered headers, so a notice no
   fire recovered is never printed — not `ABSENT`, not `NOT MEASURED`, not named
   anywhere. On 10-18 that is **4 of 10**: IPCN25300X, PCN23-002, PCN24-029 and
   TYC-PCN-24-210412 (the complement of the 1 compared plus the 5 `ABSENT`).
   Two of them I measured directly as all-three timeouts. **The gate accounted
   for 6 of 10 notices and said nothing whatever about the other four.**

A fourth, about recoverability: the echo cap is 262144 bytes against a 430039 /
432679 / 434187 byte log, so **~40 % of each fire log — the early notices — is
unrecoverable** once the pod is gone. That is why ADI, Diodes and EOL-36 can
only be placed by elimination (ABSENT, so lost by at least one fire and
recovered by at least one), not measured.

---

## 2. The nondeterminism, named: it is the same defect, and it is not sampling

A 408 does not merely fail to record a header — it **writes a different one**:

- the timeout raises, caught by `except Exception` at
  `plugins/sustainment.py:1344`: `header = None`, `needs_review = True`, and a
  doc flag `header extraction failed: ...`;
- `header_d = empty_header(doc_id)` (`sustainment_merge.py:53`) yields
  `mfr ""`, `pub_date ""`, `revision None`, and `doc_id` **seeded from the
  pipeline doc_id** — the key-derived fallback — with `doc_id_extracted = None`;
- `written_header` (`pcn_corpus_run.py:396`) maps `""` back to `None`.

So the written identity half of a timed-out fire is
`mfr = None, doc_id = <pipeline/filename-derived key>`, against
`mfr = "TEXAS INSTRUMENTS", doc_id = "PCN#20210316000.1"` from a fire that
completed. **The identity half is exactly `(mfr, doc_id)`** — so
`identity_half_unstable` on byte-identical input is a *latency-dependent branch*,
not a model that sampled differently.

Corroboration, all from the same report:

- `identity_half_unstable` = [ADI, Diodes, EOL-36, IDT] — a **subset of the five
  `ABSENT`**, and the three that block (ADI, Diodes, EOL-36) are exactly the
  `ABSENT` notices that are not exempted.
- `revision_half_unstable` = **[]**, which is what this mechanism predicts:
  `empty_header` writes `revision None`, and the completed fires also wrote
  `revision None` for every notice recovered above. The half that the fallback
  cannot perturb is the half that is stable.
- `header_correctness` fire 2 is the one with `clean: false` and `exact: 5`
  against 7 and 7 — and fire 2 is the fire that timed out four times.

**The deterministic-extraction promise is intact inside the model call**:
temperature 0, and PD26044X1 — the one notice whose header call completed in all
three fires — `agree`s across all three. The instability enters entirely through
the timeout fallback, which substitutes a filename for an extracted notice
number and a null for a printed manufacturer.

That also makes the cure a code change rather than a prompt or a model change:
a header timeout must not be able to write a key-derived `doc_id` into the
identity triple. Either the pass retries, or a timed-out header is refused
outright rather than filled in.

---

## 3. The pin holds, and a re-fire is the wrong instrument

Condition (3) is **not** met: the absences are not attributable to the cluster
window — thirteen hours clear of it, every fire exit 0, 10/10 documents, 0
errors. By the architect's own test that makes it the instrument, plus an
endpoint that was already degrading a day earlier. So:

- **no pin bump**, and
- **no re-fire.** Three more fires would measure the endpoint's mood on the
  night they run, not whether the instrument can survive a timeout. Nine of
  fifteen header calls timing out is not a condition a repeat run clears; it is
  the condition the instrument has to report honestly and currently cannot.

---

## What I did not do, and what is open

- **Did not re-fire** (above), and did not touch the pin.
- **Did not identify the layer that imposes 300 s.** Measured: the cut is 300 s,
  the configured bound is 600 s, and nothing in doc-tools sets 300000. The
  candidates are baml_py's `openai-generic` client default and the gateway in
  front of `LLM_BASE_URL`. Naming it is the first step of the fix, because if it
  is the client default then a per-client `timeout` key next to
  `AbortController` fixes it in this repo.
- **No code shipped tonight.** The three instrument defects above are specified,
  not landed; defect 1 changes what the gate reports (ABSENT becomes DISAGREE),
  which is a reporting-contract change and wants the architect's eyes first.

### Next

1. Name the 300 s layer, then raise the header bound to the configured 600 s —
   or lower the configured value to the truth, so the two stop disagreeing.
2. Point `run_header_agreement` at `corpus_f{n}.json`'s `written_header` instead
   of the fire logs, and make `compare` enumerate the **declared corpus**, not
   the union of what the fires recovered, so a notice lost by every fire is
   named instead of vanishing.
3. Decide the header-timeout contract: retry, or refuse the field rather than
   writing a key-derived `doc_id` into the identity triple.
4. Behind this: the `mil.ttl` draft (placed as a packet to ia-74), and the
   idempotency second write — still blocked on a permission rule, see below.

### Blocked on a permission rule (for Chris)

The idempotency write, approved twice, is refused by the auto-mode classifier on
the `kubectl exec` shape — the **read-only** fingerprint was refused as well, so
it is not the mutation that trips it. The two literals, against pod
`doc-tools-557cc96c6b-7v2z2` in namespace `sandbox`:

```
kubectl exec -n sandbox doc-tools-557cc96c6b-7v2z2 -- python /tmp/idem_fingerprint.py
kubectl exec -n sandbox doc-tools-557cc96c6b-7v2z2 -- python /tmp/idem_relaunch.py --launch ingress-user__xml__bdf04c5fce2188e10ed390a4c6d7b77ff28071a80358839cfec8035e0e43b6c4__DMC-ODMRAD-A-34-10-01-00A-941A-A_001-00_EN-US.xml
```

Both scripts are already staged in the pod at those paths. The partition key
above was read off the live instance tonight. BEFORE is on record (total 157,
module 37 over 7 subjects, bnodes 0/0, sha256 `5f378a2da5443ec3`) and the
prediction is registered: every field identical after the second write; a
changed sha256 at an unchanged 157 is the defect.
