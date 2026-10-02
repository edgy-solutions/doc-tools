"""The PCN/PDN corpus gate report must be present, green, and fresh, or CI
must say so loudly.

WHAT THIS GUARDS. `scripts/pcn_corpus_gate.py --run` runs inside an opt-in
Kubernetes CronJob (`charts/doc-tools/templates/corpus-gate-cronjob.yaml`),
not in CI: CI runners cannot reach the RFC1918 LLM/vision endpoints or the
in-cluster MinIO the corpus lives in. The report it produces,
`docs/corpus-gate/latest.json`, is committed to the repo by the same CronJob
run, through `scripts/pcn_gate_publish.py` — onto a branch with a standing
pull request, never onto main. That step is inert until a push-scoped token
and `corpusGate.publish.repo` are configured, and falls back to a human
copying the file out of the pod; either way what reaches CI is a commit. This
file is the CI-side half of that split: it reads the committed report rather
than trying to reproduce the run.

A MISSING REPORT MUST FAIL, NOT SKIP. This repo has already shipped the
opposite mistake once — see tests/test_chart_image_pin_guard.py's own
docstring, where a guard's CI coverage silently rested on an absent binary
for two days because every test in the file skipped instead of asserting, and
the job stayed green throughout. A skip reads as "fine" to anyone scanning CI;
it actually means "unproven". A report that has never been committed, or was
deleted, is exactly the "unproven" case and must turn this job red, not grey.

WHY THIS FILE DOES NOT ASSERT THE REPORT NAMES THE INCOMING DIGEST. A report
for digest D can only exist after D has been built and rolled — and rolling D
*is* the pin commit under review. Requiring the report to already name the
digest of the diff that produces it would make every new pin permanently
unmergeable (the report for pin N+1 cannot exist until pin N+1 merges). The
order this gate implements says a red gate blocks the *next* pin, not that
every pin must carry proof of itself: the gate is "green and not stale",
never "green for the exact digest in this diff".

WHAT IT DOES ASSERT ABOUT THE IMAGE, since 2026-10-02. The architect ruled:
"a report whose measured_image differs from the chart digest or the pods'
imageID is VOID, not a verdict." That comparison is made by the PRODUCER
(scripts/pcn_corpus_gate.py's check_image_identity), because only the
producer knows what it was told to expect, and a void report carries
`verdict: "void"` — which `test_verdict_is_pass` already refuses. What the
checks below add is that the report cannot be silent about the question: it
must carry the `image_identity` block, and it must name the image it
measured.

TWO GAPS, STATED RATHER THAN HIDDEN — both of the same shape, that CI cannot
assert a thing only a later change can supply (PR #40's mistake):

1. `image_identity.checked` can be False — "no expectation was supplied, so
   nothing was compared" — and CI does not fail on that. The missing input is
   the pods' `imageID`, which neither CI nor the gate's own Job can read (the
   Job's ServiceAccount has no Role; there is no role.yaml in
   charts/doc-tools/templates/). A human supplies it at helm-upgrade time
   through `corpusGate.expectImage`. Tighten to `checked is True` once that is
   set in values-sandbox.yaml.
2. The block may be absent entirely, because the gate runs the image the CHART
   is pinned to — so the block appears only after a pin bump carries the
   emitting code into that image. Tighten to a presence assertion once such a
   bump has landed.

Neither is "fine". Both are surfaced in the report's own markdown, which is
what a human reads when merging it: an unreconciled run leads with a **NOT
RECONCILED** section above the scores, and a report with no block renders
"whether it measured the declared image is **unknown**". Both tightenings are
tracked in HANDOFF.md so they do not rest on someone remembering.
"""
import datetime
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.corpus_gate

REPORT_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "corpus-gate" / "latest.json"
)

# Nightly cadence (see values.yaml corpusGate.schedule: "0 7 * * *") with two
# nights of slack, so a single missed or delayed run does not itself turn the
# gate red before anyone had a chance to act on the last real result.
CORPUS_GATE_MAX_AGE_DAYS = int(os.environ.get("CORPUS_GATE_MAX_AGE_DAYS", "3"))


def _load_report():
    if not REPORT_PATH.is_file():
        pytest.fail(
            f"{REPORT_PATH} does not exist. This is a FAIL, not a skip (see this "
            f"file's docstring): the corpus gate has never reported, or its report "
            f"was deleted, and either way that is unproven, not fine. Run the "
            f"corpus-gate CronJob (or `python scripts/pcn_corpus_gate.py --from-logs "
            f"<dir>` over a completed fire set) and commit docs/corpus-gate/latest.json."
        )
    try:
        return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        pytest.fail(f"{REPORT_PATH} exists but does not parse as JSON: {e}")


def test_report_exists_and_has_the_expected_schema():
    report = _load_report()
    assert report.get("schema") == 1, (
        f"{REPORT_PATH} has schema={report.get('schema')!r}, expected 1. Either the "
        f"report predates pcn_corpus_gate.py's current output shape, or something "
        f"else wrote this file."
    )


def test_verdict_is_pass():
    report = _load_report()
    verdict = report.get("verdict")
    if verdict == "pass":
        return
    if verdict == "void":
        # A VOID REPORT IS NOT A FAILING CORPUS, and must not be reported as
        # one: its `blocking` list is about an image nobody asked to be
        # measured, so printing it would send a reader looking for extraction
        # defects that are not there. The remedy is the opposite one — re-run
        # the gate against the declared image.
        reasons = report.get("image_identity", {}).get("void_reasons", [])
        pytest.fail(
            "corpus gate report is VOID, which is not a verdict: the image it "
            "measured is not the image it was supposed to measure, so neither "
            "its pass nor its blocking list is evidence about this branch. Do "
            "NOT read the scores. Re-run the gate against the declared image.\n"
            + "\n".join(f"  - {r}" for r in reasons)
        )
    blocking = report.get("blocking", [])
    if blocking:
        detail = "blocking:\n" + "\n".join(f"  - {b}" for b in blocking)
    else:
        detail = (
            "'blocking' is empty — this is a fires_ok failure with no "
            "per-condition detail; see the fires[] totals in the report directly."
        )
    pytest.fail(f"corpus gate verdict is {verdict!r}, not 'pass'. {detail}")


def test_report_is_not_stale():
    report = _load_report()
    generated_at = report.get("generated_at")
    assert generated_at, f"{REPORT_PATH} has no generated_at field"
    try:
        generated = datetime.datetime.strptime(
            generated_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=datetime.timezone.utc)
    except ValueError as e:
        pytest.fail(f"generated_at={generated_at!r} does not parse as UTC ISO 8601: {e}")
    age = datetime.datetime.now(datetime.timezone.utc) - generated
    max_age = datetime.timedelta(days=CORPUS_GATE_MAX_AGE_DAYS)
    assert age <= max_age, (
        f"corpus gate report is {age} old (generated_at={generated_at}), older than "
        f"CORPUS_GATE_MAX_AGE_DAYS={CORPUS_GATE_MAX_AGE_DAYS} days. A stale 'pass' is "
        f"not evidence about the code currently on this branch — re-run the gate."
    )


def test_the_report_states_the_corpus_it_was_measured_against():
    """A score is a fraction, and a committed report that carries only the
    numerator cannot be compared with the next one: `898/898` will mean something
    different the day a tenth notice is ingested. The gate copies the `_corpus`
    enumeration out of scripts/pcn_ground_truth.json into every report, and this
    is the CI-side check that the two still describe the same corpus.

    A REPORT WITHOUT THE BLOCK FAILS rather than skipping, for the reason in this
    file's docstring: it is a report whose denominator is unstated, which is
    unproven, not fine. It clears when the next gate run commits a report.
    """
    report = _load_report()
    gt = json.loads(
        (Path(__file__).resolve().parents[1] / "scripts" / "pcn_ground_truth.json")
        .read_text(encoding="utf-8"))
    declared = gt.get("_corpus") or {}
    assert declared, (
        "scripts/pcn_ground_truth.json carries no `_corpus` block, so there is no "
        "enumeration for a report to be checked against."
    )
    corpus = report.get("corpus")
    assert corpus, (
        f"{REPORT_PATH} states no corpus. The gate copies the `_corpus` block of "
        f"scripts/pcn_ground_truth.json into the report so the denominator travels "
        f"with the numerator; a report predating that is a measurement whose corpus "
        f"is unstated. Re-run the gate and commit the report."
    )
    for key in ("distinct_documents", "scored_entries", "gt_parts", "distinct_parts"):
        assert corpus.get(key) == declared.get(key), (
            f"{REPORT_PATH} was measured against {key}={corpus.get(key)!r} but "
            f"ground truth now declares {key}={declared.get(key)!r}. Either the "
            f"corpus widened since this report (re-run the gate) or the "
            f"enumeration was edited without re-enumerating the bucket."
        )


def test_the_report_names_the_image_it_measured():
    """A report with `measured_image: null` is a synthetic one.

    Only a `--run` inside the CronJob has `DOC_TOOLS_IMAGE` set; a
    `--from-logs` reduction over fixture logs writes null. That is not a
    hypothetical: on 2026-10-02 a diagnostic `--from-logs` run with no
    `--out-dir` overwrote `docs/corpus-gate/latest.json` — the committed
    authority for the pinned image — with exactly such a report, and the
    overwrite was invisible until someone read `git status`, because git calls
    it a modification and CI calls it a pass.

    An unnamed image also makes the whole identity ruling unenforceable: there
    is nothing to compare, so the producer's check is `uncomparable` at best.
    """
    report = _load_report()
    measured = report.get("measured_image")
    assert measured, (
        f"{REPORT_PATH} has measured_image={measured!r}. A report that does "
        f"not name the image it measured cannot be evidence about any image — "
        f"and null specifically means this file was written by a --from-logs "
        f"reduction, not by a gate run in the cluster. Re-run the gate "
        f"(`--run`), or re-point the diagnostic run at `--out-dir` and restore "
        f"this file from git."
    )
    assert "sha256:" in measured, (
        f"{REPORT_PATH} names measured_image={measured!r}, which carries no "
        f"sha256 digest. A tag is not an identity: `:latest` in this cluster "
        f"has reported a config digest matching no image, which is how 'what "
        f"is sandbox running?' became unanswerable. Pin image.digest."
    )


def test_the_image_identity_block_is_consistent_if_it_is_there():
    """IF the report records image comparisons, they must agree with its verdict.

    WHY PRESENCE IS NOT ASSERTED, and why that is not the usual skip-as-pass
    mistake. A first draft of this test demanded the `image_identity` block of
    any report generated after a cutoff date. That cutoff was a time bomb, and
    the reason is worth keeping: the gate runs the image the CHART is pinned
    to, so the block can only appear in a report once a pin bump has carried
    this code into the gate image. A date-based demand goes red on the next
    nightly — before any pin bump can possibly have happened — and because
    `corpus-gate` is required on main, it would block every chart PR including
    the bump that fixes it. That is PR #40's mistake verbatim: a guard test
    demanding a report block only a later change can supply.

    THE STALENESS GUARD DOES NOT CLOSE THIS, which the first draft wrongly
    claimed. Staleness bounds how old a report may be; it says nothing about
    how old the CODE that produced it is, and those are a pin bump apart.

    So the absence is surfaced where it will be read instead of asserted here:
    a report with no block renders "Not recorded — ... whether it measured the
    declared image is **unknown**" in its own section, above the scores.

    TIGHTEN THIS to a hard presence assertion once a pin bump has landed a
    gate image that emits the block (tracked in HANDOFF.md). Until then this
    test is a consistency check, not a coverage claim.
    """
    report = _load_report()
    identity = report.get("image_identity")
    if identity is None:
        # The report predates the check. It can still be held to one thing:
        # a gate build with no identity check cannot have produced a void.
        assert report.get("verdict") != "void", (
            f"{REPORT_PATH} reports verdict='void' but carries no "
            f"`image_identity` block. No gate build can produce that "
            f"combination — void is only ever set from that block's "
            f"void_reasons — so something other than the gate wrote this file."
        )
        return

    assert isinstance(identity.get("checked"), bool), (
        f"image_identity.checked is {identity.get('checked')!r}, not a bool. "
        f"This field is the difference between 'reconciled and agreed' and "
        f"'never reconciled', and it must never be absent or truthy-by-accident."
    )
    comparisons = identity.get("comparisons")
    assert isinstance(comparisons, list), (
        f"image_identity.comparisons is {type(comparisons).__name__}, not a list"
    )
    assert identity["checked"] == bool(comparisons), (
        f"image_identity says checked={identity['checked']} with "
        f"{len(comparisons or [])} comparison(s) recorded. Those two must agree: "
        f"a check that did not run must never be indistinguishable from a check "
        f"that passed (the `source_key` lesson — a set-wide boolean read "
        f"'verified' across manifests it was inert on)."
    )
    # If the producer recorded a mismatch, the verdict MUST be void. This is
    # the ruling itself, asserted against the committed artifact rather than
    # trusted to the producer's control flow.
    bad = [c for c in comparisons if c.get("result") != "match"]
    if bad:
        assert report.get("verdict") == "void", (
            f"{REPORT_PATH} records {len(bad)} non-matching image comparison(s) "
            f"{[(c.get('source'), c.get('result')) for c in bad]} but reports "
            f"verdict={report.get('verdict')!r}. Under the 2026-10-02 ruling "
            f"that report is VOID, not a verdict — the producer's verdict and "
            f"its own evidence disagree."
        )
