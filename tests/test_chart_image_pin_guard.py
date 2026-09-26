"""The chart must REFUSE a pin it cannot show to be real.

WHY THIS FILE EXISTS AT ALL. On 2026-09-25 sandbox was pinned to d7434d6, the
#11 merge. There is no `:d7434d6` image: that PR corrected the ground-truth
denominator to 898 but left a test asserting 896, so its `main` build failed the
`tests` job and `build-and-push` never ran. The pin rendered cleanly, Helm
reported the release successful, and the pod went to ImagePullBackOff minutes
later on a manifest-unknown -- where it reads as a cluster fault rather than as a
bad pin. The inline `required "image.tag is required"` did not catch it and could
not: it refuses an ABSENT tag, and the tag was present. Absent and never-built
are different facts, and only the first one had a guard.

WHAT IS ACTUALLY BEING TESTED. Not that images exist -- Helm does not reach the
registry at render time, so neither the chart nor this file can check that. What
is tested is the one honest thing available: the pin that CANNOT lie (a digest,
which exists only as the output of a real push) renders freely, and the pin that
CAN lie (a tag, which is copyable out of `git log`) is refused until someone
states in a tracked file that they checked. The guard converts an invisible
assumption into a reviewable claim. It does not verify it.

These tests shell out to the real `helm` binary rather than asserting on template
text, because the thing under test IS the rendering -- a guard that fails to
parse refuses everything and would satisfy any grep-based test. That is not
hypothetical: the first draft of this helper had a doubled closing paren and
refused every input, including the digest path it exists to enable.

Skipped when helm is absent. CI has no helm step today, so a skip here means
"unproven", not "fine".
"""

import shutil
import subprocess
from pathlib import Path

import pytest

CHART = Path(__file__).resolve().parents[1] / "charts" / "doc-tools"

HELM = shutil.which("helm")
requires_helm = pytest.mark.skipif(HELM is None, reason="helm binary not on PATH")

GOOD_DIGEST = "sha256:" + "0123456789abcdef" * 4  # 64 hex, 71 chars total


def render(*args, values_file=None):
    """helm template the chart. Returns (returncode, stdout + stderr)."""
    cmd = [HELM, "template", "t", str(CHART)]
    if values_file:
        cmd += ["-f", str(CHART / values_file)]
    cmd += list(args)
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def image_line(out):
    """The container image reference, from the app container only.

    Scoped deliberately: the chart also renders a busybox init container, and a
    test that grabbed the first `image:` in the manifest stream would pass while
    the app image was wrong.
    """
    lines = [
        ln.strip()
        for ln in out.splitlines()
        if ln.strip().startswith("image:") and "busybox" not in ln
    ]
    assert len(lines) == 1, f"expected exactly one app image line, got {lines}"
    return lines[0]


# --------------------------------------------------------------------------
# The refusals. Each one is a pin that used to render.
# --------------------------------------------------------------------------

@requires_helm
def test_a_bare_tag_is_REFUSED():
    """THE REGRESSION. This is the d7434d6 shape exactly: a plausible sha, no
    evidence it was ever built. It rendered before this guard existed."""
    rc, out = render("--set", "image.tag=d7434d6")
    assert rc != 0, f"a tag with no evidence of a build rendered:\n{out}"
    assert "REFUSING to pin by tag alone" in out
    # The refusal has to name the way out, or the next person deletes the guard
    # instead of using it.
    assert "image.digest" in out
    assert "image.unverifiedTagAck" in out


@requires_helm
def test_an_EMPTY_ack_does_not_satisfy_the_guard():
    """An ack set to the empty string must not count. Setting a value to empty
    is how a guard gets silenced without anyone appearing to silence it."""
    rc, out = render("--set", "image.tag=d7434d6", "--set", "image.unverifiedTagAck=")
    assert rc != 0, f"an empty ack satisfied the guard:\n{out}"
    assert "REFUSING to pin by tag alone" in out


@requires_helm
def test_NEITHER_digest_nor_tag_is_refused():
    """The chart must not fall back to appVersion, which is a scaffold string
    and not a publishable image."""
    rc, out = render()
    assert rc != 0, f"the chart rendered without being told which code to run:\n{out}"
    assert "does not say which code it runs" in out


@requires_helm
@pytest.mark.parametrize(
    "bad,expected",
    [
        ("0123456789abcdef" * 4, 'must start with "sha256:"'),
        ("sha256:0123", "64 hex characters"),
        (GOOD_DIGEST + "ab", "64 hex characters"),
    ],
    ids=["no-sha256-prefix", "truncated", "over-long"],
)
def test_a_MALFORMED_digest_is_refused(bad, expected):
    """A digest is a proof-carrying pin only if it is whole. A truncated one
    fails at the kubelet -- the precise failure that pinning by digest removes."""
    rc, out = render("--set", f"image.digest={bad}")
    assert rc != 0, f"malformed digest {bad!r} rendered:\n{out}"
    assert expected in out


# --------------------------------------------------------------------------
# The paths that must stay open. A guard that refuses everything is not a
# guard, and this is the half the doubled-paren bug broke.
# --------------------------------------------------------------------------

@requires_helm
def test_a_DIGEST_renders_and_needs_no_acknowledgement():
    """The preferred path. No ack is required because a digest cannot name an
    image that was never pushed -- there is nothing left to attest to."""
    rc, out = render("--set", f"image.digest={GOOD_DIGEST}")
    assert rc == 0, f"the digest path was refused:\n{out}"
    line = image_line(out)
    assert line.endswith(f'@{GOOD_DIGEST}"'), line
    # repo@digest, never repo:tag@digest.
    assert line.split("@")[0].count(":") == 1, f"a tag leaked into a digest pin: {line}"


@requires_helm
def test_a_tag_WITH_an_acknowledgement_renders():
    """The escape hatch stays usable. Refusing tags outright would strand
    anyone mid-incident who has verified a tag by hand."""
    rc, out = render(
        "--set", "image.tag=deadbeef",
        "--set",
        "image.unverifiedTagAck=https://github.com/edgy-solutions/doc-tools/actions/runs/1",
    )
    assert rc == 0, f"an acknowledged tag was refused:\n{out}"
    assert image_line(out).endswith(':deadbeef"')


@requires_helm
def test_the_DIGEST_WINS_when_both_are_set():
    """And it drags no ack requirement along with it. During a cutover both
    fields will be set at once; the stronger pin must be the one used, and it
    must not be blocked by the weaker one's paperwork."""
    rc, out = render("--set", f"image.digest={GOOD_DIGEST}", "--set", "image.tag=d7434d6")
    assert rc == 0, f"setting both fields was refused:\n{out}"
    line = image_line(out)
    assert f"@{GOOD_DIGEST}" in line
    assert "d7434d6" not in line


@requires_helm
def test_the_version_label_survives_a_DIGEST_only_pin():
    """A digest-pinned release still has to answer which code it is running.

    This guards the seam between the two halves of the change: the image moved
    to the digest path while the version label still keyed off image.tag, which
    for a digest-only pin is unset -- so the label silently vanished.
    """
    rc, out = render("--set", f"image.digest={GOOD_DIGEST}")
    assert rc == 0, out
    assert 'app.kubernetes.io/version: "sha256-0123456789ab"' in out, (
        "a digest-pinned release rendered with no version label:\n"
        + "\n".join(ln for ln in out.splitlines() if "version" in ln)
    )


# --------------------------------------------------------------------------
# The guard must not refuse the values files that are actually committed.
# --------------------------------------------------------------------------

@requires_helm
def test_the_COMMITTED_sandbox_values_still_render():
    """The failure mode this catches is a guard that is correct and also
    unshippable. If values-sandbox.yaml stops rendering, the morning roll fails
    at `helm upgrade` -- better than ImagePullBackOff, but still an outage, and
    one this repo can detect for free.
    """
    rc, out = render(values_file="values-sandbox.yaml")
    assert rc == 0, f"the committed sandbox values are refused by their own chart:\n{out}"
    line = image_line(out)
    assert "ghcr.io/edgy-solutions/doc-tools" in line
    # Pinned, whichever way. What must never render is a floating tag.
    assert ":latest" not in line
    assert not line.endswith('doc-tools"')


@requires_helm
def test_every_TRACKED_values_file_names_an_image_and_is_not_refused():
    """Every committed environment file, not just sandbox. A new one that omits
    the ack (or the digest) should fail here, in a test, not at rollout.

    TRACKED, not globbed. A glob catches `values-sandbox.secret.yaml`, which is
    an untracked local overlay carrying only `env:` -- it is passed IN ADDITION
    to values-sandbox.yaml and was never meant to render on its own, so it has
    no image stanza and the guard correctly refuses it. Asking git which files
    the repo actually ships is the real boundary, and it keeps whatever
    untracked overlays a given machine happens to have out of the assertion.
    """
    listed = subprocess.run(
        ["git", "ls-files", "values-*.yaml"],
        cwd=str(CHART), capture_output=True, text=True, check=True,
    ).stdout.split()
    assert listed, "no tracked environment values files found; this would vacuously pass"
    for name in listed:
        rc, out = render(values_file=name)
        assert rc == 0, f"{name} is refused by the chart:\n{out}"
        assert image_line(out)
