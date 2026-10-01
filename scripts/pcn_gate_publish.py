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

ENV

    PCN_GATE_PUBLISH_TOKEN   required. A token that may push to PCN_GATE_PUBLISH_REPO.
    PCN_GATE_PUBLISH_REPO    required. `owner/name`.
    PCN_GATE_REPORT_DIR      where the gate wrote the report. Same variable the
                             gate reads, so the two cannot point at different
                             directories. Default docs/corpus-gate.
    PCN_GATE_PUBLISH_PATH    destination path in the repo. Default docs/corpus-gate.
    PCN_GATE_PUBLISH_BRANCH  default corpus-gate/nightly.
    PCN_GATE_PUBLISH_BASE    default main. Used only to create the branch.
    PCN_GATE_PUBLISH_API     default https://api.github.com.
"""
from __future__ import annotations

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


def _resolve_head(api, repo, token, branch, base):
    """The branch's head sha, creating the branch off `base` the first time."""
    try:
        ref = _api("GET", f"{api}/repos/{repo}/git/ref/heads/{branch}", token)
        return ref["object"]["sha"], False
    except PublishError as e:
        if "HTTP 404" not in str(e):
            raise
    base_ref = _api("GET", f"{api}/repos/{repo}/git/ref/heads/{base}", token)
    sha = base_ref["object"]["sha"]
    _api("POST", f"{api}/repos/{repo}/git/refs", token,
         {"ref": f"refs/heads/{branch}", "sha": sha})
    return sha, True


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
    """One commit carrying the whole report onto `branch`, plus a standing PR.

    ONE commit, via the git data API, rather than a PUT per file: two PUTs are
    two commits, and a reader of the branch would see a state where latest.json
    has been updated and the markdown beside it has not.

    An unchanged report does NOT produce an empty commit — the new tree is
    compared with the parent's. A nightly job that commits every night whether
    or not anything moved trains a reader to ignore it.
    """
    files = collect_report(report_dir)
    verdict = "unknown"
    try:
        verdict = json.loads(files["latest.json"]).get("verdict", "unknown")
    except (ValueError, KeyError):
        pass

    head, created_branch = _resolve_head(api, repo, token, branch, base)
    parent = _api("GET", f"{api}/repos/{repo}/git/commits/{head}", token)
    tree = _api("POST", f"{api}/repos/{repo}/git/trees", token, {
        "base_tree": parent["tree"]["sha"],
        "tree": [{"path": f"{dest.rstrip('/')}/{name}", "mode": "100644",
                  "type": "blob", "content": text}
                 for name, text in sorted(files.items())],
    })
    if tree["sha"] == parent["tree"]["sha"]:
        pr_url, _ = _ensure_pr(api, repo, token, branch, base, verdict)
        return {"committed": False, "reason": "report is byte-identical to the "
                                              "one already on the branch",
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
        "parents": [head],
    })
    _api("PATCH", f"{api}/repos/{repo}/git/refs/heads/{branch}", token,
         {"sha": commit["sha"]})
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
