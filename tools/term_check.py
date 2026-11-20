"""Term check over records: host-shaped literals, internal suffixes, domain-shaped tokens.

Exit codes, per the architect's ruling of 2026-11-19 ("the check must exit non-zero
when it finds a hit; exiting zero with hits is a fault"):

    0  no hit
    1  at least one HARD hit: an IPv4 literal or an internal suffix
    2  no hard hit, but at least one domain-shaped token
    3  usage error, or no file to check

Codes 1 and 2 are both non-zero, as ruled. They are distinct so that a caller can
tell a host literal, which must never be written at all, from a domain-shaped token
that a record may be explaining on purpose (this repo's ontology namespace IRI, the
kit's public repository, a `kubernetes.io` label key). The distinction is not an
exemption: 2 is a failure.

Output is diagnostic and is never pasted into a record, a packet or a PR body. For
the two hard classes the token itself is NOT printed -- `path:line` locates it and
the value is shown as `len=N sha256:XXXXXXXX`, the same convention `drift_check.py`
uses, so running the check cannot be what puts a site identifier in a transcript.
A domain-shaped token is printed, because deciding whether it is a host or a label
key means reading it.

The only allow-list is the two required attribution lines, and only with
--text-file, which is the mode for a commit message or a PR body. A record is
checked without it: those lines do not belong in one.
"""
import hashlib
import re
import sys
from pathlib import Path

HARD = (
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("internal-suffix", re.compile(r"\.(?:svc|local|internal|corp|cluster|lan|intranet)\b")),
)
DOMAIN = (
    "domain-shaped",
    re.compile(r"\b[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.(?:com|io|net|org|dev|ai|co|gov|mil|edu)\b"),
)

# Exactly the two required attribution lines. Whole-line match after stripping, so a
# line that merely contains one does not inherit the allowance.
ATTRIBUTION = frozenset({
    "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>",
    "\U0001f916 Generated with [Claude Code](https://claude.com/claude-code)",
})


def fp(value):
    return "len=%d sha256:%s" % (len(value), hashlib.sha256(value.encode()).hexdigest()[:8])


def targets(args):
    out = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            out.extend(sorted(p.rglob("*.md")))
        elif p.is_file():
            out.append(p)
    return out


def scan(path, allow_attribution):
    hits = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for n, line in enumerate(text.splitlines(), 1):
        if allow_attribution and line.strip() in ATTRIBUTION:
            continue
        for name, pattern in HARD:
            for m in pattern.finditer(line):
                hits.append((name, path, n, fp(m.group(0)), True))
        for m in DOMAIN[1].finditer(line):
            hits.append((DOMAIN[0], path, n, m.group(0), False))
    return hits


def main(argv):
    args = [a for a in argv if a != "--text-file"]
    allow_attribution = "--text-file" in argv
    if not args:
        args = ["docs/arch", "docs/adr"]
    files = targets(args)
    if not files:
        sys.stderr.write("term_check: nothing to check in %s\n" % " ".join(args))
        return 3

    hits = []
    for f in files:
        hits.extend(scan(f, allow_attribution))

    counts = {"ipv4": 0, "internal-suffix": 0, "domain-shaped": 0}
    for name, path, n, shown, _hard in hits:
        counts[name] += 1
        print("%s:%d: %s: %s" % (path.as_posix(), n, name, shown))

    print(
        "term_check: %d file(s); ipv4=%d internal-suffix=%d domain-shaped=%d"
        % (len(files), counts["ipv4"], counts["internal-suffix"], counts["domain-shaped"])
    )
    if counts["ipv4"] or counts["internal-suffix"]:
        return 1
    if counts["domain-shaped"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
