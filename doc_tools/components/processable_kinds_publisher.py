"""PUT this image's ingestable-kinds list to Lane 1's door.

WHY A PUSH WHEN THERE IS ALREADY A GET. `GET /kinds/processable` (see
``doc_tools.api.kinds``) answers the question for anyone who asks this image. The
door is not anyone who asks: it decides whether to accept a drop at the moment
the drop arrives, and a door that has to reach a code location to find out is a
door that fails closed when the code location is rolling. So the image tells the
door, and the door caches the answer. Both directions serve the SAME
``ingestable_kinds()`` -- the GET and this PUT are one definition and two
transports, never two lists.

EVERY TICK PUBLISHES, DELIBERATELY. The obvious optimisation is a cursor holding
the last published fingerprint and a PUT only when it changes. That is wrong
here, and this repo has already paid for the general version of the mistake: a
cursor that records what WE did is not evidence of what the OTHER SIDE still
holds. The door can restart, be redeployed, or be rolled back to a build that
never received our PUT, and a fingerprint-gated publisher would then never tell
it again -- the list would be stale for as long as nothing in this image
changed, which is forever on a quiet week. The PUT is small, idempotent and
every 300s; the cursor here is for the TICK LOG, never a gate on publishing.

AND THE PUBLISH IS NOT THE FLIP. Lane 1 gates its own door on
``INGEST_DOOR_READS_PROCESSABLE_KINDS``. This publisher makes the list available;
it does not and must not decide that the door should start obeying it. Which pin
carries this publisher is a fact Lane 1 needs before flipping that flag, and it
is reported to them, not inferred by them.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Tuple

from dagster import (
    DefaultSensorStatus,
    SensorDefinition,
    SensorEvaluationContext,
    SensorResult,
    SkipReason,
)

from doc_tools.utils.mesh_identity import publisher_auth_headers

#: Same default as `ingest_retry_sensor._DEFAULT_GATEWAY_URL` and the same env
#: var: one gateway, one way to find it.
_DEFAULT_GATEWAY_URL = "http://iagent-cortex-bff:8090"
_KINDS_PATH = "/ingest/processable-kinds"
_PUT_TIMEOUT_S = 10.0

#: 300s, matching `ingest_retry_sensor`. The list changes only when an image
#: changes, so this cadence is about how fast a RESTARTED door is re-told, not
#: about how fast a change propagates.
_MINIMUM_INTERVAL_S = 300

SENSOR_NAME = "processable_kinds_publisher_sensor"


def gateway_base() -> str:
    return os.getenv("IAGENT_GATEWAY_URL", _DEFAULT_GATEWAY_URL).rstrip("/")


def publish_payload() -> Dict[str, Any]:
    """The body of the PUT: the GET route's payload, unaltered.

    Not a trimmed variant. The door needs `kinds`; a human debugging why a drop
    was refused needs `arms`, `excluded` and `held_out`, and that human is
    looking at whatever the door stored, not at this process's logs.
    """
    from doc_tools.api.kinds import processable_kinds_payload

    return processable_kinds_payload()


def _publish(payload: Dict[str, Any],
             headers: Dict[str, str]) -> Tuple[bool, str]:
    """PUT once. Returns (published, detail); never raises.

    A sensor that raises goes red on every tick and takes its tick log with it,
    which is the one place this failure is visible.
    """
    url = f"{gateway_base()}{_KINDS_PATH}"
    try:
        import httpx

        resp = httpx.put(url, json=payload, headers=headers,
                         timeout=_PUT_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        return False, f"PUT {url} failed to connect: {type(exc).__name__}: {exc}"

    if resp.status_code == 404:
        # NAMED, not lumped with 4xx: until Lane 1 ships the route this is the
        # expected state, and a tick log that cannot tell "not built yet" from
        # "built and refusing us" is a tick log nobody can act on. The retry
        # poller's own 404 branch was carried for weeks on an assumption that
        # turned out to be false, so this says only what the response says.
        return False, f"PUT {url} -> 404: Lane 1's kinds route is not deployed yet"
    if resp.status_code in (401, 403):
        return False, (
            f"PUT {url} -> {resp.status_code}: svc:doc-tools minted a token the "
            "route rejected — this is an ENTITLEMENT answer, not a mint failure; "
            "the client exists and authenticated"
        )
    if resp.status_code >= 400:
        return False, f"PUT {url} -> {resp.status_code} (body {resp.text[:200]!r})"
    return True, f"PUT {url} -> {resp.status_code}"


def publish_once(context: Optional[SensorEvaluationContext] = None,
                 headers_fn=publisher_auth_headers,
                 put_fn=_publish) -> Tuple[bool, str, Dict[str, Any]]:
    """Mint (retried) and PUT. Returns (published, detail, payload).

    Seam-shaped on purpose: both the credential and the transport are arguments,
    so a test can exercise the refusal paths without a Keycloak or a gateway.
    The payload is returned either way -- an unpublished list still belongs in
    the tick log, because "what we would have told the door" is the first thing
    anyone asks when the door is refusing a drop.
    """
    payload = publish_payload()
    headers = headers_fn()
    if headers is None:
        # The mint helper has already logged the cause and the remedy. Anonymous
        # is not a fallback: this route authenticates, and tolerating an
        # anonymous call once already hid an unset KEYCLOAK_REALM_URL in sandbox
        # for weeks.
        return False, (
            "no svc:doc-tools token could be minted after retries — not "
            f"publishing {len(payload['kinds'])} kind(s) anonymously; check "
            "KEYCLOAK_REALM_URL and the client secret"
        ), payload
    published, detail = put_fn(payload, headers)
    if context is not None:
        (context.log.info if published else context.log.warning)(
            "processable-kinds publish: %s (kinds=%s fingerprint=%s)",
            detail, ",".join(payload["kinds"]), payload["registry_fingerprint"],
        )
    return published, detail, payload


def build_processable_kinds_publisher_sensor(
    name: str = SENSOR_NAME,
    minimum_interval_seconds: int = _MINIMUM_INTERVAL_S,
    default_status: DefaultSensorStatus = DefaultSensorStatus.RUNNING,
    publish_fn=publish_once,
) -> SensorDefinition:
    """A sensor that launches NO runs and exists for its side effect.

    Unusual, and chosen over a schedule for one reason: a schedule's unit of work
    is a RUN, so a publishing schedule would mint a Dagster run per publish --
    288 a day of run records that carry no asset materialisation and would bury
    the runs anyone is actually looking for. A sensor tick is already the
    repo's established shape for a periodic platform call (`ingest_retry_sensor`
    polls on exactly this cadence), and its SkipReason is a first-class place to
    put the outcome.

    EVERY TICK SKIPS, including the successful ones, and the SkipReason says
    which happened. A reader of the tick log must be able to tell a publish that
    SUCCEEDED from one that was refused, and "skipped" alone cannot.
    """
    def _evaluate(context: SensorEvaluationContext) -> SensorResult:
        published, detail, payload = publish_fn(context)
        kinds = ",".join(payload["kinds"])
        held = ",".join(e["kind"] for e in payload.get("held_out", []))
        prefix = "PUBLISHED" if published else "NOT published"
        # The cursor is a RECORD, never a gate: see EVERY TICK PUBLISHES above.
        # It holds the last outcome so a reader of one tick can see whether the
        # previous one differed, without reading back through the log.
        cursor = json.dumps({
            "published": published,
            "fingerprint": payload["registry_fingerprint"],
            "kinds": payload["kinds"],
            "detail": detail[:200],
        }, separators=(",", ":"))
        return SensorResult(
            skip_reason=SkipReason(
                f"{prefix}: {detail} | kinds={kinds or 'none'}"
                + (f" | held_out={held}" if held else "")
                + f" | fingerprint={payload['registry_fingerprint']}"
            ),
            cursor=cursor,
        )

    return SensorDefinition(
        name=name,
        evaluation_fn=_evaluate,
        minimum_interval_seconds=minimum_interval_seconds,
        default_status=default_status,
        description=(
            "PUTs this image's ingestable-kinds list to Lane 1's door every "
            "tick (idempotent; a door that restarted must be re-told). Launches "
            "no runs."
        ),
    )
