"""Tests for IngestStatusResource's real HTTP transport to Lane 1's stage route.

`doc_tools/utils/dagster_resources.py`'s `IngestStatusResource.update()` used
to be a validating no-op. This module tests the transport that replaced it:
the stage-vocabulary bridge (`_WIRE_STAGE` / `_WIRE_POSTABLE`) at the HTTP
boundary, the `httpx.post` call to Lane 1's `POST /ingest/{id}/stage`, and
that none of it can ever raise out of an extraction.

SDK GAP, LOCAL ONLY. This repo's shared `.venv` pins iagent-mesh 0.9.4, which
has no `iagent_mesh.ingest` module at all (see `tests/test_ingress_user_
stamp.py`'s own module docstring and `tests/test_mesh_sdk_pin.py`).
`IngestStatusResource.update()` does `from iagent_mesh.ingest import
INGEST_STAGES` unconditionally, before any transport runs — so every
behaviour test below needs that import to succeed. Rather than skip this
whole file locally (which would leave the new transport untested wherever
this venv is the gate), each behaviour test injects a STUB `iagent_mesh.
ingest` module via `monkeypatch.setitem(sys.modules, ...)` carrying the real
vocabulary (`received` / `extracting` / `awaiting_disposition` / `promoted`
/ `rejected` / `failed`, matching iagent-mesh v0.9.5 / v0.9.6 and
invincible-agent's mirror of it). `monkeypatch` reverts the injection after
each test, so it never leaks into the one test that must NOT see it.

That one exception is the tripwire at the bottom: it exists specifically to
watch the REAL SDK for `review` landing in `INGEST_STAGES`, so stubbing it
would defeat its purpose. It `importorskip`s and therefore SKIPS (not
fails, not passes) under this pinned venv, which is correct — it has
nothing to assert until a real SDK ships `review`.
"""
from __future__ import annotations

import sys
import types

import httpx
import pytest

from doc_tools.utils import dagster_resources
from doc_tools.utils import mesh_identity
from doc_tools.utils.dagster_resources import IngestStatusResource

CANON_INGEST_ID = "sha256:" + "ab" * 32
FAKE_TOKEN_HEADERS = {"Authorization": "Bearer test-mesh-token"}

#: The real vocabulary at iagent-mesh v0.9.5 / v0.9.6 — see module docstring.
_REAL_INGEST_STAGES = (
    "received", "extracting", "awaiting_disposition",
    "promoted", "rejected", "failed",
)


def _stub_ingest_stages(monkeypatch):
    """Inject a stub `iagent_mesh.ingest` module carrying INGEST_STAGES.

    Needed because this venv's pinned SDK (0.9.4) has no such module — see
    module docstring. `monkeypatch.setitem` auto-reverts after the test, so
    this never leaks into the tripwire test at the bottom.
    """
    stub = types.ModuleType("iagent_mesh.ingest")
    stub.INGEST_STAGES = _REAL_INGEST_STAGES
    monkeypatch.setitem(sys.modules, "iagent_mesh.ingest", stub)


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class _FakePost:
    """Records every call; never makes a real network call."""

    def __init__(self, response=None, exc=None):
        self.response = response if response is not None else _FakeResponse(200, "ok")
        self.exc = exc
        self.calls = []

    def __call__(self, url, *, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if self.exc is not None:
            raise self.exc
        return self.response


def _authed(monkeypatch, headers=FAKE_TOKEN_HEADERS):
    monkeypatch.setattr(mesh_identity, "stage_auth_headers", lambda: headers)


def _resource():
    return IngestStatusResource()


# --------------------------------------------------------------------------- #
# extracting posts to the right URL with the right body and Bearer header.
# --------------------------------------------------------------------------- #
def test_extracting_posts_to_right_url_with_body_and_bearer_header(monkeypatch):
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    fake_post = _FakePost()
    monkeypatch.setattr(httpx, "post", fake_post)

    _resource().update(CANON_INGEST_ID, "extracting")

    assert len(fake_post.calls) == 1
    call = fake_post.calls[0]
    assert call["url"] == f"http://iagent-cortex-bff:8090/ingest/{CANON_INGEST_ID}/stage"
    assert call["json"] == {"stage": "extracting"}
    assert call["headers"] == FAKE_TOKEN_HEADERS
    assert call["timeout"] == dagster_resources._STAGE_POST_TIMEOUT_S


# --------------------------------------------------------------------------- #
# awaiting_disposition posts with wire stage "review" — the bridge.
# --------------------------------------------------------------------------- #
def test_awaiting_disposition_posts_with_wire_stage_review(monkeypatch):
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    fake_post = _FakePost()
    monkeypatch.setattr(httpx, "post", fake_post)

    _resource().update(
        CANON_INGEST_ID, "awaiting_disposition",
        extracted_count=18, extracted_total=9,
    )

    assert len(fake_post.calls) == 1
    body = fake_post.calls[0]["json"]
    assert body["stage"] == "review"
    assert body["extracted_count"] == 18
    assert body["extracted_total"] == 9


# --------------------------------------------------------------------------- #
# failed posts and carries detail.
# --------------------------------------------------------------------------- #
def test_failed_posts_and_carries_detail(monkeypatch):
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    fake_post = _FakePost()
    monkeypatch.setattr(httpx, "post", fake_post)

    _resource().update(CANON_INGEST_ID, "failed", detail="boom")

    assert len(fake_post.calls) == 1
    body = fake_post.calls[0]["json"]
    assert body["stage"] == "failed"
    assert body["detail"] == "boom"


# --------------------------------------------------------------------------- #
# received / promoted / rejected never post — Lane 1 / the human disposition
# task own those stages, not this seam.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("stage,kwargs", [
    ("received", {}),
    ("promoted", {}),
    ("rejected", {"detail": "operator rejected"}),
])
def test_locally_observed_stages_do_not_post(monkeypatch, stage, kwargs):
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    fake_post = _FakePost()
    monkeypatch.setattr(httpx, "post", fake_post)

    _resource().update(CANON_INGEST_ID, stage, **kwargs)

    assert fake_post.calls == []


# --------------------------------------------------------------------------- #
# None fields are absent from the body (never sent as explicit nulls).
# --------------------------------------------------------------------------- #
def test_none_fields_are_absent_from_body(monkeypatch):
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    fake_post = _FakePost()
    monkeypatch.setattr(httpx, "post", fake_post)

    _resource().update(CANON_INGEST_ID, "extracting")

    body = fake_post.calls[0]["json"]
    assert body == {"stage": "extracting"}
    assert "extracted_count" not in body
    assert "extracted_total" not in body
    assert "detail" not in body


# --------------------------------------------------------------------------- #
# extracted_count / extracted_total are forwarded when present — including
# 0, which must not be dropped as falsy (only None is omitted).
# --------------------------------------------------------------------------- #
def test_extracted_count_and_total_are_forwarded_when_present(monkeypatch):
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    fake_post = _FakePost()
    monkeypatch.setattr(httpx, "post", fake_post)

    _resource().update(
        CANON_INGEST_ID, "awaiting_disposition",
        extracted_count=412, extracted_total=0,
    )

    body = fake_post.calls[0]["json"]
    assert body["extracted_count"] == 412
    assert body["extracted_total"] == 0


# --------------------------------------------------------------------------- #
# A non-2xx response is non-fatal: update() returns None, never raises.
# --------------------------------------------------------------------------- #
def test_non_2xx_response_is_non_fatal(monkeypatch):
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    fake_post = _FakePost(response=_FakeResponse(500, "internal error"))
    monkeypatch.setattr(httpx, "post", fake_post)

    result = _resource().update(CANON_INGEST_ID, "extracting")

    assert result is None
    assert len(fake_post.calls) == 1


# --------------------------------------------------------------------------- #
# A raised exception (e.g. a network error) is non-fatal too.
# --------------------------------------------------------------------------- #
def test_raised_exception_is_non_fatal(monkeypatch):
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    fake_post = _FakePost(exc=httpx.ConnectError("connection refused"))
    monkeypatch.setattr(httpx, "post", fake_post)

    result = _resource().update(CANON_INGEST_ID, "extracting")

    assert result is None
    assert len(fake_post.calls) == 1


# --------------------------------------------------------------------------- #
# A mint failure (stage_auth_headers() -> None) means no post at all — this
# route hard-401s an unauthenticated caller, so posting without a token is
# pointless.
# --------------------------------------------------------------------------- #
def test_mint_failure_results_in_no_post(monkeypatch):
    _stub_ingest_stages(monkeypatch)
    monkeypatch.setattr(mesh_identity, "stage_auth_headers", lambda: None)
    fake_post = _FakePost()
    monkeypatch.setattr(httpx, "post", fake_post)

    result = _resource().update(CANON_INGEST_ID, "extracting")

    assert result is None
    assert fake_post.calls == []


# --------------------------------------------------------------------------- #
# IAGENT_GATEWAY_URL override is honoured, and a trailing slash on it does
# not produce a double slash in the posted URL.
# --------------------------------------------------------------------------- #
def test_gateway_url_override_is_honoured(monkeypatch):
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    monkeypatch.setenv("IAGENT_GATEWAY_URL", "http://custom-gateway:9999")
    fake_post = _FakePost()
    monkeypatch.setattr(httpx, "post", fake_post)

    _resource().update(CANON_INGEST_ID, "extracting")

    assert fake_post.calls[0]["url"] == (
        f"http://custom-gateway:9999/ingest/{CANON_INGEST_ID}/stage"
    )


def test_gateway_url_trailing_slash_does_not_double(monkeypatch):
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    monkeypatch.setenv("IAGENT_GATEWAY_URL", "http://custom-gateway:9999/")
    fake_post = _FakePost()
    monkeypatch.setattr(httpx, "post", fake_post)

    _resource().update(CANON_INGEST_ID, "extracting")

    url = fake_post.calls[0]["url"]
    assert url == f"http://custom-gateway:9999/ingest/{CANON_INGEST_ID}/stage"
    assert url.count("//") == 1  # only the scheme's "//"


# --------------------------------------------------------------------------- #
# THE PROMOTION PAYLOAD'S ONE DOC-TOOLS FIELD.
#
# Measured live by Lane 1 on roll #19: PCN26-119 reached `review` through this
# method, Lane 1 filed a `document_promotion` task from the POST, and the
# promote was refused `422 promotion_payload_invalid` for a payload that could
# not name the extraction it was about. `extraction_ref` is the one field of
# the six that only this side can supply; Lane 1 derives `pipeline_version`
# and `format_fingerprint` FROM the named artifact rather than from anything
# asserted here (ADR-0034), which is why this seam sends a key and not a
# claim.
# --------------------------------------------------------------------------- #
def test_review_post_carries_extraction_ref(monkeypatch):
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    fake_post = _FakePost()
    monkeypatch.setattr(httpx, "post", fake_post)

    ref = "ingress-user/pdf/abc/generated/PCN26-119_pdf/doc-tools@deadbee/manifest.json"
    _resource().update(
        CANON_INGEST_ID, "awaiting_disposition",
        extracted_count=18, extracted_total=9, extraction_ref=ref,
    )

    body = fake_post.calls[0]["json"]
    assert body["stage"] == "review"
    # Verbatim. A ref the transport normalises, strips or re-prefixes names a
    # different object than the one the producer wrote.
    assert body["extraction_ref"] == ref


def test_extraction_ref_rides_other_stages_too_when_given(monkeypatch):
    """Not gated on the stage.

    The WARNING below is specific to `review`, but the field is not: gating
    the field on a stage spelling would mean a future route change (or a
    second filing stage) silently drops it, which is the failure this whole
    change exists to cure.
    """
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    fake_post = _FakePost()
    monkeypatch.setattr(httpx, "post", fake_post)

    _resource().update(CANON_INGEST_ID, "extracting", extraction_ref="k/m.json")

    assert fake_post.calls[0]["json"]["extraction_ref"] == "k/m.json"


def test_absent_extraction_ref_leaves_the_body_as_it_was(monkeypatch):
    """The compatibility half, pinned.

    Lane 1's route accepts the field as optional, so a body without it must
    still be exactly the body that posted before this change — no `null`, no
    empty string, no key at all.
    """
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    fake_post = _FakePost()
    monkeypatch.setattr(httpx, "post", fake_post)

    _resource().update(CANON_INGEST_ID, "awaiting_disposition", extracted_count=1)

    assert fake_post.calls[0]["json"] == {"stage": "review", "extracted_count": 1}


@pytest.mark.parametrize("blank", ["", "   ", "\n", "\t "])
def test_a_blank_extraction_ref_is_refused_before_the_post(monkeypatch, blank):
    """Blank is worse than absent, so it raises rather than posting.

    A present-but-unresolvable ref trades the 422 this field cures for a 404
    on a key that names nothing — and a 404 is diagnosed at Lane 1's end,
    days later, by someone who cannot see which producer sent it. The refusal
    happens where the caller still knows what it meant to send.
    """
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    fake_post = _FakePost()
    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(ValueError, match="extraction_ref"):
        _resource().update(
            CANON_INGEST_ID, "awaiting_disposition", extraction_ref=blank)

    assert fake_post.calls == []


def test_review_without_extraction_ref_warns_and_still_posts(monkeypatch, caplog):
    """Loud, but never fatal.

    This is the exact state that produced the live 422, so it must not pass
    silently. It must also not stop the POST: the row still belongs at
    `review`, and a stage write that failed an extraction would be a far
    worse trade than a task that needs its payload backfilled.
    """
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    fake_post = _FakePost()
    monkeypatch.setattr(httpx, "post", fake_post)

    with caplog.at_level("WARNING", logger="doc_tools.utils.dagster_resources"):
        _resource().update(CANON_INGEST_ID, "awaiting_disposition")

    assert len(fake_post.calls) == 1
    assert any("extraction_ref" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("stage", ["extracting", "failed"])
def test_other_stages_do_not_warn_about_a_missing_ref(monkeypatch, caplog, stage):
    """The silence half.

    `extracting` runs before a manifest exists and `failed` has no extraction
    to name, so warning on either would train a reader to ignore the warning
    that matters.
    """
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    monkeypatch.setattr(httpx, "post", _FakePost())

    with caplog.at_level("WARNING", logger="doc_tools.utils.dagster_resources"):
        _resource().update(CANON_INGEST_ID, stage, detail="because")

    assert not any("extraction_ref" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- #
# TRIPWIRE, not a behaviour test. Deliberately NOT using the stub above —
# this one watches the REAL SDK. If it fails, the SDK has adopted "review"
# into INGEST_STAGES and `_WIRE_STAGE` (dagster_resources.py) must be
# DELETED, along with this assumption.
# --------------------------------------------------------------------------- #
def test_tripwire_sdk_vocabulary_still_lacks_review():
    pytest.importorskip("iagent_mesh.ingest")
    from iagent_mesh.ingest import INGEST_STAGES

    assert "review" not in INGEST_STAGES, (
        "iagent_mesh.ingest.INGEST_STAGES now contains 'review' — the SDK "
        "has adopted Lane 1's spelling. Delete _WIRE_STAGE in "
        "doc_tools/utils/dagster_resources.py; the bridge is no longer "
        "needed."
    )
    assert "awaiting_disposition" in INGEST_STAGES
