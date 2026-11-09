"""Read an OCI index and both of its platform children for a doc-tools pin.

Prints exactly the facts the values-sandbox.yaml pin comment has to carry:
the child digests, the architecture taken from each child's CONFIG BLOB
(never the index platform claim), and the revision/version labels and
created timestamp read off the same blob.

Usage:  python read_index.py <repo> <index-digest-or-tag>

No third-party imports: the Bash tool has no jq and this must not depend on
the project environment.
"""

import json
import subprocess
import sys

ATTESTATION = "unknown"


def crane(*args):
    out = subprocess.run(
        ["crane", *args], capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        sys.exit(f"crane {' '.join(args)} failed:\n{out.stderr.strip()}")
    return out.stdout


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    repo, ref = sys.argv[1], sys.argv[2]
    sep = "@" if ref.startswith("sha256:") else ":"
    target = f"{repo}{sep}{ref}"

    index_digest = crane("digest", target).strip()
    index = json.loads(crane("manifest", target))

    print(f"index      {index_digest}")
    print(f"mediaType  {index.get('mediaType')}")
    print(f"manifests  {len(index.get('manifests', []))}")
    print()

    real, attest = [], 0
    for m in index.get("manifests", []):
        plat = m.get("platform", {})
        if plat.get("architecture") == ATTESTATION or plat.get("os") == ATTESTATION:
            attest += 1
            continue
        real.append((m["digest"], plat))

    for digest, claim in real:
        cfg = json.loads(crane("config", f"{repo}@{digest}"))
        labels = (cfg.get("config") or {}).get("Labels") or {}
        blob_arch = f"{cfg.get('os')}/{cfg.get('architecture')}"
        claim_arch = f"{claim.get('os')}/{claim.get('architecture')}"
        agree = "OK" if blob_arch == claim_arch else "MISMATCH"
        print(f"child      {digest}")
        print(f"  blob     {blob_arch}   (index claimed {claim_arch})  [{agree}]")
        print(f"  revision {labels.get('org.opencontainers.image.revision')}")
        print(f"  version  {labels.get('org.opencontainers.image.version')}")
        print(f"  created  {cfg.get('created')}")
        print()

    print(f"attestation manifests (unknown/unknown, satisfy no platform): {attest}")

    revs = set()
    for digest, _ in real:
        cfg = json.loads(crane("config", f"{repo}@{digest}"))
        labels = (cfg.get("config") or {}).get("Labels") or {}
        revs.add(labels.get("org.opencontainers.image.revision"))
    if len(revs) == 1:
        print(f"both children carry the SAME revision: {revs.pop()}")
    else:
        print(f"REVISION DISAGREEMENT across children: {sorted(map(str, revs))}")


if __name__ == "__main__":
    main()
