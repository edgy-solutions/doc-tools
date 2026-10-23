"""Does a registry tag resolve to the digest it is supposed to name?

WHY THIS EXISTS, MEASURED. On 2026-10-23 the GitHub release `v0.2.0` was cut on
`133714c`, the commit the sandbox runs. Publishing it fired this repo's
`push: tags: ['v*']` trigger, which REBUILT the image from that same commit and
pushed it as both `v0.2.0` and `133714c…`. Same source, different bytes: the
new index was `sha256:9883b5d3…`, while the gated index the sandbox pins is
`sha256:ac853308…`. So the release tag named bytes that had never passed a
gate, and the commit-sha tag — the ONLY evidence linking `ac853308` to its
commit, since that build stamped no `org.opencontainers.image.revision` — was
moved off it. Nothing deployed changed, because a digest is immutable and the
pin is a digest; the digest simply became unreachable by any tag.

A release tag is therefore not a build. It is an assertion about which bytes a
version names, and an assertion is worth having only if something checks it.
This script is that check.

    python3 scripts/verify_release_tag.py --expect sha256:ac853308... v0.2.0 133714c...

THE CONTROLS RUN FIRST AND THEY ARE NOT DECORATION. A digest check whose
negative case was never exercised proves nothing: if the registry (or a proxy,
or a mistyped repository name) answers 200 to a truncated digest and to a
well-shaped digest nobody ever pushed, then every MATCH below it is an artifact
of the harness. Both controls MUST 404 before any row is reported, and when
either resolves this script refuses to print a verdict at all (exit 3) rather
than printing one that cannot be trusted.

EXIT CODES
    0  every reference resolved to --expect (or no --expect was given: report only)
    1  at least one reference is missing or resolves to other bytes
    2  UNDETERMINED: a network or auth failure. Not evidence of absence.
    3  CONTROLS BROKEN: the registry resolved something it must not have.

REGISTRY: ghcr.io only, same as scripts/verify_image_pin.py, and the same token
convention — `GHCR_TOKEN` or `GITHUB_TOKEN` is sent as HTTP Basic on the token
endpoint when present, and the anonymous pull token is used when it is not. A
read needs neither in a public package; CI passes one anyway so that a package
turned private does not silently become UNDETERMINED.
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_REPO = "edgy-solutions/doc-tools"

ACCEPT_HEADER = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)

# A truncated digest and a 64-hex digest that was never pushed. The first
# catches a registry or proxy that prefix-matches; the second catches one that
# answers 200 to anything shaped like a digest.
CONTROL_REFS = [
    ("sha256:" + "0" * 8, "a truncated digest"),
    ("sha256:" + "de" * 32, "a well-shaped digest nobody pushed"),
]

TIMEOUT_S = 30


class Undetermined(Exception):
    """A network or auth failure. NOT evidence that a manifest is absent."""


def _get_token(name: str) -> str:
    """Bearer token for pulls on `name`. Same convention as verify_image_pin."""
    url = f"https://ghcr.io/token?service=ghcr.io&scope=repository:{name}:pull"
    req = urllib.request.Request(url)
    secret = os.environ.get("GHCR_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if secret:
        user = os.environ.get("GITHUB_ACTOR") or "x-access-token"
        basic = base64.b64encode(f"{user}:{secret}".encode()).decode()
        req.add_header("Authorization", f"Basic {basic}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            payload = json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise Undetermined(f"could not fetch a ghcr.io pull token for {name}: {e}")
    token = payload.get("token") or payload.get("access_token")
    if not token:
        raise Undetermined(f"ghcr.io token response for {name!r} carried no token")
    return token


def resolve(name: str, ref: str) -> tuple[int, str | None]:
    """(status, digest) for one tag or digest reference. THE SEAM.

    This is the only function in the module that touches a socket, and it is
    what tests monkeypatch. A 404 is a RESULT, returned as (404, None) — the
    absence of a tag is exactly what this script is often asked to measure. A
    transport failure is not a result and raises Undetermined.
    """
    token = _get_token(name)
    req = urllib.request.Request(
        f"https://ghcr.io/v2/{name}/manifests/{ref}", method="HEAD"
    )
    req.add_header("Accept", ACCEPT_HEADER)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return r.status, r.headers.get("Docker-Content-Digest")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            # 401/403 on a HEAD of a manifest is how ghcr.io reports "no such
            # tag" for a package the caller cannot list. Treated as absence
            # here rather than as a transport failure, which is why the
            # controls matter: they establish that absence is reported at all.
            return e.code, None
        raise Undetermined(f"ghcr.io/v2/{name}/manifests/{ref} -> HTTP {e.code}")
    except (urllib.error.URLError, OSError) as e:
        raise Undetermined(f"could not reach ghcr.io for {name}/{ref}: {e}")


def run(name, refs, expect=None, resolver=None):
    """Resolve the controls, then the references. Returns a result dict.

    Pure apart from `resolver`, so the verdict logic is testable without a
    socket. `controls_ok` False short-circuits: `refs` is left empty and no
    verdict is computed, because a verdict would be meaningless.

    `resolver` defaults to None rather than to `resolve` itself so that the
    lookup happens per call: a default argument would bind the function object
    at import time and a test that replaces `verify_release_tag.resolve` would
    silently keep hitting the network.
    """
    resolver = resolver or resolve
    controls = []
    controls_ok = True
    for ref, why in CONTROL_REFS:
        status, digest = resolver(name, ref)
        ok = status in (401, 403, 404)
        controls.append({"ref": ref, "why": why, "status": status, "ok": ok})
        if not ok:
            controls_ok = False

    result = {
        "name": name,
        "expect": expect,
        "controls": controls,
        "controls_ok": controls_ok,
        "refs": [],
        "exit": 0,
    }
    if not controls_ok:
        result["exit"] = 3
        return result

    for ref in refs:
        status, digest = resolver(name, ref)
        row = {"ref": ref, "status": status, "digest": digest}
        if expect is not None:
            row["verdict"] = "MATCH" if digest == expect else "MISMATCH"
        result["refs"].append(row)

    if expect is not None and any(r["verdict"] != "MATCH" for r in result["refs"]):
        result["exit"] = 1
    return result


def render(result) -> str:
    """The result as the markdown that goes in a job summary / release note."""
    name = result["name"]
    lines = [f"### Tag resolution — `ghcr.io/{name}`", ""]
    lines.append("| control | reference | HTTP | verdict |")
    lines.append("|---|---|---|---|")
    for c in result["controls"]:
        lines.append(
            f"| {c['why']} | `{c['ref'][:22]}…` | {c['status']} | "
            f"{'ok (absent, as required)' if c['ok'] else '**BROKEN — it resolved**'} |"
        )
    lines.append("")
    if not result["controls_ok"]:
        lines.append(
            "**CONTROLS BROKEN.** The registry resolved a reference it must not "
            "have, so no tag verdict is reported: any MATCH here would be an "
            "artifact of the check, not a fact about the image."
        )
        return "\n".join(lines) + "\n"
    if result["expect"]:
        lines.append(f"Expected digest: `{result['expect']}`")
        lines.append("")
    lines.append("| reference | HTTP | resolves to | verdict |")
    lines.append("|---|---|---|---|")
    for r in result["refs"]:
        verdict = r.get("verdict", "—")
        if verdict == "MISMATCH":
            verdict = "**MISMATCH**"
        lines.append(
            f"| `{r['ref']}` | {r['status']} | `{r['digest'] or '<none>'}` | {verdict} |"
        )
    lines.append("")
    if result["exit"] == 0 and result["expect"]:
        lines.append(
            f"All {len(result['refs'])} reference(s) resolve to the pinned digest. "
            "No rebuild: these are the bytes that passed the gates."
        )
    elif result["exit"] == 1:
        bad = [r["ref"] for r in result["refs"] if r.get("verdict") == "MISMATCH"]
        lines.append(
            f"**{len(bad)} of {len(result['refs'])} reference(s) do not resolve to "
            f"the expected digest:** {', '.join('`' + b + '`' for b in bad)}."
        )
    return "\n".join(lines) + "\n"


def _emit(path, result):
    """`exists` and `digest` for the FIRST reference, for a job output.

    Deliberately first-reference-only and documented as such: a caller asking
    "is there already an image for this commit" passes exactly one reference.
    """
    first = result["refs"][0] if result["refs"] else {"status": 0, "digest": None}
    exists = "true" if first["status"] == 200 and first["digest"] else "false"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"exists={exists}\n")
        fh.write(f"digest={first['digest'] or ''}\n")
        fh.write(f"controls_ok={'true' if result['controls_ok'] else 'false'}\n")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("refs", nargs="+", help="tags and/or digests to resolve")
    p.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO,
        help="ghcr.io package path, <owner>/<name> (default: $GITHUB_REPOSITORY)",
    )
    p.add_argument("--expect", help="digest every reference must resolve to")
    p.add_argument("--summary-file", help="append the markdown table here")
    p.add_argument("--github-output", help="append exists=/digest= for the first ref")
    args = p.parse_args(argv)

    name = args.repo.lower()
    if args.expect and not args.expect.startswith("sha256:"):
        p.error(f"--expect must be a sha256: digest, got {args.expect!r}")

    try:
        result = run(name, args.refs, args.expect)
    except Undetermined as e:
        print(f"UNDETERMINED: {e}", file=sys.stderr)
        print(
            "This is a failure of the CHECK, not evidence the tag is wrong.",
            file=sys.stderr,
        )
        return 2

    text = render(result)
    print(text)
    if args.summary_file:
        with open(args.summary_file, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    if args.github_output:
        _emit(args.github_output, result)
    return result["exit"]


if __name__ == "__main__":
    sys.exit(main())
