"""A CANCELLED header pass is retried once, and the cancel's ORIGIN is on the record.

The architect's order of 2026-10-24, on the one cancel in the 2026-10-25 corpus fire:
*"Find what cancels it ... a client disconnect, a task-group cancel from a sibling
failure, a cancellation token shared with a stage that finished early. Log the cancel
origin, then make a cancelled header retry once before it is reported as absent."*

The premise in that order -- an *instant* cancel -- is the thing this file's subject
disproves, and the disproof is why the instrumentation here is shaped the way it is.
The cancel carries no time in the record: the plugin wrote `header pass failed:
AbortError` and nothing else, byte-identical on `onsemi_Generic_IPCN25300X` and on
24_0003, and `stats` held no header timing at all. The only timing available was by
SUBTRACTION from the BAML log of the fire -- the last timestamped line before the
cancelled notice is `03:34:15.694`, the cancel is `03:35:45.903`, a gap of **90.2 s**
against `HEADER_TIMEOUT_MS_DEFAULT = 90_000`. So that cancel was our own
`AbortController` reaching its ceiling, not a disconnect and not a sibling's cancel
propagating, and the nine healthy calls in the same fire returned in 19.1-55.0 s.

Hence two things, both tested here:

  * the plugin RECORDS elapsed, bound and a classified origin on every header pass, so
    the next cancel is diagnosed from `stats["header_pass"]` rather than from a log that
    only exists while a pod does. `early_cancel` is the verdict that would support the
    order's three hypotheses; `client_bound` is the verdict the measured case gets.
  * a cancelled attempt is retried ONCE. A pass that was answered badly is not.

What this file deliberately does NOT relax: a cancel on BOTH attempts still refuses the
field, still sets `needs_review`, and still writes the gate-visible `header pass failed`
declaration. See `tests/test_mfr_survives_a_cut_header.py` for the other half -- the
document's own `mfr` survives a cut regardless, which is what made the refusal safe in
the first place.
"""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from doc_tools.plugins.sustainment import (
    SustainmentPlugin,
    classify_header_cancel,
    header_bound_ms,
    looks_cancelled,
)

# The healthy control fixture, same page as `tests/test_mfr_survives_a_cut_header.py`
# and `tests/test_doc_id_text_layer_arm.py`: a document that names its own manufacturer
# and whose text layer measures healthy. A degraded fixture would gate the arms under
# test off and look green doing it.
_CONTROL_PARAGRAPHS = [
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
            for i, p in enumerate(_CONTROL_PARAGRAPHS)]


def _header():
    """A header the MODEL supplied. `revision`, `categories` and `summary` are the
    discriminators: they are not in `HEADER_SOURCED_FIELDS`, so no refusal can blank
    them, and `empty_header()` leaves them None / [] / "" -- so finding them written is
    proof the retry's RESULT reached the record, not merely that a second call was made.
    """
    return SimpleNamespace(
        doc_id="PCN-24-210412", doc_type="PCN", revision="B",
        pub_date=None, pub_date_source=None,
        mfr="TE Connectivity", mfr_source="TE Connectivity",
        categories=["site_transfer"], summary="A site transfer, qualification complete.",
        doc_level_ltb_date=None, doc_level_ltb_date_source=None,
    )


class _AbortError(Exception):
    """The live cut's exception, reproduced in the one way that matters.

    `str()` is the bare class name -- that is what the corpus fire recorded (`header
    pass failed: AbortError`), so the message carries no elapsed, no cause and not even
    the word "cancelled". A classifier that read the message would call this a plain
    failure.
    """

    def __str__(self):
        return "AbortError"


class _CancelsThenAnswers:
    """Cancelled on attempt 1, answers on attempt 2 -- the measured case's shape."""

    def __init__(self, cancels=1):
        self.calls = 0
        self.cancels = cancels

    def ExtractHeader(self, doc, system_instructions, baml_options=None):
        self.calls += 1
        if self.calls <= self.cancels:
            raise _AbortError()
        return _header()

    def __getattr__(self, name):
        raise AttributeError(name)


class _AnswersBadly:
    """Not a cancel: the pass RAN and came back unusable. Gets no second attempt."""

    def __init__(self):
        self.calls = 0

    def ExtractHeader(self, doc, system_instructions, baml_options=None):
        self.calls += 1
        raise ValueError("400 Bad Request: response did not match the schema")

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
    return nodes[0].domain_augmentation, fake


# --------------------------------------------------------------------------- #
# The retry
# --------------------------------------------------------------------------- #

def test_a_cancelled_first_attempt_is_retried_exactly_once(monkeypatch):
    aug, fake = _run(monkeypatch, _CancelsThenAnswers())
    assert fake.calls == 2
    assert aug.stats["header_pass"]["retried"] is True
    assert aug.stats["header_pass"]["outcome"] == "ok"
    assert aug.stats["header_pass"]["cut_then_recovered"] is True


def test_the_retrys_header_is_the_one_that_reaches_the_record(monkeypatch):
    """Not just "a second call happened" -- the second call's VALUES are written. On the
    old never-retry path these three are `empty_header()`'s None / [] / ""."""
    aug, _ = _run(monkeypatch, _CancelsThenAnswers())
    assert aug.notice.revision == "B"
    assert aug.notice.categories == ["site_transfer"]
    assert aug.notice.summary == "A site transfer, qualification complete."


def test_the_cancelled_attempt_is_itself_on_the_record(monkeypatch):
    """A recovered cut is still a cut. It cost a fire ~90 s and it has to be countable
    across fires, which is why attempt 1 survives in `attempts` with its own elapsed."""
    aug, _ = _run(monkeypatch, _CancelsThenAnswers())
    attempts = aug.stats["header_pass"]["attempts"]
    assert [a["outcome"] for a in attempts] == ["cancelled", "ok"]
    assert attempts[0]["error_type"] == "_AbortError"
    assert attempts[0]["n"] == 1 and attempts[1]["n"] == 2
    assert all("elapsed_ms" in a for a in attempts)


def test_an_answered_but_unusable_pass_is_not_retried(monkeypatch):
    """The order was about a CANCEL. A schema failure or a 400 tells us the next attempt
    would do the same thing, and retrying it would double the cost of every bad response
    in the corpus for nothing."""
    aug, fake = _run(monkeypatch, _AnswersBadly())
    assert fake.calls == 1
    assert aug.stats["header_pass"]["outcome"] == "failed"
    assert aug.stats["header_pass"]["origin"] == "error"
    assert aug.stats["header_pass"]["retried"] is False
    assert any("not a cancel, so not retried" in r for r in aug.review_reasons)


def test_a_cancel_on_both_attempts_still_refuses_and_still_declares(monkeypatch):
    """The half of `da7c1ee` that is NOT reversed: two cancels and the field is absent,
    `needs_review` is true, and the gate-visible declaration is written verbatim."""
    aug, fake = _run(monkeypatch, _CancelsThenAnswers(cancels=2))
    assert fake.calls == 2
    assert aug.needs_review is True
    assert aug.stats["header_pass"]["outcome"] == "cancelled"
    assert aug.stats["header_pass"]["retried"] is True
    assert any("header pass failed: AbortError" in r for r in aug.review_reasons)
    assert any("attempt 2 of 2" in r for r in aug.review_reasons)
    # And the document's own mfr still survives it -- the text-layer arm runs anyway.
    assert aug.notice.mfr == "TE Connectivity"


# --------------------------------------------------------------------------- #
# The gate must not read a RECOVERED cut as a header declaration
# --------------------------------------------------------------------------- #

def _gate():
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(
        "pcn_corpus_gate", scripts / "pcn_corpus_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_recovered_cut_claims_no_header_exemption(monkeypatch):
    """`pcn_corpus_gate.header_declaration_for_field_in_fire` matches
    `_HEADER_WIDE_DECLARATION_MARKERS` (and the per-field `header.<field> refused` /
    `region witness LOST` shapes) as SUBSTRINGS of `review_reasons`, and a declaration
    exempts header fields from correctness. A pass that was cut and then ANSWERED has no
    header problem, so its reason is phrased to match none of those -- asserted against
    the gate's own tuple rather than a copy of it, so adding a marker that catches this
    phrasing fails here, and through the predicate itself for the per-field shapes.
    """
    aug, _ = _run(monkeypatch, _CancelsThenAnswers())
    cut = [r for r in aug.review_reasons if "header pass cut" in r]
    assert len(cut) == 1, aug.review_reasons
    gate = _gate()
    markers = gate._HEADER_WIDE_DECLARATION_MARKERS
    assert not [m for m in markers if m in cut[0]]
    corpus = {n: {"N.pdf": {"needs_review": True, "review_reasons": [cut[0]]}}
              for n in (1, 2, 3)}
    for field in ("mfr", "doc_id", "pub_date", "doc_level_ltb_date"):
        assert not gate.header_declaration_for_field_in_all_fires(corpus, "N.pdf", field)
    assert not [r for r in aug.review_reasons if "header pass failed" in r]


def test_the_recovered_reason_names_the_bound_and_the_origin(monkeypatch):
    aug, _ = _run(monkeypatch, _CancelsThenAnswers())
    cut = [r for r in aug.review_reasons if "header pass cut" in r][0]
    assert "bound 90000 ms" in cut
    assert "cancel origin" in cut
    assert "the retry answered in" in cut


# --------------------------------------------------------------------------- #
# The classifier: the measurement that separates the architect's three hypotheses
# from our own ceiling
# --------------------------------------------------------------------------- #

def test_the_measured_cancel_classifies_as_our_own_bound():
    """The 2026-10-25 case, with its measured numbers: 90.2 s against a 90 000 ms bound.
    A client disconnect, a sibling task-group cancel and a shared cancellation token are
    all EARLY events -- none of them waits for our ceiling to arrive first."""
    assert classify_header_cancel(90_209, 90_000) == "client_bound"


def test_a_cancel_well_inside_the_bound_is_not_ours():
    """What the order's three hypotheses would actually look like: a cancel at 1.2 s on a
    90 s bound was raised by something else, and the elapsed beside it is the evidence."""
    assert classify_header_cancel(1_200, 90_000) == "early_cancel"


def test_the_boundary_is_nine_tenths_of_the_bound():
    """Deliberately not 1.0: the elapsed measured in the plugin starts BEFORE BAML's own
    clock (its stub: "the timeout will only start AFTER the object is passed to a BAML
    function"), so our figure is the bound plus setup and never less. The margin is for
    the other direction -- a cancel at 81 s with a 55 s healthy worst case is still
    ours."""
    assert classify_header_cancel(81_000, 90_000) == "client_bound"
    assert classify_header_cancel(80_999, 90_000) == "early_cancel"


def test_a_zero_bound_never_claims_the_cancel():
    """`HEADER_REQUEST_TIMEOUT_MS=0` is a misconfiguration, not a bound of zero. Without
    the guard every cancel under it would read as `client_bound` and the misconfiguration
    would be invisible."""
    assert classify_header_cancel(0, 0) == "early_cancel"


def test_the_cut_is_recognised_by_type_not_by_message():
    """The live `AbortError`'s `str()` is the bare class name, so the type is the test."""
    assert looks_cancelled(_AbortError()) is True
    assert looks_cancelled(TimeoutError("ExtractHeader: request timed out")) is True
    assert looks_cancelled(RuntimeError("AbortError")) is True  # the 24_0003 stand-in
    assert looks_cancelled(ValueError("400 Bad Request")) is False


def test_the_classifier_reads_the_same_bound_the_call_was_made_with(monkeypatch):
    """One reader, `header_bound_ms`, for `_header_call_opts` and for the record. A
    drift between them would silently classify every cancel as `early_cancel`."""
    assert header_bound_ms() == 90_000
    monkeypatch.setenv("HEADER_REQUEST_TIMEOUT_MS", "150000")
    assert header_bound_ms() == 150_000
    aug, _ = _run(monkeypatch, _CancelsThenAnswers())
    assert aug.stats["header_pass"]["bound_ms"] == 150_000


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
