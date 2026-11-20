"""Tests for the structured failure reasons on the ADR-0041 `failed` stage.

Covers `doc_tools/utils/ingest_failure.py` (classifier, vocabulary, code
identity) and the five failure fields `IngestStatusResource.update()` puts on
the wire. Mirrors the stub/fake shape of `test_ingest_stage_transport.py`.
"""
from __future__ import annotations

import httpx
import pytest

from doc_tools.utils.content_kind import KIND_MAPPING
from doc_tools.utils.ingest_failure import (
    REASON_CODES, _MAX_REASON, classify, running_code_identity,
)
from tests.test_ingest_stage_transport import (
    CANON_INGEST_ID, _FakePost, _authed, _resource, _stub_ingest_stages,
)


# --------------------------------------------------------------------------- #
# Message lock: one per real guard in document_parser.py. This test exists so
# REWORDING A GUARD FAILS CI instead of silently degrading to
# `extraction_failed`. Phrases are copied from the real raise sites.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("message, code", [
    ("ADR-0041 guard: sidecar 'k' carries no domain_type (got None) AND no "
     "registered content_kind (got 'zzz'). Registered kinds: []",
     "kind_unregistered"),
    ("ADR-0041 sidecar manifest missing or unparseable at key='k' "
     "(bucket='b'): boom", "sidecar_unreadable"),
    ("ADR-0041 guard: sidecar 'k' domain_type='pdf' is a file FORMAT "
     "(ingest_status.KINDS), not a semantic domain", "domain_is_a_format"),
    ("ADR-0041 guard: sidecar 'k' content_kind='ab' is a sha256 hash, not a "
     "content kind", "content_kind_is_a_hash"),
])
def test_each_real_guard_message_maps_to_its_code(message, code):
    assert classify(ValueError(message))[0] == code


def test_ingest_id_and_fallback_classification():
    assert classify(ValueError("ingest_id 'x' is not canonical sha256:<hex>"))[0] \
        == "ingest_id_malformed"
    assert classify(ValueError("something else broke"))[0] == "extraction_failed"
    assert "timeout" in REASON_CODES


def test_classify_is_total():
    class Bad(Exception):
        def __str__(self):
            raise RuntimeError("no str for you")

    assert classify(Exception(""))[0] in REASON_CODES  # never raises
    code, _ = classify(Bad())
    assert code == "unexpected_error"
    assert classify(None)[0] in REASON_CODES  # type: ignore[arg-type]


def test_kind_unregistered_reason_carries_the_count_and_never_a_part_list():
    """The names no longer fit, and a PART list is what must not be emitted.

    Fourteen kinds render to 191 characters on their own, past the whole
    160-character bound set on 2026-11-19 (night), so no arrangement carries
    them. The count is the part that stays true at any length. A truncated
    list would read as complete, and "is my kind registered?" is the one
    question this message exists to answer, so the list is omitted and said to
    be omitted rather than cut.
    """
    _, reason = classify(
        ValueError("carries no domain_type AND no registered content_kind")
    )
    n = len({e.kind for e in KIND_MAPPING.values()})
    assert f"Registered kinds: {n} (names omitted to fit)." in reason
    assert len(reason) <= _MAX_REASON
    # No list was emitted, in either rendering of one.
    assert "['" not in reason
    assert "s1000d-data-module" not in reason


def test_the_bound_is_the_one_this_repo_already_uses_for_a_read_phrase():
    """Two numbers for "what may a person read" is how they drift apart."""
    from doc_tools.utils.pass_failure import _MAX_PHRASE

    assert _MAX_REASON == _MAX_PHRASE == 160


@pytest.mark.parametrize("message", [
    # A real guard message with a real key: already past 160 on its own.
    "ADR-0041 guard: sidecar 'ingress-user/pdf/" + "a" * 64 + "/datasheet.pdf' "
    "carries no domain_type (got None) AND no registered content_kind (got "
    "'zzz'). Registered kinds: []",
    "ADR-0041 sidecar manifest missing or unparseable at key='"
    + "b" * 200 + "': boom",
    "x" * 5000,
    "a line" + chr(10) + "and another" + chr(13) + chr(10) + "and a third",
    "",
])
def test_every_reason_is_one_bounded_line(message):
    code, reason = classify(ValueError(message))
    assert code in REASON_CODES
    assert len(reason) <= _MAX_REASON, len(reason)
    assert chr(10) not in reason and chr(13) not in reason


def test_a_cut_message_says_it_was_cut():
    _, reason = classify(ValueError("y" * 500))
    assert len(reason) == _MAX_REASON
    assert reason.endswith("...")
    _, short = classify(ValueError("y" * 20))
    assert not short.endswith("...")


def test_a_marker_past_the_bound_still_classifies():
    """Classification reads the WHOLE message; only the output is bounded.

    Bounding first would demote a real failure to `extraction_failed`, and
    `ingest_id_malformed` is the case that bites: its markers sit at the end
    of a message whose head is a 100-character object key.
    """
    code, reason = classify(ValueError(
        "ADR-0041: the sidecar for ingress-user/pdf/" + "c" * 64
        + "/x.pdf could not be used because its ingest_id is not canonical "
          "sha256:<hex>"
    ))
    assert code == "ingest_id_malformed"
    assert len(reason) <= _MAX_REASON


# --------------------------------------------------------------------------- #
# Wire body.
# --------------------------------------------------------------------------- #
def _post_failed(monkeypatch, **kw):
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    fake = _FakePost()
    monkeypatch.setattr(httpx, "post", fake)
    _resource().update(CANON_INGEST_ID, "failed", detail="boom", **kw)
    return fake.calls[0]["json"]


def test_failed_post_carries_all_five_fields_and_autofills_pin(monkeypatch):
    monkeypatch.delenv("DOC_TOOLS_IMAGE", raising=False)
    monkeypatch.setenv("DOC_TOOLS_VERSION", "doc-tools@abc")
    body = _post_failed(monkeypatch, reason_code="timeout", reason="slow",
                        step="asset", run_id="r1")
    assert body["reason_code"] == "timeout"
    assert body["reason"] == "slow"
    assert body["step"] == "asset"
    assert body["run_id"] == "r1"
    assert body["pin_digest"] == "doc-tools@abc"

    monkeypatch.setenv("DOC_TOOLS_IMAGE", "sha256:img")
    body = _post_failed(monkeypatch, reason_code="timeout")
    assert body["pin_digest"] == "sha256:img"


def test_pin_digest_absent_when_no_identity(monkeypatch):
    monkeypatch.delenv("DOC_TOOLS_IMAGE", raising=False)
    monkeypatch.delenv("DOC_TOOLS_VERSION", raising=False)
    body = _post_failed(monkeypatch, reason_code="timeout")
    assert "pin_digest" not in body


def test_unknown_reason_code_is_coerced_not_raised(monkeypatch):
    body = _post_failed(monkeypatch, reason_code="nope")
    assert body["reason_code"] == "unexpected_error"


def test_blank_detail_still_raises_for_failed(monkeypatch):
    _stub_ingest_stages(monkeypatch)
    with pytest.raises(ValueError):
        _resource().update(CANON_INGEST_ID, "failed", detail="  ",
                           reason_code="timeout")


def test_running_code_identity_none_on_blank_env(monkeypatch):
    monkeypatch.setenv("DOC_TOOLS_IMAGE", "")
    monkeypatch.setenv("DOC_TOOLS_VERSION", "  ")
    assert running_code_identity() is None


# --------------------------------------------------------------------------- #
# Unit A2: Lane 1's wire rules, the boundary, and the shared key helper.
# --------------------------------------------------------------------------- #
import logging  # noqa: E402

from doc_tools.utils.ingest_failure import (  # noqa: E402
    EMITTABLE_CODES, REASON_CODE_SLUG_RE, RESERVED_TO_LANE_1,
    ingest_id_from_object_key, resolve_join_key,
)

_LOCKED_GUARD_MESSAGES = [
    "ADR-0041 guard: sidecar 'k' carries no domain_type (got None) AND no "
    "registered content_kind (got 'zzz'). Registered kinds: []",
    "ADR-0041 sidecar manifest missing or unparseable at key='k' "
    "(bucket='b'): boom",
    "ADR-0041 guard: sidecar 'k' domain_type='pdf' is a file FORMAT "
    "(ingest_status.KINDS), not a semantic domain",
    "ADR-0041 guard: sidecar 'k' content_kind='ab' is a sha256 hash, not a "
    "content kind",
    "ingest_id 'x' is not canonical sha256:<hex>",
    "something else broke",
]


@pytest.mark.parametrize("code", sorted(EMITTABLE_CODES))
def test_every_emittable_code_matches_lane_1_slug_regex(code):
    # Would have caught a code spelled `kind-unregistered`.
    assert REASON_CODE_SLUG_RE.match(code)


def test_all_recognised_codes_are_slugs_and_timeout_is_reserved():
    assert all(REASON_CODE_SLUG_RE.match(c) for c in REASON_CODES)
    assert RESERVED_TO_LANE_1 == frozenset({"timeout"})
    assert "timeout" in REASON_CODES and "timeout" not in EMITTABLE_CODES


@pytest.mark.parametrize("message", _LOCKED_GUARD_MESSAGES)
def test_classify_never_returns_timeout(message):
    assert classify(ValueError(message))[0] != "timeout"
    assert classify(Exception("timeout"))[0] != "timeout"


def test_non_failed_stage_omits_failure_only_fields_but_keeps_run_id(
    monkeypatch, caplog
):
    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    fake = _FakePost()
    monkeypatch.setattr(httpx, "post", fake)
    with caplog.at_level(logging.WARNING):
        _resource().update(
            CANON_INGEST_ID, "extracting", step="s", reason_code="timeout",
            reason="r", pin_digest="p", run_id="run-1",
        )
    body = fake.calls[0]["json"]
    for f in ("step", "reason_code", "reason", "pin_digest"):
        assert f not in body
        assert any(f in r.getMessage() and "extracting" in r.getMessage()
                   for r in caplog.records)
    assert body["run_id"] == "run-1"


def test_failed_stage_carries_every_field(monkeypatch):
    monkeypatch.delenv("DOC_TOOLS_IMAGE", raising=False)
    monkeypatch.delenv("DOC_TOOLS_VERSION", raising=False)
    body = _post_failed(monkeypatch, reason_code="extraction_failed",
                        reason="r", step="s", run_id="run-1", pin_digest="p")
    assert body["reason_code"] == "extraction_failed"
    assert (body["reason"], body["step"], body["run_id"], body["pin_digest"]) \
        == ("r", "s", "run-1", "p")


@pytest.mark.parametrize("bad", ["not_in_vocab", "Bad-Code", "kind-unregistered", ""])
def test_unknown_or_non_slug_code_coerces_without_raising(monkeypatch, bad):
    body = _post_failed(monkeypatch, reason_code=bad)
    assert body["reason_code"] == "unexpected_error"


def test_kind_guard_failure_posts_kind_unregistered_through_the_boundary(
    monkeypatch,
):
    """Handler-path test (the real op needs S3, Dagster context and a
    component instance -- impractical). It replays exactly what the new
    sidecar/guard boundary in document_parser.py does: classify, derive the
    join key via the shared helper, POST `failed`."""
    msg = (
        "ADR-0041 guard: sidecar 'k' carries no domain_type (got None) AND no "
        "registered content_kind (got 'zzz'). Registered kinds: []"
    )
    e = ValueError(msg)
    reason_code, reason = classify(e)
    assert reason_code == "kind_unregistered"

    key = f"ingress-user/pdf/{'a' * 64}/x.pdf"
    join_key = resolve_join_key(None, key)  # ingest_id is None here
    assert join_key == f"sha256:{'a' * 64}"

    _stub_ingest_stages(monkeypatch)
    _authed(monkeypatch)
    fake = _FakePost()
    monkeypatch.setattr(httpx, "post", fake)
    _resource().update(join_key, "failed", detail=str(e),
                       reason_code=reason_code, reason=reason,
                       step="document_parser", run_id="run-1")
    body = fake.calls[0]["json"]
    assert body["reason_code"] == "kind_unregistered"
    assert body["step"] == "document_parser"
    n = len({e.kind for e in KIND_MAPPING.values()})
    assert f"Registered kinds: {n} (names omitted to fit)." in body["reason"]
    assert len(body["reason"]) <= _MAX_REASON
    assert "s1000d-data-module" not in body["reason"]


def test_ingest_id_from_object_key():
    h = "0123456789abcdef" * 4
    assert ingest_id_from_object_key(f"ingress-user/pdf/{h}/x.pdf") == f"sha256:{h}"
    assert ingest_id_from_object_key("ingress-user/pdf/short/x.pdf") is None
    assert ingest_id_from_object_key(None) is None


# --------------------------------------------------------------------------- #
# The join key must be CANONICAL, or `ingest_id_malformed` can never post.
# --------------------------------------------------------------------------- #
def test_resolve_join_key_prefers_a_canonical_candidate():
    h = "0123456789abcdef" * 4
    key = f"ingress-user/pdf/{'a' * 64}/x.pdf"
    assert resolve_join_key(f"sha256:{h}", key) == f"sha256:{h}"
    assert resolve_join_key(f"  sha256:{h}  ", key) == f"sha256:{h}"


def test_resolve_join_key_falls_back_when_the_candidate_is_not_canonical():
    """THE REGRESSION THIS EXISTS FOR. `canonical_ingest_id()` raises WITHOUT
    assigning, so when the ingest_id guard is what failed, `ingest_id` still
    holds the sidecar's malformed value — truthy, so a plain
    `ingest_id or <fallback>` selects it, `update()` refuses it as
    non-canonical, and the handler's never-mask-`e` wrapper swallows the
    refusal. `ingest_id_malformed` would then be the one code in
    EMITTABLE_CODES that could never reach a row. It is emittable, so it must
    be postable."""
    key = f"ingress-user/pdf/{'b' * 64}/x.pdf"
    expected = f"sha256:{'b' * 64}"
    for bad in (
        "7f3a9c21-4b8e-4d2a-9f11-2c6d5e8a1b40",   # a uuid
        "a" * 64,                                  # bare hex, no prefix
        "sha256:" + "a" * 63,                      # truncated
        "SHA256:" + "a" * 64,                      # wrong case
        "",
        None,
        object(),
    ):
        assert resolve_join_key(bad, key) == expected, bad

    # No 64-hex segment anywhere: there is nothing to address, and None is the
    # honest answer. The handler then logs the gap instead of posting.
    assert resolve_join_key("not-canonical", "ingress-user/pdf/short/x.pdf") is None


def test_the_mirrored_canonical_pattern_agrees_with_the_authority():
    """`ingest_failure` mirrors the canonical ingest_id pattern so it stays
    importable with nothing else loaded. `ingest_id.INGEST_ID_RE` is the
    authority; this fails if they drift."""
    from doc_tools.utils.ingest_failure import _CANONICAL_INGEST_ID_RE
    from doc_tools.utils.ingest_id import INGEST_ID_RE

    assert _CANONICAL_INGEST_ID_RE.pattern == INGEST_ID_RE.pattern


def test_extraction_empty_is_emittable():
    # Raised from semantic_assets.py when a review-contract document yields
    # zero part rows; it is NOT reserved to Lane 1.
    assert "extraction_empty" in EMITTABLE_CODES
