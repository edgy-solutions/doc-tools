"""Starlette app serving this image's processable kinds.

THIS APP IS SERVED NOWHERE, BY RULING, AND THAT IS NOT AN OMISSION.
RULED 2026-10-16 (F2, architect): the reversed route is the one that ships --
`doc_tools.components.processable_kinds_publisher` PUTs the list from inside the
Dagster code-location pod to Lane 1's BFF, which is why doc-tools needs no HTTP
surface at all. Nothing in `charts/` references this module; the one container
runs `dagster api grpc -p 3030` and starts no ASGI server. So there is no second
container and no Service, and the Deployment's `containerPort`/probe naming is
left alone until the day a port actually exists.

What this app is FOR, then: it is the same `ingestable_kinds()` behind a
transport anyone can call by hand, kept in the tree so the payload has one
definition and a human (or a future third-party consumer) can get at it without
a Dagster run. It is code, deliberately unwired -- not a half-finished deploy.

THE STANDING POSTURE RULE, recorded here rather than in the chart because the
chart has nothing to record it against. The auth behaviour described below is
correct for an UNSERVED module and must not survive being served: the day this
app is put behind a port, it ships with `REQUIRE_TRANSPORT_AUTH=true` AND a
verification key configured FIRST. "unverified => 200" never ships on a served
route. Flipping REQUIRE with no key configured 401s every caller including a
legitimate one, so the key is the first half of that change, not a follow-up.

Starlette only: the SDK moved its heavier web framework behind an extra on
purpose, and this repo imports neither half of it.

AUTH: REFUSE WHAT CAN BE JUDGED FALSE, MARK WHAT CANNOT BE JUDGED.
``transport_auth`` is imported at module import and an ImportError propagates --
a missing SDK is a broken image, and a fallback that serves while verifying
nothing is the presence-only defect that module exists to have closed.

The three outcomes, and why a flat "unverified means 401" is wrong WHILE
UNSERVED (see the standing posture rule above -- being served reverses this):
``verify_bearer`` NEVER RAISES. It returns ``verified=False`` with a named
reason, and two of those reasons -- ``no-verification-key`` and
``pyjwt-missing`` -- mean THIS POD cannot judge the token, not that the token is
bad. No ``MESH_JWT_PUBLIC_KEY``/``KEYCLOAK_PUBLIC_KEY`` is configured on this
deployment today, so refusing every unverified bearer would 401 Lane 1's door
holding a GENUINE mint. The reasons that mean the token IS bad --
``undecodable``, ``invalid``, a missing entitlement claim -- are refused, under
either posture.

A request admitted without proof is marked, never silent: every response carries
``X-Mesh-Auth`` (``verified`` / ``anonymous`` / ``unverified:<reason>``) and an
unverifiable bearer logs at WARNING naming the reason. A tolerated anonymous
call that nothing records is a path nobody ever fixes.

Under ``REQUIRE_TRANSPORT_AUTH`` (the SDK's ``POSTURE_REQUIRE``) anything short
of ``verified`` is a 401, anonymous included. ``/healthz`` is exempt BEFORE the
posture check: a kubelet probe sends no bearer, and a REQUIRE flip that starts
401ing the liveness probe would kill the pod it was meant to protect.
"""
import logging
from contextlib import asynccontextmanager

from iagent_mesh import transport_auth
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from doc_tools.api.kinds import processable_kinds_payload

logger = logging.getLogger(__name__)

#: Paths served before any auth decision. See the module docstring.
EXEMPT_PATHS = frozenset({"/healthz"})

#: `verify_bearer` reasons that mean THIS POD COULD NOT JUDGE the token, as
#: opposed to the token being bad. Marked and served under OBSERVE.
UNJUDGEABLE_REASONS = frozenset({"no-verification-key", "pyjwt-missing"})


def _bearer(header):
    """The token out of an ``Authorization`` header, or None."""
    if not header:
        return None
    parts = header.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return header.strip() or None


class TransportAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        caller = transport_auth.verify_bearer(_bearer(request.headers.get("Authorization")))
        # A reason is a short SDK code; the token itself is never logged or echoed.
        code = caller.reason.split(":")[0]

        if caller.verified:
            return await self._mark(call_next, request, "verified")

        if transport_auth.resolve_posture() == transport_auth.POSTURE_REQUIRE:
            logger.warning("kinds route: refused under REQUIRE (%s)", code)
            return JSONResponse({"error": "unauthorized", "reason": code}, status_code=401)

        if caller.reason == "absent":
            return await self._mark(call_next, request, "anonymous")

        if caller.reason in UNJUDGEABLE_REASONS:
            logger.warning(
                "kinds route: bearer ADMITTED UNVERIFIED (%s) -- this pod has no "
                "verification key, so the token was not judged", code)
            return await self._mark(call_next, request, f"unverified:{code}")

        logger.warning("kinds route: bearer refused (%s)", code)
        return JSONResponse({"error": "unauthorized", "reason": code}, status_code=401)

    @staticmethod
    async def _mark(call_next, request, state):
        response = await call_next(request)
        response.headers["X-Mesh-Auth"] = state
        return response


async def kinds_processable(request):
    return JSONResponse(processable_kinds_payload())


async def healthz(request):
    return JSONResponse({"status": "ok"})


@asynccontextmanager
async def _lifespan(_app):
    # `lifespan`, not `on_startup`: starlette deprecated the latter and removes
    # it at 1.0, and a route that ships a DeprecationWarning teaches a reader to
    # ignore warnings from this package.
    logger.info(transport_auth.posture_line("doc-tools-kinds"))
    yield


app = Starlette(
    routes=[
        Route("/kinds/processable", kinds_processable, methods=["GET"]),
        Route("/healthz", healthz, methods=["GET"]),
    ],
    middleware=[Middleware(TransportAuthMiddleware)],
    lifespan=_lifespan,
)
