"""No raw prompt and no raw model reply reaches a record a person reads.

RULING of 2026-11-18 (the architect, via Chris), for doc-tools and cortex both:

    *"A failure reason that reaches a user is a code and a bounded message. Raw
    prompts and raw model output stay in telemetry and never enter a record a
    person reads. doc-tools stops writing them into the review record; cortex
    does not render them if present."*

THE MECHANISM, measured from the installed `baml_py` 0.222.0
(`baml_py/internal_monkeypatch.py`): `BamlValidationError.__init__` takes
`(prompt, message, raw_output, detailed_message)` and its `__str__` returns

    BamlValidationError(message=..., raw_output=..., prompt=...)

so `str(exc)` is the model's reply AND the rendered prompt -- and on this
repo's paths the rendered prompt contains the document's own text. The plugin
wrote `str(e)` into `review_reasons`, into the doc-level banner
`doc_review_reasons`, and into `stats["header_pass"]["attempts"][*]["error"]`,
and `semantic_assets.py` copies `review_reasons` and `stats` onto `review.json`.
So a notice whose header pass raised a validation error published its own text
and the model's reply into the record a steward opens.

`test_the_leak_this_file_closes_was_real` asserts the FIRST half of that -- the
exception really does carry both -- because a regression test for a leak that
the library no longer produces would pass for the wrong reason.

Truncation is not the fix: the envelope puts `raw_output` first, so the first
400 characters of it are the reply. The fix is that no exception text is written
at all; the record carries a code from `PASS_FAILURE_CODES`, a sentence from
`pass_failure.py`, and the exception's type name.

What this file deliberately does NOT relax: the gate-visible declaration. The
`header pass failed` prefix (`scripts/pcn_corpus_gate.py`'s
`_HEADER_DECLARATION_MARKERS`), the `parts pass failed` marker and the
`PARTS MAY BE MISSING` banner are all asserted still present, because a
declaration that stopped matching would silently change what the corpus gate
exempts.
"""
import json
from types import SimpleNamespace

import pytest

from doc_tools.plugins.sustainment import SustainmentPlugin
from doc_tools.utils.pass_failure import (
    PASS_FAILURE_CODES,
    carries_model_text,
    classify_pass_failure,
    reason_phrase,
    telemetry_text,
)

# Two sentinels that could only have come from the exception. `DOC_SENTINEL`
# stands for the document text a rendered prompt carries; `REPLY_SENTINEL` for
# the model's reply. Neither appears in the fixture below, so finding either in
# a record is proof of an echo and not of extraction.
DOC_SENTINEL = "ZZQQ-DOCUMENT-TEXT-SENTINEL-77"
REPLY_SENTINEL = "ZZQQ-MODEL-REPLY-SENTINEL-88"


# --------------------------------------------------------------------------- #
# The fixture document: healthy, so no arm is gated off by a degraded text
# layer. Same shape as tests/test_a_cancelled_header_retries_once.py.
# --------------------------------------------------------------------------- #
_PARAGRAPHS = [
    "Product Change Notification",
    "TE Connectivity",
    "This notification informs customers that the identified parts are transitioning to "
    "a new manufacturing site. The qualification testing is complete and the "
    "certification report is available on request.",
    "Customers with further questions about this notification should contact their TE "
    "Connectivity field sales engineer, who will gather the information and coordinate "
    "the transition with the operations team.",
    "There is no change to the form, fit or function of the affected parts. The "
    "estimated date of the first shipment from the new location is stated in the "
    "attached schedule, together with the last time buy instructions.",
]


def _el(text, etype="NarrativeText"):
    return {"type": etype, "text": text,
            "metadata": {"page_number": 1,
                         "coordinates": {"points": [[0, 0], [100, 0], [100, 20], [0, 20]],
                                         "layout_width": 612, "layout_height": 792}}}


def _elements():
    return [_el(p, etype="Title" if i < 2 else "NarrativeText")
            for i, p in enumerate(_PARAGRAPHS)]


def _baml_validation_error():
    """The real class, constructed the way BAML constructs it.

    Not a stand-in: the point of the test is that THIS library's `__str__` is
    the leak, so a synthetic class with the same attributes would be testing
    this file's own assumption instead of the dependency.
    """
    from baml_py.errors import BamlValidationError

    return BamlValidationError(
        # prompt -- what the model was sent, which is the document
        f"Extract the header from the following notice.\n\n{DOC_SENTINEL}\n",
        # message -- BAML's own parser complaint
        "Failed to coerce value: <root>: Missing required field: pub_date",
        # raw_output -- what the model replied
        f'{{"doc_id": "{REPLY_SENTINEL}", "pub_date": null}}',
        # detailed_message
        "",
    )


class _HeaderRaisesValidation:
    def __init__(self):
        self.calls = 0

    def ExtractHeader(self, doc, system_instructions, baml_options=None):
        self.calls += 1
        raise _baml_validation_error()

    def __getattr__(self, name):
        raise AttributeError(name)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "file")
    monkeypatch.delenv("VISION_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("HEADER_REQUEST_TIMEOUT_MS", raising=False)


def _run(monkeypatch, fake):
    from doc_tools.baml_client import sync_client as sync_client_module
    monkeypatch.setattr(sync_client_module, "b", fake)
    els = _elements()
    plugin = SustainmentPlugin(domain_type="sustainment")
    nodes = plugin._extract_fulltext(" ".join(e["text"] for e in els),
                                     "TYC-PCN-24-210412", elements=els)
    return nodes[0].domain_augmentation


def _review_record(aug):
    """Everything `semantic_assets.py` copies onto review.json, as one string.

    The assertion has to cover the WHOLE record rather than the one list the
    defect was reported against: the same `str(e)` reached the banner and
    `stats`, and `review_payload` is built by copying `review`, `review_reasons`
    and `stats` wholesale (`semantic_assets.py`, the review.json write), so the
    faithful test is over the serialized payload.
    """
    payload = dict(getattr(aug, "review", {}) or {})
    payload["review_reasons"] = list(getattr(aug, "review_reasons", []) or [])
    payload["stats"] = dict(getattr(aug, "stats", {}) or {})
    return json.dumps(payload, default=str)


# --------------------------------------------------------------------------- #
# The leak was real
# --------------------------------------------------------------------------- #

def test_the_leak_this_file_closes_was_real():
    """`str()` of the dependency's exception carries the prompt and the reply.

    If a future `baml_py` stops putting them on `__str__`, this test fails and
    the rest of the file stops being a regression test -- which is the correct
    moment to re-read the ruling against the new shape, not to delete the test.
    """
    exc = _baml_validation_error()
    text = str(exc)
    assert DOC_SENTINEL in text, "the rendered prompt is on __str__"
    assert REPLY_SENTINEL in text, "the model's reply is on __str__"
    # And truncation is no defence: the reply comes before the prompt, so a
    # bounded echo still publishes model output.
    assert REPLY_SENTINEL in text[:400]
    assert carries_model_text(exc) is True


# --------------------------------------------------------------------------- #
# The review record
# --------------------------------------------------------------------------- #

def test_no_sentinel_reaches_the_review_record(monkeypatch):
    aug = _run(monkeypatch, _HeaderRaisesValidation())
    record = _review_record(aug)
    assert DOC_SENTINEL not in record
    assert REPLY_SENTINEL not in record
    # The BAML envelope's own field names are a second tell: if any part of the
    # exception's text were echoed, one of these would ride along with it.
    assert "raw_output" not in record
    assert "BamlValidationError(" not in record


def test_the_record_carries_a_code_and_a_bounded_message(monkeypatch):
    """The ruling asks for both. A sentence with no code is half-compliant."""
    aug = _run(monkeypatch, _HeaderRaisesValidation())
    failed = [r for r in aug.review_reasons if "header pass failed" in r]
    assert failed, "the declaration must still be written"
    assert "model_output_invalid" in failed[0]
    assert "the model answered and the reply did not satisfy the schema" in failed[0]
    # The type name is kept: a class name is neither a prompt nor model output,
    # and it is the only thing the live cut's `str()` actually carried.
    assert "BamlValidationError" in failed[0]


def test_the_attempt_record_names_the_code_and_keeps_no_error_text(monkeypatch):
    aug = _run(monkeypatch, _HeaderRaisesValidation())
    attempts = aug.stats["header_pass"]["attempts"]
    assert len(attempts) == 1, "a schema failure is not a cancel, so it is not retried"
    a = attempts[0]
    assert a["reason_code"] == "model_output_invalid"
    assert a["error_type"] == "BamlValidationError"
    assert "error" not in a, "the raw echo key is gone, not merely shortened"


def test_the_doc_level_banner_is_a_code_too(monkeypatch):
    aug = _run(monkeypatch, _HeaderRaisesValidation())
    flags = [f for f in aug.review["doc_review_reasons"]
             if "header extraction failed" in f]
    assert flags, "the reviewer must still be told the header died"
    assert "model_output_invalid" in flags[0]
    assert DOC_SENTINEL not in flags[0] and REPLY_SENTINEL not in flags[0]


def test_the_gate_visible_declaration_still_matches(monkeypatch):
    """The corpus gate reads `header pass failed` as a SUBSTRING of a
    review_reason to see that the product declared a header problem. The prefix
    is unchanged by this fix, and that is load-bearing: a declaration that
    stopped matching would change what the gate exempts without any gate change.

    The markers are imported FROM THE INSTRUMENT rather than restated here, so
    this assertion cannot drift from what the gate actually matches.
    """
    import importlib.util
    import sys
    from pathlib import Path

    scripts = Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(
        "pcn_corpus_gate", scripts / "pcn_corpus_gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)

    aug = _run(monkeypatch, _HeaderRaisesValidation())
    assert any(any(m in r for m in gate._HEADER_WIDE_DECLARATION_MARKERS)
               for r in aug.review_reasons)


def test_the_header_still_degrades_the_way_it_did(monkeypatch):
    """This PR changes the TEXT of a failure, not the behaviour behind it: the
    document's own `mfr` still survives, and the notice is still flagged."""
    aug = _run(monkeypatch, _HeaderRaisesValidation())
    assert aug.needs_review is True
    assert aug.notice.mfr == "TE Connectivity"


# --------------------------------------------------------------------------- #
# The classifier
# --------------------------------------------------------------------------- #

class _Abort(Exception):
    def __str__(self):
        return "AbortError"


class _Hostile(Exception):
    """An exception that fights back: `__str__` raises and attributes raise.

    The classifier's callers are error boundaries, so a raise inside one would
    mask the failure being reported.
    """

    def __str__(self):
        raise RuntimeError("no")

    @property
    def prompt(self):
        raise RuntimeError("no")


@pytest.mark.parametrize("exc,expected", [
    (_Abort(), "call_cancelled"),
    (TimeoutError("timed out"), "call_cancelled"),
    (_baml_validation_error(), "model_output_invalid"),
    (ValueError("anything at all"), "pass_failed"),
    (KeyError("rows"), "pass_failed"),
])
def test_classify_codes(exc, expected):
    code, message = classify_pass_failure(exc)
    assert code == expected
    assert code in PASS_FAILURE_CODES
    assert len(message) <= 200


def test_a_caller_with_a_cancel_verdict_wins():
    """`looks_cancelled` reads the message as a fallback and `pass_failure` does
    not, so without the override the record could say `outcome: cancelled`
    beside a code that disagreed."""
    exc = ValueError("the operation was cancelled")
    assert classify_pass_failure(exc)[0] == "pass_failed"
    assert classify_pass_failure(exc, cancelled=True)[0] == "call_cancelled"


def test_a_finish_reason_error_is_not_called_invalid_output():
    """It carries `raw_output` too, so the order of the tests matters."""
    from baml_py.errors import BamlClientFinishReasonError

    exc = BamlClientFinishReasonError(
        f"prompt {DOC_SENTINEL}", "stopped", f"partial {REPLY_SENTINEL}", "length", "")
    code, message = classify_pass_failure(exc)
    assert code == "model_stopped_early"
    assert DOC_SENTINEL not in message and REPLY_SENTINEL not in message


def test_an_http_error_is_a_refusal():
    from baml_py.errors import BamlClientHttpError

    exc = BamlClientHttpError("HeaderBounded", "rate limited", 429, "retry later")
    assert classify_pass_failure(exc)[0] == "model_endpoint_refused"


def test_the_classifier_is_total():
    code, message = classify_pass_failure(_Hostile())
    assert code in PASS_FAILURE_CODES
    assert message


def test_the_phrase_is_deterministic_across_two_different_replies():
    """A side effect worth a test: `str(e)` embedded the reply, which differs
    between fires on identical input, so the old reason string was unstable by
    construction. The gate compares these strings across three fires."""
    from baml_py.errors import BamlValidationError

    a = BamlValidationError("p", "m", '{"doc_id": "A"}', "")
    b = BamlValidationError("p", "m", '{"doc_id": "B-and-longer"}', "")
    assert reason_phrase(a) == reason_phrase(b)
    assert str(a) != str(b), "the raw texts really do differ"


def test_no_code_or_phrase_ever_contains_exception_text():
    exc = _baml_validation_error()
    code, message = classify_pass_failure(exc)
    phrase = reason_phrase(exc)
    for text in (code, message, phrase):
        assert DOC_SENTINEL not in text
        assert REPLY_SENTINEL not in text
        assert "Missing required field" not in text


# --------------------------------------------------------------------------- #
# Telemetry keeps what the record gives up
# --------------------------------------------------------------------------- #

def test_telemetry_keeps_the_reply_and_omits_the_prompt():
    """The ruling puts the raw text in telemetry, so it has to still be there --
    this fix must not be a net loss of diagnosis. The prompt is omitted on
    purpose: it is reconstructible from the pin and the document, and a log line
    is not the place for a second copy of a document."""
    text = telemetry_text(_baml_validation_error())
    assert REPLY_SENTINEL in text, "the reply is the diagnostic"
    assert "Missing required field: pub_date" in text
    assert DOC_SENTINEL not in text
    assert "prompt=<omitted" in text


def test_telemetry_echoes_an_ordinary_exception_whole():
    assert "boom" in telemetry_text(ValueError("boom"))


def test_telemetry_is_bounded():
    big = ValueError("x" * 10_000)
    assert len(telemetry_text(big)) <= 4000


def test_telemetry_is_total():
    assert telemetry_text(_Hostile())


# --------------------------------------------------------------------------- #
# The ingest row, which a person also reads
# --------------------------------------------------------------------------- #

def test_the_ingest_rows_reason_does_not_echo_a_baml_envelope():
    """`ingest_failure.classify` bounds its echo to 400 characters, which is no
    defence against this shape: the envelope puts `raw_output` first. An
    exception carrying the envelope is therefore not echoed at all."""
    from doc_tools.utils.ingest_failure import classify

    code, reason = classify(_baml_validation_error())
    assert code == "extraction_failed"
    assert DOC_SENTINEL not in reason and REPLY_SENTINEL not in reason
    assert "model_output_invalid" not in code  # the ingest vocabulary is its own
    assert "did not satisfy the schema" in reason


def test_the_ingest_row_still_echoes_our_own_guard_messages():
    """The echo exists to carry OUR guard text, which is written in this repo and
    is the thing the row exists to say. Only the model-text case changed."""
    from doc_tools.utils.ingest_failure import classify

    code, reason = classify(ValueError(
        "sidecar manifest missing or unparseable for ingress-user/pdf/x/y.pdf"))
    assert code == "sidecar_unreadable"
    assert "sidecar manifest missing or unparseable" in reason
