# Report to 7f — the pin was the unwedge; nightly → pin → roll → fires → report

**Sequence as ordered, in order.** Nightly first, then the pin, then the roll,
then three fires, then this report.

## 1. The nightly, READ rather than assumed

07:00Z on the superseded pin `c8dce84a`:

- parts **898/898 exact, three fires out of three** — zero spurious, zero
  missing, zero malformed
- header correctness **3/3 and clean, three out of three**
- verdict **FAIL**, on one blocking condition

The blocking condition is the `Diodes_PCN_2683_Rev1_EOL` `doc_id`. Across the
three fires it read `PCN-2683` | `PCN #: 2683` | `PCN-2683`. **Fire 2 leaked the
field LABEL into the value**, on byte-identical input, and `needs_review` was not
set True. Stochastic sampling. It is the same defect CLASS the TI work addressed
on the parts side, and per the standing ruling on TYC `mfr` it is a real
extraction weakness, not gate noise — so it is NOT exempted. Flagged for an
order, not fixed unordered.

**2026-10-09 was not a red.** That night's verdict **PASSED**; the Job exited 1
on `PUBLISH FAILED: PATCH .../git/refs/heads/corpus-gate/nightly -> HTTP 504`. A
publish failure and a measured red share an exit code, which is why three
consecutive failed Jobs had to be opened one at a time rather than counted.

## 2. THE FINDING: the repo was wedged, and the pin was the only key

This was not merely the next step in a sequence. Before touching the pin I read
the required check's failing assertion on #103, and it reframed the task.

`tests/test_corpus_gate_guard.py` asserts the committed report's `corpus` block
equals ground truth's `_corpus` on four keys — `distinct_documents`,
`scored_entries`, `gt_parts`, `distinct_parts`. **#106 moved main's declaration
to 10 / 11 / 924 / 522.** The nightly runs the CHART-PINNED image, and
`c8dce84a` predates #106, so it measures **8 / 9 / 898 / 496**.

**No report the old pin could ever produce would satisfy the required check.**
`charts/**` and `docs/corpus-gate/**` were frozen. #103 reads
`mergeStateStatus: BLOCKED` for exactly that reason: the pin was stale, the
report was not wrong.

`d16b4402` is the build of `2c4c186`, which **is #106** — push-run `38098478738`.
That is precisely why it is the unblock: it is the first image whose emitted
corpus block matches main's declaration. Confirmed from inside the rolled pod
before committing to a 75-minute measurement:
`[('distinct_documents', 10), ('scored_entries', 11), ('gt_parts', 924),
('distinct_parts', 522)]`.

**Not main's tip, and the reason is measured.** main is `9649538` (#63, S1000D
week 2), which `d16b4402` does not carry. `git diff --stat 2c4c186 9649538 --
scripts/pcn_ground_truth.json` is EMPTY, so #63 moved no ground truth and the
corpus block is unaffected by the gap.

## 3. Pin — commit `3aaae26`, PR #108

Both digests moved, which is the whole of the two-leaf delta:

- `image.digest`
- `corpusGate.expectImage`

A pin bump has two digests to move, and moving one is a silent half-roll.

The ghcr index and **both platform children were verified by fetching each by
its own digest**, not by reading the index's labels — the convention this file
records for every prior pin. `scripts/verify_image_pin.py` exits 0 for
`linux/amd64` and `linux/arm64`. A 62-line provenance block went in above the
digest in the style of its predecessors: both children, the push run, why this
digest and not main's tip, what it carries beyond `c8dce84a`, that THIS PIN IS
THE UNWEDGE, what the superseded pin measured, and that 10-09 was a 504.

## 4. Roll — release `doc-tools` revision 42

Plain `helm upgrade`, three `-f` files, STATUS deployed. Single pod
`doc-tools-d77c58fcd-7p9hc`, and its `imageID` equals the chart pin exactly.
`global` is absent, so this is not the overlay that reverts every image to a 404
tag.

**The values diff was shown before the roll, as required, without reading the
secret file.** `helm get values -o json` piped into `scratchpad/drift_check.py`,
which prints the two non-secret digests in full and every other leaf as
`len=N sha256:XXXXXXXX`. Exactly two leaves changed.

## 5. Three fires

Launched `--from=cronjob` with no YAML dump — the CronJob holds
`LANGFUSE_SECRET_KEY` as an inline env value, so a `--dry-run -o yaml` would
have printed a live credential into a transcript, and a transcript is not
editable.

`DOC_TOOLS_IMAGE` and `PCN_GATE_EXPECT_IMAGE` both verified at the new digest.
`PROMPT_SOURCE=file`, so no live prompt text can void the measurement.

**This run's identity check is not circular.** The chart comment records that the
`c8dce84a` run compared `DOC_TOOLS_IMAGE` against the imageID of the pod it had
just set it on. Here the deployment pod is independently on `d16b4402`, so the
comparison has two sides.

### Results

Job `doc-tools-corpus-gate-d16b4402`, started 03:52:38Z, terminal **failed=1**.
Published successfully as `236959f` — so this is a **measured red, not a 504**.
The two are distinguished by reading the log, never by the exit code.

**Parts — three fires, byte-identical results:**

| fire | exit | elapsed_s | exact/gt | spurious | missing | malformed |
|---|---|---|---|---|---|---|
| 1 | 1 | 3250.4 | **915/924** | 1 | 9 | 1 |
| 2 | 1 | 2844.9 | **915/924** | 1 | 9 | 1 |
| 3 | 1 | 3056.2 | **915/924** | 1 | 9 | 1 |

**Every one of the 9 missing, the 1 spurious and the 1 malformed is TI, and it is
the same defect three times:**

- missing (9): `TPS54340DDA`, `TPS54340DDAR`, `TPS54340DDAR-P`, `TPS54360DDA`,
  `TPS54360DDAR`, `TPS54540DDA`, `TPS54540DDAR`, `TPS54560DDA`, `TPS54560DDAR`
- spurious (1) and malformed (1): `Jun 22, 2021`

**This is the TI live miss, reproduced on the gate, deterministically.** It is
precisely the defect PR #107 was built against — a date harvested as a part while
the Product Affected table is missed entirely. #107 is open, mergeable, base
`main`, `tests` green, and is ordered for the NEXT pin. The nine other notices
contributed nothing: **915/924 is 924 minus TI's nine.**

**Headers — 7/9 exact, three out of three:**

| fire | exact/scored | clean |
|---|---|---|
| 1 | 7/9 | False |
| 2 | 7/9 | False |
| 3 | 7/9 | False |

One of the two non-exact is a PASS: TI `doc_level_ltb_date` is **correctly
absent** — ground truth declares the document states no value, and none was
written. That is #105's `expect_absent` state doing its job, counted as correct
but apart from `exact`.

### Header agreement, and a finding

| notice | verdict | disagreeing fields |
|---|---|---|
| Diodes_PCN_2683_FULLGREEN.pdf | **DISAGREE** | `doc_id`: 'PCN-2683' \| 'PCN-2683' \| 'PCN #: 2683' |
| TYC-PCN-24-210412.pdf | DISAGREE (exempted) | `mfr`: 'TE' \| 'TE' \| 'TE Connecvity' · `doc_level_ltb_date_source`: '06-JUN-2024' \| '-2024' \| '06-JUN-2024' |
| the other 9 | agree | — |

**NEW AND SHARPER THAN LAST NIGHT: the Diodes label leak swapped files.** The
07:00Z nightly had `Rev1_EOL` leaking `'PCN #: 2683'` in fire 2 while `FULLGREEN`
agreed. Tonight it is the exact reverse — `Rev1_EOL` agrees and `FULLGREEN` leaks
the same string, in fire 3. **The Diodes pair is byte-identical** (it is the
reason scored entries exceed documents by exactly one). So the leak is not a
property of either file: the same bytes yield it on whichever copy the sampler
happens to land on. Alternating across nights is what sampling looks like, and it
means "the Diodes_Rev1_EOL red" was never the right name for it.

**The TYC exemption worked exactly as ruled.** `mfr` picked the distractor `TE`
in two fires and the misspelling `TE Connecvity` in the third, and it was
exempted only because `needs_review=True` in all three — distractor without
witness agreement gives null plus review, never the distractor. Also visible
again: `doc_level_ltb_date_source` read `'-2024'` in fire 2, the known
`fold_typography` truncation, which is not offset-preserving.

**TI `mfr` is the one deterministic header defect: 3/3 misformatted.** It wrote
`'TEXAS INSTRUMENTS'` against ground truth `'Texas Instruments Incorporated'` —
scored `misformatted`, i.e. *the same value in an unusable shape*, not a wrong
manufacturer. This is the shape the TYC ruling already has an answer for:
an accepted-alias set with a canonical form, compared canonical-after-alias and
never as a raw string. TI needs that entry. Recommended, not built — unordered.

### What the fires proved about the unwedge

The published report carries `corpus` = **10 / 11 / 924 / 522**, which is main's
declaration exactly, and `measured_image` = the chart pin `d16b4402`. Run
locally under the required check's own selection
(`-m "corpus_gate and not corpus_gate_verdict"`): **6 passed, exit 0.** The wedge
is broken. The guard's own warning states the position better than I can:

> corpus gate report is a measured FAIL. That does not block a merge — currency
> and identity are what this check asserts — but it is the current truth about
> the pinned image, and it still blocks the next pin through the
> corpus-gate-verdict job.

## 6. The ordered rider, beside the corpus block

**The nightly measured 898 by the old enumeration — now 898/924 by ordering, so
nobody reads it as a regression.** The denominator widened in #106 from 898 to
924 over ten documents. 898 and 896 are both historical denominators. The parts
score did not fall; the corpus grew.

## 7. #108 now carries its own proof — and one decision is yours

The publisher's commit was cherry-picked onto `pin/d16b4402` as `f7b1930`, so
**#108 is one merge carrying both the pin and the measurement of the pin.** Every
pin must carry proof of itself. The publisher also folded forward the 10-10 and
10-11 reports, which were on the branch and not on `main`, so no report is
silently dropped.

Expected check state on #108: `corpus-gate` **green** (verified locally, 6
passed), `corpus-gate-verdict` **red and advisory**.

**THE DECISION, and I am not taking it unilaterally.** The advisory job exists to
make "a red verdict blocks the next pin" real, and #108 is a pin. So merging it
means knowingly pinning on a red. The argument that it should merge anyway is
this, and it is measured rather than argued:

- The red is **entirely TI**, a notice #106 added to the corpus. Nine missing,
  one spurious, one malformed, all of it, and 915/924 is exactly 924 minus nine.
- `charts/**` and `docs/corpus-gate/**` are frozen until a report whose corpus
  block reads 10/11/924/522 lands, and **only an image carrying #106 can emit
  one.** `d16b4402` is the first such image.
- **Waiting for a green verdict does not terminate.** #107 fixes the TI parts
  defect, but TI `mfr` misformatted is a header defect that #107 does not touch,
  and the Diodes label leak is stochastic and unfixed. So the next pin is red
  too. "Merge only on green" and "unwedge the repo" cannot both be satisfied on
  any pin currently reachable.

So the choice is to merge the unwedge on an advisory red, or to leave `charts/**`
frozen. I recommend merging #108 and closing #103 as superseded — its report
measured the old pin and can never reconcile the ten-document declaration — then
taking #107 as the next pin, which should move parts to 924/924.

**Not done, awaiting your word:** merging #108, closing #103.

## 8. Carried forward

- **#107 is the next pin, as ordered.** Open, mergeable, base `main`, green.
- **TI `mfr` needs an accepted-alias entry** (`TEXAS INSTRUMENTS` → canonical
  `Texas Instruments Incorporated`), by the TYC ruling's existing shape. This is
  the only deterministic header defect in the corpus. Recommended, unbuilt.
- **The Diodes label leak needs renaming and an order.** It is not
  `Rev1_EOL`'s defect and not `FULLGREEN`'s; it is one defect on one set of bytes
  that surfaces on either copy. Per the standing ruling on TYC `mfr`, a label
  leaked into a value is a real extraction weakness, not gate noise.
- **`fold_typography` truncation** showed up again as `'-2024'`. Known, open.
- The 07:00Z nightly will run against `d16b4402` and should reproduce this red
  independently. Report filenames carry a timestamp, so it will not overwrite
  this one; `latest.json` will be replaced by an equivalent red.
- **`source_sha256` packet**: feasibility measured, two routes found, one of them
  dishonest (deriving from `source_key` is a path-derivation guess the field's own
  comment forbids, and is inert on half the manifests). The honest route is to
  hash the bytes at parse time, where `mint_ingest_id` already does it. Not
  built — unordered. Details in `HANDOFF.md`.
