"""GET /kinds/processable: the image serves what it can RUN; the gateway never recomputes it."""
import base64
import json
import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from doc_tools.api.app import app
from doc_tools.api.kinds import (
    ARM_INGRESS_USER_XML,
    ARM_PYTHON_PASS,
    ingestable_kinds,
    processable_kinds_payload,
)
from doc_tools.utils import content_kind as ck

CODES = {ck.KIND_UNBUILT_PASS, ck.KIND_PASS_IS_A_CLASS, ck.KIND_PASS_UNRESOLVED,
         ck.KIND_PASS_NOT_CALLABLE, ck.KIND_NO_PASSES}


@pytest.fixture
def client():
    return TestClient(app)


def _unsigned_jwt(claims):
    """A well-formed, decodable, UNSIGNED JWT. Not a credential: `alg: none`
    with a literal signature segment, so it can never authenticate anywhere."""
    def seg(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{seg({'alg': 'none', 'typ': 'JWT'})}.{seg(claims)}.not-a-signature"


def test_processable_kinds_is_still_a_sorted_tuple_and_is_the_python_pass_arm():
    # Pins: the refactor onto the shared predicate did not change the return
    # type/order, and the function is published as ONE ARM -- not as the answer.
    k = ck.processable_kinds()
    assert isinstance(k, tuple) and list(k) == sorted(k)
    assert processable_kinds_payload()["arms"][ARM_PYTHON_PASS] == list(k)


def test_partition_invariant_no_kind_missing_from_every_set():
    # Pins: no registered kind is INVISIBLE in the payload. Three places a kind
    # can land -- advertised, excluded (no arm can run it), or held out by ruling
    # -- and a kind in none of them is an omission a consumer cannot interpret.
    # `excluded` and `held_out` may OVERLAP, and today do: `xml` is both
    # unrunnable and held, which is why this is a cover, not a partition.
    p = processable_kinds_payload()
    registered = [e.kind for e in ck.KIND_MAPPING.values()]
    excl = [e["kind"] for e in p["excluded"]]
    held = [e["kind"] for e in p["held_out"]]
    assert len(set(p["kinds"])) == len(p["kinds"]) and len(set(excl)) == len(excl)
    assert len(set(held)) == len(held)
    assert not set(p["kinds"]) & set(excl), "a kind is both processable and excluded"
    assert not set(p["kinds"]) & set(held), "a held kind is being advertised"
    assert set(p["kinds"]) | set(excl) | set(held) == set(registered)
    assert p["registered_count"] == len(registered)


def test_kinds_is_the_union_of_the_arms_MINUS_the_hold_list():
    # The advertised list is not the raw union, and this assertion is the whole
    # reason `held_out` exists: arm membership is evidence that a PASS resolves,
    # never evidence that a DROP has travelled that path. Written as
    # union-minus-held rather than == sorted(union) because the two are equal
    # today (nothing held is claimed by an arm) and the day that stops being true
    # is exactly the day this test has to notice.
    p = processable_kinds_payload()
    union = set(p["arms"][ARM_PYTHON_PASS]) | set(p["arms"][ARM_INGRESS_USER_XML])
    held = {e["kind"] for e in p["held_out"]}
    assert p["kinds"] == sorted(union - held)
    assert p["kinds"] == list(ingestable_kinds()), (
        "the route and the publisher must serve ONE definition")


def test_the_arms_disagree_on_s1000d_and_the_union_sides_with_the_one_that_RAN_it():
    # THE FINDING THIS ROUTE EXISTS TO NOT REPEAT. `processable_kinds()` excludes
    # s1000d-data-module because its pass is a class and dispatch refuses a class
    # by contract -- true of THAT ARM. But the user-drop table routes the kind to
    # that same class, and on 2026-10-16 ten ODMRAD data modules completed all
    # five stages of xml_graph_sync_job through it. A door served the python-pass
    # arm alone would have been told the opposite of what the cluster did.
    p = processable_kinds_payload()
    assert "s1000d-data-module" not in p["arms"][ARM_PYTHON_PASS]
    assert "s1000d-data-module" in p["arms"][ARM_INGRESS_USER_XML]
    assert "s1000d-data-module" in p["kinds"], (
        "ten ODMRAD data modules were ingested end to end through this kind; a "
        "payload calling it unprocessable asserts a false fact about the image")
    assert "s1000d-data-module" not in [e["kind"] for e in p["excluded"]], (
        "a kind one arm routes is not excluded")


def test_every_exclusion_has_a_known_reason_and_a_detail_naming_the_pass():
    # Pins: a door that omits a kind must be able to say why.
    for e in ck.kind_exclusions():
        assert e["reason_code"] in CODES, e
        assert e["detail"], e
        if e["pass"] is not None:
            assert e["pass"] in e["detail"], e


def test_the_unbuilt_exclusions_carry_their_reasons_and_name_both_arms():
    # xml is the live OpenDDIL case: rev188-door-probe.xml declared it and HALTED
    # with this reason named, which is the halt working, not a gap. cad's row
    # (PR #114) deliberately landed ahead of its pass.
    by = {e["kind"]: e for e in processable_kinds_payload()["excluded"]}
    assert by["xml"]["reason_code"] == ck.KIND_UNBUILT_PASS
    assert by["cad"]["reason_code"] == ck.KIND_UNBUILT_PASS
    for kind in ("xml", "cad"):
        assert "ingress-user XML parser" in by[kind]["detail"], (
            "an exclusion must say NEITHER arm can run it, or a reader assumes "
            "only the python-pass arm was checked")


def test_route_body_equals_the_payload(client):
    r = client.get("/kinds/processable")
    assert r.status_code == 200
    assert r.json() == processable_kinds_payload()


def test_image_key_is_always_present_and_tracks_the_env(monkeypatch):
    # Pins: absent DOC_TOOLS_IMAGE is a STATE (None), never an omitted key or a git sha.
    monkeypatch.setenv("DOC_TOOLS_IMAGE", "reg/doc-tools@sha256:abc")
    p = processable_kinds_payload()
    assert "image" in p and p["image"] == "reg/doc-tools@sha256:abc"
    monkeypatch.delenv("DOC_TOOLS_IMAGE")
    p = processable_kinds_payload()
    assert "image" in p and p["image"] is None


def test_payload_is_deterministic_and_fingerprint_shape():
    a, b = processable_kinds_payload(), processable_kinds_payload()
    assert a == b
    assert re.fullmatch(r"sha256:[0-9a-f]{16}", a["registry_fingerprint"])


def test_healthz_is_200(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_no_authorization_header_is_served_and_MARKED_anonymous(client):
    # Pins the SDK's OBSERVE posture: absent header serves. The mark is the
    # point -- a tolerated anonymous call that nothing records is never fixed.
    r = client.get("/kinds/processable")
    assert r.status_code == 200
    assert r.headers["X-Mesh-Auth"] == "anonymous"


def test_a_bad_bearer_is_401_and_never_echoed(client):
    # "notatoken" does not decode at all, so it is JUDGED FALSE and refused
    # even with no verification key configured.
    r = client.get("/kinds/processable", headers={"Authorization": "Bearer notatoken"})
    assert r.status_code == 401
    assert "notatoken" not in r.text


def test_an_unjudgeable_bearer_is_admitted_and_marked_not_refused(client, monkeypatch):
    # THE FALSE-REFUSAL THIS AVOIDS: with no MESH_JWT_PUBLIC_KEY on the pod,
    # verify_bearer returns unverified for a GENUINE mint too ("no-verification-key").
    # Refusing that would 401 Lane 1's door for holding a real token.
    monkeypatch.delenv("MESH_JWT_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("KEYCLOAK_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("REQUIRE_TRANSPORT_AUTH", raising=False)
    r = client.get(
        "/kinds/processable",
        headers={"Authorization": "Bearer " + _unsigned_jwt({"email": "a@b.c"})},
    )
    assert r.status_code == 200
    assert r.headers["X-Mesh-Auth"] == "unverified:no-verification-key"


def test_require_posture_refuses_anonymous_but_never_the_health_probe(client, monkeypatch):
    # Pins the REQUIRE flip: it must not 401 the kubelet probe, or it kills the
    # pod it was meant to protect.
    monkeypatch.setenv("REQUIRE_TRANSPORT_AUTH", "true")
    assert client.get("/kinds/processable").status_code == 401
    assert client.get("/healthz").status_code == 200


def test_no_fastapi_under_the_api_package():
    # Pins: fastapi is not installed and the SDK dropped it on purpose.
    import doc_tools.api as pkg
    for f in Path(pkg.__file__).parent.glob("*.py"):
        assert "fastapi" not in f.read_text(encoding="utf-8").lower(), f.name


def test_payload_has_no_secret_ish_key_or_value(monkeypatch):
    monkeypatch.setenv("DOC_TOOLS_TEST_SECRET", "s3cr3t-value-xyz")
    p = processable_kinds_payload()
    word = re.compile(r"(^|_)(token|secret|key|password|pass|cred\w*)($|_)", re.I)
    assert not [k for k in p if word.search(k)], "secret-ish payload key"
    assert "s3cr3t-value-xyz" not in repr(p)
