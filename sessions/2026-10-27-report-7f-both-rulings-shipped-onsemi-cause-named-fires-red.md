# Report — lane 7f, 2026-10-27 (late): both rulings shipped, the onsemi cause is named, the fires stay RED

Answering the architect's two rulings. Same PR (#179,
`7f/gate-triggers-suspend-nightly`, off `main` at `b8a3dd0`).

| commit | ruling | what |
|---|---|---|
| `fce37de` | 1 | the identity half is keyed to the field that MOVED |
| `bd235fb` | 2 | the parts crop gets the retry the region read already has |

**The 2026-10-26 fires are recorded RED.** Both of them — 09:33Z and 21:19Z —
lost parts on `onsemi_Generic_IPCN25300X.pdf`, and the 2026-10-27 09:29Z report
that scored green did so with the old notice-level exemption in force (10 of 10
notices exempt, every header disagreement waived). Neither ruling's fix has been
through a fire yet. Nothing here is proven at a cluster.

---

## 1. The exemption, now keyed to the field — including the identity half

`8ccda54` (this morning) narrowed the scored header fields and explicitly left
the identity half keyed to the pair `{mfr, doc_id}`, because `compute_stability`
compared a composite key and returned only filenames: which half moved was not
recoverable where the decision was made. That was the last place a declaration
about one field bought an exemption for another, and the ruling closes it.

`compute_stability` now returns a third value — `moving_fields`, per notice —
built from `notice_identity.parse_notice_key` components rather than from the
composite key, and `apply_declaration_rule` requires **every** moving identity
field to be declared in **every** fire. `any` over the pair would have been the
same collapsing defect one level down: `doc_id` declared, `mfr` moved, exempt.
The blocking line now names which fields moved and which of them is undeclared,
so the reader is not left to guess which of the two to fix.

Two cases keep both fields required, deliberately. An identity that could not be
**formed** (a `None` key) names no moving half; and a caller that supplies no map
gets the old behaviour. Both are conservative in the direction of *measuring*,
never of exempting.

`identity_moving_fields` rides in the report JSON, and the markdown renders
`` fn (`mfr/doc_id` moved) `` so the narrowing is visible to a reader of the
report rather than only to a reader of the code.

### "Never the parts arm" already held — measured, not changed

The ruling's third clause needed no code. `needs_review` appears nowhere in
`scripts/pcn_score.py`, and the gate's parts blocking is the fire's own exit code
(`scripts/pcn_corpus_gate.py:2106`). A header flag cannot reach the parts arm by
construction. Recorded in `fce37de`'s message rather than invented as a change.

### #176's arm is live the day it ships

That was the point of the ruling and it is met: the written-value arm routes
through `apply_declaration_rule`, and the rule no longer exempts a field because
some other field was narrated about.

## 2. onsemi IPCN25300X — measured side by side, cause named, fixed

Both losses are the **same crop and the same call**: the sixth `ExtractParts` of
that document, the one crop carrying 17 of its 19 MPNs (the other two come from a
continuation crop). Read off the two jobs' own fire logs, not from recall:

| run / fire | that call | document |
|---|---|---|
| 09:33Z fire 2 | HTTP **400** `Failed to load image or audio file`, 0 rows | 2/19, `crops_failed=1` |
| 21:19Z fire 1 | 94.2s, 2563 in / 1923 out, StopReason `stop`, **8 of 17 rows** | 10/19, `crops_row_short=1` |
| 21:19Z fire 2 | 123.2s, 2563 in, StopReason `stop`, **17 rows** | **19/19**, clean |

What the third row makes it: a measurement, not an inference. The two 21:19Z
fires sent the **identical prompt** — 2563 input tokens in both — to the same
model on the same crop in the same invocation, and one of them read the whole
table. Crop geometry was identical in all six fires across both runs
(`n_tables=37`, `stored_cut_tables=2`, `stored_cut_words=17`). The two fires are
line-for-line identical through 7 `LabelGridColumns` and 5 `ExtractParts` calls
before this one.

So the image is innocent, the crop is innocent and the code path is innocent.
**One vision call is unreliable, and the product accepted whatever it returned
the first time.** The short read is the harder half: output tokens were nowhere
near `VISION_MAX_TOKENS`, so it is not a truncation — the call *succeeded* and
returned a well-formed, schema-valid, shorter answer. No exception, no cap, no
malformed row. Only an independent expectation of the row count can see it.

### The fix is the precedent, not a new policy

`_read_one_region` has retried this exact 400 since 2026-10-01, in its own words:
*"the rejection is not a property of the image, and a second attempt is the
correct response rather than a guess."* The parts crop never got that treatment.

- **`_extract_parts_once`** — one call, one retry on a non-timeout exception,
  a fresh `_vision_call_opts()` per attempt (a reused collector would report the
  first attempt's tokens against the second attempt's rows, and that drives the
  truncation decision). A **timeout is not retried**, detected the same way
  `_read_one_region` detects one so the two paths cannot disagree about what a
  timeout is: the ~300s ceiling is server-side, and retrying into it turns a 300s
  stall into a 600s one for the same answer.
- **`_best_declined_grid`** — one definition of "what tier 1 counted on this
  page", now used by both the re-sample and the existing post-loop row-short
  detector, so a crop can never be re-sampled against one number and judged
  against another. The detector's behaviour is unchanged and it stays the
  authority; its per-page MAX reasoning — measured on this very notice — is kept
  verbatim.
- **the one-shot re-sample** — only on a page's **first** successful crop (a
  later crop of a banded table is *expected* to be smaller than the page total),
  only when it is short of tier 1. The two reads are **never merged**: they are
  two reads of one crop and concatenating them would double every shared row. A
  truncated second is refused. On any exception the first attempt's rows are
  kept. So a re-sample cannot make a crop worse than not re-sampling it.
- **`crops_resampled`, `crops_resample_recovered`, `resample_detail`** in both
  the stats dict and the zero-stats dict, so the next recurrence is a measurement
  rather than a rediscovery.

`tests/test_parts_crop_resample.py` pins all nine arms: the 400 retried, a
timeout not retried (and the queued second result **not consumed**), both
attempts failing, the short read recovered, a re-sample that does not help, one
that raises, a truncated one refused, no decline → no re-sample, and a later crop
on the same page not re-sampled against the page total.

### The stated cause of this morning's closure was wrong and is retracted

"Fixed by #165" cannot be true: `git merge-base --is-ancestor 1dbf2bd 38b7937`
→ true, so #165 is already inside v0.2.2 = `c056fa70`, the image that failed.
Three clean fires closed the *ticket*, not the defect. The notice has now been
observed clean 3/3 and dirty 2/2 on the same code, which is exactly why a green
run was never evidence here.

## 3. #178 rebased

`corpus-gate/nightly` is **0 behind, 1 ahead** of `main` at `b8a3dd0` — the
publisher's reparent-per-run fix is working, so there was nothing to rebase by
hand. The PR had been closed this morning on the earlier packet; reopened, since
a rebase of a closed PR is not a thing. `mergeStateStatus` is `BLOCKED`
(required check not yet run), **not** `DIRTY` — no conflict.

Its in-branch report is the 09:29Z green one, which the per-field exemption now
supersedes. It should not be merged as an authority until a fire runs under
`fce37de`/`8ccda54`.

## Measurements

| what | value |
|---|---|
| full suite, from PowerShell, `-m "corpus_gate or not corpus_gate"` | **2281 passed**, 13 skipped, 1 xfailed, 1 failed, 151.7s |
| the one failure | `test_overlay_kind_drift.py::test_the_shared_kinds_declare_the_same_passes` — pre-existing; it reads a sibling lane's working tree |
| fires of 2026-10-26 | **RED**, both, per the packet |
| cluster actions this session | **none** |

## Still open

- **Fire a pre-roll Job at sandbox** — still the only thing that closes the red
  window, and still never done. Existing is not working.
- The next fire is expected to red on TYC `doc_level_ltb_date_source`: that is
  the header arm measuring for the first time, not a regression. The fix is in
  the product or the value, not in loosening the rule back.
- The re-sample is **shipped, not proven**. Read `crops_resampled` and
  `resample_detail` in the next report: a recovery there is the defect being
  caught. A short read with `crops_resample_recovered=0` and two attempts logged
  means the host failed twice, and the next lever is the prompt or the crop — not
  a third retry.
- Queue item 3: #167's contract edit and the Neo4j migration dry run.
- Queue item 4: the batch fixture chain.
- `failed:vision_timeout` — waits on the SDK's closed `REASON_CODES` (v0.9.12)
  and lane 1 accepting in the same pin.
- The required job's warning text still falsely claims a measured fail "still
  blocks the next pin through the corpus-gate-verdict job".
- `sessions/**` is still not in the build-skip allowlist; it must ride a PR that
  already touches the workflow.
