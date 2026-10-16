"""The publisher that tells Lane 1's door what this image can ingest.

Three things are pinned here, each because the cheap version of it is wrong:

  * THE HOLD IS ENFORCED, not incidental. `xml` is out of the advertised list
    today because no arm can run it. The ruling of 2026-10-16 is stronger than
    that: it stays out until a user-drop sensor processes a bare `xml` drop end
    to end. So the test adds `xml` to an arm and asserts the list STILL omits it
    — otherwise the day a parser row appears, the door starts being told about a
    path no drop has ever travelled, and nothing fails.

  * A REFUSAL IS NOT A PUBLISH. No token means nothing is sent; the tick says
    so, and the payload is still reported. Tolerating an anonymous call once
    already hid an unset KEYCLOAK_REALM_URL in sandbox for weeks.

  * EVERY TICK PUBLISHES. A fingerprint cursor would be a record of what WE
    did, which is not evidence of what the DOOR still holds — it can restart or
    roll back and would then never be re-told. The second tick must PUT again
    even though nothing changed.

The transport and the credential are both arguments to `publish_once`, so none
of this needs a gateway or a Keycloak.
"""
import json
from unittest.mock import patch

from dagster import DagsterInstance, build_sensor_context

import pytest

from doc_tools.api import kinds as kinds_mod
from doc_tools.components import processable_kinds_publisher as pub


class _Ctx:
    """Enough SensorEvaluationContext for the sensor body: a log and a cursor."""

    class _Log:
        def __init__(self):
            self.lines = []

        def info(self, msg, *a):
            self.lines.append(("info", msg % a if a else msg))

        def warning(self, msg, *a):
            self.lines.append(("warning", msg % a if a else msg))

    def __init__(self, cursor=None):
        self.log = self._Log()
        self.cursor = cursor


# --------------------------------------------------------------------------- #
# the advertised list
# --------------------------------------------------------------------------- #
def test_the_measured_kind_is_in_and_the_held_kind_is_out():
    kinds = kinds_mod.ingestable_kinds()
    # Measured: ten ODMRAD data modules through all five stages, 2026-10-16.
    assert "s1000d-data-module" in kinds
    # Ruled: held out until a bare `xml` user drop is processed end to end.
    assert "xml" not in kinds


def test_the_hold_survives_an_arm_claiming_the_kind():
    """The point of HELD_OUT: arm membership must not be able to retire a hold.

    Without this, the hold is a coincidence of today's parser table rather than
    a decision — and the decision is the thing that was ruled.
    """
    claimed = {
        kinds_mod.ARM_PYTHON_PASS: ["pcn"],
        kinds_mod.ARM_INGRESS_USER_XML: ["s1000d-data-module", "xml"],
    }
    with patch.object(kinds_mod, "processable_arms", return_value=claimed):
        assert "xml" not in kinds_mod.ingestable_kinds()
        # And the payload says WHY it is absent, naming the arm that claims it:
        # an omission with no reason reads to a consumer as a bug.
        rows = {e["kind"]: e for e in kinds_mod.held_out_entries()}
        assert rows["xml"]["claimed_by"] == [kinds_mod.ARM_INGRESS_USER_XML]
        assert "user-drop sensor processes a bare" in rows["xml"]["unblocks_when"]


def test_the_payload_publishes_the_hold_and_its_unblock_condition():
    payload = pub.publish_payload()
    assert payload["kinds"] == list(kinds_mod.ingestable_kinds())
    held = {e["kind"]: e for e in payload["held_out"]}
    assert "xml" in held
    for field in ("reason", "evidence", "unblocks_when", "ruled", "claimed_by"):
        assert field in held["xml"], field
    # The door cannot read git, so the condition travels in the payload.
    assert held["xml"]["ruled"] == "2026-10-16"


def test_held_out_says_no_arm_claims_xml_today():
    """`claimed_by` empty is a different fact from a hold that is load-bearing.

    Today nothing can run `xml`, so the hold is belt and braces; saying so beats
    implying the hold is what keeps it out.
    """
    rows = {e["kind"]: e for e in kinds_mod.held_out_entries()}
    assert rows["xml"]["claimed_by"] == []


# --------------------------------------------------------------------------- #
# publish_once: the credential seam
# --------------------------------------------------------------------------- #
def test_no_token_means_nothing_is_sent_and_the_tick_says_so():
    calls = []

    def _never(payload, headers):
        calls.append(payload)
        return True, "should not happen"

    ctx = _Ctx()
    published, detail, payload = pub.publish_once(
        ctx, headers_fn=lambda: None, put_fn=_never)
    assert published is False
    assert calls == [], "a refused mint must not reach the transport at all"
    assert "no svc:doc-tools token" in detail
    # The payload is still reported: "what we would have told the door" is the
    # first question asked when the door refuses a drop.
    assert payload["kinds"] == list(kinds_mod.ingestable_kinds())


def test_a_successful_publish_sends_the_payload_with_the_bearer_header():
    seen = {}

    def _put(payload, headers):
        seen["payload"] = payload
        seen["headers"] = headers
        return True, "PUT http://door/ingest/processable-kinds -> 200"

    published, detail, payload = pub.publish_once(
        _Ctx(), headers_fn=lambda: {"Authorization": "Bearer t"}, put_fn=_put)
    assert published is True
    assert seen["headers"] == {"Authorization": "Bearer t"}
    assert seen["payload"]["kinds"] == payload["kinds"]
    assert "registry_fingerprint" in seen["payload"]
    assert "-> 200" in detail


# --------------------------------------------------------------------------- #
# the sensor
# --------------------------------------------------------------------------- #
def _tick(sensor, cursor=None):
    """One real sensor tick. `SensorDefinition` is callable; its `evaluation_fn`
    is private, and calling the private one would stop pinning the contract
    dagster actually invokes."""
    return sensor(build_sensor_context(instance=DagsterInstance.ephemeral(),
                                       cursor=cursor))


def test_every_tick_publishes_even_when_nothing_changed():
    puts = []
    sensor = pub.build_processable_kinds_publisher_sensor(
        publish_fn=lambda ctx: (puts.append(1) or (True, "PUT -> 200",
                                                   pub.publish_payload())))
    first = _tick(sensor)
    # Second tick is handed the first tick's cursor, which must NOT suppress it.
    second = _tick(sensor, cursor=first.cursor)
    assert len(puts) == 2, "a fingerprint cursor must not gate publishing"
    assert json.loads(first.cursor)["published"] is True
    assert json.loads(second.cursor)["fingerprint"] == \
        json.loads(first.cursor)["fingerprint"]


def test_the_skip_reason_distinguishes_published_from_refused():
    payload = pub.publish_payload()
    ok = pub.build_processable_kinds_publisher_sensor(
        publish_fn=lambda ctx: (True, "PUT -> 200", payload))
    bad = pub.build_processable_kinds_publisher_sensor(
        publish_fn=lambda ctx: (False, "PUT -> 404: not deployed yet", payload))
    ok_text = _tick(ok).skip_reason.skip_message
    bad_text = _tick(bad).skip_reason.skip_message
    # "skipped" alone cannot tell these apart, and every tick skips.
    assert ok_text.startswith("PUBLISHED")
    assert bad_text.startswith("NOT published")
    assert "404" in bad_text
    # The kinds and the hold are in the tick text, so one tick is diagnosable.
    assert "s1000d-data-module" in ok_text
    assert "held_out=xml" in ok_text


def test_the_sensor_launches_no_runs():
    sensor = pub.build_processable_kinds_publisher_sensor(
        publish_fn=lambda ctx: (True, "PUT -> 200", pub.publish_payload()))
    result = _tick(sensor)
    assert not result.run_requests


# --------------------------------------------------------------------------- #
# _publish: the status codes a reader has to be able to act on
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


@pytest.mark.parametrize("status,expect", [
    (200, True), (201, True), (204, True),
])
def test_2xx_is_a_publish(status, expect):
    with patch("httpx.put", return_value=_Resp(status)):
        published, detail = pub._publish({"kinds": []}, {"Authorization": "x"})
    assert published is expect
    assert str(status) in detail


def test_404_is_named_as_a_route_that_is_not_deployed():
    with patch("httpx.put", return_value=_Resp(404)):
        published, detail = pub._publish({"kinds": []}, {"Authorization": "x"})
    assert published is False
    # "not built yet" and "built and refusing us" are different states and the
    # tick log has to separate them — the retry poller carried a 404 branch on an
    # assumption that turned out to be false for weeks.
    assert "not deployed yet" in detail


def test_401_is_reported_as_entitlement_not_as_a_mint_failure():
    with patch("httpx.put", return_value=_Resp(401)):
        published, detail = pub._publish({"kinds": []}, {"Authorization": "x"})
    assert published is False
    assert "ENTITLEMENT" in detail
    assert "authenticated" in detail


def test_a_connection_failure_is_a_refusal_not_an_exception():
    with patch("httpx.put", side_effect=OSError("no route to host")):
        published, detail = pub._publish({"kinds": []}, {"Authorization": "x"})
    assert published is False
    assert "failed to connect" in detail
    assert "no route to host" in detail
