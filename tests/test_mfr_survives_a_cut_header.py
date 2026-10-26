"""A CUT header pass must still write the document's own `mfr` — the regression test
the 90 s bound owes.

`da7c1ee` bounded `ExtractHeader` at 90 s with a refuse-never-retry contract: on a cut
the field is ABSENT and `needs_review` is True. **The never-retry half was reversed on
2026-10-24** by the architect's order -- a cancelled pass now gets ONE more attempt
before it is reported absent, see `tests/test_a_cancelled_header_retries_once.py` and
`test_a_cancelled_header_retries_exactly_once` below. The REFUSAL half stands, and this
file is still the seal on it: two cancels and the field is absent, review is forced, and
a filename still does not reach the identity triple. That refusal is only safe because
the text-layer arm runs anyway — `_DOCUMENT_WINS` is consulted from `refuse_unsourced_header_values`
even when the model returned NOTHING, so a healthy document that names its own
manufacturer does not lose `mfr` to a timeout.

Nothing proved that end to end. `tests/test_mfr_document_wins_eol36.py` exercises
`mfr_from_document` directly, and `tests/test_second_witness_wiring.py` drives the
plugin with a header that SUCCEEDED. This file drives the real `_extract_fulltext` with
a header pass that RAISES — which is what a cut looks like from inside the plugin,
since `_header_call_opts`' timeout surfaces as an exception — and pins both halves of
the bound's contract at once:

  * the document's `mfr` is written anyway, and sourced;
  * the cut forces review, and a FILENAME still does not reach the identity triple.

The fixture is the healthy control from `tests/test_doc_id_text_layer_arm.py`.
"""
from types import SimpleNamespace

import pytest

from doc_tools.plugins.sustainment import SustainmentPlugin
from doc_tools.utils import notice_identity

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


class _CutB:
    """The header pass times out. `_header_call_opts` bounds the call at 90 s and the
    cut arrives as an exception, which `_extract_fulltext` catches into `reasons` /
    `needs_review` and then falls back to `empty_header(doc_id)`."""

    def __init__(self):
        self.calls = 0

    def ExtractHeader(self, doc, system_instructions, baml_options=None):
        self.calls += 1
        raise TimeoutError("ExtractHeader: request timed out after 90000 ms")

    def __getattr__(self, name):
        raise AttributeError(name)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "file")
    monkeypatch.delenv("VISION_LLM_BASE_URL", raising=False)


@pytest.fixture()
def cut(monkeypatch):
    from doc_tools.baml_client import sync_client as sync_client_module
    fake = _CutB()
    monkeypatch.setattr(sync_client_module, "b", fake)
    els = _elements()
    plugin = SustainmentPlugin(domain_type="sustainment")
    nodes = plugin._extract_fulltext(" ".join(e["text"] for e in els),
                                     "TYC-PCN-24-210412", elements=els)
    return nodes[0].domain_augmentation, fake


def test_a_cancelled_header_retries_exactly_once(cut):
    """REVERSED 2026-10-24, on the architect's order. The argument this test carried --

        *"Refuse the field, never retry — the other half of the bound's contract. A
        retry would turn one 90 s cut into two and is exactly what the ruling
        forbade."*

    -- is kept here because the cost half of it is still true: a retry does turn one
    90 s cut into two, and `_CutB` cancels both times, so this fixture pays exactly
    that. What changed is the measurement on the other side of the trade. The one cancel
    in the 2026-10-25 corpus fire cost `onsemi_Generic_IPCN25300X` its `mfr` -- scored
    `absent`, the only non-passing field of sixteen -- on a page the model answers
    whenever it is asked, and the nine healthy calls in that same fire returned in
    19.1-55.0 s. So one cancel is not evidence the next attempt fails, and the field was
    being lost to recall rather than to the document. 90 s on one notice of ten buys it
    back.

    The bound is unchanged, and so is everything else this file pins: the second cancel
    still refuses.
    """
    _, fake = cut
    assert fake.calls == 2


def test_the_documents_own_mfr_is_written_despite_the_cut(cut):
    aug, _ = cut
    assert aug.notice.mfr == "TE Connectivity"


def test_the_written_mfr_is_sourced_not_merely_present(cut):
    """`_DOCUMENT_WINS` self-verifies through `provenance.resolve_value`, so a value
    that survives here is located in the document rather than asserted. The published
    carrier is the `header.mfr` REVIEW ITEM — the review dict has no top-level `mfr`
    key, so this item is where a consumer reads the value and its snippet."""
    aug, _ = cut
    items = [it for it in aug.review["review_items"]
             if it.get("field_path") == "header.mfr"]
    assert len(items) == 1, [it.get("field_path") for it in aug.review["review_items"]]
    assert items[0]["value"] == "TE Connectivity"
    assert items[0]["source_snippet"]


def test_the_record_says_which_arm_wrote_it(cut):
    """`review_reasons` is the only place a reader can see that the DOCUMENT supplied
    `mfr` because the header pass returned nothing."""
    aug, _ = cut
    recovered = [r for r in aug.review_reasons
                 if "mfr" in r and "document" in r.lower()]
    assert len(recovered) == 1, aug.review_reasons
    assert "TE Connectivity" in recovered[0]


def test_the_cut_forces_review_and_says_why(cut):
    aug, _ = cut
    assert aug.needs_review is True
    assert any("header" in r.lower() for r in aug.review_reasons)


def test_a_filename_still_does_not_reach_the_identity_triple(cut):
    """The drop key here IS a notice-number-shaped filename. On a cut it seeds
    `header_d["doc_id"]`, and `doc_id_origin` is None, so the identity claim must be
    None — mfr alone. Measured on fa231498 / 0096a523, two 606-byte PDFs named
    `PCN23-002.pdf` whose header pass produced nothing."""
    aug, _ = cut
    assert aug.stats["doc_id_arm"]["origin"] is None
    assert aug.review["doc_id_raw"] is None
    assert aug.stats["notice_identity"] == notice_identity.build_identity(
        "TE Connectivity", None, None)


def test_the_key_itself_is_still_populated_from_the_drop(cut):
    """A refusal upstream must not null the KEY: doc_id is the workflow id, the MinIO
    prefix, the graph IRI and the provenance index."""
    aug, _ = cut
    assert aug.notice.doc_id
    assert aug.review["doc_id"]
