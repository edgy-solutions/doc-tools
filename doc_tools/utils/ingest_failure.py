"""Structured failure reasons for the ADR-0041 ingest `failed` stage.

Pure module: no Dagster import, no network, no S3, and importable without the
SDK installed. The document parser's error boundary calls `classify()` to turn
the exception it is about to re-raise into a `(reason_code, reason)` pair that
rides on the `failed` stage POST, so Lane 1's ingest row says WHY, not only
`detail=str(e)`.

THE VOCABULARY IS DECLARED HERE, AND THAT IS A DOCUMENTED EXCEPTION. This
repo's standing doctrine (`IngestStatusResource.update()`) is "import the
vocabulary, never mirror it". Measured against `iagent_mesh.ingest`: it
exports `INGEST_STAGES`, `IngestStatus`, `ContentKindUnregistered`,
`_TERMINAL_STAGES` and `_DETAIL_REQUIRED_STAGES`, and nothing resembling
`REASON_CODES`. There is nothing to import, so `REASON_CODES` below is
declared locally. It MUST be replaced by an SDK import the moment the SDK
ships one.
"""
from __future__ import annotations

import os
import re
from typing import Optional

#: The reason codes a `failed` stage may carry. Each names its raise site.
REASON_CODES: frozenset[str] = frozenset({
    # The ADR-0041 kindless guard in document_parser.py ("carries no
    # domain_type ... AND no registered content_kind"). Named by the packet.
    "kind_unregistered",
    # The RuntimeError for a missing/unparseable sidecar manifest.
    "sidecar_unreadable",
    # The F3 guard: domain_type in ("pdf", "cad").
    "domain_is_a_format",
    # The guard rejecting a sha256 as a content kind.
    "content_kind_is_a_hash",
    # `canonical_ingest_id` refusing the id's shape.
    "ingest_id_malformed",
    # A failure inside the extraction body.
    "extraction_failed",
    # An extraction that COMPLETED but produced zero reviewable part rows, so
    # there is nothing for a steward to vet. Raised from semantic_assets.py,
    # where review.json's row count exists. RETRYABILITY IS LANE 1's QUEUE
    # PROPERTY: the deployed IngestStageUpdateRequest has no `retryable`
    # field, so this side can only NAME the code.
    "extraction_empty",
    # A store write failed (Neo4j cypher / Pass 2 roll-up, or Jena SPARQL).
    # Raised from semantic_assets.py, posted as the run's last act with the
    # failed store(s) named in `detail`. Must be listed: dagster_resources
    # coerces any code outside this set to `unexpected_error`.
    "graph_write",
    # Pass 2 link/roll-up failed (TrainingPlugin.execute_pass2_rollup raised).
    # Raised from semantic_assets.py as LinkWriteError, recorded apart from
    # graph_write so the two are told apart; graph_write wins if both occur.
    "link_write",
    # The watchdog (packet: `failed:timeout`). LANE 1 EMITS THIS, NOT US: see
    # RESERVED_TO_LANE_1. Kept here so it is RECOGNISED, never emitted.
    "timeout",
    # Total fallback.
    "unexpected_error",
})

#: Codes that are valid to RECOGNISE but that this lane must never emit.
#: Lane 1's watchdog owns `timeout` (600 s, INGEST_RECEIVED_TIMEOUT_SECONDS).
#: Their `timeout` is PROVISIONAL: a later `extracting`/`review`/`failed` from
#: us supersedes it, whereas every other failure is terminal and a POST off it
#: is 409 `backwards_move`. `classify()` therefore never returns it.
RESERVED_TO_LANE_1: frozenset[str] = frozenset({"timeout"})

#: What this lane may emit.
EMITTABLE_CODES: frozenset[str] = REASON_CODES - RESERVED_TO_LANE_1

#: Lane 1's wire rule for `reason_code`: anything else is 422
#: `invalid_reason_code`.
REASON_CODE_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_KEY_HASH_RE = re.compile(r"/([0-9a-f]{64})/")

#: The canonical ingest_id spelling. Mirrored rather than imported so this
#: module stays importable with nothing else loaded; `ingest_id.INGEST_ID_RE`
#: is the authority and a test asserts the two patterns agree.
_CANONICAL_INGEST_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

_MAX_ECHO = 400


def ingest_id_from_object_key(source_object_key: object) -> Optional[str]:
    r"""FALLBACK join key, for when the sidecar could not be read.

    Measured on a real drop: the sidecar's `ingest_id` equals `sha256:` + the
    64-hex segment of its own S3 key, and the sensor's s3_filter
    (`^ingress-user/pdf/[0-9a-f]{64}/[^/]+\.pdf$`) guarantees that segment
    exists. Returns `sha256:<hex>` or None. Total: never raises.
    """
    try:
        m = _KEY_HASH_RE.search(source_object_key)  # type: ignore[arg-type]
        return f"sha256:{m.group(1)}" if m else None
    except Exception:  # noqa: BLE001
        return None


def resolve_join_key(
    candidate: object, source_object_key: object
) -> Optional[str]:
    """The ingest_id to address Lane 1's row with, or None. Total.

    `candidate` is preferred ONLY when it is already canonical. A
    non-canonical candidate is not merely untidy, it is UNUSABLE as a join
    key: `IngestStatusResource.update` refuses a non-canonical ingest_id (one
    of its raising validations), so handing one through posts nothing at all.

    That is not hypothetical. `canonical_ingest_id()` raises *without*
    assigning, so after the ingest_id guard fails, `ingest_id` still holds the
    sidecar's malformed value — truthy, and therefore selected by a plain
    `ingest_id or <fallback>`. The POST would then be refused inside the
    resource and swallowed by the handler's never-mask-`e` wrapper, making
    `ingest_id_malformed` the one code in `EMITTABLE_CODES` that could never
    actually reach a row. Preferring a canonical value is what closes that.

    The fallback is not a substitute row, which would be the thing
    `canonical_ingest_id`'s docstring forbids: measured on a real drop, the
    sidecar's own `ingest_id` equals the path-derived value, so it names the
    SAME row the malformed value was trying to name.
    """
    try:
        if isinstance(candidate, str) and _CANONICAL_INGEST_ID_RE.match(
            candidate.strip()
        ):
            return candidate.strip()
    except Exception:  # noqa: BLE001
        pass
    return ingest_id_from_object_key(source_object_key)


def _registered_kinds() -> Optional[list[str]]:
    """Registered content kinds, derived live from KIND_MAPPING (sorted,
    deduped by `.kind`) -- never scraped from a message. None if unavailable."""
    try:
        from doc_tools.utils.content_kind import KIND_MAPPING

        return sorted({e.kind for e in KIND_MAPPING.values()})
    except Exception:  # noqa: BLE001 -- degrade to the raw message
        return None


def _is_sdk_kind_unregistered(exc: BaseException) -> bool:
    try:
        from iagent_mesh.ingest import ContentKindUnregistered
    except Exception:  # noqa: BLE001 -- a missing SDK must not break this module
        return False
    return isinstance(exc, ContentKindUnregistered)


def _code_for(exc: BaseException, msg: str) -> str:
    # KNOWN WEAKNESS: this is marker matching on message text. The guards in
    # document_parser.py raise bare ValueError/RuntimeError, so there is no
    # type to switch on. The correct long-term fix is typed exceptions at the
    # raise sites. Until then this classifier must be updated in LOCKSTEP if a
    # guard's message is reworded; tests/test_ingest_failure_reasons.py locks
    # each real message to its code so a reword fails CI rather than silently
    # degrading to `extraction_failed`.
    if "carries no " in msg and "registered content_kind" in msg:
        return "kind_unregistered"
    if "sidecar manifest missing or unparseable" in msg:
        return "sidecar_unreadable"
    if "is a file FORMAT" in msg:
        return "domain_is_a_format"
    if "is a sha256 hash, not a content kind" in msg:
        return "content_kind_is_a_hash"
    if _is_sdk_kind_unregistered(exc):
        return "kind_unregistered"
    if "ingest_id" in msg and any(
        m in msg for m in ("canonical", "sha256:", "not one of")
    ):
        return "ingest_id_malformed"
    return "extraction_failed"


def classify(exc: BaseException) -> tuple[str, str]:
    """Return `(reason_code, reason)` for `exc`.

    TOTAL: never raises, for any input, including None-ish values and an
    exception whose `__str__` itself raises. Its only caller is an error
    boundary, and a raise there would MASK the original exception.

    `reason` is self-contained: for `kind_unregistered` it carries the
    registered-kinds list, derived live from KIND_MAPPING rather than scraped
    from the message, so it holds even when the original message omitted it.
    """
    try:
        msg = str(exc)
        code = _code_for(exc, msg)
        echoed = msg[:_MAX_ECHO]
        if code == "kind_unregistered":
            kinds = _registered_kinds()
            if kinds is not None:
                return code, f"{echoed} Registered kinds: {kinds}"
        return code, echoed
    except Exception:  # noqa: BLE001 -- totality is the contract
        return "unexpected_error", "<classifier failed>"


def running_code_identity() -> Optional[str]:
    """First non-blank of DOC_TOOLS_IMAGE, DOC_TOOLS_VERSION, else None.

    Never invents a value. The wire field is named `pin_digest`, but in
    sandbox today `DOC_TOOLS_IMAGE` is unset in the deployment (measured:
    empty in the pod), so the value is the `doc-tools@<git-sha>` stamp from
    `DOC_TOOLS_VERSION` -- a git sha, NOT an image digest. A consumer must not
    parse it as a bare digest. Setting `DOC_TOOLS_IMAGE` in the chart is the
    fix that makes the field's name true.
    """
    for name in ("DOC_TOOLS_IMAGE", "DOC_TOOLS_VERSION"):
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None
