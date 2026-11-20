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

# Equally pure, and the reason the import is safe here: no Dagster, no network,
# no SDK, no BAML. It owns the "what may a person read" question for both the
# ingest row and the review record, so the two cannot drift apart.
from doc_tools.utils.pass_failure import carries_model_text, classify_pass_failure

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
    # A per-chunk `plugin.augment` raised, so that chunk contributed NO domain
    # nodes -- for training, a slide with no TEACHES edges, which is
    # indistinguishable from a slide that teaches nothing. Measured by lane tr
    # at steps d+e: 2 of 20 decks, both BamlValidationError "Missing required
    # field: summary", and both runs reported SUCCESS. Raised from
    # semantic_assets.py as AugmentationError, posted as the run's last act.
    "concept_parse",
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

#: What a `failed` stage's person-read fields may carry, in characters.
#: Set by the architect's order of 2026-11-19 (night), and the number is not
#: new here: `pass_failure._MAX_PHRASE` is already 160 and owns the same
#: question for the review record. A test asserts the two agree, because two
#: numbers for "what may a person read" is how they drift apart. It replaces a
#: 400-character echo that `kind_unregistered` then appended a 191-character
#: list to, so the field this bound governs could reach ~600.
_MAX_REASON = 160

#: What is cut is SHOWN as cut. A silently truncated message reads as whole,
#: and a reader cannot tell a short message from a shortened one.
_TRUNCATION_MARK = "..."


def _clamp(text: object, budget: int = _MAX_REASON) -> str:
    """`text` as ONE line of at most `budget` characters, cut marked. Total.

    Newlines are folded out rather than carried: the destination is one cell of
    an ingest row, and a message that wraps there is read as several facts.
    """
    try:
        one_line = " ".join(str(text).split())
    except Exception:  # noqa: BLE001 -- an exception whose __str__ raises
        return "<unprintable>"
    if len(one_line) <= budget:
        return one_line
    keep = budget - len(_TRUNCATION_MARK)
    return one_line[:keep] + _TRUNCATION_MARK if keep > 0 else one_line[:budget]


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

    `reason` is BOUNDED at `_MAX_REASON` characters, on one line, and what is
    cut is marked. For `kind_unregistered` it carries the *number* of
    registered kinds, counted live from KIND_MAPPING rather than scraped from
    the message, so the count holds even when the original message omitted the
    list. It does NOT carry the names: see the comment at that branch.
    """
    try:
        # RULING 2026-11-18: "raw prompts and raw model output ... never enter a
        # record a person reads". Lane 1's ingest row IS read by a person, and
        # this echo is bounded but not safe: `str()` of a BAML validation or
        # finish-reason error puts `raw_output=` BEFORE `prompt=`, so the first
        # `_MAX_REASON` characters are the model's reply, and the rest is the
        # rendered prompt -- which carries the document's own text. Truncation
        # cannot fix that shape, so an exception that carries the envelope is
        # not echoed at all: it reports a code and this module's own sentence.
        #
        # Every other raise on this path is one of OUR guards, whose message is
        # written in this repo and is the thing the row exists to carry, so the
        # echo below is unchanged for them.
        if carries_model_text(exc):
            code = _code_for(exc, "")
            _, phrase = classify_pass_failure(exc)
            return code, _clamp(phrase)
        msg = str(exc)
        # CLASSIFY BEFORE BOUNDING. `_code_for` is marker matching on message
        # text, and a marker can sit past the bound -- the ingest_id markers
        # do, on a real key. Bounding first would silently demote those
        # failures to `extraction_failed`.
        code = _code_for(exc, msg)
        if code == "kind_unregistered":
            kinds = _registered_kinds()
            if kinds is not None:
                # THE LIST NO LONGER FITS, and that is a loss, recorded as
                # F-25. Fourteen kinds render to 191 characters on their own,
                # past the whole bound, so under a 160-character field there is
                # no arrangement that carries them. A *truncated* list is the
                # one thing not to emit: it reads as complete, so a reader
                # cannot tell a kind that is absent from one that was cut off,
                # and "your kind is not registered" is exactly the question
                # this message exists to answer. The count is true at any
                # length; the names stay in KIND_MAPPING.
                suffix = f" Registered kinds: {len(kinds)} (names omitted to fit)."
                return code, _clamp(msg, _MAX_REASON - len(suffix)) + suffix
        return code, _clamp(msg)
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
