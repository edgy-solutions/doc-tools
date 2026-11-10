"""Roll 2 of the instance-write pin: arm the gate from the POD READING.

The value written here was read off the running pod's
`.status.containerStatuses[*].imageID` AFTER roll 1 settled and the old
ReplicaSet had scaled to zero -- not copied from `image.digest`, which it
happens to equal. That equality is the result being asserted, not the source of
the value.

Refuses unless the anchors match exactly once.
"""
from pathlib import Path

VALUES = Path("charts/doc-tools/values-sandbox.yaml")

OLD = "sha256:5846f877ce3e41a89f7df373a41faa14503991b8928f6a84bb18e49c08a1887b"
NEW = "sha256:2bf85719d2ca8e0cd651df4f45a0ce563732e059d59cafca009839ba3c4fbaa9"

OLD_LINE = f'  expectImage: "pods=ghcr.io/edgy-solutions/doc-tools@{OLD}"'
NEW_LINE = f'  expectImage: "pods=ghcr.io/edgy-solutions/doc-tools@{NEW}"'

COMMENT = '''  #
  # 2026-10-17, READ-THEN-WRITE, THIRD TIME. The f4d6440 pin
  # (`sha256:2bf85719`, one merge: #127, the XML path's second RDF write) rolled
  # as helm REVISION 48, `deployed`, at 04:08Z. This value was then read off the
  # pod -- `custom-columns=...:.status.containerStatuses[*].imageID`, ONE
  # distinct value -- and written from that reading.
  #
  # THE OLD POD WAS STILL RUNNING WHEN THE ROLLOUT REPORTED SUCCESS. `kubectl
  # rollout status` said "successfully rolled out" while the previous pod was
  # still in `Running`, pending termination, so for ~84s a read of "the pods"
  # would have returned TWO distinct imageIDs -- `5846f877` and `2bf85719` --
  # and "ONE distinct value" would have been false. This value was taken only
  # after the pod count came back to 1. A read taken on the strength of the
  # rollout message alone can capture the digest being replaced.
  #
  # The window between the two rolls was RED on image identity by construction,
  # and the pre-roll diff proved it rather than assuming it: `expectImage`
  # appeared ZERO times in it, so the gate would have compared a `2bf85719` run
  # against a `5846f877` expectation. Both rolls were taken inside an hour,
  # ~3h clear of the 07:00Z nightly, so no gate run fell inside the window.
'''

text = VALUES.read_text(encoding="utf-8")

n = text.count(OLD_LINE)
if n != 1:
    raise SystemExit(f"REFUSING: {n} matches for the expectImage line")

# image.digest must ALREADY be on the new digest -- this roll follows roll 1.
if text.count(f'  digest: "{NEW}"') != 1:
    raise SystemExit("REFUSING: image.digest is not on the new digest; roll 1 first")

text = text.replace(OLD_LINE, COMMENT + NEW_LINE)

if text.count(OLD) != 0:
    print(f"NOTE: the old digest still appears {text.count(OLD)}x -- in comments only")

VALUES.write_text(text, encoding="utf-8", newline="\n")
print(f"patched {VALUES}")
print(f"  expectImage -> {NEW}  (from the pod reading)")
