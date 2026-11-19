# The corpus gate (CO-CORPUS-GATE)

The corpus gate is doc-tools' measurement authority. It runs the extraction over a fixed,
enumerated corpus three times, scores each run against committed ground truth, and
publishes one verdict with the evidence that produced it. Nothing else in this repo turns
"the extractor works" into a citable number, and no verdict is reached by reading a
Dagster run log.

It is **not** a CI check that runs on a change. It is a long job fired into a cluster by an
operator, whose published report a CI check then reads. The two halves are separate
findings below, and conflating them is how a green build has been mistaken for a green
corpus.

**This record describes; it proposes nothing.** Statuses are those of [the README](../README.md),
and line numbers are valid only at the pin listed there. The record shape is provisional.
Nothing in this record was run: it is read from the scripts, the chart and the tests.

## Findings

1. **Three fires, one verdict.** `FIRE_COUNT = 3`. The authority script runs the corpus
   driver three times into distinct per-fire paths (`corpus_f{N}.json`, `score_f{N}.json`,
   `seal_f{N}.json`, `fire{N}.log`) and scores the set with `score_fires`. Three is the
   instrument, not a retry policy: a defect that appears in one fire and not another is a
   finding about stability, and the declaration rules below are written in terms of *which*
   fires saw it. `built`
2. **A void is not a failure, and the distinction lives in the exit code.** The script
   returns 0 on a pass, 1 on a fail and **2 on a void**, with the reason written at the
   return: a void report and a failing report call for opposite actions — re-run against the
   right image, versus go and fix an extraction defect — and a caller that can only see
   "non-zero" treats the first as the second. The publisher and the CronJob both read this
   status. `built`
3. **The parts arm is set identity, never a count.** Scoring compares the emitted part
   numbers to ground truth as sets; a duplicate is not credited twice and a substitution is
   not a pass. The gate's own parts term is each fire's exit code, and the driver exits 0
   only when `exact == gt` with no spurious, missing or malformed rows **and** the crop seal
   reports nothing repaired and no errors. `built`
4. **The denominator lives where the gate reads it.** `scripts/pcn_ground_truth.json`
   carries a `_corpus` block: ten scored entries over ten distinct documents, `gt_parts ==
   distinct_parts == 512`. The driver asserts the targets against it at startup and aborts
   on a disagreement, and the gate copies the block into the published report, so a
   committed report states the corpus it was measured against. The block also records that
   896, 898, 924 and 522 are *historical* denominators: a score is only comparable to
   another score measured against the same one. `built`
5. **A rate compares; a count does not.** Rates are per-document `{count, denominator}`
   flags, aggregated as the worst case per flag across the fires. A fire with no `rates` key
   reads as `None` — unavailable — and never as zero, which is pinned by its own test. The
   same rule holds for the crop seal: not read is not "found nothing". `built`
6. **An instrument gap blocks, and earns no exemption.** A notice recorded `ABSENT` or
   `NOT MEASURED` by the header-agreement instrument, or an unparseable instrument output,
   appends to `blocking`. Absent is a block, not a skip: a notice one fire recorded and
   another did not cannot be compared, and the gate refuses to call that agreement. `built`
7. **A disagreement is exempt only where every fire that saw it declared it.** A value
   difference between fires is exempted only if all three fires declared a problem with
   *that* field; a field blank in one fire and populated in another is exempted only if
   every blank fire declared *that* field. `needs_review` alone is too weak and is decided
   per (notice, field). The identity half (`mfr`, `doc_id`) is keyed to the field that
   actually moved, and every moving field must be declared. `built`
8. **DECLINED is a third bucket, and all four of its conditions must hold**: blank in at
   least one fire and populated in another; every blank fire declared that field with a
   reason naming it; every other fire published the ground-truth value; and ground truth
   holds a value for it. `correctly_absent` is not a publication. A DECLINED row leaves
   `blocking` and `exempted` but stays in `failing_notices`. `built`
9. **The strict verdict is the safety, and it grants nothing.** `strict_verdict` allows no
   exemption and does not drop a DECLINED row: it fails on any unsettled written row, on an
   unstable identity half, on any failing notice in the correctness arm, and on a void. It
   is printed beside the verdict in the report. A reader who wants to know whether the
   extractor is actually clean reads this one. `built`
10. **Image identity makes a report void, and no expectation does not.** The measured image
    digest is compared with the expectation; a mismatch, a tag on either side, a null
    measured image or an uncomparable pair is **void**. `checked: false` — no expectation
    supplied — is by design *not* a void, so a pre-roll fire of a built-but-unpinned image
    still produces a usable report. `built`
11. **Three arms are advisory and say so in the report.** The customer-alias column, the raw
    model-output header agreement (advisory by the 2026-10-26 ruling), and the `mfr` witness
    branches are reported and are never gate terms. The word ADVISORY is printed every time,
    next to the number. `built`
12. **The clock is off by ruling, not by deletion.** The chart ships the gate as a CronJob
    with `suspend: true`; the `schedule` field stays only because the API server rejects a
    CronJob without one, and is inert. `concurrencyPolicy: Forbid`, `backoffLimit: 0` and a
    six-hour `activeDeadlineSeconds` apply. A fire therefore happens because an operator
    fires it. `built`
13. **The pod publishes its own report, and never to the default branch.** The CronJob runs
    the authority script and then the publisher in one shell, so the Job's exit code is the
    gate's and a publish failure cannot paint a red run green. The publisher commits
    `latest.json` and `report-<ISO>.md` to the `corpus-gate/nightly` branch through the
    GitHub API, opens a standing PR, and carries forward reports not yet merged. `latest.json`
    is overwritten each run; the dated archive is named per *run*, not per day. `built`
14. **The CI side reads the published report and fails when it is missing.** A missing report
    is a failure, never a skip. The guard asserts that the report names the digest the chart
    declares and states the corpus it was measured against. `built`
15. **The two CI gate jobs have different dispatch conditions, and the narrower one is
    deliberate.** `corpus-gate` runs when the diff touches `charts/**`, `docs/corpus-gate/**`
    or the gate's own script surface; `corpus-gate-verdict` runs **only** on `charts`, which
    was ruled rather than widened — a change to the gate's scripts cannot move a verdict
    that was measured by an image those scripts are not in, so only a pin bump legitimately
    moves it. A PR stacked on a non-`main` branch dispatches no workflow at all, so neither
    job is a "skip": there is no run record. `built`
16. **`--from-logs` reconstructs what `--run` measures.** In log mode no subprocess ran, so
    the driver's exit criterion is recomputed from the stored artifacts. The script says
    plainly that this can read `fires_ok = True` for a fire set whose live run exited 1 on
    the crop-seal term alone. A replay is therefore weaker evidence than a fire. `built`

## Settings and defaults

| Setting | Default | Where | What it does |
|---|---|---|---|
| `corpusGate.suspend` | `true` | `charts/doc-tools/values.yaml:296` | whether the clock fires at all |
| `corpusGate.schedule` | `"0 7 * * *"` | `values.yaml:288` | inert while suspended; present because the API server demands it |
| `corpusGate.expectImage` | `""` | `values.yaml:329` | the expected digest; empty means `checked: false`, not void |
| `corpusGate.activeDeadlineSeconds` | `21600` | `values.yaml:377` | six hours for three fires |
| `concurrencyPolicy` / `backoffLimit` | `Forbid` / `0` | `templates/corpus-gate-cronjob.yaml:37`, `:46` | one fire at a time; no automatic retry |
| `PCN_GATE_EXPECT_IMAGE`, `DOC_TOOLS_IMAGE` | from the chart | `templates/corpus-gate-cronjob.yaml` | the expectation and the image under measurement |

## Gaps

- **The roll lock is an operator convention and is verified by nothing.** The pre-roll design
  document says a hand fire takes a `sandbox/roll-lock` ConfigMap (ruled 2026-11-04), and it
  is asserted by the operator: no script, chart template or test reads it.
  `accepted` (the rule); `not built` (the check).
- **The pre-fire helper does not check the lock either**, by its own design note, and shells
  out to `kubectl` to build a Job from the CronJob. `built` (the helper); the lock term is
  `not built`.
- **The durations written in the code are stale.** The authority script's docstring says
  "~70 minutes", two comments say 2.5 hours, and the workflow says "~22 minutes ×3", while
  the design document records a measured 2h22m–2h34m per fire. The code figures are not
  wrong about a past run; they are wrong as guidance now. `built` (the measurement, in the
  design document); the code's figures are stale.
- **A fire's `stats` keys are observable only while the pod exists.** The gate reads a fixed
  set of keys from the artifacts; a key added to a fire's output that the gate does not read
  cannot be recovered after the Job finishes. `built` (the limitation, by construction).

## Not established from code

- Whether a `sandbox/roll-lock` ConfigMap exists in any deployed namespace. It appears in no
  script, template or `AGENTS.md` at this pin — only in `docs/pcn-pre-roll-fire-design.md`
  as an operator convention. Reading a cluster is out of scope for these records.
- What the current declared duration of a fire is, as opposed to the measured 2h22m–2h34m and
  the three stale figures in code. One number should be authoritative and none is marked so.
- Whether `tests/test_gate_publish.py` and `tests/test_gate_prefire.py` pin specific rules of
  the publisher and the pre-fire helper, or only their shapes. Both files exist; their test
  names were not read into this record.
- Which alignment rows of the outside references the gate answers to. The rows suggested
  below are this lane's reading, not the arch lane's; dag-tools' alignment records do not
  name doc-tools at their pin. `proposed`

## Place in the mesh

| Aspect | What the code and chart show | Suggested alignment row |
|---|---|---|
| Purpose | turn "the extractor works" into a citable verdict over an enumerated corpus, three times, with the evidence attached | [DoD S13](https://github.com/edgy-solutions/dag-tools/blob/lane/arch-alignment/docs/arch/alignment/dod-dmra.md) — quality measured and kept as metadata `proposed` |
| How the mesh wires it | nothing calls it; an operator fires it into the cluster and the pod publishes to a branch. CI reads the published report, not the gate | — |
| Data path | it reads the corpus through the ordinary extraction path, in the image under measurement; it has no path of its own | — |
| What it emits | one verdict, one strict verdict, per-fire artifacts, and a committed report that names the digest it measured | — |
| Security role | none. It makes no access decision and holds no credential of its own; it runs as the pipeline does | — |
| Plane | data management: it is a lifecycle service over the extraction, not a producer of data | [NATO L3](https://github.com/edgy-solutions/dag-tools/blob/lane/arch-alignment/docs/arch/alignment/nato-dcra.md) `proposed` |

## Sources

All paths are in this repo at the pin in [the README](../README.md).

| Claim | Source | Decision | Evidence | Status |
|---|---|---|---|---|
| Three fires, distinct per-fire artifact paths, scored by one function | `scripts/pcn_corpus_gate.py:54`, `:117`, `:1912` | — | `tests/test_corpus_gate_defects_and_logs.py::test_a_failing_verdict_preserves_EVERY_fire_log_even_the_clean_ones` | `built` |
| Verdict assembly; void overrides; exit 0/1/2 with the reason stated | `pcn_corpus_gate.py:1917`, `:2125`, `:2127`, `:3112-3114` | — | `tests/test_corpus_gate_image_identity.py::test_a_mismatch_names_the_source_and_both_digests` | `built` |
| Parts scoring is set identity | `scripts/pcn_score.py:151` | ruled 2026-10-29 (customer alias column) | `tests/test_pcn_score.py::test_substitution_is_not_a_pass`, `::test_duplicate_emission_is_not_credited_twice` | `built` |
| The driver's exit criterion includes the crop seal | `scripts/pcn_corpus_run.py:730-733` | — | `tests/test_corpus_gate_crop_seal.py::test_worst_case_per_counter_is_what_decided_the_verdict` | `built` |
| The denominator and its history live in the ground-truth file and are copied into the report | `scripts/pcn_ground_truth.json:3-11` | re-key 2026-10-12; re-label 2026-10-29 | `tests/test_pcn_score.py::test_shipped_ground_truth_is_self_consistent`; `tests/test_corpus_gate_guard.py:525` | `built` |
| Absent rates are unavailable, never zero | `pcn_corpus_gate.py:2012-2020`; `doc_tools/utils/ingest_rates.py:17-33` | — | `tests/test_corpus_gate_written_headers.py::test_absent_rates_are_reported_as_unavailable_never_as_zero` | `built` |
| ABSENT is a block, not a skip; instrument gaps block | `pcn_corpus_gate.py:79-80`, `:510`, `:826` | — | `tests/test_corpus_gate_written_headers.py::test_an_unrecordable_bytes_check_is_not_a_pass` | `built` |
| The all-fires declaration rule, the blank-fire rule and the identity half | `pcn_corpus_gate.py:1150`, `:1383` | ruled 2026-11-08, 2026-11-15 | `tests/test_corpus_gate_written_agreement.py::test_the_same_difference_declared_in_all_three_fires_is_exempted`, `::test_a_blank_fire_is_exempted_only_by_a_declaration_naming_its_field`, `::test_the_identity_half_is_keyed_to_the_field_that_actually_moved` | `built` |
| Written comparison is of canonical forms, through the scorer | `pcn_corpus_gate.py:474`; `scripts/pcn_score.py:480` | ruled 2026-11-08 | `tests/test_corpus_gate_written_agreement.py::test_an_accepted_spelling_unifies_and_reverses_the_2026_10_29_block`, `::test_the_fallback_is_stricter_than_the_canonical_comparison` | `built` |
| DECLINED, its four conditions, and that it stays in `failing_notices` | `pcn_corpus_gate.py:1300`, `:1071` | ruled 2026-11-17 | `tests/test_corpus_gate_declined.py::test_an_undeclared_blank_is_not_declined_and_still_blocks`, `::test_every_blank_fire_must_have_declared`, `::test_correctly_absent_ground_truth_is_not_declined`, `::test_header_correctness_drops_the_line_and_keeps_failing_notices` | `built` |
| The strict verdict grants no exemptions | `pcn_corpus_gate.py:2134-2144`, `:2655` | — | `tests/test_corpus_gate_written_headers.py::test_an_exempted_failure_is_still_a_failing_notice_for_the_strict_view`; `tests/test_corpus_gate_declined.py::test_the_report_carries_a_declined_section_with_the_strict_verdict_beside_it` | `built` |
| Image identity: mismatch/tag/null is void; no expectation is not | `pcn_corpus_gate.py:1660` | — | `tests/test_corpus_gate_image_identity.py::test_no_expectation_is_checked_False_and_NOT_a_void`, `::test_a_tag_on_either_side_is_uncomparable_and_also_void` | `built` |
| Advisory arms, with the word printed | `pcn_corpus_gate.py:2007`, `:2185-2187`, `:2197-2199`, `:2404`; `:256` | ruling 2026-10-26 (raw); advisory 2026-10-29 (aliases) | — | `built` |
| The clock is off by ruling | `charts/doc-tools/values.yaml:286-296`, `:377`; `templates/corpus-gate-cronjob.yaml:26-47` | ruled (comment at `corpus-gate-cronjob.yaml:27`) | — | `built` |
| Publisher: branch, standing PR, carry-forward; archive per run | `scripts/pcn_gate_publish.py:56-57`, `:73-74`, `:183-215`; `pcn_corpus_gate.py:2915` | — | `tests/test_corpus_gate_report_archive.py::test_two_runs_on_the_same_day_do_not_share_a_filename`, `::test_the_publisher_glob_still_matches` | `built` |
| A missing report fails; the report must name the pinned digest | `tests/test_corpus_gate_guard.py:401`, `:470`, `:525`, `:593` | — | the guard is the test | `built` |
| Two gate jobs, different conditions; verdict job scoped to `charts` by ruling | `.github/workflows/build-container.yml:915`, `:998`, `:1023`, `:1025`, `:1040`, `:1054`; `:379-386` | ruled 2026-11-03 | — | `built` |
| A stacked PR dispatches nothing | `.github/workflows/build-container.yml:48`; `CLAUDE.md` | convention, this repo | — | `built` |
| `--from-logs` reconstructs the exit code and can read a seal-red fire as green | `pcn_corpus_gate.py:215-226` | — | — | `built` |
| The lock is an operator convention | `docs/pcn-pre-roll-fire-design.md:97-112`; `scripts/pcn_gate_prefire.py:12-13` | ruled 2026-11-04 | — | `accepted`; the check is `not built` |
