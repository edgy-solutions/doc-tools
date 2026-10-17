"""The retry poller: the run_key shape, and every refusal it is supposed to make.

The point of these tests is NOT that the sensor launches runs -- it is that the
run_key carries the attempt counter, and that every path which cannot produce a
correct launch REFUSES AND SAYS WHY rather than launching something wrong or
skipping silently. Dagster consumes a failed run's run_key permanently (see the
module docstring), so a retry launched under the original key is swallowed with
no error anywhere: the only defence is the key shape asserted here.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest
from dagster import DagsterInstance, build_sensor_context

from doc_tools.components import ingest_retry_sensor as mod

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
ID_A = f"sha256:{DIGEST_A}"
ID_B = f"sha256:{DIGEST_B}"

PARTITION_NAME = "user_pdf_files"
BUCKET = "processing-artifacts"
TARGET_OP = "process_user_document_artifact"
PQ_KEY = f"ingress-user/pdf/{DIGEST_A}/q.pdf"
XML_PARTITION = "xml_files"
XML_OP = "extract_rdf_from_xml"


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload is not None else "")

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def instance():
    with DagsterInstance.ephemeral() as inst:
        yield inst


def _build(*, xml: bool = False, ingress_prefix: Optional[str] = None):
    if xml:
        return mod.build_ingest_retry_sensor(
            name="ingest_retry_sensor_xml",
            job_name="xml_graph_sync_job",
            target_op=XML_OP,
            bucket=BUCKET,
            partition_name=XML_PARTITION,
            ingress_prefix=ingress_prefix or "xml",
        )
    return mod.build_ingest_retry_sensor(
        name="ingest_retry_sensor",
        job_name=f"{TARGET_OP}_job",
        target_op=TARGET_OP,
        bucket=BUCKET,
        partition_name=PARTITION_NAME,
        ingress_prefix=ingress_prefix or "pdf",
    )


def _run(
    monkeypatch,
    instance,
    *,
    rows: Any,
    status: int = 200,
    token: bool = True,
    xml: bool = False,
):
    """Evaluate the sensor against a canned retry-route response."""
    monkeypatch.setattr(
        mod, "stage_auth_headers", lambda: ({"Authorization": "Bearer t"} if token else None)
    )
    import httpx

    captured: Dict[str, Any] = {}

    def _get(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        return _FakeResponse(status, rows)

    monkeypatch.setattr(httpx, "get", _get)
    ctx = build_sensor_context(instance=instance)
    result = _build(xml=xml)(ctx)
    return result, captured


def _requests(result) -> List[Any]:
    return list(result.run_requests or [])


def _skip_text(result) -> str:
    return result.skip_reason.skip_message if result.skip_reason else ""


# --------------------------------------------------------------------------
# The key shape -- the thing a wrong value makes invisible
# --------------------------------------------------------------------------


def test_the_run_key_is_attempt_scoped_so_a_second_retry_is_not_swallowed(
    monkeypatch, instance
):
    """`{ingest_id}-a{attempt}`, and attempt 3 differs from attempt 2.

    If the key were the ingest id alone, attempt 3 would hit Dagster's dedup
    (the attempt-2 run exists and is not NOT_STARTED) and be skipped with no
    error raised anywhere -- the exact failure this shape exists to prevent.
    """
    key = f"ingress-user/pdf/{DIGEST_A}/PCN23-002.pdf"
    rows = [
        {"ingest_id": ID_A, "attempt": 2, "source_object_key": key},
        {"ingest_id": ID_A, "attempt": 3, "source_object_key": key},
    ]
    result, _ = _run(monkeypatch, instance, rows=rows)
    assert [r.run_key for r in _requests(result)] == [f"{ID_A}-a2", f"{ID_A}-a3"]


def test_a_launch_carries_the_file_url_partition_key_and_join_tags(monkeypatch, instance):
    key = f"ingress-user/pdf/{DIGEST_A}/PCN23-002.pdf"
    result, _ = _run(
        monkeypatch,
        instance,
        rows=[{"ingest_id": ID_A, "attempt": 2, "source_object_key": key}],
    )
    (req,) = _requests(result)
    assert req.partition_key == f"ingress-user__pdf__{DIGEST_A}__PCN23-002.pdf"
    assert req.run_config["ops"][TARGET_OP]["config"]["file_url"] == f"s3://{BUCKET}/{key}"
    # The row this run belongs to must be recoverable from the run itself --
    # a run whose ingest_id lives only in a log line cannot be joined back.
    assert req.tags["ingest_id"] == ID_A
    assert req.tags["ingest_attempt"] == "2"
    assert req.tags["ingest_retry"] == "true"
    # The partition the original drop registered may be gone; adding it is
    # idempotent, and without it the launch fails on an unknown partition.
    assert result.dynamic_partitions_requests[0].partition_keys == [req.partition_key]


# --------------------------------------------------------------------------
# Refusals: each one names itself in the tick log
# --------------------------------------------------------------------------


def test_no_token_means_no_request_at_all(monkeypatch, instance):
    """Never an anonymous poll. A tolerated anonymous call hid an unset
    KEYCLOAK_REALM_URL in sandbox for weeks; this route 401s anyway."""
    result, captured = _run(monkeypatch, instance, rows=[], token=False)
    assert captured == {}, "the sensor must not reach the network without a token"
    assert "token" in _skip_text(result)
    assert not _requests(result)


def test_a_404_is_reported_as_the_route_not_existing(monkeypatch, instance):
    """The expected state until Lane 1 ships it -- named, not swallowed."""
    result, _ = _run(monkeypatch, instance, rows=None, status=404)
    assert "404" in _skip_text(result)
    assert "not deployed" in _skip_text(result)
    assert not _requests(result)


def test_a_row_with_no_attempt_is_refused_not_launched(monkeypatch, instance):
    """Launching it under the bare ingest id is the silent-skip failure."""
    result, _ = _run(
        monkeypatch,
        instance,
        rows=[
            {
                "ingest_id": ID_A,
                "source_object_key": f"ingress-user/pdf/{DIGEST_A}/x.pdf",
            }
        ],
    )
    assert not _requests(result)
    assert "attempt" in _skip_text(result)


def test_attempt_one_is_refused_because_it_belongs_to_the_drop_sensor(
    monkeypatch, instance
):
    result, _ = _run(
        monkeypatch,
        instance,
        rows=[
            {
                "ingest_id": ID_A,
                "attempt": 1,
                "source_object_key": f"ingress-user/pdf/{DIGEST_A}/x.pdf",
            }
        ],
    )
    assert not _requests(result)
    assert "attempt 1" in _skip_text(result)


def test_a_non_canonical_ingest_id_is_refused(monkeypatch, instance):
    result, _ = _run(
        monkeypatch,
        instance,
        rows=[{"ingest_id": DIGEST_A, "attempt": 2, "source_object_key": "a/b.pdf"}],
    )
    assert not _requests(result)
    assert "canonical" in _skip_text(result)


def test_one_bad_row_does_not_cost_the_good_rows_their_retry(monkeypatch, instance):
    good = f"ingress-user/pdf/{DIGEST_B}/ok.pdf"
    result, _ = _run(
        monkeypatch,
        instance,
        rows=[
            {"ingest_id": "not-an-id", "attempt": 2, "source_object_key": "a/b.pdf"},
            {"ingest_id": ID_B, "attempt": 2, "source_object_key": good},
        ],
    )
    assert [r.run_key for r in _requests(result)] == [f"{ID_B}-a2"]


# --------------------------------------------------------------------------
# The fallback: recovering the key when the route omits source_object_key
# --------------------------------------------------------------------------


def test_the_fallback_recovers_a_filename_that_itself_contains_a_double_underscore(
    monkeypatch, instance
):
    """Decoding is exact, not a blanket `__` -> `/`.

    `PCN23__002.pdf` is a legal filename under the drop sensor's own filter
    (`[^/]+\\.pdf$`), and a blanket replace would turn it into a path and
    point file_url at an object that does not exist.
    """
    key = f"ingress-user/pdf/{DIGEST_A}/PCN23__002.pdf"
    instance.add_dynamic_partitions(PARTITION_NAME, [mod._encode_partition_key(key)])
    result, _ = _run(
        monkeypatch, instance, rows=[{"ingest_id": ID_A, "attempt": 2}]
    )
    (req,) = _requests(result)
    assert req.run_config["ops"][TARGET_OP]["config"]["file_url"] == f"s3://{BUCKET}/{key}"


def test_two_partitions_under_one_digest_are_ambiguous_and_refused(monkeypatch, instance):
    """The same bytes uploaded twice under different names. Which file to
    reprocess is genuinely unknown, so the poller skips instead of guessing."""
    for name in ("first.pdf", "second.pdf"):
        instance.add_dynamic_partitions(
            PARTITION_NAME,
            [mod._encode_partition_key(f"ingress-user/pdf/{DIGEST_A}/{name}")],
        )
    result, _ = _run(monkeypatch, instance, rows=[{"ingest_id": ID_A, "attempt": 2}])
    assert not _requests(result)
    assert "ambiguous" in _skip_text(result)


def test_no_matching_partition_is_refused_rather_than_guessed(monkeypatch, instance):
    result, _ = _run(monkeypatch, instance, rows=[{"ingest_id": ID_A, "attempt": 2}])
    assert not _requests(result)
    assert "source_object_key" in _skip_text(result)


# --------------------------------------------------------------------------
# Transport shapes the route is free to choose
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        [{"ingest_id": ID_A, "attempt": 2, "source_object_key": PQ_KEY}],
        {"retries": [{"ingest_id": ID_A, "attempt": 2, "source_object_key": PQ_KEY}]},
        {"rows": [{"ingest_id": ID_A, "attempt": 2, "source_object_key": PQ_KEY}]},
    ],
)
def test_a_bare_list_or_either_envelope_is_accepted(monkeypatch, instance, payload):
    result, _ = _run(monkeypatch, instance, rows=payload)
    assert [r.run_key for r in _requests(result)] == [f"{ID_A}-a2"]


def test_an_empty_route_is_a_plain_skip_not_an_error(monkeypatch, instance):
    result, _ = _run(monkeypatch, instance, rows=[])
    assert not _requests(result)
    assert "awaiting a retry" in _skip_text(result)


def test_a_transport_failure_skips_with_the_exception_named(monkeypatch, instance):
    """A sensor that raises goes red every tick and the daemon retries it
    for ever; a named skip is visible without being a fault."""
    monkeypatch.setattr(mod, "stage_auth_headers", lambda: {"Authorization": "Bearer t"})
    import httpx

    def _boom(url, **kwargs):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx, "get", _boom)
    result = _build()(build_sensor_context(instance=instance))
    assert "ConnectError" in _skip_text(result)
    assert not _requests(result)


# --------------------------------------------------------------------------
# Two sensors, one route: the key guard keeps them from cross-launching
# --------------------------------------------------------------------------

XML_KEY = f"ingress-user/xml/{DIGEST_A}/mrad.xml"
PDF_KEY = f"ingress-user/pdf/{DIGEST_A}/x.pdf"


def test_the_xml_sensor_launches_a_legal_xml_row(monkeypatch, instance):
    result, _ = _run(
        monkeypatch,
        instance,
        xml=True,
        rows=[{"ingest_id": ID_A, "attempt": 2, "source_object_key": XML_KEY}],
    )
    (req,) = _requests(result)
    assert req.run_key == f"{ID_A}-a2"
    assert req.run_config["ops"][XML_OP]["config"]["file_url"] == f"s3://{BUCKET}/{XML_KEY}"
    (add,) = result.dynamic_partitions_requests
    assert add.partitions_def_name == XML_PARTITION
    assert add.partition_keys == [req.partition_key]


def test_the_pdf_sensor_refuses_an_xml_key_instead_of_cross_launching(
    monkeypatch, instance
):
    """REGRESSION. `source_object_key` bypasses the partition-set lookup, so
    before the key guard the PDF sensor launched the PDF parser on this XML
    key -- XML into the PDF parser. It must launch nothing and say why."""
    result, _ = _run(
        monkeypatch,
        instance,
        rows=[{"ingest_id": ID_A, "attempt": 2, "source_object_key": XML_KEY}],
    )
    assert not _requests(result)
    assert not result.dynamic_partitions_requests
    assert "does not match" in _skip_text(result)
    assert XML_KEY in _skip_text(result)


def test_a_row_of_another_kind_is_skipped_quietly(monkeypatch, instance):
    """`kind` is a silent pre-filter: not a refusal, not a warning."""
    result, _ = _run(
        monkeypatch,
        instance,
        xml=True,
        rows=[
            {"ingest_id": ID_A, "attempt": 2, "source_object_key": PDF_KEY, "kind": "pdf"}
        ],
    )
    assert not _requests(result)
    text = _skip_text(result)
    assert "'xml'" in text
    assert "none for ingress prefix" in text
    assert "does not match" not in text and "refused" not in text


def test_a_content_kind_that_names_no_ingress_prefix_still_launches(
    monkeypatch, instance
):
    """The rows this sensor exists for are content kind `s1000d-data-module`,
    NOT `xml`. If the pre-filter skipped every kind != its own prefix, both
    sensors would drop these in SILENCE -- no refusal, no warning, the queue
    draining to nothing with no log line saying why. Only a kind naming
    another REGISTERED prefix is skipped; anything else is judged on its key,
    and this key is a legal XML one, so it launches."""
    result, _ = _run(
        monkeypatch,
        instance,
        xml=True,
        rows=[
            {
                "ingest_id": ID_A,
                "attempt": 2,
                "source_object_key": XML_KEY,
                "kind": "s1000d-data-module",
            }
        ],
    )
    (req,) = _requests(result)
    assert req.run_key == f"{ID_A}-a2"


def test_the_key_guard_does_not_depend_on_a_kind_field(monkeypatch, instance):
    """The one that proves the guard needs nothing from the route: a PDF key
    with NO `kind` at all is still refused by the XML sensor, because the
    route is not known to send `kind`."""
    result, _ = _run(
        monkeypatch,
        instance,
        xml=True,
        rows=[{"ingest_id": ID_A, "attempt": 2, "source_object_key": PDF_KEY}],
    )
    assert not _requests(result)
    assert "does not match" in _skip_text(result)


def test_an_unknown_ingress_prefix_fails_at_build_time():
    with pytest.raises(ValueError, match="nope"):
        _build(ingress_prefix="nope")
