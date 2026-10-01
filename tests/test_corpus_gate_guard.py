"""The PCN/PDN corpus gate report must be present, green, and fresh, or CI
must say so loudly.

WHAT THIS GUARDS. `scripts/pcn_corpus_gate.py --run` runs inside an opt-in
Kubernetes CronJob (`charts/doc-tools/templates/corpus-gate-cronjob.yaml`),
not in CI: CI runners cannot reach the RFC1918 LLM/vision endpoints or the
in-cluster MinIO the corpus lives in. The report it produces,
`docs/corpus-gate/latest.json`, is committed to the repo BY HAND after a run.
This file is the CI-side half of that split: it reads the committed report
rather than trying to reproduce the run.

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
