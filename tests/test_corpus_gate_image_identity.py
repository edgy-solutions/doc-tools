"""A report that measured the wrong image is VOID, not a verdict.

THE RULING (architect, 2026-10-02): "a report whose measured_image differs
from the chart digest or the pods' imageID is VOID, not a verdict; add the
check."

WHY VOID AND NOT FAIL, which is the whole content of the ruling. A mismatch
does not say the corpus scored badly. It says the score is about a different
image, so the pass/fail it carries is a statement about nothing — and
reporting that as `fail` is as wrong as reporting it as `pass`, because
someone would go looking for extraction defects that are not there. The two
states call for opposite actions (re-run against the right image vs. go fix
an extractor), which is why they also have different exit codes.

WHAT MADE IT NECESSARY. On 2026-10-01 a green `corpus-gate` check was read as
evidence about the digest in a pin-bump diff. It was not: the report's
`measured_image` named a BRANCH image that never reached main, and nothing
anywhere compared the two. The repo can be the stale side of that comparison,
and for days it was.

THE COMPARISON IS ON THE DIGEST, never on the reference string. One image is
spelled three ways across the chart, a registry probe and a pod's `imageID`;
a string compare would call those a mismatch and void a good report.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load("pcn_corpus_gate")

A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64
REPO = "ghcr.io/edgy-solutions/doc-tools"


# --------------------------------------------------------------------------
# The digest reduction.

@pytest.mark.parametrize("ref", [
    f"{REPO}@{A}",                                  # the chart's spelling
    f"ghcr.io/v2/edgy-solutions/doc-tools/manifests/{A}",  # a registry probe
    f"{REPO}:0.4.12@{A}",                           # tag AND digest
    A,                                              # the bare digest
])
def test_one_image_spelled_four_ways_reduces_to_one_digest(ref):
    """The reason comparison is not a string compare.

    All four of these name the same image, and at least three of them are
    spellings this repo has actually had to read.
    """
    assert gate._digest_of(ref) == A


@pytest.mark.parametrize("ref", [
    None, "", f"{REPO}:latest", f"{REPO}:0.4.12", "sha256:deadbeef",
    "sha256:" + "a" * 63, 42,
])
def test_a_reference_with_no_digest_reduces_to_None(ref):
    """None is a RESULT, not a parse failure to swallow.

    `:latest` is the specific case that made "what is sandbox running?"
    unanswerable: it has reported a config digest matching no image in this
    cluster's history. A tag cannot be reconciled with anything, so it is
    reported uncomparable rather than guessed at.
    """
    assert gate._digest_of(ref) is None


# --------------------------------------------------------------------------
# The expectations, and why the source label is required.

def test_the_source_label_is_carried_because_the_two_findings_differ():
    """"differs from the chart" and "differs from the pods" are not the same
    finding: the first says this report is not about the chart's pin, the
    second says the cluster is not running it. Different remedies, so a
    report that says only "mismatch" leaves a reader unable to act."""
    exp = gate.parse_expectations([f"chart={REPO}@{A}", f"pods={REPO}@{B}"])
    assert [e["source"] for e in exp] == ["chart", "pods"]
    assert exp[0]["ref"] == f"{REPO}@{A}"


def test_one_comma_separated_value_works_because_an_env_var_is_one_string():
    """PCN_GATE_EXPECT_IMAGE is a single env var; the chart cannot pass a list."""
    exp = gate.parse_expectations([f"chart={REPO}@{A},pods={REPO}@{B}"])
    assert [e["source"] for e in exp] == ["chart", "pods"]


def test_an_unlabelled_value_is_accepted_rather_than_refused():
    """An operator in a hurry still gets the comparison, labelled honestly."""
    exp = gate.parse_expectations([f"{REPO}@{A}"])
    assert exp == [{"source": "unlabelled", "ref": f"{REPO}@{A}"}]


@pytest.mark.parametrize("raw", [None, [], [""], ["  "], [",,"]])
def test_nothing_supplied_yields_no_expectations(raw):
    """The unset env var must not become a comparison against the empty string."""
    assert gate.parse_expectations(raw) == []


# --------------------------------------------------------------------------
# The check itself.

def test_the_same_image_spelled_differently_is_a_match_and_not_void():
    """The false-positive this check must not have. A chart pin and a pod's
    imageID routinely differ as strings while naming one image; voiding a
    good report would be worse than not checking, because the next real
    mismatch would be dismissed as noise."""
    r = gate.check_image_identity(
        f"ghcr.io/v2/edgy-solutions/doc-tools/manifests/{A}",
        gate.parse_expectations([f"chart={REPO}@{A}"]))
    assert r["void_reasons"] == []
    assert [c["result"] for c in r["comparisons"]] == ["match"]
    assert r["checked"] is True


def test_a_mismatch_names_the_source_and_both_digests():
    """A void report has to be actionable without a second investigation."""
    r = gate.check_image_identity(
        f"{REPO}@{A}", gate.parse_expectations([f"pods={REPO}@{B}"]))
    assert [c["result"] for c in r["comparisons"]] == ["mismatch"]
    assert len(r["void_reasons"]) == 1
    reason = r["void_reasons"][0]
    assert "pods" in reason and A in reason and B in reason
    assert "VOID, not" in reason, "the reason must say which kind of result it is"


def test_a_partial_mismatch_still_voids_and_still_reports_the_match():
    """Agreeing with the chart does not rescue a report the pods contradict:
    that combination is precisely "the cluster is not running the pin", which
    is the case the 2026-09-26 digest pin exists to make visible."""
    r = gate.check_image_identity(
        f"{REPO}@{A}",
        gate.parse_expectations([f"chart={REPO}@{A}", f"pods={REPO}@{B}"]))
    assert [c["result"] for c in r["comparisons"]] == ["match", "mismatch"]
    assert len(r["void_reasons"]) == 1


def test_a_tag_on_either_side_is_uncomparable_and_also_void():
    """Not a match, and not a mismatch — and above all not a pass. A report
    pinned by a moving tag cannot be shown to be about any image."""
    for measured, expected in ((f"{REPO}:latest", f"chart={REPO}@{A}"),
                               (f"{REPO}@{A}", f"chart={REPO}:latest")):
        r = gate.check_image_identity(measured, gate.parse_expectations([expected]))
        assert [c["result"] for c in r["comparisons"]] == ["uncomparable"]
        assert len(r["void_reasons"]) == 1
        assert "UNCOMPARABLE" in r["void_reasons"][0]


def test_no_expectation_is_checked_False_and_NOT_a_void():
    """The declared gap, pinned so it cannot drift either way.

    `checked: False` must not void (nothing was found wrong), and must not
    read as a pass either. This is the `source_key` lesson: that check went
    inert on 11 of 22 manifests while a set-wide boolean still reported
    "verified". A check that did not run must be distinguishable from a check
    that passed.
    """
    r = gate.check_image_identity(f"{REPO}@{A}", [])
    assert r["checked"] is False
    assert r["comparisons"] == []
    assert r["void_reasons"] == []


def test_a_null_measured_image_against_an_expectation_is_void():
    """The 2026-10-02 incident: a --from-logs run with no --out-dir wrote a
    report with measured_image null over the committed authority."""
    r = gate.check_image_identity(None, gate.parse_expectations([f"chart={REPO}@{A}"]))
    assert [c["result"] for c in r["comparisons"]] == ["uncomparable"]
    assert r["void_reasons"]


# --------------------------------------------------------------------------
# The verdict, and the exit code.

#: The markdown renderer touches most of the report's keys, so these tests
#: build their fixtures by overriding a REAL committed report rather than
#: hand-rolling a dict. A hand-rolled one drifts the moment the report gains a
#: field — the first draft of this file KeyError'd on `rates_available` — and,
#: worse, a renderer test that exercises a fixture shape no gate run produces
#: proves nothing about what a reader will actually see.
_REAL = (Path(__file__).resolve().parents[1] / "docs" / "corpus-gate"
         / "latest.json")


def _report(verdict, identity):
    report = json.loads(_REAL.read_text(encoding="utf-8"))
    report["verdict"] = verdict
    report["strict_verdict"] = verdict
    report["measured_image"] = f"{REPO}@{A}"
    if identity is None:
        report.pop("image_identity", None)
    else:
        report["image_identity"] = identity
    # Give the void path something it must NOT surface as a finding.
    report["blocking"] = ["a parts defect nobody asked about"]
    return report


def test_the_void_markdown_withholds_the_sentence_that_reads_as_a_verdict():
    """A reader who sees "898/898" beside VOID remembers the number.

    That is how a green check became evidence about a digest that never
    reached main. The score stays in the JSON and in the per-fire table — what
    is withheld is the PASS/FAIL sentence.
    """
    identity = {
        "measured": f"{REPO}@{A}", "measured_digest": A, "checked": True,
        "comparisons": [{"source": "pods", "expected": f"{REPO}@{B}",
                          "expected_digest": B, "result": "mismatch"}],
        "void_reasons": ["measured_image digest %s differs from the pods digest %s"
                         % (A, B)],
    }
    md = gate.render_markdown(_report("void", identity), ".", "cmd", [])
    assert "**VOID — this is not a verdict.**" in md
    assert "**PASS**" not in md and "**FAIL**" not in md
    assert "pods" in md and B in md
    # And it must not silently drop the blocking list into the reader's lap as
    # if it were a finding about this branch.
    assert "not evidence about" in md or "not a score" in md


def test_the_unreconciled_markdown_says_so_above_the_scores():
    """The absence of the check has to be visible where a human reads it.

    This no longer says "because CI deliberately does not fail on it". As of
    2026-10-03 CI DOES fail on it — tests/test_corpus_gate_guard.py now
    asserts `image_identity.checked is True` on the committed report, the
    condition in its docstring having fired. The rendering is still required,
    because a report is read by humans outside CI and must tell the truth
    there too; it is simply no longer the only thing standing between an
    unreconciled run and a green check."""
    identity = {"measured": f"{REPO}@{A}", "measured_digest": A,
                "checked": False, "comparisons": [], "void_reasons": []}
    md = gate.render_markdown(_report("pass", identity), ".", "cmd", [])
    assert "NOT RECONCILED" in md
    assert md.index("NOT RECONCILED") < md.index("## Per-fire results"), (
        "the unreconciled notice must come BEFORE the scores; after them it is "
        "a footnote nobody reads"
    )


def test_a_report_with_no_identity_block_renders_unknown_not_nothing():
    """Reports from a gate image predating this check still render. They must
    not render as if the question had been asked and answered."""
    md = gate.render_markdown(_report("pass", None), ".", "cmd", [])
    assert "unknown" in md.lower()


def test_a_void_report_preserves_every_fire_log():
    """Void selects logs for preservation exactly as fail does: the run has to
    be re-done, and the logs are the only place the header values live."""
    report = {"verdict": "void", "fires": [
        {"n": 1, "exit": 0, "totals": {"missing": 0}, "defects": {}},
        {"n": 2, "exit": 0, "totals": {"missing": 0}, "defects": {}},
    ]}
    fires = [{"n": 1, "log": "a", "log_path": "a"},
             {"n": 2, "log": "b", "log_path": "b"}]
    assert [e["n"] for e, _ in gate.fires_needing_preservation(report, fires)] == [1, 2]


def test_the_exit_code_distinguishes_void_from_fail():
    """2, not 1. A caller that can only see "non-zero" treats a void as a
    failing corpus and goes looking for an extractor bug. The CronJob
    preserves this code as the Job's own, and the publisher commits the
    verdict either way."""
    src = (SCRIPTS / "pcn_corpus_gate.py").read_text(encoding="utf-8")
    assert 'if report["verdict"] == "void":\n        return 2' in src
    assert 'return 0 if report["verdict"] == "pass" else 1' in src


# --------------------------------------------------------------------------
# The chart wiring.

CHART = Path(__file__).resolve().parents[1] / "charts" / "doc-tools"


def test_the_cronjob_passes_the_expectation_through():
    tpl = (CHART / "templates" / "corpus-gate-cronjob.yaml").read_text(
        encoding="utf-8")
    assert "PCN_GATE_EXPECT_IMAGE" in tpl
    assert ".Values.corpusGate.expectImage" in tpl


def test_the_chart_does_not_supply_its_own_pin_as_the_expectation():
    """THE TAUTOLOGY TRAP, pinned.

    Inside the CronJob, DOC_TOOLS_IMAGE and the container's `image:` both
    render from `include "doc-tools.image" .`. So a `chart=<that>` expectation
    would compare a value with itself and report **match** every single run —
    a check that cannot fail, published as a pass. That is strictly worse than
    no check, and it is the `source_key` failure shape again.

    The informative comparison is the pods' imageID, which this Job cannot
    read: its ServiceAccount has no Role (there is no role.yaml in
    charts/doc-tools/templates/) and the image carries no kubectl. It is
    supplied from outside. If a later change gives the gate pod-read RBAC,
    this test should be revisited deliberately rather than deleted — an
    instrument that sources its own expectation can agree with itself.
    """
    assert not (CHART / "templates" / "role.yaml").exists(), (
        "the gate's ServiceAccount has gained a Role; re-derive whether it can "
        "now read the pods' imageID, and whether it should"
    )
    values = _yaml_get(CHART / "values.yaml", "expectImage")
    assert values in ('""', "''", ""), (
        f"corpusGate.expectImage defaults to {values}, not empty. The chart "
        f"must not pass its own pin (see this test's docstring)."
    )


def _yaml_get(path, key):
    """The one line, without taking a yaml dependency for one assertion."""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key}:"):
            return stripped.split(":", 1)[1].strip()
    raise AssertionError(f"{key} not found in {path}")
