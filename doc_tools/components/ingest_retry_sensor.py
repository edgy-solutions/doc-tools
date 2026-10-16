"""The Dagster half of Lane 1's `POST /ingest/{id}/retry`.

A standalone sensor that polls `GET /ingest/retries` and launches the
user-drop parser again for each row the gateway re-opened. It never touches
S3 listings and never touches the LastModified cursor `ingress_user_sensor`
keeps, so the two cannot interfere.

WHY A SEPARATE SENSOR, AND WHY AN ATTEMPT COUNTER. Measured in the dagster
this repo runs (1.12.21), `_daemon/sensor.py:1345`
`_get_or_create_sensor_run`:

    run = (run_key and existing_runs_by_key.get(run_key)) or instance.get_run_by_id(run_id)
    if run:
        if run.status != DagsterRunStatus.NOT_STARTED:
            return SkippedSensorRun(run_key=run_request.run_key, existing_run=run)

`NOT_STARTED` is the ONLY status that falls through to a launch, and that
branch's own comment says it is there for a daemon that crashed between
creating the run and updating the tick -- crash recovery, not retry. So
SUCCESS, FAILURE, CANCELED, QUEUED and STARTED all skip: **a failed run has
consumed its run_key permanently.** `fetch_existing_runs` (:1286) is a bare
tag query with no `created_after` and no tick bound, so the key is consumed
for as long as the run row exists -- "retry tomorrow" is not a recovery path
either.

Two things follow, and both are load-bearing here:

1. Dedup is scoped by `SENSOR_NAME_TAG == sensor.name` plus the repository
   origin selector (:1307-1320), so a NEW sensor gets a clean run_key
   namespace and cannot be blocked by keys `ingress_user_sensor` already
   burned. Re-yielding the original key from inside that sensor would be
   skipped for ever; this module exists because of that.
2. A new namespace is NOT sufficient on its own. Within this sensor,
   retrying one ingest twice collides with itself at the second attempt.
   Hence the run_key is `{ingest_id}-a{attempt}` -- the attempt counter is
   the thing that makes a second retry possible at all, not decoration.

Modifying `ingress_user_sensor` was never an option regardless: it is a
declarative `S3SensorComponent` from external `dag_tools`, with no seam of
ours to hook.

IDLE, BUT NOT FOR THE REASON THIS DOCSTRING FIRST GAVE. It said the route was
not deployed yet. MEASURED 2026-10-16 against the sandbox: `GET
/ingest/retries` IS deployed and answers, and the 404 branch below has never
once been taken -- 109 of 109 ticks from the sensor's first tick at 04:29:40Z
returned HTTP 200. Every one of them carried an EMPTY row list, so the skip is
"no ingest rows are awaiting a retry", which is only reachable past the 404 and
>=400 branches.

So this sensor is idle because NOTHING ENQUEUES A FAILED INGEST, not because the
route is missing. That distinction decides a remedy: the five `ingress-user/pdf/`
drops that failed the ADR-0041 guard are NOT in the queue and this sensor will
never pick them up, so they need a re-drop under a new object key. Do not tell
anyone that shipping the route will relaunch them; the route is shipped.

The named-SkipReason design is what made that measurable, and it stays: each
refusal says which one it was -- no token, route absent, transport error, empty
queue, or a row this module refused and why. A degradation nobody can see is a
path nobody fixes.

One real hole, also measured: 2 of those 109 ticks could not mint a
`svc:doc-tools` token and skipped rather than polling anonymously. The refusal
is right (an anonymous poll would 401), but a tick that cannot mint is a tick
that inspects nothing.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from dagster import (
    AddDynamicPartitionsRequest,
    DefaultSensorStatus,
    RunRequest,
    SensorDefinition,
    SensorEvaluationContext,
    SensorResult,
    SkipReason,
    sensor,
)

from doc_tools.utils.ingest_id import INGEST_ID_RE
from doc_tools.utils.mesh_identity import stage_auth_headers

# Same gateway base and env var as IngestStatusResource
# (doc_tools/utils/dagster_resources.py) -- one gateway, one env var. Kept as
# a literal rather than imported so a retry poll cannot be re-pointed by an
# edit to the stage POST path, or the reverse.
_DEFAULT_GATEWAY_URL = "http://iagent-cortex-bff:8090"
_RETRIES_PATH = "/ingest/retries"
_RETRIES_GET_TIMEOUT_S = 10.0

# The 64-hex content digest inside a canonical ingest id. The id gives this
# directory segment of the S3 key and NOTHING else -- not the filename --
# which is why `source_object_key` is a required field of the route's rows
# and why the fallback below has to go looking.
_DIGEST_RE = re.compile(r"^sha256:([0-9a-f]{64})$")

# A retry is human-initiated, so five minutes of latency costs nothing, and
# while the route is absent it divides the 404 tick noise by five.
_MINIMUM_INTERVAL_S = 300


def _gateway_base() -> str:
    return os.getenv("IAGENT_GATEWAY_URL", _DEFAULT_GATEWAY_URL).rstrip("/")


def _fetch_retry_rows(
    context: SensorEvaluationContext,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """GET the re-opened rows. Returns (rows, skip_reason); never raises.

    The token is required, not preferred. `stage_auth_headers()` returns None
    when no token could be minted, and this route will 401 an anonymous
    caller the same way the stage route does -- so we send nothing and say
    so. Tolerating an anonymous call once already hid an unset
    KEYCLOAK_REALM_URL in sandbox for weeks.
    """
    headers = stage_auth_headers()
    if headers is None:
        return [], (
            "no svc:doc-tools token could be minted -- not polling "
            f"{_RETRIES_PATH} anonymously (it would 401); check "
            "KEYCLOAK_REALM_URL and the client secret"
        )

    url = f"{_gateway_base()}{_RETRIES_PATH}"
    try:
        import httpx

        resp = httpx.get(url, headers=headers, timeout=_RETRIES_GET_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 -- a sensor that raises goes red every tick
        return [], f"GET {url} failed to connect: {type(exc).__name__}: {exc}"

    if resp.status_code == 404:
        # The expected state until Lane 1 ships the route. Named, so the tick
        # log distinguishes "not built yet" from "built and broken".
        return [], f"GET {url} -> 404: Lane 1's retry route is not deployed yet"
    if resp.status_code >= 400:
        return [], f"GET {url} -> {resp.status_code} (body {resp.text[:200]!r})"

    try:
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        return [], f"GET {url} -> 200 but the body is not JSON: {type(exc).__name__}: {exc}"

    # Accept either a bare list or {"retries": [...]} / {"rows": [...]} -- the
    # envelope is Lane 1's to choose and is not worth a round trip to settle.
    if isinstance(payload, dict):
        rows = payload.get("retries", payload.get("rows", []))
    else:
        rows = payload
    if not isinstance(rows, list):
        return [], (
            f"GET {url} -> 200 but no row list in the body "
            f"(got {type(payload).__name__})"
        )

    return [r for r in rows if isinstance(r, dict)], None


def _encode_partition_key(object_key: str) -> str:
    """The partition-key encoding dag_tools' S3SensorComponent uses."""
    return object_key.replace("/", "__")


def _key_from_registered_partitions(
    context: SensorEvaluationContext,
    partition_name: str,
    digest: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Recover the full S3 key from the partition the ORIGINAL drop registered.

    The fallback for a route that ships without `source_object_key`. The
    original run registered `ingress-user/pdf/<digest>/<name>.pdf` in encoded
    form, so the digest is enough to find it again.

    Decoding is exact rather than a blanket `__` -> `/`: a filename may well
    contain `__`, and `ingress_user_sensor`'s own filter
    (`^ingress-user/pdf/[0-9a-f]{64}/[^/]+\\.pdf$`) guarantees exactly one
    path segment after the digest. So only the FIRST separator after the
    digest is a slash, and everything past it belongs to the filename.

    Returns (object_key, refusal_reason). Two registered partitions under one
    digest -- the same bytes uploaded twice under different names -- is
    genuinely ambiguous, and this refuses rather than picking one.
    """
    try:
        registered = context.instance.get_dynamic_partitions(partition_name)
    except Exception as exc:  # noqa: BLE001
        return None, (
            f"could not read the {partition_name} partitions: "
            f"{type(exc).__name__}: {exc}"
        )

    matches = [pk for pk in registered if digest in pk]
    if not matches:
        return None, (
            f"no registered {partition_name} partition carries digest "
            f"{digest[:12]}... -- the original drop's partition is gone, so the "
            "object key cannot be recovered; Lane 1 should send source_object_key"
        )
    if len(matches) > 1:
        return None, (
            f"{len(matches)} registered partitions carry digest {digest[:12]}... "
            f"({matches!r}) -- the same bytes under more than one filename, so "
            "which file to reprocess is ambiguous; refusing to guess. Lane 1 "
            "should send source_object_key"
        )

    encoded = matches[0]
    head, _, tail = encoded.partition(digest)
    object_key = head.replace("__", "/") + digest + tail.replace("__", "/", 1)
    return object_key, None


def build_ingest_retry_sensor(
    *,
    name: str,
    job_name: str,
    target_op: str,
    bucket: str,
    partition_name: str,
    minimum_interval_seconds: int = _MINIMUM_INTERVAL_S,
    default_status: DefaultSensorStatus = DefaultSensorStatus.RUNNING,
) -> SensorDefinition:
    """A sensor that re-launches `job_name` for every row at the retry route.

    `default_status` is RUNNING, matching `ingress_user_sensor` and for the
    same reason: this is the recovery path for a user's own upload, and a
    recovery path nobody remembered to switch on is a defect this repo has
    already hit (`xml_sensor` sat STOPPED). The other sensors here stay
    STOPPED deliberately; this one and the drop it recovers are the pair a
    user is actually waiting on. NOT RETROACTIVE -- `default_status` is
    consulted only when the instance holds no stored status for the sensor.
    """

    @sensor(
        name=name,
        job_name=job_name,
        minimum_interval_seconds=minimum_interval_seconds,
        default_status=default_status,
    )
    def _ingest_retry_sensor(context: SensorEvaluationContext) -> SensorResult:
        rows, skip = _fetch_retry_rows(context)
        if skip is not None:
            return SensorResult(skip_reason=SkipReason(skip))
        if not rows:
            return SensorResult(
                skip_reason=SkipReason("no ingest rows are awaiting a retry")
            )

        run_requests: List[RunRequest] = []
        new_partitions: List[str] = []
        refused: List[str] = []

        try:
            registered = set(context.instance.get_dynamic_partitions(partition_name))
        except Exception:  # noqa: BLE001 -- the per-row read reports its own failure
            registered = set()

        for row in rows:
            ingest_id = row.get("ingest_id")
            if not isinstance(ingest_id, str) or not INGEST_ID_RE.match(ingest_id):
                refused.append(
                    f"ingest_id {ingest_id!r} is not canonical sha256:<64hex>"
                )
                continue

            # `attempt` is the other half of the run_key. Without it the key is
            # the one Dagster already consumed, so a row that omits it is
            # refused rather than launched into a silent skip.
            attempt = row.get("attempt")
            if isinstance(attempt, bool) or not isinstance(attempt, int):
                refused.append(f"{ingest_id}: attempt {attempt!r} is not an int")
                continue
            if attempt < 2:
                refused.append(
                    f"{ingest_id}: attempt {attempt} -- the retry route lists "
                    "attempt > 1; attempt 1 is the original drop and belongs to "
                    "ingress_user_sensor"
                )
                continue

            digest_match = _DIGEST_RE.match(ingest_id)
            if digest_match is None:  # unreachable: INGEST_ID_RE already matched
                refused.append(f"{ingest_id}: no 64-hex digest in the ingest id")
                continue
            digest = digest_match.group(1)

            object_key = row.get("source_object_key")
            if isinstance(object_key, str) and object_key:
                if "/" not in object_key:
                    refused.append(
                        f"{ingest_id}: source_object_key {object_key!r} is not an S3 key"
                    )
                    continue
            else:
                object_key, reason = _key_from_registered_partitions(
                    context, partition_name, digest
                )
                if object_key is None:
                    refused.append(f"{ingest_id}: {reason}")
                    continue

            partition_key = _encode_partition_key(object_key)
            if partition_key not in registered:
                # The original drop normally registered this already; adding it
                # is idempotent and covers a drop that failed before the
                # partition landed. SensorResult applies these before the runs.
                new_partitions.append(partition_key)
                registered.add(partition_key)

            run_requests.append(
                RunRequest(
                    run_key=f"{ingest_id}-a{attempt}",
                    partition_key=partition_key,
                    run_config={
                        "ops": {
                            target_op: {
                                "config": {"file_url": f"s3://{bucket}/{object_key}"}
                            }
                        }
                    },
                    tags={
                        "ingest_id": ingest_id,
                        "ingest_attempt": str(attempt),
                        "ingest_retry": "true",
                    },
                )
            )

        for message in refused:
            context.log.warning("%s refused a retry row -- %s", name, message)

        if not run_requests:
            return SensorResult(
                skip_reason=SkipReason(
                    f"{len(rows)} row(s) at the retry route, none launchable: "
                    + "; ".join(refused)[:900]
                )
            )

        context.log.info(
            "%s launching %d retry run(s) (run_keys %s); refused %d row(s)",
            name,
            len(run_requests),
            [r.run_key for r in run_requests],
            len(refused),
        )

        return SensorResult(
            run_requests=run_requests,
            dynamic_partitions_requests=(
                [
                    AddDynamicPartitionsRequest(
                        partitions_def_name=partition_name,
                        partition_keys=new_partitions,
                    )
                ]
                if new_partitions
                else []
            ),
        )

    return _ingest_retry_sensor
