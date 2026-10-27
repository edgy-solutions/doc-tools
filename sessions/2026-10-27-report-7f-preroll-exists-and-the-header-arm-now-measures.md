# Report — lane 7f, 2026-10-27 (later): pre-roll exists, and the header arm now measures

Queue items 1 and 2 of the architect's packet, on the same PR (#179,
`7f/gate-triggers-suspend-nightly`, off `main` at `b8a3dd0`).

| commit | what |
|---|---|
| `d625fa6` | item 1 — the pre-roll fire |
| `51d7518` | the guard docstring, now that pre-roll exists |
| `8ccda54` | item 2 — the header exemption, keyed to the field under test |

---

## 1. Pre-roll: the gate can measure an image before the chart pins it

The one fire path copies the CronJob's pod template, so the image it measures
is always the chart's current pin. A pin-bump PR therefore could not carry a
report for the digest it lands — the red window the architect accepted this
morning as an interim cost.

`scripts/pcn_gate_prefire.py` builds the Job **from** the CronJob, because the
CronJob is the only place the measured environment lives (`LLM_NUM_CTX`, both
DPI knobs, `PROMPT_SOURCE`, the inline `envFrom`). It overrides five fields and
nothing else, refuses an image with no `sha256` digest before it does anything
at all, and reads the pod's `imageID` to corroborate — **before** the 2.5 hours
of GPU time, not after. A mismatch deletes the Job; a *failed* delete is the
loudest exit the script has, because a surviving mismatched Job spends the GPU
time and then publishes a report naming an image it is not running.

The gate side **records** the mode and acts on nothing. `pre_roll` means the
digest is self-declared: the Job has no Role and no kubectl, so it cannot read
its own `imageID`, and the report now says that rather than implying a
comparison happened. `checked` stays false and the report stays unvoided —
voiding on an absence that is the designed state would make the feature
useless, since a void report is not a verdict. An expectation *supplied* in
`pre_roll` is still compared and still voids: nobody is silenced for having an
answer.

Two asymmetries, both deliberate. An **absent** mode defaults to `rolled`,
because every report written before today was a rolled fire. An **unknown**
mode is refused outright, before any fire runs, because defaulting it would
label a measurement of some unpinned candidate as a measurement of the deployed
system — the one claim the mode exists to make checkable.

`build_parser()` was extracted from `main()` to make one default assertable:
`--identity-mode` must default to `None` or `PCN_GATE_IDENTITY_MODE` is never
read. The pre-roll path overrides **env**, not argv — it copies the CronJob's
command verbatim — so a non-None default would leave the override rendering,
reviewable, and inert. This repo has shipped that exact shape before, so it now
has a test.

**Not done, and it is the next step: nothing has fired a pre-roll Job at a
cluster.** Existing is not working. Until a pre-roll report actually lands in a
pin-bump PR, the red window is still real and still accepted, and `--admin`
remains banned regardless. The guard's docstring (`51d7518`) now says exactly
that, and also records what `pre_roll` does *not* change: the guard compares
`measured_image` to the chart's pin, and in a pin-bump PR carrying a pre-roll
report those are the same image by construction. Adding a `pre_roll` branch to
that guard would be weakening it.

## 2. The header exemption is keyed to the field under test

`needs_review` is a document-level flag and the gate consumed it as an
exemption from header correctness. It went 3/4/3 of ten on v0.2.1 to **10 of
10** on v0.2.2, because the doc_id precedence ruling makes the plugin narrate a
`doc_id` reason on every notice. A flag about `doc_id` — not a scored field —
bought every notice an exemption for `mfr`, `pub_date` and
`doc_level_ltb_date`, and #176's written-value arm would have inherited it and
shipped inert.

The decision is now per field. A field is exempt only if all three fires carry
a reason that **names** it (`header.<field> refused`, or a region-witness LOST
reason listing it) or a header-**wide** reason (`header pass failed`, `region
witness DISABLED` — the two cases where no field was extracted or could be
corroborated at all). `needs_review` is still required as well. Blocking and
exempted lines now say which of the two a reader is looking at: a missing flag
and a flag about the wrong field are different defects with different fixes.

The vocabulary is the product's own, read from the tree rather than invented,
and the field names are shared — `witness_regions.py` declares the same keys
`pcn_ground_truth.json` scores — so no alias table exists and none should be
added.

`could not be located` is no longer a marker. It was one, commented "no header
region was locatable at all", and that was wrong: its only emitter is a
`_REFUSAL_CLAUSE` value, so it only ever appeared inside a `header.<field>
refused` reason about one field. As a header-wide marker it re-widened the
exemption to every field on any single refusal.

One `_source` suffix is stripped before matching, because the companion is the
citation for the same field and the product never refuses it by that name.
Without that the rule would be *stricter* than the ruling.

### Expect the next fire to go red, and it is correct

Measured, not assumed, against the one live exemption in this morning's green
report. TYC-PCN-24-210412 disagreed on `doc_level_ltb_date_source` — fire 3
wrote `'-2024'` against `'06-JUN-2024'` in the other two — and was exempted by
a `doc_id` reason. Under the per-field rule:

| reasons in all three fires | result |
|---|---|
| doc_id narration + degraded text layer (today's 10-of-10 shape) | **blocking** |
| `header.doc_level_ltb_date refused: ...` | exempted |
| `header.mfr refused: ...` (another field) | **blocking** |

So the next gate fire will likely red on that notice, on the required
`corpus-gate` check. That is the arm measuring for the first time. The fix is
in the product — refuse that field, in all three fires — or in the value
itself, not in loosening the rule back.

### Deliberately not done

The identity half stays keyed to the pair `{mfr, doc_id}`: `compute_stability`
compares a composite identity key and records only the filename, so which half
moved is not recoverable where the decision is made. Narrowing it means
teaching that function to report the moving half, which is a separate change.
`needs_review_in_all_fires` is now unused but left in place.

## Measurements

| what | value |
|---|---|
| full suite, from PowerShell, `-m "corpus_gate or not corpus_gate"` | 2269 passed, 13 skipped, 1 xfailed, 1 failed |
| the one failure | `test_overlay_kind_drift.py::test_the_shared_kinds_declare_the_same_passes` — pre-existing; it reads a sibling lane's working tree |
| #179 checks at `51d7518` | all green, `tests` 1m50s |
| pre-roll tag refusal | exit 2, no cluster touched |

## Still open

- Fire a pre-roll Job at sandbox — the only thing that closes the red window.
- Queue item 3: #167's contract edit and the Neo4j migration dry run.
- Queue item 4: the batch fixture chain.
- `failed:vision_timeout` — waits on the SDK's closed `REASON_CODES` (v0.9.12)
  and lane 1 accepting in the same pin.
- The required job's warning text still falsely claims a measured fail "still
  blocks the next pin through the corpus-gate-verdict job".
- `sessions/**` is still not in the build-skip allowlist; it must ride a PR
  that already touches the workflow.
