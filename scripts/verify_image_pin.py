"""Turn "this image exists" from a written claim into a checked fact.

WHAT THE CHART GUARD DOES AND DOES NOT DO. `charts/doc-tools/templates/_helpers.tpl`
(`doc-tools.image`) refuses a tag pin that carries no `image.unverifiedTagAck`, and
requires a digest to be well-formed (`sha256:` + 64 hex, 71 characters). That is a
real guard -- it is what caught the d7434d6 shape by construction, not by accident --
but it is a SHAPE check. Helm does not reach a registry when it renders a template.
It cannot: `helm template` and `helm upgrade` are asked to produce YAML, and nothing
in that path performs an HTTP request. So the guard can prove a digest is the right
LENGTH and prove a tag ack is non-empty; it cannot prove the thing on the other side
of either string was ever pushed. "This image exists" was, until this script, a
sentence a human typed into a values file and everyone else believed.

THE INCIDENT THIS WOULD HAVE CAUGHT. On 2026-09-25, sandbox was pinned to `d7434d6`
-- the #11 merge. There is no `:d7434d6` image: that PR corrected the ground-truth
denominator to 898 but left a test asserting 896, so its `main` build failed the
`tests` job and `build-and-push` never ran. `helm template` rendered the pin cleanly
(it was a syntactically fine tag with, at the time, no ack guard yet), Helm reported
the release successful, and the pod went to ImagePullBackOff on a manifest-unknown
several minutes later -- read, in the moment, as a cluster fault rather than as what
it was: a pin that named an image nobody had built. The `_helpers.tpl` guard added
after that incident stops a FUTURE bare tag from rendering without a paper trail. It
does not, and structurally cannot, stop a *tag with an ack* or a *digest* from being
wrong, because "wrong" here means "not present in the registry" and only the
registry can answer that. This script asks it.

WHAT THIS SCRIPT DOES NOT PROVE, stated so nobody mistakes a green run for more than
it is. A 200 on `GET /v2/<name>/manifests/<ref>` proves the registry has *a*
manifest at that reference, and (with `--require-platform`) that the index lists a
child manifest claiming to be built for that OS/architecture. It does NOT prove the
image runs, starts cleanly, or does the right thing -- only that the pull the
kubelet is about to attempt has something real to land on. Proving "it works" is
what the `tests` CI job and a real rollout are for; this job's whole and only scope
is the gap between "the pin renders" and "the pin names a pushed manifest".

WHY A SEPARATE SCRIPT AND NOT MORE `_helpers.tpl`. Helm's template language cannot
issue an HTTP request, so the check cannot live in the chart at any level -- it has
to live somewhere that runs in CI, once, against the tracked values files, which is
exactly what this is and why `.github/workflows/build-container.yml` runs it as its
own job rather than folding it into `helm template`/`helm lint`.

REGISTRY: ghcr.io ONLY. The image is public there (an anonymous
`GET https://ghcr.io/token?service=ghcr.io&scope=repository:<name>:pull` returns a
usable bearer token -- no GITHUB_TOKEN, no `packages: read` permission needed for
THIS repository today). If `image.repository` ever points anywhere else, this
script has no way to authenticate or query it, and the honest move is to REFUSE
(exit 2), not to silently report success for a registry it never actually asked.

EXIT CODES -- read this before wiring the number into anything.
    0  every checked pin resolved in the registry, and every `--require-platform`
       (if any were given) was found among its children.
    1  a pin is BAD: the manifest 404'd, a required platform is absent from an
       index that DID resolve, or a values file names neither a digest nor a tag
       at all (the same "does not say which code it runs" case `_helpers.tpl`
       refuses at render time -- this script refuses it again here because a
       `--values` override can point at a file the chart itself never renders).
    2  UNDETERMINED: a network/auth error, a non-ghcr registry, or YAML this
       script could not parse. This is NOT "probably fine" -- it means the check
       could not complete, so it must not report a 0.
Both 1 and 2 are non-zero ON PURPOSE: CI reds either way, because a build that
cannot be verified is not safer than one verified to be broken. They are kept
DISTINCT so a human reading a red job can tell the two apart at a glance: 1 says
"the pin is wrong, fix the pin"; 2 says "this check itself could not run, fix the
check or its access" -- a 500 from ghcr.io is not evidence the image is missing,
and must not be reported as if it were.

FAILING CLOSED IS DELIBERATE, both ways. A red for an auth reason (2) is safe: it
costs a rerun. A false green is not: it is exactly the belief the d7434d6 incident
ran on for several minutes before the kubelet disagreed. Nothing in this script
downgrades an exception or an unexpected status into a 0.

TARGET FILE SET: TRACKED, NOT GLOBBED. `git ls-files values-*.yaml` (run with cwd
set to the chart directory), not a filesystem glob. `values-sandbox.secret.yaml` is
an untracked local overlay carrying only `env:` -- passed IN ADDITION to
values-sandbox.yaml, never meant to render alone, and correctly has no image
stanza. `tests/test_chart_image_pin_guard.py::
test_every_TRACKED_values_file_names_an_image_and_is_not_refused` documents the
identical boundary for the chart guard's own test; this script keeps the same
rationale rather than re-deriving a different one. `--values FILE` (repeatable)
overrides the tracked-file discovery entirely, for CI-free local checks and for
this script's own tests.

USAGE:
    python scripts/verify_image_pin.py
    python scripts/verify_image_pin.py --require-platform linux/amd64 --require-platform linux/arm64
    python scripts/verify_image_pin.py --values /tmp/candidate-values.yaml
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHART_DIR = REPO_ROOT / "charts" / "doc-tools"

GHCR_HOST_PREFIX = "ghcr.io/"

# Every media type worth accepting for a manifest GET: an OCI or Docker index
# (manifest list), or a bare OCI single-platform manifest. Asking for all three
# lets a single-platform image (no `--require-platform` case) resolve too,
# instead of only ever matching multi-arch pushes.
ACCEPT_HEADER = (
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json,"
    "application/vnd.oci.image.manifest.v1+json"
)

# buildx emits these alongside the real platform manifests for provenance/SBOM
# attestations. They are not something anyone can deploy to, so a required
# platform must never be satisfied by one, and an index containing only these
# plus zero real platforms must read as "no platforms", not "found some".
_ATTESTATION_PLATFORM = ("unknown", "unknown")


class VerifyError(Exception):
    """A single pin's check could not be completed (network/auth/parse failure).

    Distinct from a pin simply being wrong (that is a normal return value, not
    an exception) -- this is the UNDETERMINED bucket, exit code 2.
    """


def _tracked_values_files(chart_dir: Path) -> list[Path]:
    """Ask git, not the filesystem, which values-*.yaml files this repo ships.

    See the module docstring's TARGET FILE SET section: a glob would also catch
    untracked local overlays like values-sandbox.secret.yaml, which carry no
    image stanza and were never meant to be checked on their own.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "values-*.yaml"],
            cwd=str(chart_dir),
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as e:
        # No git on PATH, or not a checkout. The target set is then UNKNOWN,
        # which is not the same as empty. Letting this propagate would exit 1
        # on an uncaught traceback, and 1 is reserved for "the pin is wrong" --
        # precisely the confusion the EXIT CODES section exists to prevent.
        raise VerifyError(
            f"could not list tracked values files in {chart_dir}: {e}"
        ) from e
    names = result.stdout.split()
    return [chart_dir / name for name in names]


def _load_values(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as e:
        raise VerifyError(f"could not read/parse {path}: {e}") from e
    return data or {}


def _pin_from_image_block(image: dict) -> tuple[str | None, str | None]:
    """Mirror `doc-tools.image`'s precedence exactly: digest wins outright.

    Returns (kind, ref) where kind is "digest", "tag", or None (neither set --
    the same "does not say which code it runs" case the chart itself refuses).
    """
    image = image or {}
    digest = str(image.get("digest") or "").strip()
    tag = str(image.get("tag") or "").strip()
    if digest:
        return "digest", digest
    if tag:
        return "tag", tag
    return None, None


def _ghcr_name(repository: str) -> str | None:
    """Extract the `<owner>/<image>` path ghcr.io's API expects, or None if
    `repository` is not a ghcr.io reference at all (only registry supported)."""
    repository = (repository or "").strip()
    if not repository.startswith(GHCR_HOST_PREFIX):
        return None
    name = repository[len(GHCR_HOST_PREFIX):].strip("/")
    return name or None


def _get_token(name: str) -> str:
    """Anonymous by default -- the package is public, measured directly against
    ghcr.io on 2026-09-26 (see the PR/commit this script shipped with). If
    GHCR_TOKEN or GITHUB_TOKEN is set, send it as HTTP Basic on the token
    request instead, so this keeps working the day the package is made
    private. GITHUB_ACTOR / GHCR_USERNAME name the Basic user; a literal
    "x-access-token" is GitHub's own convention when no better username exists.
    """
    url = f"https://ghcr.io/token?service=ghcr.io&scope=repository:{name}:pull"
    req = urllib.request.Request(url)
    secret = os.environ.get("GHCR_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if secret:
        user = (
            os.environ.get("GHCR_USERNAME")
            or os.environ.get("GITHUB_ACTOR")
            or "x-access-token"
        )
        creds = base64.b64encode(f"{user}:{secret}".encode()).decode("ascii")
        req.add_header("Authorization", f"Basic {creds}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    token = payload.get("token") or payload.get("access_token")
    if not token:
        raise VerifyError(f"ghcr.io token response for {name!r} carried no token")
    return token


def _fetch_manifest(name: str, ref: str) -> tuple[int, dict | None]:
    """THE ONE NETWORK SEAM. Tests monkeypatch this function and never touch a
    socket. Returns (http_status, manifest_dict_or_None) for any real HTTP
    response, including 404 -- a 404 is a determined, meaningful answer ("no
    such manifest"), not a failure of this function. Only a genuine transport
    failure (DNS, timeout, connection refused, auth-token fetch failure)
    raises, and callers must treat that as UNDETERMINED, not as a 404.
    """
    token = _get_token(name)
    url = f"https://ghcr.io/v2/{name}/manifests/{ref}"
    req = urllib.request.Request(
        url,
        headers={"Accept": ACCEPT_HEADER, "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            manifest = json.loads(body) if body else None
            return resp.status, manifest
    except urllib.error.HTTPError as e:
        # e.g. 404 manifest-unknown -- a real, determined response.
        try:
            body = e.read()
            manifest = json.loads(body) if body else None
        except (ValueError, OSError):
            manifest = None
        return e.code, manifest


def _index_platforms(manifest: dict) -> list[tuple[str, str]]:
    """(os, architecture) pairs from an index's child manifests, EXCLUDING the
    unknown/unknown attestation entries buildx adds (provenance/SBOM) -- those
    are not platforms anyone can deploy to."""
    platforms = []
    for child in manifest.get("manifests", []):
        platform = child.get("platform") or {}
        os_, arch = platform.get("os", ""), platform.get("architecture", "")
        if (os_, arch) == _ATTESTATION_PLATFORM:
            continue
        if os_ and arch:
            platforms.append((os_, arch))
    return platforms


def _parse_platform_arg(value: str) -> tuple[str, str]:
    if "/" not in value:
        raise argparse.ArgumentTypeError(
            f"--require-platform expects os/arch (e.g. linux/amd64), got {value!r}"
        )
    os_, _, arch = value.partition("/")
    return os_, arch


def verify_one(values_path: Path, require_platforms: list[tuple[str, str]]) -> dict:
    """Check a single values file's pin. Returns a result dict with keys:
    values_path, kind, ref, verdict ("OK"/"BAD"/"UNDETERMINED"), message,
    platforms (list of "os/arch" strings found, or []).

    Never raises: every failure mode this function can hit (bad YAML, no
    image block, non-ghcr repo, network error, 404, missing platform) is
    reported IN the result, because the caller aggregates many of these and a
    raised exception from one file must not abort checking the rest.
    """
    try:
        values = _load_values(values_path)
    except VerifyError as e:
        return _result(values_path, None, None, "UNDETERMINED", str(e))

    image = values.get("image") or {}
    repository = image.get("repository")
    kind, ref = _pin_from_image_block(image)

    if kind is None:
        return _result(
            values_path, None, None, "BAD",
            "neither image.digest nor image.tag is set -- this values file "
            "does not say which code it runs.",
        )

    name = _ghcr_name(repository) if repository else None
    if name is None:
        return _result(
            values_path, kind, ref, "UNDETERMINED",
            f"image.repository={repository!r} is not a ghcr.io reference; "
            "this check only knows how to query ghcr.io and must not silently "
            "pass a registry it cannot verify.",
        )

    try:
        status, manifest = _fetch_manifest(name, ref)
    except Exception as e:  # noqa: BLE001 - any transport failure is UNDETERMINED
        return _result(
            values_path, kind, ref, "UNDETERMINED",
            f"could not reach ghcr.io for {name}@{ref}: {e}",
        )

    if status == 404:
        return _result(
            values_path, kind, ref, "BAD",
            f"ghcr.io/v2/{name}/manifests/{ref} -> 404: no such manifest. "
            "This is exactly the d7434d6 shape -- a pin naming an image that "
            "was never pushed.",
        )
    if status != 200:
        return _result(
            values_path, kind, ref, "UNDETERMINED",
            f"ghcr.io/v2/{name}/manifests/{ref} -> HTTP {status} (expected 200 "
            "or 404); treating as undetermined rather than guessing.",
        )

    manifest = manifest or {}
    is_index = "manifests" in manifest
    platforms = _index_platforms(manifest) if is_index else []

    if require_platforms:
        if not is_index:
            return _result(
                values_path, kind, ref, "BAD",
                f"{name}@{ref} resolved to a single-platform manifest "
                f"(mediaType={manifest.get('mediaType')!r}), not an index -- "
                "there are no per-platform children to check "
                f"{require_platforms} against.",
                platforms=[],
            )
        missing = [p for p in require_platforms if p not in platforms]
        if missing:
            return _result(
                values_path, kind, ref, "BAD",
                f"{name}@{ref} resolved, but required platform(s) "
                f"{[f'{o}/{a}' for o, a in missing]} are absent from its index "
                f"(found: {[f'{o}/{a}' for o, a in platforms]}).",
                platforms=platforms,
            )

    return _result(
        values_path, kind, ref, "OK",
        f"{name}@{ref} resolved (HTTP 200).",
        platforms=platforms,
    )


def _result(values_path, kind, ref, verdict, message, platforms=None):
    return {
        "values_path": values_path,
        "kind": kind,
        "ref": ref,
        "verdict": verdict,
        "message": message,
        "platforms": platforms or [],
    }


def _abbrev_ref(kind, ref):
    if ref is None:
        return "-"
    if kind == "digest" and ref.startswith("sha256:") and len(ref) >= 19:
        return ref[:19] + "…"
    return ref


def _print_summary(results):
    header = f"{'values file':<28} {'kind':<8} {'ref':<22} {'verdict':<13} platforms"
    print(header)
    print("-" * len(header))
    for r in results:
        platforms = ", ".join(f"{o}/{a}" for o, a in r["platforms"]) or "-"
        print(
            f"{r['values_path'].name:<28} "
            f"{(r['kind'] or '-'):<8} "
            f"{_abbrev_ref(r['kind'], r['ref']):<22} "
            f"{r['verdict']:<13} "
            f"{platforms}"
        )
        print(f"    {r['message']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify_image_pin.py",
        description=(
            "Resolve each chart values file's pinned image (digest or tag) "
            "against the registry it lives in. See this file's module "
            "docstring for the full why. Exit codes: 0 every pin resolved "
            "(and every --require-platform present); 1 a pin is BAD (404, "
            "missing required platform, or no pin at all); 2 UNDETERMINED "
            "(network/auth error, non-ghcr registry, malformed YAML) -- both "
            "1 and 2 are failures, kept distinct so a reader can tell 'the "
            "pin is wrong' from 'the check could not run'."
        ),
    )
    parser.add_argument(
        "--chart", type=Path, default=DEFAULT_CHART_DIR,
        help="chart directory to discover tracked values-*.yaml files in "
             f"(default: {DEFAULT_CHART_DIR})",
    )
    parser.add_argument(
        "--require-platform", action="append", dest="require_platforms",
        type=_parse_platform_arg, default=[],
        metavar="os/arch",
        help="assert this os/arch appears among an index's real platform "
             "children (repeatable); unknown/unknown attestation entries "
             "never satisfy this",
    )
    parser.add_argument(
        "--values", action="append", dest="values", type=Path, default=None,
        metavar="FILE",
        help="check this values file instead of discovering tracked "
             "values-*.yaml under --chart (repeatable)",
    )
    args = parser.parse_args(argv)

    if args.values:
        values_files = args.values
    else:
        try:
            values_files = _tracked_values_files(args.chart)
        except VerifyError as e:
            print(f"{e} -- UNDETERMINED.", file=sys.stderr)
            return 2

    if not values_files:
        print("no values files to check (tracked set is empty) -- treating as "
              "UNDETERMINED rather than a vacuous pass.", file=sys.stderr)
        return 2

    results = [verify_one(p, args.require_platforms) for p in values_files]
    _print_summary(results)

    # Aggregate: a BAD (a confirmed-wrong pin) is reported over an
    # UNDETERMINED (a check that could not complete) when both occur, because
    # it is the more specific and more actionable of the two facts. Either way
    # the process exits non-zero -- see the module docstring's EXIT CODES
    # section for why 1 and 2 are kept distinct rather than collapsed to one.
    if any(r["verdict"] == "BAD" for r in results):
        return 1
    if any(r["verdict"] == "UNDETERMINED" for r in results):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
