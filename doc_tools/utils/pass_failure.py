"""Reason codes and bounded messages for a failure that reaches the REVIEW RECORD.

Ruling of 2026-11-18 (the architect, via Chris), for doc-tools and cortex both:

    *"A failure reason that reaches a user is a code and a bounded message. Raw
    prompts and raw model output stay in telemetry and never enter a record a
    person reads. doc-tools stops writing them into the review record; cortex
    does not render them if present."*

WHY THIS IS NOT A TRUNCATION PROBLEM, measured from the installed library
(`baml_py` 0.222.0, `baml_py/internal_monkeypatch.py`). Three of BAML's
exception classes put the whole call on their `__str__`:

    BamlValidationError.__str__        -> message=, raw_output=, prompt=
    BamlClientFinishReasonError.__str__-> message=, raw_output=, prompt=
    BamlClientHttpError.__str__        -> message=, status_code=, detailed_message=

`raw_output` is the model's reply verbatim and `prompt` is the RENDERED prompt,
which on this repo's paths contains **the document's own text**. So an
`str(exc)` written into `review.json` published the document and the reply into
a record a person reads, and a 400-character echo does not fix it: the envelope
puts `raw_output` first, so the first 400 characters are the reply.

Hence the rule this module implements: **the review record carries no exception
text at all.** It carries a code from `PASS_FAILURE_CODES`, a sentence written
here, and the exception's TYPE NAME -- a class name from a library or from this
repo, which is neither a prompt nor model output, and which is the one thing the
live cut actually carried (`str()` of the real abort is the bare string
`AbortError`).

Pure module: no Dagster, no network, no SDK, no BAML import. It classifies on
the exception's TYPE and on the presence of BAML's envelope ATTRIBUTES, never on
message text -- a classifier that read the message would re-introduce the
dependency on the text this module exists to keep out, and `looks_cancelled`'s
docstring already records that the live cut's message carried nothing to read.

A SIDE EFFECT WORTH THE NAME: the phrase is now deterministic. `str()` of a
validation error embeds the reply, which differs between fires on identical
input, so the old reason string was unstable across fires by construction. A
code plus a fixed sentence is byte-identical, which is what
`scripts/pcn_corpus_gate.py` compares when it looks for a declaration.
"""
from __future__ import annotations

from typing import Optional

#: Every code this module may return. A consumer may switch on these.
PASS_FAILURE_CODES: frozenset[str] = frozenset({
    # The call did not answer: our own AbortController reaching its ceiling, or
    # a cancel from outside. `sustainment.classify_header_cancel` tells those
    # two apart from elapsed-against-the-bound, and that verdict rides in
    # `stats["header_pass"]`, not here.
    "call_cancelled",
    # The model ANSWERED and the reply did not satisfy the schema. The null
    # `pub_date` of Order A was this code's shape: a required field the model
    # correctly left null, so BAML could not coerce the reply at all.
    "model_output_invalid",
    # The model stopped before it finished the reply (BAML's finish-reason
    # error: a length cap, a content filter, a stop sequence).
    "model_stopped_early",
    # The endpoint refused the call: an HTTP status, not a reply.
    "model_endpoint_refused",
    # Anything else raised inside the pass -- including a failure in OUR code,
    # which is why the sentence does not blame the model.
    "pass_failed",
})

_SENTENCES: dict[str, str] = {
    "call_cancelled": "the call was cancelled before it answered",
    "model_output_invalid": "the model answered and the reply did not satisfy the schema",
    "model_stopped_early": "the model stopped before it finished the reply",
    "model_endpoint_refused": "the model endpoint refused the call",
    "pass_failed": "the pass raised before it produced a result",
}

#: A type name is short in practice (`_AbortError`, `BamlValidationError`); the
#: clamp is there so a generated or dynamic class cannot make a reason long.
_MAX_TYPE = 64

#: The clamp on the whole phrase. Every sentence above is fixed-length, so this
#: can only ever bite on a pathological type name.
_MAX_PHRASE = 200

#: Telemetry keeps the raw text, by the ruling. It is still bounded, because a
#: rendered prompt is the size of a document and a log line is not the place to
#: carry a second copy of one.
_MAX_TELEMETRY = 4000


def _type_name(exc: object) -> str:
    try:
        return type(exc).__name__[:_MAX_TYPE] or "unknown"
    except Exception:  # noqa: BLE001 -- totality is the contract
        return "unknown"


def carries_model_text(exc: object) -> bool:
    """Does `exc` carry a rendered prompt or a raw reply on itself?

    The ATTRIBUTE test, not a name test: `BamlValidationError` and
    `BamlClientFinishReasonError` both set `.prompt` and `.raw_output` in
    `__init__`, and both put them on `__str__`. Any exception that answers True
    here must never have its text written into a record a person reads, and
    `ingest_failure.classify` consults this for the same reason.

    Total: never raises, including for an object whose attribute access raises.
    """
    for attr in ("prompt", "raw_output"):
        try:
            if getattr(exc, attr, None) is not None:
                return True
        except Exception:  # noqa: BLE001
            # An attribute that RAISES is not evidence of absence. Treat the
            # exception as carrying model text: the safe direction.
            return True
    return False


def _code_for(exc: object, cancelled: Optional[bool]) -> str:
    # The caller's cancel verdict wins where it has one. `looks_cancelled`
    # reads the message as a fallback and this module does not, so without
    # this the record could say `outcome: "cancelled"` beside a code that
    # disagreed with it.
    if cancelled:
        return "call_cancelled"
    name = _type_name(exc).lower()
    if "abort" in name or "cancel" in name or "timeout" in name:
        return "call_cancelled"
    # BEFORE the raw_output test: a finish-reason error carries `raw_output`
    # too, and "stopped early" is the more precise statement of it.
    if getattr(exc, "finish_reason", None) is not None or "finishreason" in name:
        return "model_stopped_early"
    if getattr(exc, "status_code", None) is not None or "httperror" in name:
        return "model_endpoint_refused"
    if getattr(exc, "raw_output", None) is not None or "validation" in name:
        return "model_output_invalid"
    return "pass_failed"


def classify_pass_failure(
    exc: object, *, cancelled: Optional[bool] = None
) -> tuple[str, str]:
    """Return `(reason_code, message)` for a failure entering the review record.

    `message` is written HERE and ends in the exception's type name. Neither the
    code nor the message contains any part of `str(exc)`.

    TOTAL: never raises, for any input -- including an object whose `__str__`,
    `__class__` or attribute access raises. Its callers are error boundaries,
    and a raise in one would mask the failure it is reporting.
    """
    try:
        code = _code_for(exc, cancelled)
        if code not in PASS_FAILURE_CODES:  # pragma: no cover -- defensive
            code = "pass_failed"
        phrase = "%s (%s)" % (_SENTENCES[code], _type_name(exc))
        return code, phrase[:_MAX_PHRASE]
    except Exception:  # noqa: BLE001 -- totality is the contract
        return "pass_failed", "%s (unknown)" % _SENTENCES["pass_failed"]


def reason_phrase(exc: object, *, cancelled: Optional[bool] = None) -> str:
    """`"<code> — <message>"`, the one spelling every review-record site uses.

    One composer so the code is always present in the text a person reads, and
    always in the same place -- the ruling asks for a code AND a message, so a
    site that printed only the sentence would be half-compliant.
    """
    code, message = classify_pass_failure(exc, cancelled=cancelled)
    return "%s — %s" % (code, message)


def telemetry_text(exc: object, *, limit: int = _MAX_TELEMETRY) -> str:
    """The raw text, for a LOG LINE only. Never for a record a person reads.

    For an exception carrying BAML's envelope this returns the model's own
    message and reply and deliberately OMITS `prompt`: the reply is what a
    diagnosis needs, while the prompt is reconstructible from the pin and the
    document and would put a second copy of the document in the log.

    Total: never raises.
    """
    try:
        name = _type_name(exc)
        if carries_model_text(exc):
            message = getattr(exc, "message", None)
            raw = getattr(exc, "raw_output", None)
            parts = [name]
            if message is not None:
                parts.append("message=%s" % message)
            if raw is not None:
                parts.append("raw_output=%s" % raw)
            parts.append("prompt=<omitted: carries the document text>")
            return " ".join(parts)[:limit]
        return ("%s: %s" % (name, exc))[:limit]
    except Exception:  # noqa: BLE001
        return "<telemetry unavailable>"
