"""Pre-roll diff: rendered chart vs the live release, secrets redacted.

Prints a length and a sha256 prefix for anything secret-bearing, never a value
(the repo's standing convention). Redaction is applied BEFORE any output, and
belt-and-braces: a line is redacted if its key name looks secret-ish OR if it
sits inside a Secret resource's data/stringData block.
"""
from __future__ import annotations

import difflib
import hashlib
import re
import subprocess
import sys

NS = "sandbox"
REL = "doc-tools"
CHART = "charts/doc-tools"
VALUES = ("charts/doc-tools/values-sandbox.yaml",
          "charts/doc-tools/values-sandbox.secret.yaml")

SECRETISH = ("TOKEN", "SECRET", "KEY", "PASSWORD", "PASS", "CRED")


def run(args: list[str]) -> str:
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"FAILED: {' '.join(args)}\n{p.stderr[:2000]}")
    return p.stdout


def fingerprint(value: str) -> str:
    raw = value.strip().strip('"').strip("'")
    if not raw:
        return '""'
    h = hashlib.sha256(raw.encode()).hexdigest()[:8]
    return f"<len={len(raw)} sha256:{h}>"


KV = re.compile(r"^(\s*)([A-Za-z0-9_.\-/]+):\s*(\S.*)$")


def redact(text: str) -> list[str]:
    out: list[str] = []
    in_secret_kind = False
    in_data_block = False
    data_indent = 0
    for line in text.splitlines():
        if line.startswith("---") or re.match(r"^\s*kind:\s*", line):
            in_secret_kind = bool(re.match(r"^\s*kind:\s*Secret\s*$", line))
            in_data_block = False
        m = KV.match(line)
        if m and m.group(2) in ("data", "stringData"):
            in_data_block = True
            data_indent = len(m.group(1))
            out.append(line)
            continue
        if in_data_block and m and len(m.group(1)) <= data_indent:
            in_data_block = False
        if m:
            indent, key, value = m.groups()
            secretish = any(s in key.upper() for s in SECRETISH)
            if secretish or (in_secret_kind and in_data_block):
                out.append(f"{indent}{key}: {fingerprint(value)}")
                continue
        elif in_secret_kind and in_data_block:
            # a bare list/continuation line inside a Secret body
            out.append(re.sub(r"\S+", "<redacted>", line, count=0))
            continue
        out.append(line)
    return out


def main() -> None:
    live = run(["helm", "get", "manifest", REL, "-n", NS])
    # Read the revision rather than labelling it with a literal: the label
    # said "rev 37" while the release was at 39, which is exactly the kind of
    # stale caption that gets quoted later as if it were measured.
    import json as _json
    rev = _json.loads(
        run(["helm", "status", REL, "-n", NS, "-o", "json"])
    )["version"]
    args = ["helm", "template", REL, CHART, "-n", NS]
    for v in VALUES:
        args += ["-f", v]
    rendered = run(args)

    a, b = redact(live), redact(rendered)
    diff = list(difflib.unified_diff(
        a, b, fromfile=f"LIVE (helm get manifest, rev {rev})",
        tofile="RENDERED (helm template, this branch)", lineterm="", n=2))

    if not diff:
        print("no manifest difference")
        return
    changed = sum(1 for d in diff if d.startswith(("+", "-"))
                  and not d.startswith(("+++", "---")))
    print(f"{changed} changed lines, secrets shown as len+sha256 prefix only\n")
    for d in diff:
        print(d)


if __name__ == "__main__":
    main()
