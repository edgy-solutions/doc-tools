"""THE CROSS-REPO SEAL — doc-tools' kind rows vs the platform's overlay rows.

Ordered 2026-10-06: *"a test that doc-tools' rows equal the overlay's
content_kinds.yaml (pcn, pdn -> SUSTAINMENT; s1000d-data-module -> MAINTENANCE),
so the two registries can't diverge while the platform reads the overlay."*

WHY THIS CAN EXIST ONLY SINCE 2026-10-06. When the order was written the platform
composed exactly ``['maintenance-fault-event']`` -- measured in the deployed
``iagent-cortex-bff``, with ``pcn``/``pdn``/``s1000d-data-module`` all False -- so
an equality test would have been red on day one, asserting a registration decision
nobody had taken. `invincible-agent` `914c7fa` ("reviewers resolve from
content_kind") then took it: the overlay gained ``pcn``, ``pdn`` (sustainment) and
``s1000d-data-module`` (maintenance), which is Option A of the two the seam
decision offered. The premise is now true and the seal is writable.

WHAT IS AND IS NOT SEALED HERE, stated so nobody reads more into a green run:

 1. **The intersection is sealed.** For every kind declared on BOTH sides, the
    ``passes``, ``outputs`` and declared domain must agree exactly. That is the
    real drift risk -- two services disagreeing about what a kind MEANS, where
    the platform would run a pass set we do not declare, or stamp a domain we did
    not rule.

    **Equality is symmetric; ownership is not.** The architect's ruling of
    2026-10-24, amending 10-07: the platform owns what a kind IS (``kind``,
    ``domain``, ``arrives_as``, ``review_shape``, ``label``); doc-tools owns what
    it RUNS (``passes``). The overlay MIRRORS ``passes`` from the registry here,
    never the reverse, because the platform never executes them -- its copy is
    documentary. So a ``passes`` divergence is always the overlay's to correct,
    and this file must never be made green by aligning our declaration DOWN to a
    row nothing runs. The ``passes`` arm below says so in its failure, so that
    whoever reads the red knows which side owes the change; the ``outputs`` and
    domain arms stay symmetric, because those the platform does own.
 2. **The one-sided SET is sealed; absence as such is not.** A kind declared on
    only one side is a registration gap, and making a gap a failure would mean a
    red suite for a decision owned by another repo. But the SET of one-sided
    kinds is pinned exactly (``OURS_ONLY`` / ``OVERLAY_ONLY`` below, one reason
    per entry), so a NEW one-sided kind on either side is loud: it is a
    registration decision the platform takes, never something to make green by
    deleting a row here. At the pinned ref the sets are ours-only ``cad``,
    ``document``, ``dxf``, ``step-ap242`` and overlay-only
    ``maintenance-fault-event``. (This item used to name ``work-instruction``,
    ``pdf``, ``doors-export`` and ``engineering-document`` as ours-only; the
    overlay has since gained all four.)
 3. **The DEPLOYED fleet is not sealed at all.** These are both committed trees. At
    the time of writing the running pods still compose one kind, because the merge
    above is newer than the deployed image. A green test here says the two
    REGISTRIES agree, never that the fleet serves them.

WHY IT READS A PINNED REF, AND NEVER A WORKING TREE. The overlay lives in
`invincible-agent`. Vendoring a snapshot into this repo would create exactly the
cross-repo coupling AGENTS.md removed when the TBox TTLs moved out, and a stale
snapshot is worse than no check: it would go green against a copy nobody updates.
That argument still holds, and it is why a pinned FETCH beats a copy.

This file used to read the sibling checkout's working tree, and that was its
defect. Measured 2026-10-27: the sibling sat on
``lane/ca-resolve-instance-adoption``, 149 commits behind ``origin/master``, so
the seal was reporting another lane's in-progress branch as the platform's
registry. The red it showed (``doors-export``) was not the drift that exists --
at ``origin/master`` ``doors-export`` agrees and the real divergence is
``course``, whose overlay ``passes`` omit ``render.pages``. A working tree that
far behind could as easily have reported a green that did not exist either.
No seal reads "whatever branch is checked out."

So the overlay is resolved from the sha in ``tests/pins/invincible-agent.ref``:
CI checks the platform out at that sha and points
``IAGENT_CONTENT_KIND_OVERLAY_DIR`` at it (setting
``IAGENT_CONTENT_KIND_OVERLAY_REF`` too, so the seal can prove the directory IS
the pin); locally, a sibling repo is read from the pinned commit's OBJECTS via
``git archive``, never its files. A missing fetch FAILS in CI and skips only when
CI's env var is absent. The pin is bumped in a one-line PR carrying the drift
report.
"""
import io
import json
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ROWS_DIR = REPO_ROOT / "registry" / "content_kinds"
DOMAINS_FILE = REPO_ROOT / "registry" / "content_kind_domains.json"

#: The pinned platform commit. A full 40-hex sha, so it cannot move under the seal.
PIN_FILE = REPO_ROOT / "tests" / "pins" / "invincible-agent.ref"

#: Where the platform's overlay rows are. The DIR env var is the explicit CI/job
#: path (CI checks out the pin and points here); the REF env var, when also set,
#: must equal the pin so a job that fetched the wrong commit is caught.
OVERLAY_ENV = "IAGENT_CONTENT_KIND_OVERLAY_DIR"
OVERLAY_REF_ENV = "IAGENT_CONTENT_KIND_OVERLAY_REF"
OVERLAY_SUBPATH = "policy/overlays/openddil-lab/content_kinds"
SIBLING_REPO = REPO_ROOT.parent / "invincible-agent"
FETCH_COMMAND = "git -C ../invincible-agent fetch origin master"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _read_pin(path=None):
    """The pinned sha. Strips, ignores blanks and ``#`` comments, demands 40 hex."""
    path = PIN_FILE if path is None else path
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]
    sha = lines[0] if lines else ""
    assert _SHA_RE.match(sha), (
        f"{path} must hold one full 40-hex lowercase commit sha, got {sha!r}. A "
        f"short sha or a branch name is not acceptable here: the whole point is "
        f"that the ref cannot move under the seal.")
    return sha


def _overlay_from_pinned_objects(sibling, sha, scratch):
    """Materialize the overlay from ``sha``'s git objects in ``sibling``, or None.

    ``git archive`` reads the commit, never the working tree. Extracted by hand
    from the tar (regular files only) rather than shelling out to ``tar``.
    """
    have = subprocess.run(
        ["git", "-C", str(sibling), "cat-file", "-e", f"{sha}^{{commit}}"],
        capture_output=True)
    if have.returncode != 0:
        return None
    arc = subprocess.run(
        ["git", "-C", str(sibling), "archive", sha, OVERLAY_SUBPATH],
        capture_output=True)
    if arc.returncode != 0:
        return None
    with tarfile.open(fileobj=io.BytesIO(arc.stdout)) as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            dest = (scratch / m.name).resolve()
            assert scratch.resolve() in dest.parents, f"unsafe tar member {m.name}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(tf.extractfile(m).read())
    out = scratch / OVERLAY_SUBPATH
    return out if out.is_dir() else None


def _resolve_overlay(scratch_factory):
    """The overlay directory at the PIN. Fails or skips; never guesses.

    Order: (1) the explicit DIR env var, with REF (if set) proven equal to the
    pin; (2) a sibling repo's pinned commit objects; (3) nothing -- FAIL under
    CI, skip otherwise.
    """
    pin = _read_pin()
    env = os.environ.get(OVERLAY_ENV)
    if env:
        p = Path(env)
        if not p.is_dir():
            pytest.fail(
                f"{OVERLAY_ENV} is set to {env!r} but that is not a directory. An "
                f"explicitly configured overlay path that does not resolve is a "
                f"broken job, not a reason to skip -- skipping here would hide "
                f"the seal while looking green.")
        ref = os.environ.get(OVERLAY_REF_ENV)
        if ref and ref.strip() != pin:
            pytest.fail(
                f"{OVERLAY_REF_ENV} is {ref.strip()!r} but {PIN_FILE.name} pins "
                f"{pin!r}. The job fetched a different commit than the one this "
                f"seal is pinned to; a seal that believed it would be measuring "
                f"the wrong registry.")
        return p
    if (SIBLING_REPO / ".git").exists():
        d = _overlay_from_pinned_objects(
            SIBLING_REPO, pin, scratch_factory.mktemp("overlay-pin"))
        if d is not None:
            return d
    msg = (f"the platform's content-kind overlay at pin {pin} cannot be resolved. "
           f"Fetch it with `{FETCH_COMMAND}` (or check invincible-agent out "
           f"beside this repo at {SIBLING_REPO}), or point {OVERLAY_ENV} at "
           f"{OVERLAY_SUBPATH} of a checkout AT that sha.")
    if os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"):
        pytest.fail(
            f"{msg} In CI a missing fetch is a broken job, not a skip: a seal "
            f"that skips in the one place it is meant to run is the defect.")
    pytest.skip(
        f"{msg} The cross-repo seal cannot run. It is NOT satisfied, only unrun.")


def _load_rows(d):
    """{kind: row dict} from a directory of one-row-per-file YAML."""
    rows = {}
    for f in sorted(d.iterdir()):
        if f.suffix not in (".yaml", ".yml"):
            continue
        row = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        kind = row.get("kind")
        assert kind, f"{f} declares no kind"
        assert kind not in rows, (
            f"{kind} is declared twice in {d}: {f.name} and an earlier file. The "
            f"composer refuses a kind declared twice anywhere on the path, and "
            f"the registry FAILS CLOSED -- so this would take every other kind "
            f"down with it, including maintenance-fault-event.")
        rows[kind] = row
    return rows


@pytest.fixture(scope="module")
def overlay_rows(tmp_path_factory):
    return _load_rows(_resolve_overlay(tmp_path_factory))


@pytest.fixture(scope="module")
def our_rows():
    return _load_rows(ROWS_DIR)


@pytest.fixture(scope="module")
def our_domains():
    return json.loads(DOMAINS_FILE.read_text(encoding="utf-8"))["domains"]


def _shared(a, b):
    return sorted(set(a) & set(b))


def _domainless_split(rows):
    """``(explicit_null, omitted)`` — two sets, because they are two claims.

    Lane 1's route distinguishes them (pydantic ``model_fields_set``, through
    ``iagent_mesh.ingest.compose``): an explicit ``domain: null`` is the
    2026-10-02 ruling and routes to ``awaiting_origin``; an OMITTED key is
    still refused ``422 no_declared_domain``. A single ``not
    row.get("domain")`` cannot tell them apart, so the split lives here and
    both tests below use it rather than re-deriving it.
    """
    explicit_null = {k for k, row in rows.items()
                     if "domain" in row and not row["domain"]}
    omitted = {k for k, row in rows.items() if "domain" not in row}
    return explicit_null, omitted


def test_the_two_registries_share_the_ruled_kinds(overlay_rows, our_rows):
    """The ordered pairs must be on both sides, or there is nothing to seal.

    Without this, every assertion below would pass vacuously on an empty
    intersection -- which is exactly the state the order was written in, and
    exactly the state a green run must not be able to mean.
    """
    for kind in ("pcn", "pdn", "s1000d-data-module"):
        assert kind in our_rows, f"{kind} is missing from {ROWS_DIR}"
        assert kind in overlay_rows, (
            f"{kind} is no longer declared in the platform's overlay. It was "
            f"added in invincible-agent 914c7fa; if it has been removed, the "
            f"platform cannot route that kind and the rest of this file is "
            f"sealing an intersection that no longer contains it.")


def test_the_shared_kinds_declare_the_same_passes(overlay_rows, our_rows):
    """The overlay must mirror OUR ``passes``; doc-tools is the source.

    Equality is still what is asserted -- but the two sides are not
    interchangeable, so the failure names which one owes the change. Per the
    2026-10-24 ownership ruling, ``passes`` is doc-tools' field and the overlay
    carries a documentary copy the platform never executes. The remedy for a red
    here is therefore ALWAYS to update the overlay row, and never to narrow what
    we declare to match it: a pass we stop declaring is a pass that stops
    running, which is a real behaviour change traded for a green test.

    The name of this function is load-bearing outside this repo. The platform's
    ``cross-repo-kind-drift.yml`` control step greps pytest output for it, and
    for the mismatched kind, to prove the seal reds for the right reason -- so
    renaming it, or dropping the kind key from the message below, breaks a gate
    in another tree.
    """
    shared = _shared(overlay_rows, our_rows)
    assert shared, "no shared kinds; see the sharing test above"
    mismatched = {
        k: {"source (doc-tools, authoritative)":
                list(our_rows[k].get("passes") or []),
            "mirror (overlay, must match the source)":
                list(overlay_rows[k].get("passes") or [])}
        for k in shared
        if list(our_rows[k].get("passes") or [])
        != list(overlay_rows[k].get("passes") or [])
    }
    assert not mismatched, (
        f"the overlay's passes do not mirror this registry, which owns them. "
        f"Fix the overlay row(s) in invincible-agent; do not change ours to "
        f"match. Ownership ruling 2026-10-24.\n"
        f"{json.dumps(mismatched, indent=2)}")


def test_the_shared_kinds_declare_the_same_outputs(overlay_rows, our_rows):
    """Outputs name the classes that reach the graph; a divergence here means
    one side writes a class the other never declared."""
    shared = _shared(overlay_rows, our_rows)
    assert shared, "no shared kinds; see the sharing test above"
    mismatched = {
        k: {"ours": list(our_rows[k].get("outputs") or []),
            "overlay": list(overlay_rows[k].get("outputs") or [])}
        for k in shared
        if list(our_rows[k].get("outputs") or [])
        != list(overlay_rows[k].get("outputs") or [])
    }
    assert not mismatched, (
        f"outputs diverged between the two registries: "
        f"{json.dumps(mismatched, indent=2)}")


def test_the_shared_kinds_declare_the_same_domain(overlay_rows, our_domains):
    """THE PAIR THE ORDER NAMED: pcn, pdn -> sustainment; s1000d-data-module ->
    maintenance.

    Compared against our SIDECAR, not against our rows, because ``domain`` is
    not an authorable field in a doc-tools row at our SDK pin -- adding one
    raises -- which is why the domain rides in
    ``registry/content_kind_domains.json`` in the first place.

    Case is normalised: ours is the lowercase ``domain_type``, and the platform
    writes the same value; the ruling's SUSTAINMENT/MAINTENANCE is the uppercase
    Neo4j label and graph name either way.
    """
    mismatched = {}
    for kind, row in sorted(overlay_rows.items()):
        if kind not in our_domains:
            continue  # theirs alone; absence is not sealed here, see the docstring
        theirs = row.get("domain")
        ours = our_domains[kind]
        if (theirs or "").lower() != (ours or "").lower():
            mismatched[kind] = {"ours": ours, "overlay": theirs}
    assert not mismatched, (
        f"declared domain diverged between the two registries: "
        f"{json.dumps(mismatched, indent=2)}. A kind whose domain disagrees "
        f"writes instances into the wrong <http://internal/DOMAIN_INSTANCES> "
        f"graph, or into none.")


def test_a_domainless_overlay_row_is_exactly_one_we_ruled_domainless(
        overlay_rows, our_domains):
    """NARROWED 2026-10-07: domainless is now a RULING, not a defect.

    This test used to assert that NO overlay row was domainless, and that was
    right while `invincible-agent` 914c7fa refused such a row at review with
    ``422 no_declared_domain`` and wrote nothing — a drop that ingests and then
    strands, the shape of the PCN26-117 bug.

    Roll #20 (`invincible-agent` master ``a0c2ba18``) changed the behaviour it
    was guarding: a REGISTERED kind whose row carries an EXPLICIT ``domain:
    null`` now files no task, moves the row to ``awaiting_origin`` and returns
    **200**, with the detail "origin resolved by evidence, not kind (ruling
    2026-10-02)". That is precisely the disposition this repo rules for ``pdf``,
    ``engineering-document`` and ``doors-export``, so keeping the blanket
    assertion would make a correct overlay row red the moment Lane 1 adds one —
    a test blocking the change it was written to protect.

    So the assertion moves from "none" to "exactly the ruled set". An UNRULED
    domainless row is still loud: the two registries would then disagree about
    whether a kind resolves its origin from evidence, and this file exists to
    catch exactly that disagreement.

    VACUOUS TODAY, DELIBERATELY. The overlay currently declares four rows and
    every one of them names a domain, so this assertion has nothing to reject
    yet. It becomes load-bearing the moment Lane 1 adds the three ruled rows —
    which is the point: the blanket version would have turned red on that
    commit. ``test_the_discrimination_is_on_key_presence`` below seals the
    LOGIC meanwhile, against synthetic rows, so a green run here is not the
    only thing standing behind it.
    """
    ruled_domainless = {k for k, v in our_domains.items() if v is None}
    explicit_null, _ = _domainless_split(overlay_rows)

    unruled = sorted(explicit_null - ruled_domainless)
    assert not unruled, (
        f"the platform's overlay declares {unruled} with an explicit null "
        f"domain, but {DOMAINS_FILE.name} rules a domain for them (or does not "
        f"declare them at all). Our ruled-domainless set is "
        f"{sorted(ruled_domainless)}. Either the ruling moved or the overlay "
        f"row is wrong; the two cannot both be right.")


def test_an_overlay_row_that_omits_domain_entirely_is_still_a_defect(overlay_rows):
    """The half the ruling did NOT make legal, kept separate on purpose.

    Lane 1's route distinguishes an explicit ``domain: null`` from an OMITTED
    key (pydantic ``model_fields_set``, through ``iagent_mesh.ingest.compose``).
    The explicit null is the 2026-10-02 ruling and routes to
    ``awaiting_origin``; an omitted key is still refused ``422
    no_declared_domain``, because "we ruled this kind resolves its origin from
    evidence" and "nobody filled the field in" are different claims that happen
    to produce the same empty value.

    Folding these two into one ``not row.get("domain")`` check — which is what
    the previous version of this file did — would let an omitted key ride in
    under the ruling's exemption and strand every drop of that kind.
    """
    _, omitted_set = _domainless_split(overlay_rows)
    omitted = sorted(omitted_set)
    assert not omitted, (
        f"the platform's overlay rows {omitted} OMIT the domain key. An "
        f"omitted key is not the 2026-10-02 ruling: review refuses it 422 "
        f"no_declared_domain and writes nothing, so every drop of that kind "
        f"would ingest and then strand. A kind that resolves its origin from "
        f"evidence must say so with an explicit `domain: null`.")


def test_the_discrimination_is_on_key_presence_not_on_falsiness():
    """The logic the two tests above lean on, sealed without the overlay.

    Both of them are satisfied today by an overlay in which every row names a
    domain, so neither can show that the explicit-null / omitted distinction is
    actually made. This can, and it needs no overlay checkout — so it also runs
    in single-repo CI, where the two tests above skip.

    The empty string is here because it is the third way a YAML row can fail to
    name a domain, and it must land with the explicit nulls rather than with
    the omissions: the key was written, so the row is making the ruling's claim
    badly, not failing to make it.
    """
    rows = {
        "named": {"kind": "named", "domain": "sustainment"},
        "null": {"kind": "null", "domain": None},
        "empty": {"kind": "empty", "domain": ""},
        "absent": {"kind": "absent"},
    }
    explicit_null, omitted = _domainless_split(rows)
    assert explicit_null == {"null", "empty"}
    assert omitted == {"absent"}
    # And a row that names a domain is in neither — the property that keeps
    # both assertions above from firing on a perfectly ordinary row.
    assert "named" not in explicit_null and "named" not in omitted


# --- the one-sided-kind arm ---------------------------------------------------

#: Kinds WE declare that the overlay does not, at the pinned ref. Each is a
#: ruling, not an oversight; a new entry is a registration decision.
OURS_ONLY = frozenset({
    "cad",           # ours and unregistered on the platform
    "document",      # #168; inert pending lane 1's allowed_leaves
    "dxf",           # ours and unregistered on the platform
    "step-ap242",    # ours and unregistered on the platform
})

#: Kinds the overlay declares that we do not.
OVERLAY_ONLY = frozenset({
    "maintenance-fault-event",  # the platform's; we run no pass for it
})


def test_the_one_sided_kinds_are_exactly_the_ones_we_have_ruled(
        overlay_rows, our_rows):
    ours_only = frozenset(set(our_rows) - set(overlay_rows))
    overlay_only = frozenset(set(overlay_rows) - set(our_rows))
    problems = []
    if ours_only != OURS_ONLY:
        problems.append(
            f"OUR side gained {sorted(ours_only - OURS_ONLY)} and lost "
            f"{sorted(OURS_ONLY - ours_only)} versus the ruled ours-only set")
    if overlay_only != OVERLAY_ONLY:
        problems.append(
            f"the OVERLAY side gained {sorted(overlay_only - OVERLAY_ONLY)} and "
            f"lost {sorted(OVERLAY_ONLY - overlay_only)} versus the ruled "
            f"overlay-only set")
    assert not problems, (
        "; ".join(problems) + ". Whether a kind is registered on both sides is "
        "a registration decision the platform takes -- update the ruled sets "
        "above with a reason, never make this green by deleting a row here.")


# --- the seal's own machinery (resolution of the pin) -------------------------

class _NoScratch:
    def mktemp(self, name):  # pragma: no cover - must not be reached
        raise AssertionError("scratch requested with nothing to materialize")


def _nothing_resolvable(monkeypatch, tmp_path):
    monkeypatch.delenv(OVERLAY_ENV, raising=False)
    monkeypatch.delenv(OVERLAY_REF_ENV, raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(sys.modules[__name__], "SIBLING_REPO", tmp_path / "absent")


def test_the_pin_file_is_one_lf_terminated_sha():
    data = PIN_FILE.read_bytes()
    assert b"\r" not in data, "pin file has a CR; write it as bytes with a bare LF"
    assert data.endswith(b"\n")
    assert _SHA_RE.match(_read_pin())
    assert len([ln for ln in data.decode().splitlines() if ln.strip()]) == 1


@pytest.mark.parametrize("content", ["abc1234\n", "master\n", "", "\n# only a comment\n"])
def test_a_short_sha_a_branch_or_an_empty_pin_fails_the_reader(tmp_path, content):
    f = tmp_path / "pin.ref"
    f.write_bytes(content.encode())
    with pytest.raises(AssertionError):
        _read_pin(f)


def test_a_ref_env_that_differs_from_the_pin_fails_naming_both(
        monkeypatch, tmp_path):
    other = "0" * 40
    monkeypatch.setenv(OVERLAY_ENV, str(tmp_path))
    monkeypatch.setenv(OVERLAY_REF_ENV, other)
    with pytest.raises(pytest.fail.Exception) as e:
        _resolve_overlay(_NoScratch())
    assert other in str(e.value) and _read_pin() in str(e.value)


def test_a_dir_env_that_is_not_a_directory_still_fails(monkeypatch, tmp_path):
    monkeypatch.setenv(OVERLAY_ENV, str(tmp_path / "nope"))
    monkeypatch.delenv(OVERLAY_REF_ENV, raising=False)
    with pytest.raises(pytest.fail.Exception, match="not a directory"):
        _resolve_overlay(_NoScratch())


def test_nothing_resolvable_in_ci_fails_and_names_the_fetch(monkeypatch, tmp_path):
    _nothing_resolvable(monkeypatch, tmp_path)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(pytest.fail.Exception) as e:
        _resolve_overlay(_NoScratch())
    assert FETCH_COMMAND in str(e.value)


def test_nothing_resolvable_outside_ci_skips_as_unrun(monkeypatch, tmp_path):
    _nothing_resolvable(monkeypatch, tmp_path)
    with pytest.raises(pytest.skip.Exception) as e:
        _resolve_overlay(_NoScratch())
    assert "NOT satisfied, only unrun" in str(e.value)
