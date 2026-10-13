import logging
import os
from typing import ClassVar, Optional

import httpx
from dagster import ConfigurableResource

# We will need some stubs for the resources that the assets depend on.
# For doc-tools, we can use these simple wrappers around the clients.

from pydantic import Field

class Neo4jResource(ConfigurableResource):
    uri: str
    username: str
    password: str

    def get_client(self):
        # In a real system, this would return a driver or a wrapper
        from .neo4j_client import Neo4jClient
        return Neo4jClient(uri=self.uri, user=self.username, password=self.password)

    def get_driver(self):
        """Return a raw ``neo4j.Driver`` for callers that want to use the
        native ``with driver.session() as session:`` pattern directly.

        ``aitool_linker.sync_aitool_predicate_to_neo4j`` calls this. Without
        the method the asset raises ``AttributeError: 'Neo4jResource' object
        has no attribute 'get_driver'`` on every sync, every URN, which then
        gets caught by Dagster's broad except and reported as a generic
        step failure with no operator-visible cause.
        """
        from neo4j import GraphDatabase
        return GraphDatabase.driver(self.uri, auth=(self.username, self.password))

class WeaviateResource(ConfigurableResource):
    http_host: str = Field(description="The HTTP REST endpoint for Weaviate (e.g., weaviate:8080)")
    grpc_host: str = Field(description="The high-speed gRPC endpoint for Weaviate (e.g., weaviate-grpc:50051)")

    def get_client(self):
        from .weaviate_client import get_weaviate_client
        return get_weaviate_client(http_host=self.http_host, grpc_host=self.grpc_host)

class LLMExtractorResource(ConfigurableResource):
    langfuse_public_key: str = Field(description="Public key for Langfuse tracing")
    langfuse_secret_key: str = Field(description="Secret key for Langfuse tracing")
    langfuse_host: str = Field(description="Langfuse API host (e.g., https://cloud.langfuse.com)")

    def get_client(self):
        # This provides a centralized way to access Langfuse config if needed
        return {
            "public_key": self.langfuse_public_key,
            "secret_key": self.langfuse_secret_key,
            "host": self.langfuse_host
        }

# Stage vocabularies converged at SDK v0.9.8: `iagent_mesh.ingest.
# INGEST_STAGES` spells the review stage `review`, as Lane 1's route always
# did, so nothing is translated here any more. The one-entry bridge dict that
# used to do it is deleted; a tripwire in
# `tests/test_ingest_stage_transport.py` asserts it is not reintroduced.

#: What Lane 1's `POST /ingest/{id}/stage` route accepts
#: (`gateway.py`'s `_stage_targets`) — forward
#: transitions only. `received` is Lane 1's OWN stamp (it creates the row
#: on `POST /ingest`), and `promoted`/`rejected` belong to the human
#: disposition task, not this seam. A stage outside this set is
#: observed locally (logged) and never POSTed.
_WIRE_POSTABLE = frozenset({"extracting", "review", "failed"})

#: No chart key existed for this before now. `charts/doc-tools/values.yaml`
#: and `values-sandbox.yaml` set `IAGENT_GATEWAY_URL` beside
#: `ONTOLOGY_SERVICE_URL`; this default matches the sandbox service.
_DEFAULT_GATEWAY_URL = "http://iagent-cortex-bff:8090"

#: This seam must NEVER stall an extraction waiting on Lane 1's gateway — a
#: stage write is observability, not something the parse blocks on.
_STAGE_POST_TIMEOUT_S = 10.0


class IngestStatusResource(ConfigurableResource):
    """ADR-0041 stage-status seam for the ingress-user path.

    Lane 1 (`invincible-agent/src/iagent/gateway.py`'s `POST /ingest`) owns a
    `ingest_status_projection` row per ingest, keyed on the `ingest_id` its
    own sidecar manifest already carries. This resource announces the stage
    *doc-tools* observes (received the file -> extracting -> review /
    failed) against that row over HTTP:
    `POST {IAGENT_GATEWAY_URL}/ingest/{ingest_id}/stage` — live in sandbox.
    The route requires a Bearer JWT minted under svc:doc-tools
    (`doc_tools/utils/mesh_identity.py`'s `stage_auth_headers()`) and 403s
    any caller whose `authz_id` is not `svc:doc-tools`.

    VOCABULARY. `update()` validates `stage` against the REAL imported
    `iagent_mesh.ingest.INGEST_STAGES` (never a mirrored copy). Since SDK
    v0.9.8 that vocabulary and Lane 1's route vocabulary agree (`review`), so
    nothing is translated; `_WIRE_POSTABLE` above is the set Lane 1's route
    accepts. `received` is observed locally only
    (Lane 1 owns that stamp) and `promoted`/`rejected` are observed locally
    only (the human disposition task owns those) — neither is POSTed here.

    NON-FATAL, ALWAYS. A failed token mint, a network error, and a non-2xx
    response are all logged at WARNING and swallowed: a stage write must
    never fail an extraction. `update()` still validates every call against
    the real vocabulary and Lane 1's own rules (shape, blank-detail) BEFORE
    any of that transport is attempted.

    STRUCTURED FAILURE. A `failed` stage may carry five more fields beyond
    `detail`: `reason_code` (a member of `ingest_failure.REASON_CODES`),
    `reason` (human-readable, self-contained), `step` (the op/asset that
    failed), `run_id` (the Dagster run) and `pin_digest` (the running-code
    identity; auto-filled from `running_code_identity()` when omitted). The
    SDK's `IngestStatus` is `extra="forbid"` with only `stage` and `detail`,
    but Lane 1's live route accepts the extras anyway: probed against the
    sandbox gateway with a canonical but nonexistent ingest_id, `{stage,
    detail}` and `{stage, detail, reason_code, step, run_id, pin_digest}`
    both returned an identical `404 ingest_not_found` -- a 404, not a 422,
    so body validation passed. Lane 1 ignores them until it lands the
    field; it owns persisting them and `POST /ingest/{id}/retry`.
    """

    #: THE UNITS, stated (architect ruling 2026-10-02: "extracted_count /
    #: extracted_total are two fields with units stated"). They are two
    #: fields, and they are NOT a progress fraction: they count different
    #: things, so `extracted_count / extracted_total` is meaningless and a
    #: consumer rendering "412 of 9" has mistaken the contract. Named as
    #: constants rather than prose so the no-op log below carries the units
    #: with every value it prints — that log is the entire observable surface
    #: of this seam until a transport exists, so units living only in a
    #: docstring are units a reader of the logs does not have.
    #:
    #: `ClassVar`, not a field: `ConfigurableResource` is a pydantic model, so
    #: a bare annotated attribute here would be read as a REQUIRED config
    #: field, and an UNannotated one is refused outright — which breaks the
    #: import of `doc_tools.definitions`, and therefore every asset in the
    #: repo, not just this seam.
    EXTRACTED_COUNT_UNIT: ClassVar[str] = "unstructured elements extracted from the document"
    EXTRACTED_TOTAL_UNIT: ClassVar[str] = "pages rasterized from the source PDF"

    #: The stage whose POST Lane 1 turns into a `document_promotion` task —
    #: canonical and wire spelling are the same string since SDK v0.9.8.
    #: A promote/reject on that task builds a decision record, and the
    #: record must name what was reviewed — so this is the one stage where an
    #: absent `extraction_ref` is a defect rather than a missing nicety. See
    #: `update()`'s `extraction_ref` paragraph.
    _PROMOTION_FILING_WIRE_STAGE: ClassVar[str] = "review"

    def update(self, ingest_id: str, stage: str, *,
               extracted_count: Optional[int] = None,
               extracted_total: Optional[int] = None,
               extraction_ref: Optional[str] = None,
               detail: Optional[str] = None,
               reason_code: Optional[str] = None,
               reason: Optional[str] = None,
               step: Optional[str] = None,
               run_id: Optional[str] = None,
               pin_digest: Optional[str] = None) -> None:
        """Validate and (for now) log one stage transition for `ingest_id`.

        `ingest_id` must be ``sha256:<64 lowercase hex>``. That is Lane 1's
        rule, NOT the SDK's — `invincible-agent/src/iagent/promotion.py:65`'s
        `INGEST_ID_RE`, which `ingest_status.update_status` (the real transport
        this no-op stands in for) already refuses a mismatch against. Checking
        it here is the whole point of a *validating* no-op: a shape this seam
        accepts today but the transport will reject is a defect that would
        otherwise surface only once the transport lands. A bare hexdigest is
        coerced with a warning; anything else raises. See
        `doc_tools/utils/ingest_id.py` for why that constant is mirrored
        rather than imported, and for what the SDK does and does not declare.

        `extracted_count` and `extracted_total` are two independent fields in
        the units named by `EXTRACTED_COUNT_UNIT` / `EXTRACTED_TOTAL_UNIT`
        above. They are not numerator and denominator.

        Import the vocabulary, never mirror it: `INGEST_STAGES` is owned by
        `iagent_mesh.ingest` (SDK v0.9.5+, pinned in pyproject.toml).
        `invincible-agent/src/iagent/ingest_status.py` mirrors this same
        tuple only because the fleet's OLD v0.9.3 pin lacked the module —
        doc-tools is on v0.9.5 and imports the real thing. Local import so
        this resource (and this whole module) stays importable without the
        SDK installed for every caller that never calls `update()`.

        `extraction_ref` NAMES THE EXTRACTION THE DECISION RECORD IS ABOUT.
        Measured live on roll #19 (Lane 1's packet 2026-10-07): PCN26-119
        reached `review` through this very method, Lane 1 filed
        `document_promotion:<id>` from it, and the promote was refused
        `422 promotion_payload_invalid … missing ['object_ref',
        'content_kind', 'pipeline_version', 'format_fingerprint',
        'standing', 'extraction_ref']`. Lane 1 holds `object_ref`,
        `content_kind` and `standing` already; the other three describe an
        extraction only this side has seen. Under ADR-0034 `pipeline_version`
        and `format_fingerprint` must NOT be caller-asserted, so this seam
        sends neither — it sends one bucket-relative artifact KEY and Lane 1
        derives them from the artifact. That is the whole of the contract: a
        key, not a claim.

        Bucket-relative on purpose: `object_ref` (which Lane 1 wrote at
        `/ingest` for the same document) is a bare key in the same bucket, so
        the two refs resolve the same way. A fully-qualified `s3://` URL here
        would be a second convention for one pair of fields.

        An absent `extraction_ref` is loud at `review` and silent everywhere
        else, because `review` is the only stage that files a promotion task
        — at `extracting` or `failed` there is no record to name and no
        manifest written yet.
        """
        from iagent_mesh.ingest import INGEST_STAGES

        from doc_tools.utils.ingest_id import canonical_ingest_id

        ingest_id = canonical_ingest_id(
            ingest_id, where=f"IngestStatusResource.update(stage={stage!r})"
        )

        if stage not in INGEST_STAGES:
            raise ValueError(
                f"stage={stage!r} is not one of INGEST_STAGES={INGEST_STAGES!r}"
            )
        # Lane 1's own rule, at ingest_status.update_status: a terminal
        # negative stage must say why.
        if stage in ("rejected", "failed") and not (detail and detail.strip()):
            raise ValueError(
                f"stage={stage!r} requires a non-blank `detail` (Lane 1's "
                f"rule at ingest_status.update_status) — got detail={detail!r}"
            )

        # A blank/whitespace `extraction_ref` is worse than none: it reaches
        # Lane 1 as a present-but-unresolvable key, so the 422 it was sent to
        # cure is replaced by a 404 on a key that names nothing. Refused at
        # the call site, where the caller still knows what it meant to send.
        if extraction_ref is not None and not str(extraction_ref).strip():
            raise ValueError(
                f"extraction_ref={extraction_ref!r} is blank. Pass the "
                f"artifact key or pass None — a blank ref names no artifact "
                f"and Lane 1 cannot derive pipeline_version or "
                f"format_fingerprint from it."
            )

        logger = logging.getLogger(__name__)

        # NON-RAISING, unlike every validation above. Those run on paths
        # where the caller can still fix the call; `reason_code`'s only
        # caller is an error boundary, and the comment at that boundary
        # already records that a raise inside the handler MASKS the original
        # exception. So an unknown code is logged and coerced, never raised.
        from doc_tools.utils.ingest_failure import (
            REASON_CODE_SLUG_RE, REASON_CODES, running_code_identity,
        )

        # Lane 1 422s `invalid_reason_code` unless the code matches
        # REASON_CODE_SLUG_RE (^[a-z][a-z0-9_]{0,63}$), so a non-slug is
        # coerced here as well as an unknown-but-slug-shaped one.
        if reason_code is not None and (
            not isinstance(reason_code, str)
            or not REASON_CODE_SLUG_RE.match(reason_code)
            or reason_code not in REASON_CODES
        ):
            logger.warning(
                "ADR-0041 ingest status: bad reason_code=%r (must match "
                "%s and be one of %s) -- coerced to 'unexpected_error', "
                "not raised.",
                reason_code, REASON_CODE_SLUG_RE.pattern, sorted(REASON_CODES),
            )
            reason_code = "unexpected_error"
        # Lane 1 refuses failure-only fields on any other stage with 422
        # `failure_fields_without_failed`. Omit them (with a warning) rather
        # than send a request that will be refused. `run_id` is exempt: it is
        # accepted on EVERY stage, and Lane 1 wants it on `extracting` (their
        # watchdog names the run with it when a row stalls).
        if stage != "failed":
            _fields = {"reason_code": reason_code, "reason": reason,
                       "step": step, "pin_digest": pin_digest}
            for _fname, _fval in _fields.items():
                if _fval is not None:
                    logger.warning(
                        "ADR-0041 ingest status: %s is failure-only (Lane 1: "
                        "422 failure_fields_without_failed) but stage=%r -- "
                        "omitted from the body.", _fname, stage,
                    )
            reason_code = reason = step = pin_digest = None
        if stage == "failed" and pin_digest is None:
            pin_digest = running_code_identity()

        # The SDK and Lane 1's route share one spelling since v0.9.8; check
        # what the route accepts. See `_WIRE_POSTABLE` above.
        wire_stage = stage

        if wire_stage not in _WIRE_POSTABLE:
            logger.info(
                "ADR-0041 ingest status LOCALLY OBSERVED ONLY (Lane 1's "
                "stage route does not accept stage=%s [wire=%s] — Lane 1 "
                "owns the 'received' stamp and the human disposition task "
                "owns 'promoted'/'rejected'; neither is posted here): "
                "ingest_id=%s extracted_count=%s [%s] extracted_total=%s "
                "[%s] detail=%s"
                " reason_code=%s reason=%s step=%s run_id=%s pin_digest=%s",
                stage, wire_stage, ingest_id,
                extracted_count, self.EXTRACTED_COUNT_UNIT,
                extracted_total, self.EXTRACTED_TOTAL_UNIT,
                detail,
                reason_code, reason, step, run_id, pin_digest,
            )
            return

        from doc_tools.utils.mesh_identity import stage_auth_headers

        headers = stage_auth_headers()
        if headers is None:
            logger.warning(
                "ADR-0041 ingest status: no token minted for svc:doc-tools "
                "— skipping the POST for ingest_id=%s stage=%s [wire=%s] "
                "rather than send one Lane 1's route will 401 "
                "unauthenticated. extracted_count=%s [%s] extracted_total="
                "%s [%s] detail=%s"
                " reason_code=%s reason=%s step=%s run_id=%s pin_digest=%s",
                ingest_id, stage, wire_stage,
                extracted_count, self.EXTRACTED_COUNT_UNIT,
                extracted_total, self.EXTRACTED_TOTAL_UNIT,
                detail,
                reason_code, reason, step, run_id, pin_digest,
            )
            return

        # The promotion payload's one doc-tools-owned field. Sent only when
        # it is in hand; the route accepts it as optional (Lane 1's packet),
        # so an older body still posts.
        if wire_stage == self._PROMOTION_FILING_WIRE_STAGE and extraction_ref is None:
            logger.warning(
                "ADR-0041 ingest status: posting wire stage %r with NO "
                "extraction_ref for ingest_id=%s. Lane 1 files a "
                "document_promotion task from this POST, and a promote on a "
                "task whose payload cannot name the extraction is refused "
                "422 promotion_payload_invalid — the row will sit at review. "
                "The caller should pass the versioned manifest key.",
                wire_stage, ingest_id,
            )

        body = {"stage": wire_stage}
        if extracted_count is not None:
            body["extracted_count"] = extracted_count
        if extracted_total is not None:
            body["extracted_total"] = extracted_total
        if extraction_ref is not None:
            body["extraction_ref"] = extraction_ref
        if detail is not None:
            body["detail"] = detail
        for _name, _value in (
            ("reason_code", reason_code), ("reason", reason),
            ("step", step), ("run_id", run_id), ("pin_digest", pin_digest),
        ):
            if _value is not None:
                body[_name] = _value

        base = os.getenv("IAGENT_GATEWAY_URL", _DEFAULT_GATEWAY_URL).rstrip("/")
        url = f"{base}/ingest/{ingest_id}/stage"

        try:
            response = httpx.post(
                url, json=body, headers=headers, timeout=_STAGE_POST_TIMEOUT_S
            )
        except Exception as exc:  # noqa: BLE001 — NON-FATAL, ALWAYS; see class docstring
            logger.warning(
                "ADR-0041 ingest status POST failed (non-fatal — a stage "
                "write must never fail an extraction): ingest_id=%s "
                "stage=%s [wire=%s] url=%s %s: %s. extracted_count=%s [%s] "
                "extracted_total=%s [%s] detail=%s reason_code=%s reason=%s "
                "step=%s run_id=%s pin_digest=%s",
                ingest_id, stage, wire_stage, url,
                type(exc).__name__, str(exc)[:200],
                extracted_count, self.EXTRACTED_COUNT_UNIT,
                extracted_total, self.EXTRACTED_TOTAL_UNIT,
                detail,
                reason_code, reason, step, run_id, pin_digest,
            )
            return

        if 200 <= response.status_code < 300:
            logger.info(
                "ADR-0041 ingest status posted: ingest_id=%s stage=%s "
                "[wire=%s] status=%s extracted_count=%s [%s] "
                "extracted_total=%s [%s] extraction_ref=%s detail=%s "
                "reason_code=%s reason=%s step=%s run_id=%s pin_digest=%s",
                ingest_id, stage, wire_stage, response.status_code,
                extracted_count, self.EXTRACTED_COUNT_UNIT,
                extracted_total, self.EXTRACTED_TOTAL_UNIT,
                extraction_ref, detail,
                reason_code, reason, step, run_id, pin_digest,
            )
        else:
            logger.warning(
                "ADR-0041 ingest status POST non-2xx (non-fatal — a stage "
                "write must never fail an extraction): ingest_id=%s "
                "stage=%s [wire=%s] url=%s status=%s body=%s. "
                "extracted_count=%s [%s] extracted_total=%s [%s] detail=%s "
                "reason_code=%s reason=%s step=%s run_id=%s pin_digest=%s",
                ingest_id, stage, wire_stage, url, response.status_code,
                response.text[:200],
                extracted_count, self.EXTRACTED_COUNT_UNIT,
                extracted_total, self.EXTRACTED_TOTAL_UNIT,
                detail,
                reason_code, reason, step, run_id, pin_digest,
            )


class JenaResource(ConfigurableResource):
    url: str 
    dataset: str
    username: str 
    password: str 

    def get_client(self):
        from .jena_client import JenaClient
        return JenaClient(url=self.url, dataset=self.dataset, username=self.username, password=self.password)

