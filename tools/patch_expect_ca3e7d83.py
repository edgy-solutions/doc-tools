"""Roll 2 of the ca3e7d83 pin: arm the gate from the POD READING.

RUN THIS ONLY AFTER ROLL 1 HAS SETTLED. The roll is `01f016e430eb -> ca3e7d83`
and it is ONE roll in two applies: bump `image.digest`, apply, read the pods,
write `expectImage` from that reading, apply again. The post-roll write is PART
OF THE ROLL and not a follow-up (ruled 2026-11-07) -- the roll is not finished
until the second apply lands.

THE VALUE IS READ OFF THE PODS, never copied from `image.digest`. The two
happening to be equal is the result being asserted, not the source of the value.
Nothing here retypes a digest.

Step 1 -- read the pods, FROM POWERSHELL (MSYS rewrites slash-bearing kubectl
arguments, and `kubectl` here has no current-context so it needs one):

    $env:KUBECONFIG = "<scratchpad>\\ctx-overlay.yaml;$env:USERPROFILE\\.kube\\config"
    kubectl get pods -n sandbox -l app.kubernetes.io/name=doc-tools --context edge `
      -o custom-columns=IMAGEID:.status.containerStatuses[*].imageID --no-headers `
      | Sort-Object -Unique | Where-Object { $_ -ne "" } `
      | Set-Content -Encoding ascii scratchpad/pod_imageid_ca3e7d83.txt

  `custom-columns` and NOT `-o jsonpath`: a jsonpath needing a newline escape
  cannot be written in a PowerShell single-quoted string -- the backtick is
  literal there, so `{"`n"}` reaches kubectl as U+0060 and it errors
  `unrecognized character in action`. Measured, not guessed. The overlay is the
  credential-free `current-context: edge` file; this workstation's kubeconfig
  has no current-context, so a bare kubectl targets localhost:8080 and reports
  connection refused, which reads like a down cluster.

  WAIT FOR THE POD COUNT TO COME BACK TO 1 FIRST. `kubectl rollout status` has
  reported "successfully rolled out" here while the previous pod was still
  Running and pending termination -- for ~84s on the 2bf85719 roll a read of
  "the pods" returned TWO distinct imageIDs. This script refuses on that case
  rather than picking one, but the refusal costs you the window, so check
  `kubectl get pods` first.

Step 2 -- apply the write:

    .venv/Scripts/python.exe tools/patch_expect_ca3e7d83.py

Then roll again. Until that second apply lands, the cluster is RED on image
identity by construction: the gate would compare a `ca3e7d83` run against an
`03599b10` expectation. That window is safe here only because the nightly
CronJob is `suspend: true` (values-sandbox.yaml:1587), which the pre-roll diff
proved rather than assumed -- `suspend` appears nowhere in it, so live and
rendered agree. Do not lean on that if the CronJob is ever unsuspended.
"""
from datetime import datetime, timezone
from pathlib import Path

VALUES = Path("charts/doc-tools/values-sandbox.yaml")
READ = Path("scratchpad/pod_imageid_ca3e7d83.txt")

# What `expectImage` says now: the pin that was declared and NEVER ROLLED. The
# live release (rev 57) ran `01f016e430eb`, so this line has been naming a third
# image all along -- which is why roll 2 is not optional.
OLD_DIGEST = "sha256:03599b10afcd5be49bd46f515db92ad4d694849f576484dad23847c9cf4b5290"
OLD_LINE = f'  expectImage: "pods=ghcr.io/edgy-solutions/doc-tools@{OLD_DIGEST}"'

# The digest the chart pins, read from the file rather than retyped, so this
# script cannot disagree with `image.digest` about what roll 1 applied.
DIGEST_PREFIX = '  digest: "'


def chart_digest(text):
    for line in text.splitlines():
        if line.startswith(DIGEST_PREFIX):
            return line[len(DIGEST_PREFIX):].rstrip('"')
    raise SystemExit("REFUSING: no `  digest:` line found in the values file")


def main():
    if not READ.exists():
        raise SystemExit(
            f"REFUSING: {READ} does not exist. Read the pods first -- see step 1 "
            "in this file's docstring. Do NOT copy image.digest into it: the "
            "point of this write is that the value came off the running pods.")

    ids = sorted({l.strip() for l in READ.read_text(encoding="utf-8").splitlines()
                  if l.strip()})
    if len(ids) != 1:
        raise SystemExit(
            f"REFUSING: {len(ids)} distinct imageIDs on the pods: {ids}\n"
            "Two values means the old ReplicaSet has not finished scaling to "
            "zero. Wait for the pod count to come back to 1 and read again -- "
            "`rollout status` reporting success is not evidence of that.")

    observed = ids[0]
    if "@sha256:" not in observed:
        raise SystemExit(f"REFUSING: imageID is not digest-pinned: {observed}")

    text = VALUES.read_text(encoding="utf-8")
    pinned = chart_digest(text)
    observed_digest = observed.split("@", 1)[1]

    if observed_digest != pinned:
        raise SystemExit(
            "REFUSING: the pods are not running what the chart pins.\n"
            f"  pods       {observed_digest}\n"
            f"  image.digest {pinned}\n"
            "Roll 1 has not landed, or it landed something else. Writing "
            "`expectImage` from this reading would arm the gate to a digest the "
            "chart does not declare. Stop and look.")

    n = text.count(OLD_LINE)
    if n != 1:
        raise SystemExit(
            f"REFUSING: {n} matches for the expectImage line (expected 1). "
            "Either this write has already been applied, or the line moved.")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    comment = f"""  #
  # {stamp}, READ-THEN-WRITE, roll 2 of the ca3e7d83 pin. This value was read
  # off the running pods' `.status.containerStatuses[*].imageID` after roll 1
  # settled and the pod count had come back to 1 -- ONE distinct value -- and
  # written from that reading. It is NOT copied from `image.digest` above,
  # which it equals; that equality is the result being asserted.
  #
  # THE LINE THIS REPLACES NAMED A THIRD IMAGE. `03599b10afcd` was pinned and
  # never rolled, while the live release (rev 57) ran `01f016e430eb`. So before
  # this write the gate's expectation matched neither the chart nor the cluster,
  # and a nightly would have been VOIDED on image identity rather than
  # reporting on the corpus. There were three digests in play, not two.
  #
  # The window between the two rolls was red on image identity by construction.
  # It was harmless only because the nightly CronJob is `suspend: true`
  # (further up this file), which the pre-roll diff proved rather than assumed:
  # `suspend` appeared ZERO times in it, so live and rendered agree.
  #
  # IF YOU BUMP image.digest AND STOP, YOU HAVE ARMED THAT SAME FAILURE. The
  # two lines are not kept in step by anything automatic; no test and no CI job
  # compares them, because the Job that would is the one being checked.
"""
    new_line = f'  expectImage: "pods={observed}"'
    text = text.replace(OLD_LINE, comment + new_line)

    # Written as bytes with LF: the file is pure LF and a CRLF rewrite would
    # break a pinned sha elsewhere in the tree.
    VALUES.write_bytes(text.encode("utf-8"))

    stale = text.count(OLD_DIGEST.split(":", 1)[1][:8])
    print(f"patched {VALUES}")
    print(f"  expectImage -> {observed}")
    print(f"  (read off the pods; equals image.digest {pinned})")
    print(f"NOTE: `03599b10` still appears {stale}x -- in comments only")
    print("\nNOT DONE YET: roll again to apply this. The roll is not finished "
          "until the second apply lands.")


if __name__ == "__main__":
    main()
