"""Commit the corpus gate's report to git, from inside the cluster.

WHY THE POD PUSHES INSTEAD OF CI PULLING. The gate cannot run in CI: its fires
need the header LLM and the vision endpoint on RFC1918 addresses and the corpus
in in-cluster MinIO, none of which a GitHub-hosted runner can reach. CI
therefore checks a COMMITTED report (`tests/test_corpus_gate_guard.py`), and
something has to put it there. The network only allows one direction — out of
the cluster — so the run that produced the report is the only thing positioned
to commit it. Until this script existed that step was a human copying files out
of a pod, which is the step that silently does not happen, and a guard reading a
report nobody refreshed goes green on a stale measurement.

IT NEVER WRITES TO `main`, AND THAT IS NOT CAUTION, IT IS NECESSARY. `main` in
this repo has no branch protection and no required checks, so a push to it is
final and unreviewed. A machine committing a measurement straight onto an
unprotected default branch would be the one write in this pipeline with nothing
between it and the repo. So: one commit onto a long-lived branch, and a standing
pull request. A human merges, or does not.

IT DOES NOT REUSE `GIT_TOKEN`. That secret exists for the DataHub schema
assets, which CLONE repositories — a read. Pushing is a different privilege, and
borrowing the read token's name would hide that escalation at exactly the place
a reader would look to check it. This script reads `PCN_GATE_PUBLISH_TOKEN` and
nothing else, so what it can do is visible in the secret key it needs.

UNCONFIGURED IS A LOUD NO-OP. No token or no repo and it prints why and exits 0:
the gate run itself must not fail because publishing was not set up. What it must
never do is exit 0 silently, which would read as "published".

A RED REPORT IS STILL PUBLISHED. That is the report most worth having in the
repo, and the CronJob runs this step whether the gate passed or failed.

EVERY COMMIT PARENTS ON `main`'S CURRENT TIP, BY FORCE, EVERY NIGHT. The
branch is machine-owned and the commit is the deliverable; the branch is only
a delivery mechanism to get that commit in front of a human as a clean,
mergeable PR. A stale parent buys the branch nothing — it only means
`latest.json`, which every run rewrites, drifts from whatever landed on
`main` since the branch was created, until the standing PR is CONFLICTING and
gets zero CI checks and can never merge. So the branch ref update below is a
FORCE update: reparenting onto `main`'s tip is not a fast-forward. That force
is safe only because of the carry-forward immediately before it — any
`report-*.md` already sitting on the branch that has not yet reached `main`
is read back off the branch and folded into the new tree before the ref
moves, so the force-update can never silently drop a report a previous night
committed and nobody has merged yet. (`latest.json` is the one exception:
this run's copy always wins outright, it is the newest measurement.)

ENV

    PCN_GATE_PUBLISH_TOKEN   required. A token that may push to PCN_GATE_PUBLISH_REPO.
    PCN_GATE_PUBLISH_REPO    required. `owner/name`.
    PCN_GATE_REPORT_DIR      where the gate wrote the report. Same variable the
                             gate reads, so the two cannot point at different
                             directories. Default docs/corpus-gate.
    PCN_GATE_PUBLISH_PATH    destination path in the repo. Default docs/corpus-gate.
    PCN_GATE_PUBLISH_BRANCH  default corpus-gate/nightly.
    PCN_GATE_PUBLISH_BASE    default main. Resolved fresh every run: it is
                             where the branch is created from the first time
                             it does not exist, AND it is what every commit
                             parents on, every night — not just the first.
    PCN_GATE_PUBLISH_API     default https://api.github.com.
"""
from __future__ import annotations

import base64
import glob
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_REPORT_DIR = "docs/corpus-gate"
DEFAULT_BRANCH = "corpus-gate/nightly"
DEFAULT_BASE = "main"
DEFAULT_API = "https://api.github.com"


class PublishError(RuntimeError):
    pass


def _api(method, url, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "doc-tools-corpus-gate",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise PublishError(f"{method} {url} -> HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        # Egress from the cluster to api.github.com is an assumption, not a
        # given. Say that plainly rather than reporting it as an auth problem.
        raise PublishError(
            f"{method} {url} -> could not reach the GitHub API ({e.reason}). The "
            f"report is still in the pod; this pod may have no egress."
        ) from None


def collect_report(report_dir):
    """`latest.json` plus every dated markdown report present, as {name: text}.

    `latest.json` is required: it is what the CI guard reads, and publishing the
    prose without it would commit a report CI cannot see.
    """
    latest = os.path.join(report_dir, "latest.json")
    if not os.path.isfile(latest):
        raise PublishError(
            f"{latest} does not exist — there is nothing to publish. Either the "
            f"gate did not get as far as writing a report, or PCN_GATE_REPORT_DIR "
            f"does not point at where it wrote one."
        )
    files = {"latest.json": open(latest, encoding="utf-8").read()}
    for md in sorted(glob.glob(os.path.join(report_dir, "report-*.md"))):
        files[os.path.basename(md)] = open(md, encoding="utf-8").read()
    return files


def _resolve_base(api, repo, token, base):
    """`base`'s current tip sha and that commit's tree sha, read fresh every
    run. Every published commit parents here (see the module docstring for
    why), not on whatever the publish branch's own head happens to be."""
    ref = _api("GET", f"{api}/repos/{repo}/git/ref/heads/{base}", token)
    sha = ref["object"]["sha"]
    commit = _api("GET", f"{api}/repos/{repo}/git/commits/{sha}", token)
    return sha, commit["tree"]["sha"]


def _resolve_head(api, repo, token, branch, base_sha):
    """The branch's head sha, creating the branch off `base_sha` the first
    time it does not exist.

    This no longer bounds where new commits parent — every commit parents on
    `base_sha` from `_resolve_base`, every run, not on what this returns. It
    exists to (a) learn whether the branch already has content to carry
    forward and to check against for the no-op case, and (b) create the
    branch when it is missing.
    """
    try:
        ref = _api("GET", f"{api}/repos/{repo}/git/ref/heads/{branch}", token)
        return ref["object"]["sha"], False
    except PublishError as e:
        if "HTTP 404" not in str(e):
            raise
    _api("POST", f"{api}/repos/{repo}/git/refs", token,
         {"ref": f"refs/heads/{branch}", "sha": base_sha})
    return base_sha, True


def _list_dest_files(api, repo, token, tree_sha, dest):
    """{path: blob_sha} for every blob under `dest` in the tree at `tree_sha`.

    RAISES on a truncated listing rather than returning a partial one. This
    feeds the carry-forward, whose whole job is to stop the force-reparent
    dropping a report; a truncated tree omits entries with no error, which
    would silently defeat it and destroy exactly what it protects. GitHub sets
    `truncated` when a recursive tree exceeds its response limits, so a loud
    failure here -- no commit, no ref move, non-zero exit -- is the only safe
    reading of it.
    """
    tree = _api(
        "GET", f"{api}/repos/{repo}/git/trees/{tree_sha}?recursive=1", token)
    if tree.get("truncated"):
        raise PublishError(
            f"the recursive tree listing for {tree_sha} came back TRUNCATED, so "
            f"reports under {dest} may be missing from it. Refusing to publish: "
            f"a force-reparent on a partial carry-forward would discard a "
            f"not-yet-merged report. Merge the standing PR, or widen this "
            f"listing, then re-run.")
    prefix = f"{dest}/"
    return {e["path"]: e["sha"] for e in tree.get("tree", [])
            if e.get("type") == "blob" and e["path"].startswith(prefix)}


def _carry_forward_reports(api, repo, token, branch_tree_sha, base_tree_sha,
                            dest, already_paths):
    """{path: text} for every `report-*.md` that exists on the branch's tree
    but not on base's — read back via the git data API so a force-reparent
    cannot silently discard a previous night's not-yet-merged report.

    `latest.json` is deliberately excluded by the name filter below: this
    run's copy is always the newest measurement and always wins outright, it
    is never merged with an older one. A path already staged this run
    (`already_paths`) is also skipped — the local, freshly-written copy wins.
    """
    branch_files = _list_dest_files(api, repo, token, branch_tree_sha, dest)
    base_files = _list_dest_files(api, repo, token, base_tree_sha, dest)
    carried = {}
    for path, blob_sha in branch_files.items():
        name = path.rsplit("/", 1)[-1]
        if not (name.startswith("report-") and name.endswith(".md")):
            continue
        if path in base_files or path in already_paths:
            continue
        blob = _api("GET", f"{api}/repos/{repo}/git/blobs/{blob_sha}", token)
        carried[path] = base64.b64decode(blob["content"]).decode("utf-8")
    return carried


def _ensure_pr(api, repo, token, branch, base, verdict):
    owner = repo.split("/")[0]
    open_prs = _api("GET", f"{api}/repos/{repo}/pulls"
                           f"?state=open&head={owner}:{branch}", token)
    if open_prs:
        return open_prs[0]["html_url"], False
    pr = _api("POST", f"{api}/repos/{repo}/pulls", token, {
        "title": "chore(corpus-gate): nightly report",
        "head": branch,
        "base": base,
        "body": (
            "The PCN/PDN corpus gate runs nightly in-cluster (it cannot run in "
            "CI — see `scripts/pcn_gate_publish.py` for why) and commits its "
            "report here. `tests/test_corpus_gate_guard.py` reads "
            "`docs/corpus-gate/latest.json` and checks that it is present, "
            "green and not stale, so merging this branch is what keeps that "
            "guard measuring the current image rather than an old one.\n\n"
            f"Latest verdict in this branch: **{verdict}**.\n\n"
            "Opened once and reused: each night adds a commit to the same "
            "branch rather than opening another PR.\n\n"
            "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
        ),
    })
    return pr["html_url"], True


def publish(report_dir, repo, token, branch=DEFAULT_BRANCH, base=DEFAULT_BASE,
            dest=DEFAULT_REPORT_DIR, api=DEFAULT_API):
    """One commit carrying the whole report, reparented onto `base`'s current
    tip every run, plus a standing PR.

    ONE commit, via the git data API, rather than a PUT per file: two PUTs are
    two commits, and a reader of the branch would see a state where latest.json
    has been updated and the markdown beside it has not.

    The commit always parents on `base`'s tip (see the module docstring for
    why), never on the branch's own existing head, so the branch is always
    `base` plus this one commit and the standing PR is always cleanly
    mergeable. A not-yet-merged `report-*.md` already on the branch is read
    back and carried into the new tree first, so the force-reparent below
    cannot discard it.

    This does NOT mean a commit every night regardless: when the branch
    already holds exactly this tree AND is already correctly parented on
    `base`'s tip, there is truly nothing to publish and no commit is made. In
    every other case — including an unchanged tree on a branch that is
    parented on a stale commit — a commit is made, because the reparent
    itself is what clears a conflicting standing PR.
    """
    files = collect_report(report_dir)
    verdict = "unknown"
    try:
        verdict = json.loads(files["latest.json"]).get("verdict", "unknown")
    except (ValueError, KeyError):
        pass

    base_sha, base_tree_sha = _resolve_base(api, repo, token, base)
    head, created_branch = _resolve_head(api, repo, token, branch, base_sha)

    dest_clean = dest.rstrip("/")
    tree_entries = [{"path": f"{dest_clean}/{name}", "mode": "100644",
                      "type": "blob", "content": text}
                     for name, text in sorted(files.items())]
    already_paths = {e["path"] for e in tree_entries}

    branch_commit = _api("GET", f"{api}/repos/{repo}/git/commits/{head}", token)
    branch_tree_sha = branch_commit["tree"]["sha"]
    branch_parents = branch_commit.get("parents") or []

    if not created_branch:
        carried = _carry_forward_reports(
            api, repo, token, branch_tree_sha, base_tree_sha, dest_clean,
            already_paths)
        for path, text in sorted(carried.items()):
            tree_entries.append({"path": path, "mode": "100644",
                                  "type": "blob", "content": text})

    tree = _api("POST", f"{api}/repos/{repo}/git/trees", token, {
        "base_tree": base_tree_sha,
        "tree": tree_entries,
    })

    already_parented = (bool(branch_parents)
                         and branch_parents[0]["sha"] == base_sha)
    if tree["sha"] == branch_tree_sha and already_parented:
        pr_url, _ = _ensure_pr(api, repo, token, branch, base, verdict)
        return {"committed": False,
                "reason": f"branch already holds this exact report and is "
                          f"already parented on {base}'s tip; nothing to "
                          f"reparent and nothing to publish",
                "branch": branch, "pr": pr_url, "verdict": verdict}

    commit = _api("POST", f"{api}/repos/{repo}/git/commits", token, {
        "message": (
            f"chore(corpus-gate): nightly report, verdict {verdict}\n\n"
            f"Written by scripts/pcn_gate_publish.py from the in-cluster "
            f"CronJob run that produced it. Never pushed to main: see that "
            f"script for why a machine does not write to an unprotected "
            f"default branch.\n\n"
            f"Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
        ),
        "tree": tree["sha"],
        "parents": [base_sha],
    })
    _api("PATCH", f"{api}/repos/{repo}/git/refs/heads/{branch}", token,
         {"sha": commit["sha"], "force": True})
    pr_url, opened = _ensure_pr(api, repo, token, branch, base, verdict)
    return {"committed": True, "commit": commit["sha"], "branch": branch,
            "created_branch": created_branch, "pr": pr_url,
            "pr_opened": opened, "files": sorted(files), "verdict": verdict}


def main():
    token = os.environ.get("PCN_GATE_PUBLISH_TOKEN") or ""
    repo = os.environ.get("PCN_GATE_PUBLISH_REPO") or ""
    report_dir = os.environ.get("PCN_GATE_REPORT_DIR") or DEFAULT_REPORT_DIR
    if not token or not repo:
        missing = " and ".join(
            n for n, v in (("PCN_GATE_PUBLISH_TOKEN", token),
                           ("PCN_GATE_PUBLISH_REPO", repo)) if not v)
        print(f"PUBLISH SKIPPED: {missing} not set. The report is in "
              f"{report_dir} inside this pod and nowhere else; CI reads a "
              f"COMMITTED report, so until this is configured the gate's guard "
              f"is reading whatever was last committed by hand.")
        return 0

    try:
        result = publish(
            report_dir, repo, token,
            branch=os.environ.get("PCN_GATE_PUBLISH_BRANCH") or DEFAULT_BRANCH,
            base=os.environ.get("PCN_GATE_PUBLISH_BASE") or DEFAULT_BASE,
            dest=os.environ.get("PCN_GATE_PUBLISH_PATH") or DEFAULT_REPORT_DIR,
            api=os.environ.get("PCN_GATE_PUBLISH_API") or DEFAULT_API,
        )
    except PublishError as e:
        print(f"PUBLISH FAILED: {e}")
        return 1

    if result["committed"]:
        print(f"PUBLISHED {', '.join(result['files'])} to {result['branch']} "
              f"as {result['commit'][:12]} (verdict {result['verdict']})")
    else:
        print(f"PUBLISH NO-OP: {result['reason']} ({result['branch']})")
    print(f"PR: {result['pr']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
