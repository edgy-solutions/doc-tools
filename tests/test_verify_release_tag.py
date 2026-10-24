"""Tests for the release-tag resolution check, `scripts/verify_release_tag.py`.

WHAT THIS FILE PROVES. The script's job is to answer one question — does tag X
name digest D — and its value rests entirely on two things being true: that it
reports a MISMATCH when the bytes differ, and that it REFUSES to report at all
when its own negative controls come back positive. Both are decision logic, not
network code, so both are provable offline.

THE SEAM is `verify_release_tag.resolve(name, ref) -> (status, digest)`, the one
function that touches a socket. `run()` takes it as a parameter, so every test
here passes a dict-backed fake registry and asserts on how the module drives it
and on the verdict it computes. Imported by path, like `verify_image_pin` in
tests/test_verify_image_pin.py: `scripts/` is not a package.

WHY THE CONTROL TESTS ARE THE IMPORTANT ONES. The failure this script was
written for (see its docstring: the v0.2.0 rebuild of 2026-10-23) was caught by
a check with working controls. A check whose controls had silently started
resolving would have printed MATCH against the wrong digest and been believed.
`test_controls_broken_*` are the tests that keep that from being possible.
"""
import importlib.util
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

NAME = "edgy-solutions/doc-tools"
GATED = "sha256:" + "ac853308" + "f" * 56  # the digest the sandbox pins, shape-wise
REBUILT = "sha256:" + "9883b5d3" + "e" * 56  # the bytes a rebuild would produce


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vrt = _load("verify_release_tag")


def fake_registry(contents, control_status=404):
    """A resolver over a {ref: digest} dict. Everything else is absent.

    `control_status` is what the controls get, so a test can make the registry
    misbehave exactly the way the controls exist to catch.
    """
    controls = {ref for ref, _ in vrt.CONTROL_REFS}
    calls = []

    def resolver(name, ref):
        calls.append(ref)
        assert name == NAME
        if ref in controls:
            if control_status == 200:
                return 200, "sha256:" + "cc" * 32
            return control_status, None
        if ref in contents:
            return 200, contents[ref]
        return 404, None

    resolver.calls = calls
    return resolver


# --- the controls -----------------------------------------------------------


def test_controls_run_before_any_reference():
    """Order is load-bearing: a broken control must be known first."""
    r = fake_registry({"v0.2.0": GATED})
    vrt.run(NAME, ["v0.2.0"], expect=GATED, resolver=r)
    assert r.calls[: len(vrt.CONTROL_REFS)] == [ref for ref, _ in vrt.CONTROL_REFS]


def test_controls_broken_refuses_to_resolve_the_references_at_all():
    r = fake_registry({"v0.2.0": GATED}, control_status=200)
    result = vrt.run(NAME, ["v0.2.0"], expect=GATED, resolver=r)
    assert result["exit"] == 3
    assert result["controls_ok"] is False
    assert result["refs"] == []
    # The reference was never even asked about -- there would be no point.
    assert "v0.2.0" not in r.calls


def test_controls_broken_renders_no_verdict():
    r = fake_registry({"v0.2.0": GATED}, control_status=200)
    text = vrt.render(vrt.run(NAME, ["v0.2.0"], expect=GATED, resolver=r))
    assert "CONTROLS BROKEN" in text
    # No row for the reference, and so no verdict against it. (The prose does
    # contain the word MATCH, explaining why none is being printed; the thing
    # that must be absent is the TABLE ROW a reader would act on.)
    assert "`v0.2.0`" not in text
    assert "resolves to" not in text


def test_a_short_digest_and_a_fake_digest_are_both_controls():
    """Two distinct failure modes, so both must be exercised."""
    refs = [ref for ref, _ in vrt.CONTROL_REFS]
    assert len(refs) == 2
    short, fake = refs
    assert len(short) < len("sha256:") + 64
    assert len(fake) == len("sha256:") + 64


# --- the verdict ------------------------------------------------------------


def test_match_when_the_tag_names_the_pinned_digest():
    r = fake_registry({"v0.2.0": GATED, "133714c": GATED})
    result = vrt.run(NAME, ["v0.2.0", "133714c"], expect=GATED, resolver=r)
    assert result["exit"] == 0
    assert [row["verdict"] for row in result["refs"]] == ["MATCH", "MATCH"]


def test_mismatch_when_a_rebuild_moved_the_tag():
    """The 2026-10-23 failure, reproduced: same commit, different bytes."""
    r = fake_registry({"v0.2.0": REBUILT, "133714c": REBUILT})
    result = vrt.run(NAME, ["v0.2.0", "133714c"], expect=GATED, resolver=r)
    assert result["exit"] == 1
    assert [row["verdict"] for row in result["refs"]] == ["MISMATCH", "MISMATCH"]
    assert "MISMATCH" in vrt.render(result)


def test_a_missing_tag_is_a_mismatch_not_a_pass():
    r = fake_registry({})
    result = vrt.run(NAME, ["v0.2.0"], expect=GATED, resolver=r)
    assert result["exit"] == 1
    assert result["refs"][0]["status"] == 404
    assert result["refs"][0]["digest"] is None


def test_one_bad_reference_fails_the_whole_check():
    r = fake_registry({"v0.2.0": GATED, "133714c": REBUILT})
    result = vrt.run(NAME, ["v0.2.0", "133714c"], expect=GATED, resolver=r)
    assert result["exit"] == 1


def test_no_expect_is_report_only():
    r = fake_registry({})
    result = vrt.run(NAME, ["v0.2.0"], resolver=r)
    assert result["exit"] == 0
    assert "verdict" not in result["refs"][0]


# --- the job output ---------------------------------------------------------


def test_emit_says_exists_when_the_commit_tag_resolves(tmp_path):
    out = tmp_path / "out.txt"
    r = fake_registry({"133714c": GATED})
    vrt._emit(out, vrt.run(NAME, ["133714c"], resolver=r))
    body = out.read_text(encoding="utf-8")
    assert "exists=true" in body
    assert f"digest={GATED}" in body


def test_emit_says_absent_when_no_image_exists_for_the_commit(tmp_path):
    out = tmp_path / "out.txt"
    r = fake_registry({})
    vrt._emit(out, vrt.run(NAME, ["deadbeef"], resolver=r))
    body = out.read_text(encoding="utf-8")
    assert "exists=false" in body
    assert "digest=\n" in body


def test_emit_carries_controls_ok_so_a_caller_cannot_act_on_a_broken_check(tmp_path):
    """exists=false with broken controls must never read as 'go and build'.

    The workflow guards this by failing the step on exit 3, and this field is
    the second belt: a job that reads `exists` can see that the answer is void.
    """
    out = tmp_path / "out.txt"
    r = fake_registry({"133714c": GATED}, control_status=200)
    result = vrt.run(NAME, ["133714c"], resolver=r)
    vrt._emit(out, result)
    body = out.read_text(encoding="utf-8")
    assert "controls_ok=false" in body
    assert result["exit"] == 3


# --- rendering --------------------------------------------------------------


def test_render_names_the_digest_and_both_controls():
    r = fake_registry({"v0.2.0": GATED})
    text = vrt.render(vrt.run(NAME, ["v0.2.0"], expect=GATED, resolver=r))
    assert GATED in text
    for _, why in vrt.CONTROL_REFS:
        assert why in text
    assert "ghcr.io/" + NAME in text


def test_main_rejects_an_expect_that_is_not_a_digest():
    with pytest.raises(SystemExit):
        vrt.main(["--expect", "v0.2.0", "v0.2.0"])


def test_undetermined_is_not_a_mismatch(monkeypatch):
    """A network failure must not be reported as 'the tag is wrong'."""

    def boom(name, ref):
        raise vrt.Undetermined("connection refused")

    monkeypatch.setattr(vrt, "resolve", boom)
    assert vrt.main(["--expect", GATED, "v0.2.0"]) == 2


# --- the workflow wiring ----------------------------------------------------
#
# The script above is only half the mechanism. These pin the properties of
# .github/workflows/build-container.yml that the 2026-10-23 tag overwrite came
# down to, because every one of them is a single line away from being undone
# and none of them is visible in a passing build.

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "build-container.yml"


@pytest.fixture(scope="module")
def workflow():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _jobs(workflow):
    return workflow["jobs"]


def test_a_tag_ref_cannot_rebuild(workflow):
    """The gate that stops a release from pushing ungated bytes."""
    build = _jobs(workflow)["build-and-push"]
    assert "resolve-release-image" in build["needs"]
    assert "needs.resolve-release-image.outputs.needs_build == 'true'" in build["if"]


def test_the_resolver_has_no_if_so_it_cannot_skip_the_build(workflow):
    """A skipped `needs` job skips its dependents -- see the job's own comment.

    If this job ever grows an `if:`, build-and-push stops running on ordinary
    pushes to main and the failure mode is a missing image, silently.
    """
    assert "if" not in _jobs(workflow)["resolve-release-image"]


def test_the_version_tag_is_verified_against_the_commit_sha_tag_too(workflow):
    """Both references, or the digest stops being answerable back to a commit."""
    steps = _jobs(workflow)["tag-release-image"]["steps"]
    verify = [s for s in steps if "Verify the version tag" in s.get("name", "")]
    assert len(verify) == 1
    run = verify[0]["run"]
    assert "verify_release_tag.py" in run
    assert "--expect" in run
    assert "outputs.version" in run and "outputs.sha" in run


def test_the_retag_asserts_both_tags(workflow):
    """The sha tag is re-asserted, which is what makes a repair possible."""
    steps = _jobs(workflow)["tag-release-image"]["steps"]
    retag = [s for s in steps if "Add the version tag" in s.get("name", "")]
    assert len(retag) == 1
    run = retag[0]["run"]
    assert "imagetools create" in run
    assert run.count('-t "$IMAGE:') == 2


def test_every_build_stamps_revision_and_version(workflow):
    """Item 4: an image must be able to name its own commit.

    `ac853308` could not -- empty labels map -- which is why recovering its
    commit took a 1.5 MB build log instead of one label read.
    """
    steps = _jobs(workflow)["build-and-push"]["steps"]
    build = [s for s in steps if s.get("id") == "build"]
    assert len(build) == 1
    labels = build[0]["with"]["labels"]
    assert "org.opencontainers.image.revision=" in labels
    assert "org.opencontainers.image.version=" in labels


def test_release_published_is_a_trigger(workflow):
    on = workflow[True] if True in workflow else workflow["on"]
    assert on["release"]["types"] == ["published"]


def test_the_dispatch_repair_inputs_default_to_empty(workflow):
    """A plain dispatch must still be the plain rebuild it has always been."""
    on = workflow[True] if True in workflow else workflow["on"]
    inputs = on["workflow_dispatch"]["inputs"]
    assert inputs["version"]["default"] == ""
    assert inputs["digest"]["default"] == ""
    assert inputs["version"]["required"] is False
    assert inputs["digest"]["required"] is False


def test_the_retag_job_checks_out_the_commit_its_tooling_lives_in(workflow):
    """The repair job cannot check out the release's source commit.

    MEASURED, run 40054727136: the first dispatch repair (v0.2.0 ->
    sha256:ac853308...) resolved and skipped the build correctly, then died
    with `can't open file '.../scripts/verify_release_tag.py'` because it had
    checked out 133714c -- the commit v0.2.0 names, two merges BEFORE the
    script existed. A job that runs this workflow's own tooling against an
    arbitrarily old tree can never repair a tag older than itself, which is
    every tag it exists for. `github.workflow_sha` keeps the YAML and the
    script it calls in one commit.
    """
    steps = _jobs(workflow)["tag-release-image"]["steps"]
    checkouts = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout")]
    assert len(checkouts) == 1, "one checkout, so there is one answer to which tree this runs"
    ref = checkouts[0].get("with", {}).get("ref", "")
    assert "workflow_sha" in ref, (
        "tag-release-image checks out %r; a release commit older than "
        "scripts/verify_release_tag.py then has no script to run" % (ref,)
    )
    assert "resolve-release-image" not in ref

    # And the build job must keep the opposite ref, for the opposite reason.
    build = [
        s
        for s in _jobs(workflow)["build-and-push"]["steps"]
        if str(s.get("uses", "")).startswith("actions/checkout")
    ]
    assert len(build) == 1
    assert "resolve-release-image.outputs.sha" in build[0]["with"]["ref"], (
        "build-and-push must build the release's own source commit"
    )


def test_the_retag_job_runs_scripts_only_from_the_repo_root(workflow):
    """Every repo path this job names comes out of that one checkout."""
    steps = _jobs(workflow)["tag-release-image"]["steps"]
    runs = " ".join(s.get("run", "") for s in steps)
    assert "verify_release_tag.py" in runs
    assert "scripts/verify_release_tag.py" in runs
