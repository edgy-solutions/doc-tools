"""svc:doc-tools — this repo's transport identity for its one platform-facing call.

WHY THIS IS ITS OWN MODULE AND NOT INLINE IN THE ASSET. `assets/semantic_linker.py` imports
dagster, dagster_aws and datahub, so anything living there can only be tested where that whole
stack installs. The credential seam is the part that most needs a test — it is the difference
between the REQUIRE flip working and every classify call 401ing — so it lives where it can be
imported with nothing but `os` and the mesh SDK. **Testability is part of the contract: a
credential seam nothing can exercise is a seam nothing can seal.**

ONE CALL, ONE IDENTITY. doc-tools reaches exactly one platform service — engine-o
`POST /classify_legacy_table` — established by enumerating every configured endpoint in this repo
(DataHub, Jena, Weaviate, S3, the LLM bases, SQLServer, Oracle, the two git repos) and finding
one platform service among them. Not by grepping call sites and hoping enough were run.

IDENTITY IS AN ARGUMENT, and svc:doc-tools is doc-tools' own. It is NOT engine-a's, not the
supervisor's, not the review starter's — reusing any of those would make this call authenticate
as a service it is not, which is the `mint_service_token()` defect committed deliberately rather
than by accident.

TRANSPORT, NOT ENTITLEMENT. The credential says which SERVICE is classifying, never whose data
may be read. `svc:doc-tools` holds no capability grants and is planned to hold none: its one call
is a READ that changes no routing and no governed state, so per-process identity with zero grants
is the correct default. A grant would be a decision made in the platform's `policy/users.yaml`,
visible in git blame — never something inherited by sharing another service's credential.
"""
from __future__ import annotations

import logging
import os
from typing import Dict

logger = logging.getLogger(__name__)

#: Keycloak client for svc:doc-tools. Created by the PLATFORM's realm import (invincible-agent
#: `serviceClients`), consumed here — two charts, one credential.
CLIENT_ID_ENV = "DOC_TOOLS_CLIENT_ID"
CLIENT_ID_DEFAULT = "iagent-doc-tools"
CLIENT_SECRET_ENV = "DOC_TOOLS_CLIENT_SECRET"


#: Read by `iagent_mesh.service_identity.mint_token` as ``os.environ[...]`` with NO default, so an
#: unset value is a KeyError before any socket opens. Named here only so the diagnostic below can
#: tell you WHICH variable is missing — this module never reads it, the SDK does.
REALM_URL_ENV = "KEYCLOAK_REALM_URL"


def client_id() -> str:
    return os.getenv(CLIENT_ID_ENV, CLIENT_ID_DEFAULT)


def _cause(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:120]}"


def _remedy(exc: Exception) -> str:
    """Name the variable that is ACTUALLY missing, not a plausible one.

    Both warnings here used to end "configure DOC_TOOLS_CLIENT_SECRET" whatever the
    cause. On 2026-10-06 that sent a reader at the one variable the pod had set
    correctly, while the KeyError printed inline two fields earlier said
    `KEYCLOAK_REALM_URL`. A fixed remedy string is a guess with the authority of a
    diagnostic; derive it from the exception or admit you do not know.
    """
    if isinstance(exc, KeyError):
        missing = exc.args[0] if exc.args else ""
        if missing in (REALM_URL_ENV, CLIENT_SECRET_ENV, CLIENT_ID_ENV):
            return f"{missing} is unset in this deployment"
        return f"{missing!r} is unset in this deployment"
    return (
        f"check {REALM_URL_ENV} (the realm, no default), {CLIENT_SECRET_ENV} and that "
        f"Keycloak is reachable — the cause above says which"
    )


def ontology_auth_headers() -> Dict[str, str] | None:
    """Authorization header for the engine-o call, under svc:doc-tools.

    REFUSE, DO NOT DEGRADE — and this reverses what this function used to do. It
    previously logged and returned an ``X-Auth-Status`` marker so the classify POST
    went out UNAUTHENTICATED, on the reasoning that engine-o accepts such callers
    today (transport auth defaults to OBSERVE) and that an asset which works must
    not start failing over a chart value that has not landed. Both halves of that
    reasoning turned out to be the problem rather than the justification:

    - It made a missing credential INVISIBLE. On 2026-10-06 the sandbox pod held
      `DOC_TOOLS_CLIENT_ID` and `DOC_TOOLS_CLIENT_SECRET` and had been classifying
      happily for weeks — as caller:none, because `KEYCLOAK_REALM_URL` was unset
      and nothing downstream rejects an anonymous caller. A deployment can hold
      BOTH credentials and still authenticate as nobody, and a degraded path that
      succeeds is a path nobody fixes.
    - "It becomes loud when REQUIRE flips" means the flip is what discovers the
      misconfiguration, in whatever environment flips first. That is backwards:
      the credential seam should fail where it is configured, not where it is
      enforced.

    So a mint failure now returns ``None`` and the caller sends NOTHING — the same
    contract `stage_auth_headers()` already had, for the different reason that its
    route hard-401s. Two calls, one identity, and now one failure contract.

    NEVER RAISES, still. The refusal is the caller's to make and to report: this
    module stays importable with nothing but `os` and the SDK, and a helper that
    raised would make the seam harder to exercise in a test than the thing it
    guards. The call site turns ``None`` into a loud, attributable failure.

    FAILS LOCALLY BEFORE IT FAILS REMOTELY: ``os.environ[...]`` is evaluated BEFORE ``mint_token``
    is entered, so an unconfigured deployment raises here and never opens a socket. That is what
    keeps this testable without a Keycloak and keeps a misconfigured pod from hammering one.
    """
    try:
        from iagent_mesh.service_identity import mint_token
        token = mint_token(
            client_id=client_id(),
            client_secret=os.environ[CLIENT_SECRET_ENV],
        )
        return {"Authorization": f"Bearer {token}"}
    except Exception as exc:  # noqa: BLE001 — log and return None, never raise
        logger.warning(
            "doc-tools could not mint a token for %s (%s) — REFUSING the engine-o classify "
            "POST rather than send it unauthenticated; %s",
            client_id(), _cause(exc), _remedy(exc),
        )
        return None


def stage_auth_headers() -> Dict[str, str] | None:
    """Authorization header for Lane 1's `POST /ingest/{id}/stage` route.

    Same svc:doc-tools identity as `ontology_auth_headers()` (same client id
    / secret envs) — one repo, one service identity — and since 2026-10-06
    the same failure contract: a mint failure returns ``None`` and the
    caller sends nothing. The two arrived at it from opposite directions,
    which is worth keeping. This route hard-401s an unauthenticated caller
    (verified against sandbox), so there was never anything to proceed
    with; engine-o ACCEPTS one, so its helper used to degrade to an
    `X-Auth-Status` marker and proceed — until that tolerance turned out to
    hide an unset `KEYCLOAK_REALM_URL` in sandbox for weeks. A route that
    refuses you is the kinder of the two.

    Here the caller (`IngestStatusResource.update()`) skips the POST; the
    engine-o caller raises `Failure`. The difference is not about the
    credential: a stage transition is advisory telemetry about work that
    still happened, while a classify run that binds no terms has done
    nothing and should say so. Never raises — in both cases the refusal is
    the caller's to make.
    """
    try:
        from iagent_mesh.service_identity import mint_token
        token = mint_token(
            client_id=client_id(),
            client_secret=os.environ[CLIENT_SECRET_ENV],
        )
        return {"Authorization": f"Bearer {token}"}
    except Exception as exc:  # noqa: BLE001 — log and return None, never raise
        logger.warning(
            "doc-tools could not mint a token for %s (%s) — skipping the Lane 1 stage "
            "POST rather than send one that route will 401; %s",
            client_id(), _cause(exc), _remedy(exc),
        )
        return None
