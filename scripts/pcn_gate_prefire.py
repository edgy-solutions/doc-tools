"""Fire the corpus gate against an image that is BUILT but not yet PINNED.

WHY THIS EXISTS. The only fire path copies the CronJob's pod template, whose
image is the chart's current pin, so a candidate image cannot be measured until
after it is rolled. That leaves a red window between a roll and its report
(accepted as an interim cost on 2026-10-27). This script closes it: it fires the
gate on the candidate so a pin-bump PR can carry a report for the digest it
lands.

IT IS A MANIFEST BUILDER PLUS A CORROBORATION, NOTHING MORE. No new RBAC, no
in-cluster logic, no change to how the gate scores. It runs on the lane's
workstation and shells out to `kubectl`. Its whole value is (a) overriding the
few fields the CronJob would otherwise dictate and (b) proving, before 2.5 hours
of GPU time is spent, that the pod really runs the candidate.

THE MANIFEST COMES FROM THE CRONJOB, NEVER FROM SCRATCH. The CronJob is the only
place the measured environment lives: LLM_NUM_CTX, both DPI knobs, PROMPT_SOURCE
and the inline envFrom secret reference. A hand-written Job would silently
measure a different configuration, and a hand-run in the code-location pod has
already produced a `measured_image: null` report once.

IT REFUSES AN IMAGE WITH NO sha256 DIGEST, BEFORE ANYTHING ELSE. A tag is not an
identity: the gate's own `check_image_identity` calls a tag-only reference
`uncomparable` and VOID, and `:latest` is the case that made "what is sandbox
running?" unanswerable for weeks.

IT PRINTS NO ENV VALUE EXCEPT THE FIVE IT OVERRIDES. The CronJob's env is inline
and includes API keys, and this repo has put three live credentials into a
non-editable transcript once. Other env vars are never named-with-value, not
even to say "unchanged".

IT DOES NOT IMPORT `doc_tools`. That package imports the Dagster defs, which
pull `unstructured`, which pulls `python-magic`, which blocks for ever at import
on this workstation. Standard library only.

EXIT CODES
    0  fired and corroborated
    2  refused before applying (bad input, no digest)
    3  applied but corroboration FAILED (mismatch; Job deleted) or is UNPROVEN
       (no imageID in time; Job left running)
    4  kubectl itself failed -- including the case where a MISMATCH was found
       and the Job could not then be deleted. That is exit 4 and not 3 on
       purpose: a surviving mismatched Job will spend 2.5 hours of vision
       calls and publish a report naming the candidate it is not running, so
       it needs the loudest code and a by-hand command, not the ordinary
       "corroboration failed" one.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time

CONTAINER = "corpus-gate"
DIGEST_RE = re.compile(r"@(sha256:[0-9a-f]{64})(?![0-9a-f])")
MATCH, MISMATCH, UNPROVEN = "match", "mismatch", "unproven"


class PrefireError(RuntimeError):
    """Anything this script refuses or cannot do."""


class ManifestRefused(PrefireError):
    """The CronJob is not the shape this script knows how to override.

    Its own class, rather than a flag or a message a caller greps: the exit
    code distinguishes "your input or the chart is wrong" (2) from "kubectl
    failed" (4), and choosing between those by string-matching the message
    means a reworded sentence silently changes an exit code.
    """


def extract_digest(image):
    """The `sha256:<64 hex>` of a digest-pinned reference, else None.

    Matched with a regex rather than split on `@`: `repo:tag@sha256:...` and
    `repo@sha256:...` must give the same answer, and the kubelet's `imageID`
    wraps the same form in a `docker-pullable://` prefix.
    """
    m = DIGEST_RE.search(image or "")
    return m.group(1) if m else None


def require_digest(image):
    """Digest or PrefireError. A tag is not an identity, so a tag is refused."""
    digest = extract_digest(image)
    if digest is None:
        raise PrefireError(
            f"{image!r} carries no sha256 digest. A tag is not an identity: "
            f"`:latest` moves, and the gate's check_image_identity calls a "
            f"tag-only reference uncomparable and VOID. Pass repo@sha256:<64 hex>."
        )
    return digest


def _set_env(env, name, value):
    """Replace the entry called `name`, else append. Returns the old value.

    Replacing, not blindly appending: duplicates resolve to the LAST entry, so
    appending would work, but `kubectl get job -o yaml` would then show two
    entries saying different things and a reader would need to know that rule.
    """
    for entry in env:
        if entry.get("name") == name:
            old = entry.get("value")
            entry.pop("valueFrom", None)
            entry["value"] = value
            return old
    env.append({"name": name, "value": value})
    return None


def apply_overrides(job, image, publish_branch):
    """Return (new_job, changes) with exactly the five overrides applied.

    `changes` is [(field, old, new)] and holds nothing but the overridden
    fields, so printing it can never leak another env var's value.
    DOC_TOOLS_IMAGE must move with `image`: it is what the report's
    `measured_image` becomes, and leaving it at the chart's pin would produce a
    report that NAMES the old image while RUNNING the new one. EXPECT_IMAGE is
    "" because in `pre_roll` the chart still pins the OLD image, so comparing
    against it would void every pre-roll report by construction.
    """
    new = json.loads(json.dumps(job))
    try:
        containers = new["spec"]["template"]["spec"]["containers"]
    except (KeyError, TypeError):
        raise ManifestRefused(
            "manifest has no spec.template.spec.containers") from None
    names = [c.get("name") for c in containers]
    if names != [CONTAINER]:
        raise ManifestRefused(
            f"expected exactly one container named {CONTAINER!r}, found {names!r}; "
            f"refusing to guess by index."
        )
    c = containers[0]
    changes = [("image", c.get("image"), image)]
    c["image"] = image
    env = c.setdefault("env", [])
    for name, value in (
        ("DOC_TOOLS_IMAGE", image),
        ("PCN_GATE_IDENTITY_MODE", "pre_roll"),
        ("PCN_GATE_PUBLISH_BRANCH", publish_branch),
        ("PCN_GATE_EXPECT_IMAGE", ""),
    ):
        changes.append((f"env {name}", _set_env(env, name, value), value))
    return new, changes


def corroborate(candidate_digest, image_id):
    """MATCH, MISMATCH or UNPROVEN: three states, not two.

    A missing `imageID` is UNPROVEN, never a mismatch: a slow image pull is not
    the cluster resolving the reference to something else, and the caller must
    not delete a probably-fine run for it.
    """
    actual = extract_digest(image_id) if image_id else None
    if actual is None:
        return UNPROVEN
    return MATCH if actual == candidate_digest else MISMATCH


def _kubectl(args, stdin=None):
    """Thin wrapper: argument list, never a shell string."""
    try:
        r = subprocess.run(["kubectl", *args], input=stdin, capture_output=True,
                           text=True)
    except OSError as e:
        raise PrefireError(f"could not run kubectl: {e}") from None
    return r


def _pod_image_id(ns, job_name):
    r = _kubectl(["-n", ns, "get", "pods", "-l", f"job-name={job_name}",
                  "-o", "json"])
    if r.returncode != 0:
        raise PrefireError(f"kubectl get pods failed: {r.stderr.strip()[:300]}")
    for pod in json.loads(r.stdout or "{}").get("items", []):
        statuses = pod.get("status", {}).get("containerStatuses") or []
        if statuses and statuses[0].get("imageID"):
            return statuses[0]["imageID"]
    return None


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--image", required=True,
                   help="The candidate image. MUST carry a sha256 digest: a "
                        "tag is refused before anything else happens.")
    p.add_argument("--namespace", default="sandbox",
                   help="Namespace of the CronJob and the new Job "
                        "(default: sandbox).")
    p.add_argument("--cronjob", default="doc-tools-corpus-gate",
                   help="The CronJob whose pod template is copied. It is the "
                        "only place the measured environment lives, so it is "
                        "copied and never reconstructed "
                        "(default: doc-tools-corpus-gate).")
    p.add_argument("--job-name",
                   help="Default: pcn-gate-preroll-<first 12 hex of the "
                        "digest>, so the Job name says which image it "
                        "measures.")
    p.add_argument("--publish-branch",
                   help="Where the report is pushed. Default: "
                        "corpus-gate/preroll-<first 12 hex>, deliberately NOT "
                        "corpus-gate/nightly: a pre-roll report measures an "
                        "image no chart pins, and mixing it into the branch "
                        "the authority report is cherry-picked from invites "
                        "someone to land a measurement of an unpinned image "
                        "as the authority for a pinned one.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the overridden manifest to stdout and apply "
                        "NOTHING. It still READS the cluster -- the manifest "
                        "comes from `kubectl create job --from=cronjob/...`, "
                        "so this is not an offline mode; it is a no-write "
                        "mode.")
    p.add_argument("--timeout", type=int, default=180,
                   help="Seconds to wait for a pod with a readable imageID "
                        "before reporting corroboration UNPROVEN and leaving "
                        "the Job running (default: 180).")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        digest = require_digest(args.image)
    except PrefireError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    short = digest.split(":", 1)[1][:12]
    job_name = args.job_name or f"pcn-gate-preroll-{short}"
    branch = args.publish_branch or f"corpus-gate/preroll-{short}"
    ns = args.namespace

    try:
        r = _kubectl(["-n", ns, "create", "job", job_name,
                      f"--from=cronjob/{args.cronjob}", "--dry-run=client",
                      "-o", "json"])
        if r.returncode != 0:
            print(f"kubectl create --dry-run failed: {r.stderr.strip()[:300]}",
                  file=sys.stderr)
            return 4
        job, changes = apply_overrides(json.loads(r.stdout), args.image, branch)
    except ManifestRefused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    except PrefireError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 4

    for field, old, new in changes:
        print(f"override {field}: {old!r} -> {new!r}", file=sys.stderr)
    manifest = json.dumps(job, indent=2)
    if args.dry_run:
        print(manifest)
        return 0

    # apply, not create: a re-run with the same name reports a clear conflict
    # instead of leaving a partial state.
    r = _kubectl(["-n", ns, "apply", "-f", "-"], stdin=manifest)
    if r.returncode != 0:
        print(f"kubectl apply failed: {r.stderr.strip()[:300]}", file=sys.stderr)
        return 4

    deadline = time.monotonic() + args.timeout
    image_id = None
    try:
        while True:
            image_id = _pod_image_id(ns, job_name)
            if image_id or time.monotonic() >= deadline:
                break
            time.sleep(5)
    except PrefireError as e:
        print(str(e), file=sys.stderr)
        return 4

    state = corroborate(digest, image_id)
    if state == MATCH:
        print(f"CORROBORATED imageID {digest}")
    elif state == MISMATCH:
        print(f"MISMATCH candidate {digest} but pod imageID is "
              f"{extract_digest(image_id)}; deleting job {job_name}.")
        d = _kubectl(["-n", ns, "delete", "job", job_name])
        if d.returncode != 0:
            # Louder than the mismatch itself. The mismatch wastes nothing if
            # the Job dies; a Job that SURVIVES a mismatch spends 2.5 hours of
            # vision calls measuring an image nobody asked about, and then
            # publishes a report saying it measured the candidate.
            print(f"DELETE FAILED for job {job_name}: "
                  f"{d.stderr.strip()[:300]}", file=sys.stderr)
            print(f"Delete it BY HAND now: kubectl -n {ns} delete job "
                  f"{job_name}", file=sys.stderr)
            return 4
        return 3
    else:
        print(f"UNPROVEN: no imageID within {args.timeout}s. Job {job_name} is "
              f"left RUNNING (a slow pull is not a mismatch). Check "
              f"`.status.containerStatuses[0].imageID` by hand before trusting "
              f"the report.")
        return 3

    print(f"FOLLOW-UP: the report lands on branch {branch}. Cherry-pick it into "
          f"the pin-bump PR so the pin and its measurement land together.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
