"""`scripts/pcn_gate_publish.py` — the step that moves the gate's report out
of the pod and into git.

WHAT THESE TESTS ARE FOR. Everything in this publisher is a decision about
what happens when something goes wrong, because the normal path is four API
calls and is uninteresting. The failure paths are where a report quietly fails
to arrive while a Job still exits 0, which is the same shape of defect the
guard this report feeds was written to catch (a skip that reads as a pass).
So the tests here are mostly about the wrong-path behaviour:

  - an unconfigured publisher must exit 0 and SAY SO, not exit 0 silently;
  - a missing `latest.json` must be an error, not an empty success, because
    the only consumer of this pipeline (`tests/test_corpus_gate_guard.py`)
    reads exactly that file;
  - a red verdict must publish anyway;
  - an unchanged report must NOT produce a commit;
  - all files must land in ONE commit.

NO NETWORK. The HTTP layer is one function, `_api`, and these tests replace
it with a fake GitHub that records calls. That means these tests prove the
sequencing and the decisions, NOT that the GitHub request shapes are accepted
by GitHub — the first real run is what proves that, and the script's errors
are written to be readable when it does not.
"""
import base64
import importlib.util
import json
import zlib
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "pcn_gate_publish",
    Path(__file__).resolve().parents[1] / "scripts" / "pcn_gate_publish.py",
)
pub = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pub)


class FakeGitHub:
    """A GitHub stand-in that records every call in order.

    `trees` (the CREATE call, POST .../git/trees) returns a sha derived from
    the request body's `tree` list only — not `base_tree` — so an identical
    set of files yields an identical tree sha regardless of what it was
    based on. That is how the no-op-vs-reparent distinction can be tested at
    all: two runs whose files match but whose base differs still compare
    equal on tree sha, and the test has to look at `branch_parent` to tell
    them apart.

    `base` (the ref named "main") and the publish branch are resolved
    independently: `base_sha`/`base_tree` for the former,
    `branch_sha`/`branch_tree` for the latter. `branch_parent` is the branch
    head commit's own parent sha, defaulting to `base_sha` (i.e. "already
    correctly parented") — set it to something else to model a stale branch.
    `branch_dest_blobs`/`base_dest_blobs` are {path: text} maps of files that
    exist under the report path on each tree, for the carry-forward checks.
    """

    def __init__(self, branch_exists=True, open_pr=False,
                 base_sha="BASE1", base_tree="T_BASE",
                 branch_sha="HEAD1", branch_tree="T_OLD",
                 branch_parent=None,
                 branch_dest_blobs=None, base_dest_blobs=None,
                 truncated=False):
        self.calls = []
        self.truncated = truncated
        self.branch_exists = branch_exists
        self.open_pr = open_pr
        self.base_sha = base_sha
        self.base_tree = base_tree
        self.branch_sha = branch_sha
        self.branch_tree = branch_tree
        self.branch_parent = base_sha if branch_parent is None else branch_parent
        self.branch_dest_blobs = branch_dest_blobs or {}
        self.base_dest_blobs = base_dest_blobs or {}
        self.ref_now = None
        self.last_tree = None
        self._blob_content = {}

    def _blob_sha(self, text):
        sha = f"B_{zlib.crc32(text.encode())}"
        self._blob_content[sha] = text
        return sha

    def _tree_entries(self, tree_sha):
        if tree_sha == self.base_tree:
            blobs = self.base_dest_blobs
        elif tree_sha == self.branch_tree:
            blobs = self.branch_dest_blobs
        else:
            blobs = {}
        return [{"path": path, "type": "blob", "mode": "100644",
                 "sha": self._blob_sha(text)} for path, text in blobs.items()]

    def __call__(self, method, url, token, body=None):
        self.calls.append((method, url.split("/repos/")[-1], body))
        if method == "GET" and "/git/ref/heads/" in url:
            branch = url.rsplit("/heads/", 1)[1]
            if branch == "main":
                return {"object": {"sha": self.base_sha}}
            if self.branch_exists:
                return {"object": {"sha": self.branch_sha}}
            raise pub.PublishError(f"GET {url} -> HTTP 404: Not Found")
        if method == "POST" and url.endswith("/git/refs"):
            return {}
        if method == "GET" and "/git/commits/" in url:
            sha = url.rsplit("/", 1)[1]
            if sha == self.base_sha:
                return {"tree": {"sha": self.base_tree}, "parents": []}
            return {"tree": {"sha": self.branch_tree},
                    "parents": [{"sha": self.branch_parent}]}
        if method == "GET" and "/git/trees/" in url:
            tree_sha = url.rsplit("/git/trees/", 1)[1].split("?")[0]
            return {"tree": self._tree_entries(tree_sha),
                    "truncated": self.truncated}
        if method == "GET" and "/git/blobs/" in url:
            sha = url.rsplit("/", 1)[1]
            return {"content": base64.b64encode(
                self._blob_content[sha].encode()).decode(),
                "encoding": "base64"}
        if method == "POST" and url.endswith("/git/trees"):
            payload = json.dumps(body["tree"], sort_keys=True)
            self.last_tree = f"T_{zlib.crc32(payload.encode())}"
            return {"sha": self.last_tree}
        if method == "POST" and url.endswith("/git/commits"):
            return {"sha": "c0ffee1234567890"}
        if method == "PATCH" and "/git/refs/heads/" in url:
            self.ref_now = body["sha"]
            self.ref_force = body.get("force")
            return {}
        if method == "GET" and "/pulls?" in url:
            return [{"html_url": "https://pr/existing"}] if self.open_pr else []
        if method == "POST" and url.endswith("/pulls"):
            return {"html_url": "https://pr/new"}
        raise AssertionError(f"unexpected call {method} {url}")

    def method_urls(self):
        return [(m, u) for m, u, _ in self.calls]

    def body_for(self, method, suffix):
        for m, u, b in self.calls:
            if m == method and u.endswith(suffix):
                return b
        return None


@pytest.fixture
def report_dir(tmp_path):
    def _write(verdict="PASS", md=True, latest=True):
        d = tmp_path / "report"
        d.mkdir(exist_ok=True)
        if latest:
            (d / "latest.json").write_text(
                json.dumps({"verdict": verdict, "date": "2026-09-30"}),
                encoding="utf-8")
        if md:
            (d / "report-2026-09-30.md").write_text("# report\n", encoding="utf-8")
        return str(d)
    return _write


@pytest.fixture
def fake(monkeypatch):
    def _install(gh):
        monkeypatch.setattr(pub, "_api", gh)
        return gh
    return _install


# --- unconfigured ---------------------------------------------------------

def test_no_token_exits_zero_and_explains(monkeypatch, capsys):
    """Publishing not being set up must not fail the gate run that just took
    70 minutes. But it must not look like it published either."""
    monkeypatch.delenv("PCN_GATE_PUBLISH_TOKEN", raising=False)
    monkeypatch.setenv("PCN_GATE_PUBLISH_REPO", "edgy-solutions/doc-tools")
    assert pub.main() == 0
    out = capsys.readouterr().out
    assert "PUBLISH SKIPPED" in out
    assert "PCN_GATE_PUBLISH_TOKEN" in out


def test_no_repo_names_the_repo_variable(monkeypatch, capsys):
    monkeypatch.setenv("PCN_GATE_PUBLISH_TOKEN", "t")
    monkeypatch.delenv("PCN_GATE_PUBLISH_REPO", raising=False)
    assert pub.main() == 0
    assert "PCN_GATE_PUBLISH_REPO" in capsys.readouterr().out


def test_the_skip_message_says_where_the_report_actually_is(monkeypatch, capsys):
    """A reader of the Job log needs to be able to go get the file by hand,
    which is the fallback this no-op leaves them in."""
    monkeypatch.delenv("PCN_GATE_PUBLISH_TOKEN", raising=False)
    monkeypatch.delenv("PCN_GATE_PUBLISH_REPO", raising=False)
    monkeypatch.setenv("PCN_GATE_REPORT_DIR", "/tmp/pcn-gate/report")
    pub.main()
    assert "/tmp/pcn-gate/report" in capsys.readouterr().out


def test_an_empty_string_token_counts_as_unset(monkeypatch, capsys):
    """The chart ships `PCN_GATE_PUBLISH_TOKEN: ""`, so the secret key EXISTS
    in every deployment. If empty did not count as unset, the default install
    would try to authenticate with "" and report an auth failure instead of
    "not configured"."""
    monkeypatch.setenv("PCN_GATE_PUBLISH_TOKEN", "")
    monkeypatch.setenv("PCN_GATE_PUBLISH_REPO", "edgy-solutions/doc-tools")
    assert pub.main() == 0
    assert "PUBLISH SKIPPED" in capsys.readouterr().out


# --- nothing to publish ---------------------------------------------------

def test_a_missing_latest_json_is_an_error_not_an_empty_success(report_dir, fake):
    """`latest.json` is the one file CI reads. Committing the markdown without
    it would be a published report the guard cannot see."""
    d = report_dir(latest=False)
    fake(FakeGitHub())
    with pytest.raises(pub.PublishError) as e:
        pub.publish(d, "o/r", "t")
    assert "latest.json" in str(e.value)
    assert "PCN_GATE_REPORT_DIR" in str(e.value)


def test_main_returns_one_when_there_is_nothing_to_publish(
        report_dir, fake, monkeypatch, capsys):
    """Configured but empty is a real failure: the gate was expected to leave
    a report behind and did not."""
    monkeypatch.setenv("PCN_GATE_PUBLISH_TOKEN", "t")
    monkeypatch.setenv("PCN_GATE_PUBLISH_REPO", "o/r")
    monkeypatch.setenv("PCN_GATE_REPORT_DIR", report_dir(latest=False))
    fake(FakeGitHub())
    assert pub.main() == 1
    assert "PUBLISH FAILED" in capsys.readouterr().out


def test_report_without_markdown_still_publishes(report_dir, fake):
    """The dated markdown is for humans; its absence is not a reason to
    withhold the machine-readable report."""
    gh = fake(FakeGitHub())
    result = pub.publish(report_dir(md=False), "o/r", "t")
    assert result["files"] == ["latest.json"]


# --- the happy path, and what it must look like ---------------------------

def test_all_files_land_in_one_commit(report_dir, fake):
    """Two files committed separately would leave the branch, between the two
    pushes, in a state where latest.json has moved and the prose beside it has
    not. One tree, one commit."""
    gh = fake(FakeGitHub())
    result = pub.publish(report_dir(), "o/r", "t")
    assert result["committed"]
    assert [m for m, u in gh.method_urls()].count("POST") >= 1
    commits = [u for m, u in gh.method_urls() if m == "POST" and u.endswith("/git/commits")]
    assert len(commits) == 1
    tree = gh.body_for("POST", "/git/trees")
    assert sorted(e["path"] for e in tree["tree"]) == [
        "docs/corpus-gate/latest.json",
        "docs/corpus-gate/report-2026-09-30.md",
    ]


def test_the_commit_moves_the_branch_ref(report_dir, fake):
    gh = fake(FakeGitHub())
    pub.publish(report_dir(), "o/r", "t")
    assert gh.ref_now == "c0ffee1234567890"
    assert ("PATCH", "o/r/git/refs/heads/corpus-gate/nightly") in gh.method_urls()


def test_the_ref_update_forces(report_dir, fake):
    """Reparenting onto base's tip is not a fast-forward, so the PATCH must
    carry force: True or GitHub rejects it."""
    gh = fake(FakeGitHub())
    pub.publish(report_dir(), "o/r", "t")
    patch_body = gh.body_for("PATCH", "/git/refs/heads/corpus-gate/nightly")
    assert patch_body["force"] is True


def test_it_never_patches_the_base_branch(report_dir, fake):
    """The single most important property of this script. main in this repo has
    no required checks, so a push to it is an unreviewed final write."""
    gh = fake(FakeGitHub())
    pub.publish(report_dir(), "o/r", "t")
    assert not [u for m, u in gh.method_urls()
                if m in ("PATCH", "POST") and u.endswith("/git/refs/heads/main")]


def test_the_commit_builds_on_the_existing_tree(report_dir, fake):
    """base_tree, so publishing a report does not delete the rest of the repo
    from the branch."""
    gh = fake(FakeGitHub())
    pub.publish(report_dir(), "o/r", "t")
    assert gh.body_for("POST", "/git/trees")["base_tree"] == gh.base_tree


def test_the_tree_is_built_on_bases_tree_not_the_stale_branch_tree(
        report_dir, fake):
    """The reparent fix: base_tree must be `base`'s tree, not whatever the
    publish branch's own (possibly stale) tree happens to be."""
    gh = fake(FakeGitHub(base_sha="BASE_NEW", base_tree="T_BASE_NEW",
                          branch_sha="HEAD_STALE", branch_tree="T_STALE",
                          branch_parent="BASE_OLD"))
    pub.publish(report_dir(), "o/r", "t")
    assert gh.body_for("POST", "/git/trees")["base_tree"] == "T_BASE_NEW"


def test_the_commit_parents_on_bases_tip_not_the_stale_branch_head(
        report_dir, fake):
    """The whole point of the fix: a branch left behind for nights must still
    produce a commit parented on base's CURRENT tip, not its own stale
    head."""
    gh = fake(FakeGitHub(base_sha="BASE_NEW", base_tree="T_BASE_NEW",
                          branch_sha="HEAD_STALE", branch_tree="T_STALE",
                          branch_parent="BASE_OLD"))
    result = pub.publish(report_dir(), "o/r", "t")
    assert result["committed"]
    assert gh.body_for("POST", "/git/commits")["parents"] == ["BASE_NEW"]


def test_the_commit_message_carries_the_verdict(report_dir, fake):
    gh = fake(FakeGitHub())
    pub.publish(report_dir(verdict="FAIL"), "o/r", "t")
    msg = gh.body_for("POST", "/git/commits")["message"]
    assert "FAIL" in msg
    assert "Co-Authored-By: Claude Opus 5" in msg


def test_a_red_report_is_published(report_dir, fake):
    """The report you most need in the repo is the failing one."""
    gh = fake(FakeGitHub())
    result = pub.publish(report_dir(verdict="FAIL"), "o/r", "t")
    assert result["committed"] and result["verdict"] == "FAIL"


def test_an_unparseable_latest_json_is_still_published_as_unknown(
        report_dir, fake, tmp_path):
    """A report the gate wrote but we cannot parse is evidence about the run.
    Refusing to publish it would destroy the only copy when the pod exits."""
    d = report_dir()
    (Path(d) / "latest.json").write_text("{not json", encoding="utf-8")
    gh = fake(FakeGitHub())
    result = pub.publish(d, "o/r", "t")
    assert result["committed"] and result["verdict"] == "unknown"


# --- idempotence ----------------------------------------------------------

def test_an_identical_report_does_not_create_a_commit(report_dir, fake):
    """A nightly job that commits whether or not anything changed teaches its
    readers that its commits mean nothing. True no-op requires BOTH: the
    branch already holds this exact tree, AND it is already parented on
    base's tip (the default `branch_parent`)."""
    gh = FakeGitHub()
    fake(gh)
    assert pub.publish(report_dir(), "o/r", "t")["committed"]
    # Replay against a branch whose head already carries that exact tree,
    # correctly parented on base (branch_parent defaults to base_sha).
    gh2 = fake(FakeGitHub(branch_tree=gh.last_tree))
    second = pub.publish(report_dir(), "o/r", "t")
    assert second["committed"] is False
    assert "already" in second["reason"]
    assert not [u for m, u in gh2.method_urls()
                if m == "POST" and u.endswith("/git/commits")]
    assert gh2.ref_now is None


def test_a_pure_reparent_commits_even_with_an_unchanged_tree(report_dir, fake):
    """Same content, but the branch's existing head is parented on a stale
    commit, not base's current tip: that alone must still produce a commit,
    because the reparent itself is what clears the conflicting PR."""
    gh = fake(FakeGitHub())
    assert pub.publish(report_dir(), "o/r", "t")["committed"]
    gh2 = fake(FakeGitHub(branch_tree=gh.last_tree, branch_parent="OLD_BASE"))
    second = pub.publish(report_dir(), "o/r", "t")
    assert second["committed"] is True
    assert gh2.body_for("POST", "/git/commits")["parents"] == [gh2.base_sha]


def test_a_no_op_still_reports_the_pull_request(report_dir, fake, monkeypatch,
                                                capsys):
    """Unchanged is not the same as nothing to look at — the PR is still the
    thing a human has to merge."""
    gh = FakeGitHub()
    fake(gh)
    pub.publish(report_dir(), "o/r", "t")
    fake(FakeGitHub(branch_tree=gh.last_tree, open_pr=True))
    result = pub.publish(report_dir(), "o/r", "t")
    assert result["committed"] is False
    assert result["pr"] == "https://pr/existing"


# --- carry-forward ----------------------------------------------------------

def test_a_branch_only_report_is_carried_forward(report_dir, fake):
    """A previous night's report may be sitting on the branch, not yet merged
    to base. Reparenting onto base's tree must not silently drop it."""
    gh = fake(FakeGitHub(branch_dest_blobs={
        "docs/corpus-gate/report-2026-09-28.md": "# old report\n",
    }))
    pub.publish(report_dir(), "o/r", "t")
    tree = gh.body_for("POST", "/git/trees")["tree"]
    carried = [e for e in tree
               if e["path"] == "docs/corpus-gate/report-2026-09-28.md"]
    assert len(carried) == 1
    assert carried[0]["content"] == "# old report\n"
    # today's own report is still there too
    assert any(e["path"] == "docs/corpus-gate/report-2026-09-30.md"
               for e in tree)


def test_a_report_already_present_on_base_is_not_duplicated(report_dir, fake):
    """If base already carries that dated report (it was merged since), the
    branch's copy must not be carried forward a second time."""
    gh = fake(FakeGitHub(
        branch_dest_blobs={
            "docs/corpus-gate/report-2026-09-28.md": "# old report\n"},
        base_dest_blobs={
            "docs/corpus-gate/report-2026-09-28.md": "# old report\n"},
    ))
    pub.publish(report_dir(), "o/r", "t")
    tree = gh.body_for("POST", "/git/trees")["tree"]
    assert [e["path"] for e in tree].count(
        "docs/corpus-gate/report-2026-09-28.md") == 0


def test_latest_json_is_never_carried_forward(report_dir, fake):
    """latest.json is this run's measurement, always. An older copy sitting
    on the branch must never be merged with or substituted for it."""
    gh = fake(FakeGitHub(branch_dest_blobs={
        "docs/corpus-gate/latest.json": json.dumps({"verdict": "FAIL"}),
    }))
    pub.publish(report_dir(verdict="PASS"), "o/r", "t")
    tree = gh.body_for("POST", "/git/trees")["tree"]
    latest_entries = [e for e in tree
                       if e["path"] == "docs/corpus-gate/latest.json"]
    assert len(latest_entries) == 1
    assert json.loads(latest_entries[0]["content"])["verdict"] == "PASS"


# --- branch and PR lifecycle ----------------------------------------------

def test_a_missing_branch_is_created_off_base(report_dir, fake):
    gh = fake(FakeGitHub(branch_exists=False))
    result = pub.publish(report_dir(), "o/r", "t")
    assert result["created_branch"]
    assert result["committed"] is True
    created = gh.body_for("POST", "/git/refs")
    assert created == {"ref": "refs/heads/corpus-gate/nightly",
                        "sha": gh.base_sha}


def test_an_existing_pull_request_is_reused(report_dir, fake):
    """One standing PR. A new PR per night would be 30 PRs a month and nobody
    would read any of them."""
    gh = fake(FakeGitHub(open_pr=True))
    result = pub.publish(report_dir(), "o/r", "t")
    assert result["pr_opened"] is False
    assert result["pr"] == "https://pr/existing"
    assert not [u for m, u in gh.method_urls() if m == "POST" and u.endswith("/pulls")]


def test_a_pull_request_is_opened_when_none_is_open(report_dir, fake):
    gh = fake(FakeGitHub(open_pr=False))
    result = pub.publish(report_dir(), "o/r", "t")
    assert result["pr_opened"] is True
    body = gh.body_for("POST", "/pulls")
    assert body["head"] == "corpus-gate/nightly" and body["base"] == "main"
    assert "Generated with [Claude Code]" in body["body"]


def test_the_pr_query_scopes_head_to_the_owner(report_dir, fake):
    """`head=branch` without the owner prefix matches across forks."""
    gh = fake(FakeGitHub())
    pub.publish(report_dir(), "o/r", "t")
    pulls = [u for m, u in gh.method_urls() if m == "GET" and "/pulls?" in u]
    assert pulls and "head=o:corpus-gate/nightly" in pulls[0]


def test_a_non_404_error_resolving_the_branch_is_not_swallowed(report_dir,
                                                              monkeypatch):
    """A 401 must not be mistaken for "the branch does not exist yet" and lead
    to an attempt to create it."""
    def boom(method, url, token, body=None):
        raise pub.PublishError(f"{method} {url} -> HTTP 401: Bad credentials")
    monkeypatch.setattr(pub, "_api", boom)
    with pytest.raises(pub.PublishError) as e:
        pub.publish(report_dir(), "o/r", "t")
    assert "401" in str(e.value)


# --- configuration surface ------------------------------------------------

def test_env_overrides_reach_the_api_calls(report_dir, fake, monkeypatch,
                                           capsys):
    gh = FakeGitHub()
    fake(gh)
    monkeypatch.setenv("PCN_GATE_PUBLISH_TOKEN", "t")
    monkeypatch.setenv("PCN_GATE_PUBLISH_REPO", "other/repo")
    monkeypatch.setenv("PCN_GATE_PUBLISH_BRANCH", "nightly-x")
    monkeypatch.setenv("PCN_GATE_PUBLISH_BASE", "develop")
    monkeypatch.setenv("PCN_GATE_PUBLISH_PATH", "reports/gate")
    monkeypatch.setenv("PCN_GATE_REPORT_DIR", report_dir())
    assert pub.main() == 0
    assert ("PATCH", "other/repo/git/refs/heads/nightly-x") in gh.method_urls()
    assert gh.body_for("POST", "/pulls")["base"] == "develop"
    assert all(e["path"].startswith("reports/gate/")
               for e in gh.body_for("POST", "/git/trees")["tree"])


def test_a_trailing_slash_on_the_dest_path_does_not_double(report_dir, fake):
    gh = fake(FakeGitHub())
    pub.publish(report_dir(), "o/r", "t", dest="docs/corpus-gate/")
    assert all("//" not in e["path"]
               for e in gh.body_for("POST", "/git/trees")["tree"])


def test_the_default_dest_is_where_the_ci_guard_looks(report_dir, fake):
    """If these two ever drift, the publisher commits a report CI does not
    read and the guard fails on a report that exists."""
    guard = (Path(__file__).resolve().parent /
             "test_corpus_gate_guard.py").read_text(encoding="utf-8")
    assert pub.DEFAULT_REPORT_DIR == "docs/corpus-gate"
    assert '"docs" / "corpus-gate" / "latest.json"' in guard


# --- the chart wiring -----------------------------------------------------

CHART = Path(__file__).resolve().parents[1] / "charts" / "doc-tools"


def test_the_cronjob_runs_the_publisher_after_the_gate():
    tpl = (CHART / "templates" / "corpus-gate-cronjob.yaml").read_text(
        encoding="utf-8")
    # Scope to the shell script the container runs — the header comment names
    # both scripts too, and prose order is not execution order.
    script = tpl.split('command: ["/bin/sh", "-c"]', 1)[1]
    assert "pcn_gate_publish.py" in script
    assert (script.index("pcn_corpus_gate.py --run")
            < script.index("pcn_gate_publish.py"))


def test_the_cronjob_preserves_the_gate_exit_code():
    """`exit $rc` after the publisher, so a publish success cannot mask a red
    gate — the verdict is the Job's result."""
    tpl = (CHART / "templates" / "corpus-gate-cronjob.yaml").read_text(
        encoding="utf-8")
    assert 'rc=$?' in tpl and 'exit "$rc"' in tpl


def test_the_publish_token_is_not_a_plain_env_var_in_the_template():
    """It must arrive via the secretRef, or `helm get manifest` prints it."""
    tpl = (CHART / "templates" / "corpus-gate-cronjob.yaml").read_text(
        encoding="utf-8")
    assert "name: PCN_GATE_PUBLISH_TOKEN" not in tpl


def test_the_chart_default_does_not_publish():
    """Enabling the CronJob must not, by itself, start pushing to a repo."""
    values = (CHART / "values.yaml").read_text(encoding="utf-8")
    assert 'repo: ""' in values
    assert "PCN_GATE_PUBLISH_TOKEN: \"\"" in values


def test_the_chart_does_not_default_the_publish_branch_to_main():
    values = (CHART / "values.yaml").read_text(encoding="utf-8")
    assert "branch: corpus-gate/nightly" in values


def test_a_truncated_tree_listing_refuses_instead_of_carrying_forward_partially(
        report_dir, fake):
    """A truncated listing must stop the publish dead.

    The carry-forward is the only thing making the nightly force-reparent safe:
    it reads back reports that are on the branch and not yet on main, so the
    force cannot drop them. GitHub truncates a large recursive tree by OMITTING
    ENTRIES, with a 200 and no error. If that were accepted, a report missing
    from the listing would be missing from the new tree, and the force-update
    would destroy it -- the precise loss the carry-forward exists to prevent.
    So it raises, and crucially the ref must not move.
    """
    gh = fake(FakeGitHub(
        truncated=True,
        branch_tree="T_STALE",
        branch_dest_blobs={"docs/corpus-gate/report-2026-01-01T000000Z.md": "older"},
    ))


    with pytest.raises(pub.PublishError) as exc:
        pub.publish(report_dir(), "o/r", "tok")

    assert "TRUNCATED" in str(exc.value)
    assert gh.ref_now is None, "the branch ref moved despite a partial listing"
    assert not any(m == "POST" and u.endswith("/git/commits")
                   for m, u, _ in gh.calls), "it committed on a partial listing"
