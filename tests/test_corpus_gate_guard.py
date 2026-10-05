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

BOTH GAPS ARE NOW CLOSED, 2026-10-03 — and the history is kept because it is
what stops them being re-opened by a well-meaning loosening.

Until today this file asserted only that the `image_identity` block was
CONSISTENT if present, and said so loudly rather than hiding it. Two gaps:
`checked` could be False ("no expectation was supplied, so nothing was
compared"), and the block could be absent entirely — because the gate runs the
image the CHART is pinned to, so the block appears only once a pin bump carries
the emitting code into that image. Neither could be asserted at the time
without reproducing PR #40's mistake: a guard test demanding a report block
only a later change can supply, on a check that is required on main, which
would block every chart PR including the bump that fixes it.

The condition for closing them was written as a property of the REPORT, never
of the chart, precisely because a values key governs FUTURE runs while a
committed report is a PAST artifact. An earlier draft said to tighten "once
`corpusGate.expectImage` is set"; that was wrong, and on 2026-10-02 it was
measurably wrong — `expectImage` WAS set and the pinned image DID descend from
the emitting code, while `docs/corpus-gate/latest.json` still carried
`image_identity: null` from two pins back. Asserting `checked is True` that day
would have gone red on the spot.

THE ARTIFACT THAT CLOSED IT. The 2026-10-03T08:15:13Z nightly is the first
report to satisfy the condition, and it satisfies all of it:

    image_identity.checked   True
    comparisons              [{source: "pods", result: "match"}]
    void_reasons             []
    measured_digest          sha256:b54d9ef2…  == the comparison's
                             expected_digest == the chart's active image.digest

Both gaps closed at that one moment, as predicted, because both were waiting on
the same artifact: one needed the block to exist, the other needed it
populated, and the first report that has one has both.

WHAT THIS NOW MEANS WHEN IT GOES RED. A missing or unreconciled block is a
finding, not a condition to wait out. The remedy is never to relax these
assertions — it is to make the gate reconcile:

  - `checked: false` with no comparisons → the run was given no expectation to
    compare against. `corpusGate.expectImage` is supplied at helm-upgrade time
    from a pod `imageID` reading, because neither CI nor the gate's own Job can
    read pods (the Job's ServiceAccount has no Role; there is no role.yaml in
    charts/doc-tools/templates/). Supply it and re-run.
  - the block absent → the report was produced by an image older than the
    emitting code, or by a `--from-logs` reduction rather than a `--run`.

Both failure modes are ALSO surfaced in the report's own markdown, where a
human reads it when merging: an unreconciled run leads with a **NOT
RECONCILED** section above the scores, and a report with no block renders
"whether it measured the declared image is **unknown**". That rendering stays —
it is how a report read outside CI still tells the truth — but it is no longer
the only thing standing between an unreconciled run and a green check.

WHY THE REQUIRED CHECK NO LONGER ASSERTS THE OUTCOME, 2026-10-04 (ruled).
Merging the honest nightly FAIL (#67) froze merging for the whole repository,
and the freeze was circular: the extraction fix that turns the verdict green
had to merge through the check the red verdict was failing. Measured, both
mechanisms at once, on two PRs that had touched none of this:

  #68 (touches charts/**)  corpus-gate ran     -> conclusion FAILURE
  #69 (touches no charts)  corpus-gate skipped -> conclusion SKIPPED

and `main`'s protection carries exactly ONE required context, `corpus-gate`,
with no required reviews. So a FAILURE blocks chart PRs and a SKIPPED required
context blocks everything else. The `charts/**` scoping in the job comment was
written to prevent precisely this ("if a red gate blocked every PR, the fix for
a red gate could not merge"), and making the job a REQUIRED check silently
inverted it: the scoping that was the protection became half the wedge.

THE SPLIT THIS FILE NOW IMPLEMENTS. Two different questions were being asked
by one assertion, and only the first belongs in a required check:

  - IS THIS REPORT EVIDENCE ABOUT THIS CODE? — present, parseable, schema 1,
    fresh, naming its corpus, naming its image, carrying a reconciled
    `image_identity` block, and not `void`. All required, all cheap, and all
    unfalsifiable by an extraction defect. A report that fails any of these is
    not a bad score, it is NO MEASUREMENT, and that must block everything.
  - IS THE SCORE A PASS? — an outcome. It governs whether the next PIN may
    ship, which is what the original order asked for ("red blocks the next
    pin"), and it is carried by `test_verdict_is_pass` under its own
    `corpus_gate_verdict` marker, selected only by the advisory
    `corpus-gate-verdict` job on a `charts/**` diff.

A measured FAIL therefore warns in the required job and fails the advisory one.
Nothing is lost: the red is still loud, still in the report's markdown, and
still blocks a pin. What it no longer does is hold its own repair hostage.

WHAT WOULD BE THE REGRESSION. Re-adding `verdict == "pass"` to the required
check, or giving the required job an `if:` that lets it skip — a skipped
required context never satisfies the requirement, so scoping the REQUIRED job
by paths is the same bug as asserting the outcome in it, reached from the other
side. If `corpus-gate-verdict` is ever made required, it must stay
always-dispatched and decide internally, for that same reason.
"""
import datetime
import json
import os
import warnings
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


def test_the_report_is_a_real_measurement_and_not_void():
    """THE REQUIRED CHECK'S OUTCOME TERM: the report must be a measurement of
    this code — a `pass` or a `fail`, both of which are evidence about it.

    `void` is neither, and it is the one verdict that is an IDENTITY defect
    rather than an outcome: the producer sets it when the image it measured is
    not the image it was told to measure, so its scores describe something
    nobody asked about. That still fails, and must.

    A measured `fail` is deliberately ALLOWED here and warned about instead.
    A true red report is this gate working as designed; refusing to merge
    anything while one is committed is what wedged the repo shut on
    2026-10-03, because the extraction fix that turns the verdict green has to
    merge through this very check. The outcome assertion lives in
    `test_verdict_is_pass` below, which blocks a PIN rather than a merge.
    """
    report = _load_report()
    verdict = report.get("verdict")

    if verdict == "void":
        reasons = report.get("image_identity", {}).get("void_reasons", [])
        pytest.fail(
            "corpus gate report is VOID, which is not a verdict: the image it "
            "measured is not the image it was supposed to measure, so neither "
            "its pass nor its blocking list is evidence about this branch. Do "
            "NOT read the scores. Re-run the gate against the declared image.\n"
            + "\n".join(f"  - {r}" for r in reasons)
        )

    assert verdict in ("pass", "fail"), (
        f"corpus gate verdict is {verdict!r}, which is none of 'pass', 'fail' "
        f"or 'void'. Either the producer's vocabulary changed (see the "
        f"`verdict = ...` assignment in scripts/pcn_corpus_gate.py) or "
        f"something else wrote this file. An unrecognized verdict is unproven, "
        f"not fine — same rule as a missing report."
    )

    if verdict == "fail":
        blocking = report.get("blocking", [])
        detail = (
            "\n".join(f"  - {b}" for b in blocking)
            if blocking
            else "  (no per-condition detail — a fires_ok failure; read fires[] totals)"
        )
        warnings.warn(
            "corpus gate report is a measured FAIL. That does not block a merge "
            "— currency and identity are what this check asserts — but it is the "
            "current truth about the pinned image, and it still blocks the next "
            "pin through the corpus-gate-verdict job:\n" + detail,
            UserWarning,
            stacklevel=2,
        )


@pytest.mark.corpus_gate_verdict
def test_verdict_is_pass():
    """THE PIN BLOCK — the only assertion in this file about the OUTCOME, and
    the only one that is not part of the required `corpus-gate` check.

    Selected by the advisory `corpus-gate-verdict` job, which runs this only
    when the diff touches `charts/**`. That preserves the standing order "red
    blocks the next pin" — a pin bump IS a chart change — while keeping a red
    verdict off every ordinary code PR, which is the wedge this file's
    docstring describes.
    """
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


def test_the_image_identity_block_is_present_and_consistent():
    """The report must say which image it measured and that it reconciled.

    TIGHTENED 2026-10-03, when the condition in this module's docstring fired.
    This test used to be a consistency check that returned early when the
    block was absent, and the early return was correct at the time: the gate
    runs the image the CHART is pinned to, so the block could not appear in a
    report until a pin bump carried the emitting code into the gate image, and
    demanding it sooner would have been PR #40's mistake a third time. The
    2026-10-03T08:15:13Z nightly supplied the first report with
    `checked: true`, a pod-sourced match and no void reasons, so the absence is
    now a finding. See the module docstring for the remedy when this reds —
    which is to make the gate reconcile, never to restore the early return.

    NOTE ON THE DIGEST CHECK at the end. The old test could only ask whether
    the producer LABELLED each comparison a match. That trusts a label against
    the data sitting beside it, which is the failure this repo keeps paying
    for. So a comparison claiming `result: "match"` is now held to its own
    evidence: its `expected_digest` must equal the report's `measured_digest`.
    A producer bug that labels a mismatch a match is exactly the bug no other
    check can see, because every downstream consumer reads the label.
    """
    report = _load_report()
    identity = report.get("image_identity")
    assert isinstance(identity, dict), (
        f"{REPORT_PATH} carries image_identity={identity!r}. Since the "
        f"2026-10-03 nightly every gate run emits this block, so its absence "
        f"means this report was produced either by an image older than the "
        f"emitting code or by a `--from-logs` reduction rather than a `--run` "
        f"in the cluster. Either way it cannot say whether it measured the "
        f"image it was asked to measure, and that question is not optional: "
        f"re-run the gate with `--run`."
    )
    # A gate build with no identity check cannot have produced a void, so this
    # combination means something other than the gate wrote the file.
    assert report.get("verdict") != "void" or identity.get("void_reasons"), (
        f"{REPORT_PATH} reports verdict='void' with no void_reasons. Void is "
        f"only ever set from that list, so something other than the gate "
        f"wrote this file."
    )

    assert identity.get("checked") is True, (
        f"image_identity.checked is {identity.get('checked')!r}. This field is "
        f"the difference between 'reconciled and agreed' and 'never "
        f"reconciled', and `False` means the run was handed no expectation to "
        f"compare against — so the report is silent on whether it measured the "
        f"declared image. Supply `corpusGate.expectImage` from a pod imageID "
        f"reading at helm-upgrade time and re-run the gate. `is True` and not "
        f"a truthiness test on purpose: a non-empty string here would "
        f"otherwise read as reconciled."
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
    # A comparison is held to its own evidence, not to its label: the producer
    # may only call something a match when the digests actually match.
    measured_digest = identity.get("measured_digest")
    mislabelled = [
        c for c in comparisons
        if c.get("result") == "match"
        and c.get("expected_digest") != measured_digest
    ]
    assert not mislabelled, (
        f"{REPORT_PATH} records comparison(s) labelled 'match' whose "
        f"expected_digest differs from the report's measured_digest "
        f"{measured_digest!r}: "
        f"{[(c.get('source'), c.get('expected_digest')) for c in mislabelled]}. "
        f"Every consumer downstream reads the label, so a producer bug that "
        f"labels a mismatch a match is invisible everywhere except here."
    )
