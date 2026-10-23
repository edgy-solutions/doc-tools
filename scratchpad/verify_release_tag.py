"""Does a GHCR tag resolve to the digest it is supposed to pin?

Read-only, anonymous pull token, same route as resolve_tag_digest.py and
digest_to_commit.py. Prints the Docker-Content-Digest the registry returns for
each reference, and runs the short/fake controls: a truncated digest and a
digest that does not exist MUST both 404, or the check proves nothing.

    .venv/Scripts/python scratchpad/verify_release_tag.py v0.2.0 sha256:ac853308...

With two arguments it also asserts equality and exits non-zero on a mismatch.
With one or more references and no expected digest it just reports.
"""
import json
import sys
import urllib.error
import urllib.request

REPO = "edgy-solutions/doc-tools"

ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


def _token():
    url = f"https://ghcr.io/token?service=ghcr.io&scope=repository:{REPO}:pull"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())["token"]


def resolve(ref, token):
    """(status, digest) for one tag or digest reference. 404 is a result."""
    req = urllib.request.Request(
        f"https://ghcr.io/v2/{REPO}/manifests/{ref}", method="HEAD"
    )
    req.add_header("Accept", ACCEPT)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.headers.get("Docker-Content-Digest")
    except urllib.error.HTTPError as e:
        return e.code, None


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2

    expected = None
    if len(args) >= 2 and args[-1].startswith("sha256:"):
        expected = args[-1]
        refs = args[:-1]
    else:
        refs = args

    token = _token()

    # The controls go first, deliberately: if a truncated or invented digest
    # resolves, every row below it is meaningless.
    controls = [
        ("sha256:" + "0" * 8, "short digest"),
        ("sha256:" + "de" * 32, "digest that does not exist"),
    ]
    print("controls (both MUST be 404):")
    control_ok = True
    for ref, why in controls:
        status, digest = resolve(ref, token)
        flag = "ok" if status == 404 else "BROKEN"
        if status != 404:
            control_ok = False
        print(f"  {flag:7} http={status:3}  {why}  {ref[:22]}...")
    if not control_ok:
        print("\nCONTROLS BROKEN -- the registry resolved something it should not. Stop.")
        return 3

    print("\nreferences:")
    results = {}
    for ref in refs:
        status, digest = resolve(ref, token)
        results[ref] = (status, digest)
        print(f"  http={status:3}  {ref}\n          -> {digest or '<none>'}")

    if expected is None:
        return 0

    print(f"\nexpected: {expected}")
    bad = [r for r, (s, d) in results.items() if d != expected]
    for ref in refs:
        status, digest = results[ref]
        verdict = "MATCH" if digest == expected else "MISMATCH"
        print(f"  {verdict:9} {ref}")
    if bad:
        print(f"\n{len(bad)} of {len(refs)} reference(s) do not resolve to the expected digest.")
        return 1
    print(f"\nAll {len(refs)} reference(s) resolve to the pinned digest.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
