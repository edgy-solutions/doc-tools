"""Read helm user-supplied values on stdin as JSON; print structure, never a secret.

Only two leaves are printed in full, and neither is a secret: image.digest and
corpusGate.expectImage, the two digests a pin bump has to move. Every other leaf
is shown as len=N sha256:XXXXXXXX per the repo convention, so a peer --set that
moved something is still visible without disclosing what it moved it to.
"""
import hashlib
import json
import sys

SHOW_IN_FULL = {"image.digest", "corpusGate.expectImage"}

vals = json.load(sys.stdin) or {}

def fp(v):
    s = "" if v is None else str(v)
    return "len=%d sha256:%s" % (len(s), hashlib.sha256(s.encode()).hexdigest()[:8])

leaves = []
def walk(node, path):
    if isinstance(node, dict):
        for k in sorted(node):
            walk(node[k], path + [k])
    elif isinstance(node, list):
        leaves.append((".".join(path), "list[%d]" % len(node)))
    else:
        dotted = ".".join(path)
        leaves.append((dotted, repr(node) if dotted in SHOW_IN_FULL else fp(node)))

walk(vals, [])

print("top-level keys : %s" % (sorted(vals) or "(none)"))
print("global present : %s   <- must be False for this release" % ("global" in vals))
print("leaf count     : %d" % len(leaves))
print()
for dotted, shown in leaves:
    mark = "  <-- DIGEST" if dotted in SHOW_IN_FULL else ""
    print("  %-46s %s%s" % (dotted, shown, mark))
