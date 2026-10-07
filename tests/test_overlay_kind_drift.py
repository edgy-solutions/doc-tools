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
 2. **Absence is NOT sealed.** ``work-instruction``, ``pdf``, ``doors-export`` and
    ``engineering-document`` are ours and are not in the overlay. That is a
    registration gap, reported separately, not drift -- and making it a failure
    here would mean a red suite for a decision owned by another repo.
 3. **The DEPLOYED fleet is not sealed at all.** These are both committed trees. At
    the time of writing the running pods still compose one kind, because the merge
    above is newer than the deployed image. A green test here says the two
    REGISTRIES agree, never that the fleet serves them.

WHY IT SKIPS RATHER THAN VENDORS A COPY. The overlay lives in `invincible-agent`.
Vendoring a snapshot into this repo would create exactly the cross-repo coupling
AGENTS.md removed when the TBox TTLs moved out, and a stale snapshot is worse than
no check: it would go green against a copy nobody updates. So this reads the real
file when it can see it and skips, loudly and with the reason, when it cannot --
which means it is INERT in single-repo CI and earns its keep locally and in any job
that checks out both. The durable fix is for the overlay rows to be GENERATED from
``KIND_MAPPING`` rather than hand-authored; then the seal moves inside one repo and
stops depending on a checkout layout. That recommendation is in the architect
packet of 2026-10-06.
"""
import json
import os
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ROWS_DIR = REPO_ROOT / "registry" / "content_kinds"
DOMAINS_FILE = REPO_ROOT / "registry" / "content_kind_domains.json"

#: Where the platform's overlay rows are. The env var wins so a CI job that
#: checks out both repos can point at them without assuming a layout; the
#: sibling path is the local convention.
OVERLAY_ENV = "IAGENT_CONTENT_KIND_OVERLAY_DIR"
SIBLING_OVERLAY = (REPO_ROOT.parent / "invincible-agent" / "policy" / "overlays"
                   / "openddil-lab" / "content_kinds")


def _overlay_dir():
    """The overlay directory, or None. Never guesses past these two places."""
    env = os.environ.get(OVERLAY_ENV)
    if env:
        p = Path(env)
        if not p.is_dir():
            pytest.fail(
                f"{OVERLAY_ENV} is set to {env!r} but that is not a directory. An "
                f"explicitly configured overlay path that does not resolve is a "
                f"broken job, not a reason to skip -- skipping here would hide "
                f"the seal while looking green.")
        return p
    return SIBLING_OVERLAY if SIBLING_OVERLAY.is_dir() else None


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
def overlay_rows():
    d = _overlay_dir()
    if d is None:
        pytest.skip(
            f"the platform's content-kind overlay is not visible from here, so "
            f"the cross-repo seal cannot run. It is NOT satisfied, only unrun. "
            f"Point {OVERLAY_ENV} at "
            f"invincible-agent/policy/overlays/openddil-lab/content_kinds, or "
            f"check that repo out beside this one at {SIBLING_OVERLAY}.")
    return _load_rows(d)


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
    """A pass set we do not declare is a pass the platform would run blind."""
    shared = _shared(overlay_rows, our_rows)
    assert shared, "no shared kinds; see the sharing test above"
    mismatched = {
        k: {"ours": list(our_rows[k].get("passes") or []),
            "overlay": list(overlay_rows[k].get("passes") or [])}
        for k in shared
        if list(our_rows[k].get("passes") or [])
        != list(overlay_rows[k].get("passes") or [])
    }
    assert not mismatched, (
        f"passes diverged between the two registries: "
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
