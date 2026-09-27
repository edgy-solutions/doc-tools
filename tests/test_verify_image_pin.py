"""Tests for the CI registry-resolution check, `scripts/verify_image_pin.py`.

WHAT THIS FILE PROVES AND WHAT IT DELIBERATELY DOES NOT. The chart guard in
`_helpers.tpl` (see `tests/test_chart_image_pin_guard.py`) proves a pin is
well-SHAPED. It cannot prove a pin is real, because Helm never reaches a
registry. `verify_image_pin.py` is the piece that does reach one -- and this
file has to prove THAT logic (precedence, platform filtering, exit codes)
without actually reaching one, or the suite stops being safe to run offline
and in CI at the same time.

THE SEAM: `verify_image_pin._fetch_manifest(name, ref) -> (status, manifest)`
is the one place the module touches a socket (it internally also calls
`_get_token`, which every test here bypasses by monkeypatching the caller,
not the token fetch). Every test monkeypatches `_fetch_manifest` to a stub
and asserts on how the module drives it and reports on what it returns.
Imported by path, like `pcn_score` in `tests/test_pcn_score.py`: `scripts/` is
not a package and should not be made to look like library code.
"""
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vip = _load("verify_image_pin")

GOOD_DIGEST = "sha256:" + "0123456789abcdef" * 4  # 64 hex, 71 chars total
BAD_DIGEST = "sha256:" + "0123456789abcdef" * 4  # shape-valid but never pushed
D7434D6_TAG = "d7434d6"  # the real incident's exact shape: a plausible, unbuilt tag

INDEX_BOTH_PLATFORMS = {
    "mediaType": "application/vnd.oci.image.index.v1+json",
    "manifests": [
        {"platform": {"os": "linux", "architecture": "amd64"}},
        {"platform": {"os": "linux", "architecture": "arm64"}},
        # buildx attestations -- must never count as a platform.
        {"platform": {"os": "unknown", "architecture": "unknown"}},
        {"platform": {"os": "unknown", "architecture": "unknown"}},
    ],
}

INDEX_AMD64_ONLY = {
    "mediaType": "application/vnd.oci.image.index.v1+json",
    "manifests": [
        {"platform": {"os": "linux", "architecture": "amd64"}},
        {"platform": {"os": "unknown", "architecture": "unknown"}},
    ],
}

SINGLE_PLATFORM_MANIFEST = {
    "mediaType": "application/vnd.oci.image.manifest.v1+json",
    "config": {"digest": "sha256:deadbeef"},
}


def _values_file(tmp_path, image, name="values-x.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump({"image": image}), encoding="utf-8")
    return path


def _run(tmp_path, image, require_platforms=None, fetch_stub=None, monkeypatch=None):
    """Write a values file, wire the stub, invoke main(), return its exit code."""
    path = _values_file(tmp_path, image)
    if fetch_stub is not None:
        monkeypatch.setattr(vip, "_fetch_manifest", fetch_stub)
    argv = ["--values", str(path)]
    for p in (require_platforms or []):
        argv += ["--require-platform", p]
    return vip.main(argv)


# ---------------------------------------------------------------------------
# Precedence: digest wins outright, mirroring _helpers.tpl exactly.
# ---------------------------------------------------------------------------

def test_digest_resolves_exit_0(tmp_path, monkeypatch):
    stub = lambda name, ref: (200, INDEX_BOTH_PLATFORMS)
    rc = _run(tmp_path, {"repository": "ghcr.io/edgy-solutions/doc-tools", "digest": GOOD_DIGEST},
              fetch_stub=stub, monkeypatch=monkeypatch)
    assert rc == 0


def test_digest_404_exit_1(tmp_path, monkeypatch):
    stub = lambda name, ref: (404, None)
    rc = _run(tmp_path, {"repository": "ghcr.io/edgy-solutions/doc-tools", "digest": BAD_DIGEST},
              fetch_stub=stub, monkeypatch=monkeypatch)
    assert rc == 1


def test_tag_404_is_the_d7434d6_shape_exit_1(tmp_path, monkeypatch):
    stub = lambda name, ref: (404, None)
    rc = _run(tmp_path, {"repository": "ghcr.io/edgy-solutions/doc-tools", "tag": D7434D6_TAG},
              fetch_stub=stub, monkeypatch=monkeypatch)
    assert rc == 1


def test_digest_wins_when_both_set_tag_never_fetched(tmp_path, monkeypatch):
    calls = []

    def stub(name, ref):
        calls.append(ref)
        return 200, INDEX_BOTH_PLATFORMS

    rc = _run(
        tmp_path,
        {"repository": "ghcr.io/edgy-solutions/doc-tools", "digest": GOOD_DIGEST, "tag": D7434D6_TAG},
        fetch_stub=stub, monkeypatch=monkeypatch,
    )
    assert rc == 0
    assert calls == [GOOD_DIGEST], f"expected only the digest to be fetched, got {calls}"
    assert D7434D6_TAG not in calls


def test_tag_only_pin_is_verified(tmp_path, monkeypatch):
    stub = lambda name, ref: (200, SINGLE_PLATFORM_MANIFEST)
    rc = _run(tmp_path, {"repository": "ghcr.io/edgy-solutions/doc-tools", "tag": "55a6292e71671690a539f48a3478b7cfd7667727"},
              fetch_stub=stub, monkeypatch=monkeypatch)
    assert rc == 0


def test_neither_digest_nor_tag_exit_1(tmp_path, monkeypatch):
    # No fetch should even be attempted -- there is no ref to look up.
    def stub(name, ref):
        raise AssertionError("must not fetch a manifest with no pin at all")

    monkeypatch.setattr(vip, "_fetch_manifest", stub)
    rc = _run(tmp_path, {"repository": "ghcr.io/edgy-solutions/doc-tools"})
    assert rc == 1


# ---------------------------------------------------------------------------
# Platform requirements.
# ---------------------------------------------------------------------------

def test_required_platform_present_exit_0(tmp_path, monkeypatch):
    stub = lambda name, ref: (200, INDEX_BOTH_PLATFORMS)
    rc = _run(tmp_path, {"repository": "ghcr.io/edgy-solutions/doc-tools", "digest": GOOD_DIGEST},
              require_platforms=["linux/amd64", "linux/arm64"],
              fetch_stub=stub, monkeypatch=monkeypatch)
    assert rc == 0


def test_required_platform_absent_exit_1(tmp_path, monkeypatch):
    stub = lambda name, ref: (200, INDEX_AMD64_ONLY)
    rc = _run(tmp_path, {"repository": "ghcr.io/edgy-solutions/doc-tools", "digest": GOOD_DIGEST},
              require_platforms=["linux/amd64", "linux/arm64"],
              fetch_stub=stub, monkeypatch=monkeypatch)
    assert rc == 1


def test_unknown_unknown_does_not_satisfy_a_required_platform(tmp_path, monkeypatch):
    """An index with ONLY attestation entries (no real arm64 child) must not
    let `--require-platform linux/arm64` pass just because *something* is
    present in `manifests[]`."""
    only_attestations = {
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {"platform": {"os": "unknown", "architecture": "unknown"}},
            {"platform": {"os": "unknown", "architecture": "unknown"}},
        ],
    }
    stub = lambda name, ref: (200, only_attestations)
    rc = _run(tmp_path, {"repository": "ghcr.io/edgy-solutions/doc-tools", "digest": GOOD_DIGEST},
              require_platforms=["linux/arm64"],
              fetch_stub=stub, monkeypatch=monkeypatch)
    assert rc == 1


def test_required_platform_against_single_platform_manifest_fails_explained(tmp_path, monkeypatch):
    stub = lambda name, ref: (200, SINGLE_PLATFORM_MANIFEST)
    path = _values_file(tmp_path, {"repository": "ghcr.io/edgy-solutions/doc-tools", "digest": GOOD_DIGEST})
    monkeypatch.setattr(vip, "_fetch_manifest", stub)
    rc = vip.main(["--values", str(path), "--require-platform", "linux/arm64"])
    assert rc == 1


# ---------------------------------------------------------------------------
# UNDETERMINED (exit 2): the check could not run, which must never read as 0.
# ---------------------------------------------------------------------------

def test_network_error_exit_2_not_0_not_1(tmp_path, monkeypatch):
    def stub(name, ref):
        raise OSError("simulated DNS/connection failure")

    rc = _run(tmp_path, {"repository": "ghcr.io/edgy-solutions/doc-tools", "digest": GOOD_DIGEST},
              fetch_stub=stub, monkeypatch=monkeypatch)
    assert rc == 2


def test_non_ghcr_repository_exit_2(tmp_path, monkeypatch):
    def stub(name, ref):
        raise AssertionError("a non-ghcr registry must never be queried")

    monkeypatch.setattr(vip, "_fetch_manifest", stub)
    rc = _run(tmp_path, {"repository": "docker.io/edgy-solutions/doc-tools", "digest": GOOD_DIGEST})
    assert rc == 2


def test_unexpected_http_status_is_undetermined_not_a_pass(tmp_path, monkeypatch):
    """500 is neither 'resolved' nor 'confirmed missing' -- it must not be
    silently treated as either 0 or 1's more confident cousin."""
    stub = lambda name, ref: (500, None)
    rc = _run(tmp_path, {"repository": "ghcr.io/edgy-solutions/doc-tools", "digest": GOOD_DIGEST},
              fetch_stub=stub, monkeypatch=monkeypatch)
    assert rc == 2


def test_malformed_yaml_is_undetermined(tmp_path, monkeypatch):
    def stub(name, ref):
        raise AssertionError("malformed YAML must never reach a network call")

    monkeypatch.setattr(vip, "_fetch_manifest", stub)
    path = tmp_path / "values-broken.yaml"
    path.write_text("image: [unterminated\n", encoding="utf-8")
    rc = vip.main(["--values", str(path)])
    assert rc == 2


# ---------------------------------------------------------------------------
# The tracked-files boundary itself (not just its rationale, verified live).
# ---------------------------------------------------------------------------

GIT = shutil.which("git")
requires_git = pytest.mark.skipif(GIT is None, reason="git binary not on PATH")


@requires_git
def test_tracked_files_boundary_untracked_file_not_picked_up(tmp_path):
    """`git ls-files` (staged is enough -- no commit required) must return the
    added file and must NOT return the untracked one sitting right next to
    it, the same boundary `values-sandbox.secret.yaml` relies on in the real
    chart directory."""
    chart_dir = tmp_path / "chart"
    chart_dir.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=chart_dir, check=True)
    tracked = chart_dir / "values-sandbox.yaml"
    tracked.write_text(yaml.safe_dump({"image": {"repository": "ghcr.io/x/y", "digest": GOOD_DIGEST}}))
    subprocess.run(["git", "add", "values-sandbox.yaml"], cwd=chart_dir, check=True)
    untracked = chart_dir / "values-sandbox.secret.yaml"
    untracked.write_text(yaml.safe_dump({"env": {"FOO": "bar"}}))

    found = vip._tracked_values_files(chart_dir)
    names = {p.name for p in found}
    assert names == {"values-sandbox.yaml"}, (
        f"expected only the tracked file, got {names}"
    )


# ---------------------------------------------------------------------------
# The one live test. Opt-in only: everything above proves the LOGIC without a
# socket; this proves the actual, committed pin still resolves in the real
# registry. It is not run by default because (a) the offline suite must stay
# offline-safe and fast, and (b) a registry hiccup on an unrelated PR must not
# fail this repo's suite -- that is exactly the "a network error must read as
# 2, not silently as anything else" property, applied to the test suite's own
# reliability rather than to the script's exit code.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    __import__("os").environ.get("VERIFY_IMAGE_PIN_LIVE") != "1",
    reason="opt-in: set VERIFY_IMAGE_PIN_LIVE=1 to hit the real ghcr.io registry",
)
def test_live_committed_sandbox_pin_resolves_with_both_platforms():
    rc = vip.main(["--require-platform", "linux/amd64", "--require-platform", "linux/arm64"])
    assert rc == 0
