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


def client_id() -> str:
    return os.getenv(CLIENT_ID_ENV, CLIENT_ID_DEFAULT)


def ontology_auth_headers() -> Dict[str, str]:
    """Authorization header for the engine-o call, under svc:doc-tools.

    LOG AND PROCEED, NEVER RAISE. Engine-o accepts unauthenticated callers today (the mesh's
    transport auth defaults to OBSERVE), so attaching a credential where none was sent is
    behaviourally inert — and an asset that works today must not begin failing because Keycloak
    blipped or because a chart value has not landed yet. When REQUIRE flips, the same failure
    becomes a 401 at engine-o, which is the correct moment for it to become loud.

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
    except Exception as exc:  # noqa: BLE001 — see LOG AND PROCEED above
        # X-Auth-Status is DIAGNOSTIC ONLY and must never reach an authorization decision: it is
        # caller-asserted and therefore unverifiable. Legal to LOG, illegal to TRUST. It exists so
        # that a mint FAILURE and a caller that never minted are distinguishable at engine-o —
        # without the discriminant, a Keycloak blip reads as caller-readiness regressing.
        logger.warning(
            "doc-tools minting no token for %s (%s: %s) — proceeding UNAUTHENTICATED; engine-o "
            "records caller:none until %s is configured",
            client_id(), type(exc).__name__, str(exc)[:120], CLIENT_SECRET_ENV,
        )
        return {"X-Auth-Status": f"mint-failed:{type(exc).__name__}"}
