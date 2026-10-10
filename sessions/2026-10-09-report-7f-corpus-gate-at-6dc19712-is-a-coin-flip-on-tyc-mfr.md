# report — 7f — item 4: the corpus is 898/898 x3, and the gate is a COIN FLIP on one TYC field

to: doc-tools owners, ia-01/lane/01
date: 2026-10-09
order: "4. Corpus gate: run the full PCN/PDN corpus; any new identity or
currency miss gets a fixture and a failing test before a fix."

## Verdict

**FAIL — exactly one blocking condition**, and it is not an extraction defect.

```
TYC-PCN-24-210412.pdf: written header does not match ground truth
  - fire 1: mfr (distractor)
```

Everything else is clean:

| fire | exit | elapsed_s | exact/gt | spurious | missing | malformed |
|---|---|---|---|---|---|---|
| 1 | 0 | 1883.1 | 898/898 | 0 | 0 | 0 |
| 2 | 0 | 1814.1 | 898/898 | 0 | 0 | 0 |
| 3 | 0 | 1887.8 | 898/898 | 0 | 0 | 0 |

Per-notice defects: none in any fire. `crops_near_cap` 0/9, `crops_row_short`
0/9. `needs_review` 1/9 and `text_layer_degraded` 1/9 — both TYC.

## How it was run, and why not as a Job

Pod `doc-tools-55d655b547-5k8mn`, ns `sandbox`, three fires 04:30/05:01/05:32Z.
Credentials never materialized locally. `PROMPT_SOURCE=file` read from **the
pod's own env**, not the chart.

**This is the FIRST measurement of the current pin.** Measured digest
`6dc19712`, and the identity table reads **match** against `pods` — the pod's
`imageID` equals the CronJob's pin. Yesterday's PASS measured `c39c4092`, a
different image, so 10-08 and 10-09 are **not** a same-bytes comparison.

`DOC_TOOLS_IMAGE` and `PCN_GATE_EXPECT_IMAGE` are **unset in that pod**, which
is the known cause of a null `measured_image`, so both were passed explicitly.

**I did not use `kubectl create job --from=cronjob/doc-tools-corpus-gate`.** Its
container args are `pcn_corpus_gate.py --run ; ... ; pcn_gate_publish.py` — it
**publishes unconditionally**, from a `PCN_GATE_PUBLISH_TOKEN` pending rotation,
into a `report-{date}.md` that a second run of the same day overwrites. A
hand-created Job would have pushed a report branch and, if red, frozen every
merge. The exec environment had that token **unset** and an explicit
`--out-dir`, so nothing could publish and no authority report was touched.
Artifacts stay in `/tmp/pcn-gate-manual/` inside that pod; nothing was written
under `docs/corpus-gate/`.

## The finding: the blocking mechanism is newly BITING, not newly BROKEN

`mfr` on TYC flipped across the three fires. **CORRECTED 2026-10-09 after the
ruling, by reading the three `corpus_f{1,2,3}.json` artifacts rather than the
gate's summary:** the flip in THIS run was `TE` (fire 1) against `TE
Connectivity` (fires 2 and 3) — **not** `TE Connecvity`, which is the degraded
text layer's own spelling and the one EARLIER runs produced. It does not appear
in this run at all.

That matters, because `TE` is the **logo wordmark**, which renders as `TE` over
`connectivity`. Fire 1 did not read a corrupted text layer; it read a different,
real part of the page. Ground truth named both `TE` and `TE Connecvity`
**distractors**, so one of three fires reading the logo was scored a trap.

Also worth recording from those same artifacts: **every other WRITTEN header
field is identical across all three fires, and every one is the page's value** —
`pub_date` 2024-06-07 (the PCN Date, not the portal's 2024-06-10 print stamp)
and `doc_level_ltb_date` 2024-06-06 (the Last Order Date row, not the adjacent
2024-06-07 Last Ship row). That is the three-fire seal PR #32's LTB candidate
supplier never got; it passes.

**But "no fire took the distractor" would be wrong, and the earlier draft of
this report said it.** See CORRECTED AT THE RAW LAYER below: the extraction took
the `pub_date` distractor in all three fires and the supplier replaced it every
time. The written values are clean because something fixed them, not because
nothing went wrong.

What changed is the **gate**, not the extraction:

- On **2026-10-01** this identical condition was reported and carried the
  suffix `— exempted: needs_review=True in all three fires`.
- In **this run** the same condition sits under `## Blocking` with **no
  exemption**, while the *disagreement* and the *identity-half instability* for
  the same notice ARE still exempted on `needs_review`.

That is the correctness exemption having been narrowed while the disagreement
exemption still uses the broad predicate. So the gate now reds whenever **any
one of three fires** happens to write the distractor.

**Therefore yesterday's PASS was luck, not a fix, and this FAIL is not a
regression from the new pin.** The three nightlies before it (10-05/06/07) were
also FAIL, but each on a *different* mechanism — a Diodes "undeclared silent
write" — and none of them carried a ground-truth correctness block at all.

## Nothing new, so no fixture and no failing test — **SUPERSEDED, see RULED below**

The order's clause is "any **new** identity or currency miss gets a fixture and
a failing test before a fix." Checked against every committed report rather
than asserted:

- **`mfr` distractor on TYC** — not new (2026-10-01, and flips through
  10-05/10-07/10-08).
- **`doc_level_ltb_date_source` instability** — not new. It churns between
  `'06-JUN-2024'`, `'-2024'` and `'-2024\n[Unca'` in **every** recent report;
  the VALUE agrees, only the provenance snippet moves, and `[Unca` is a clipped
  `UncategorizedText` marker.
- **Parts** — 898/898 in all three fires, so no parts miss to fixture.

So I wrote no fixture and no test, and **no fix**. Writing one here would be
inventing a defect to match a verdict.

**SUPERSEDED.** The ruling found the weakness I had argued was absent: a 1-in-3
distractor pick IS an extraction weakness, and the run that passed was luck. The
fixture and the test exist now; see RULED below.

## What this costs, and the decision it needs

A coin-flip gate on a field whose correct value the page itself corrupts means
the nightly will red on an unpredictable fraction of nights with nothing wrong
downstream of it. Two candidate directions, neither mine to pick:

1. ~~**Exempt `mfr` on TYC specifically**~~ — **OVERRULED.** "Corpus gate: no
   exemption. A 1-in-3 distractor pick on TYC mfr is a real extraction weakness,
   not gate noise — yesterday's PASS being luck is the finding."
2. **Supply the value instead of refusing it** — the witness route. **RULED IN**,
   with the 0/3 diagnosed: it was the comparator, not the witness.

Related and still open: narrowing the broad `needs_review` **disagreement**
exemption would turn `verdict` red on TYC the day it lands — which this run
shows is already half-true for correctness.

## Not claimed

- Not published anywhere; no PR, no branch, no roll. The report lives in the
  pod and in this file only.
- `--run` was used, so the seal is measured rather than assumed.
- This says nothing about items 1 and 3, whose full local suite has not yet run.


## RULED 2026-10-09, and what was built

The recommendation above (exempt `mfr`) was **rejected**. The ruling: a 1-in-3
distractor pick is a real extraction weakness, the gate keeps its teeth, and the
comparator was what was wrong. Verdict stays **advisory for today**; nothing
blocks the demo.

### (a) An accepted-verbatim set, compared canonical-after-alias

`scripts/pcn_ground_truth.json`, TYC `mfr`: `accepted` is now
`["TE Connectivity", "TE Connecvity", "TE"]`, canonical `TE Connectivity`. Its
`not` block is kept and **emptied** — an mfr distractor is still possible (a
manufacturer named nowhere on the page), and an empty block records that the
question was asked rather than deleted.

`scripts/pcn_score.py` compares **canonical-after-alias, never raw string**:
`accepted_forms()` returns the accepted spellings canonical-first, and a written
value is resolved to its canonical form before anything else. Deliberate
boundaries, each with a test:

- Alias resolution runs **before** the distractor scan, so a value ground truth
  accepts can never be reported as a trap.
- The alias match is **exact-string**. A case- or whitespace-mangled form of an
  accepted spelling falls through to the shape check and is still
  `misformatted` — a failure. Folding here would have made the accepted set a
  wildcard.
- A new `alias` status is a **pass** but is counted apart from `exact`, so a
  report never has an `exact` short of `fields_scored` with no failure beside
  it, and a fire answering by logo rather than by heading stays visible.
- Ground truth that puts one spelling in **both** `accepted` and `not` **raises**
  and names the field. There is no right answer to that contradiction, so it is
  not resolved by precedence.
- A declared `accepted` block that omits its own `value` **raises**.

One adjacent defect fixed in passing: `pcn_corpus_gate.py` carried its **own
hardcoded copy** of the five failure statuses, so a failure class added to the
scorer would have been scored there and silently ignored by the gate — a new way
to fail that blocks nothing. It now reads `pcn_score.HEADER_FAILURES`, and a
test pins that it does.

### (c) The three fire outputs are a fixture; the flip is a test case

`tests/fixtures/pcn/tyc-mfr-three-fires-2026-10-09.json` — the three
`written_header` values **verbatim** from `corpus_f{1,2,3}.json` in pod
`doc-tools-55d655b547-5k8mn`, with the pin, the fire times and the source paths.

`tests/test_header_alias_compare.py` — 20 tests. The load-bearing ones:

- Fire 1 scores `alias`, fires 2 and 3 score `exact`. The fix does not work by
  loosening everything into one bucket.
- **No fire has any header failure over the whole block**, not just `mfr`. Had
  one taken the `pub_date` or LTB distractor, exempting `mfr` would have left
  the run red anyway — the thing a per-field fix hides.
- The flip is **unanimous after canonicalization**: three written strings, one
  canonical answer, where before the same three fires produced two verdicts.
- A **raw-string comparator still fails exactly fire 1** — the change pinned
  from the other side, so a regression to raw string cannot pass quietly.
- `TE Connecvity` passes although no fire wrote it, so the day one does there is
  no fourth red on the same field.
- What must still fail, each asserted: an unaccounted manufacturer (`wrong`), a
  mangled accepted spelling (`misformatted`), a real declared distractor on
  `pub_date` (`distractor`, with its reason), and nothing written (`absent`).

`42 passed` over this file plus `tests/test_pcn_score.py`.

### (b) The witness supplier — in progress

Ruled: build the region-crop supplier with the **same alias compare**; `mfr`
requires witness corroboration; a distractor without witness agreement is
**null + review, never the distractor**. The 0/3 is diagnosed — the witness read
the logo correctly and the comparator called two correct readings a
disagreement — which is why this is now a supplier rather than a filter.

### Still owed to whoever narrows the exemptions

The `mfr` distractor that the SCORER reported is resolved by (a) — fire 1's
`TE` now scores `alias`, and the full local suite is green at 1386 passed, 11
skipped.

**I am not claiming this run goes green**, for a reason measured below: ruling
(b) withdraws an `mfr` the witness does not corroborate, and what the crop read
for `mfr` in fire 1 is **not in evidence** in any artifact that run produced. If
the crop read `TE`, fire 1 is a pass; if it supplied nothing, (b) withdraws the
value and the field scores `absent`, which is a failure too. That is decided by
re-running, not by reasoning.

The broad `needs_review` **disagreement** exemption is untouched and still uses
the wide predicate, so narrowing it remains a live change with a different blast
radius.


## CORRECTED AT THE RAW LAYER, same day

Everything above about the flip was read from the corpus JSON, which holds what
was **written**. Parsing the three fire logs with the gate's own
`pcn_header_agreement.headers_from_log` gives what the model actually
**returned**, and it does not say the same thing.

| field | raw, fire 1 / 2 / 3 | written, fire 1 / 2 / 3 |
|---|---|---|
| `mfr` | `TE` / `TE` / `TE` | `TE` / `TE Connectivity` / `TE Connectivity` |
| `pub_date` | `2024-06-10` x3 | `2024-06-07` x3 |
| `doc_level_ltb_date` | `2024-06-06` x3 | `2024-06-06` x3 |

Three findings follow, and the first two reverse claims made above.

**1. The model never sampled on `mfr`.** Raw `mfr` is `TE` in all three fires.
The written flip is produced *after* extraction, by the trust logic: the crop
supplied the fuller name in two fires out of three. So "the model sometimes reads
the page and sometimes the corrupted text layer" was wrong — the header pass read
the logo wordmark consistently, and the nondeterminism is in **what the crop
read**. The ruling's instruction to build the supplier with an alias compare is
right either way; its diagnosis is now sharper than when it was written.

**2. The raw `pub_date` is the declared distractor in all three fires**, and the
supplier replaces it with the correct `2024-06-07` every time. This is the
witness route working, on a field nobody was arguing about. It also retires an
earlier finding that all three fires *wrote* `2024-06-10`: not true at this pin.

**3. The run's actual agreement failure was never `mfr`.** `header_agreement.log`
from the run reads, across all nine notices, exactly one red:

```
TYC-PCN-24-210412.pdf                        DISAGREE
      doc_level_ltb_date_source '06-JUN-2024' | '06-JUN-2024' | '-2024\n[Unca'
```

Fire 3's **citation** is truncated to twelve characters, starting mid-token, with
a newline and the head of an element marker (`[Unca...`, i.e. UncategorizedText)
bled into it. The **value** `2024-06-06` is correct in all three fires. So this
run had **two independent reds** — the scorer on fire 1's `mfr`, the agreement
instrument on fire 3's citation — and ruling (a) addresses only the first. The
mechanism behind the truncation is **not diagnosed**; it is recorded in the
fixture so the next run has a before. Per the standing rule that a new miss gets
a fixture and a failing test before a fix, the fixture exists and the fix does
not.

### What I built on the agreement comparator, and then reverted

I extended canonical-after-alias into `scripts/pcn_header_agreement.py` as well,
on the reading that "never raw string" should apply to the cross-fire comparator
too. **Reverted before commit, on measurement:**

- Raw `mfr` agreed 3/3, so there is no observed cross-fire `mfr` disagreement for
  it to fix.
- `mfr_source` equals `mfr` in every fire, and the gate compares both. A future
  fire reading the heading would differ on *both*, and only one has an accepted
  set — so the notice would still DISAGREE and the change would not even work in
  the case it was built for.
- The ruling's words scoped canonical-after-alias to ground-truth comparison,
  which is the scorer. Extending it was my reading, not a quotation.

`scripts/pcn_header_agreement.py` and its test file are byte-identical to `main`.
One piece of that work is kept, because today's real DISAGREE line justifies it
on its own: the gate renders those printed values into a **markdown table**, and
the line above contains two `|` separators, so the row describing the only red in
the run is the row that breaks the table. The value is now escaped.

### Two defects found in review, both fixed

- **`pcn_corpus_gate.py` carried its own hardcoded copy of the five header
  failure statuses.** A failure class added to the scorer would have been scored
  there and silently ignored by the gate. It now reads `pcn_score.HEADER_FAILURES`
  and a test pins that it does.
- **Ruling (b)'s check was wired BEFORE the refusal**, where it pre-empted it: on
  any degraded document `mfr` ended up withdrawn either way, so the outcome
  looked right while the reason a reader is given was the wrong one and the
  refusal's own explanation never appeared. Three assertions in
  `tests/test_second_witness_wiring.py` caught it, all three on the reason and
  none on the value. Moved after the refusal, so it judges values that survived
  it.

### An instrumentation gap, and the ask it implies

The supplier's reason strings reach neither the fire logs nor the corpus JSON:
`grep -a` for `region witness` and for `header.mfr` across all three fire logs
returns nothing. So **the gate's verdict on `mfr` cannot be explained from the
gate's own artifacts** — which is precisely why I cannot say whether fire 1 goes
green under (b). Whoever next touches the gate should carry the header trust
reasons into the per-fire artifact; it is a small change and it is the difference
between a verdict and an explained verdict.
