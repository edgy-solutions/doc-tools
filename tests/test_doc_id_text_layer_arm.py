"""Phase B of item 1 (2026-10-20 ruling): `doc_id` has a TEXT-LAYER-PRIMARY arm.

`doc_id_from_document` (phase A) reads the notice number the document prints. These tests
drive the real `_extract_fulltext` wiring: precedence (document, then model, then the
pipeline key), the degraded-layer gate, the disagreement reason, and the identity triple
reading `doc_id_origin`.

AMENDED 2026-10-24 by the architect's header identity precedence ruling. Two tests here
asserted that a doc_id disagreement, and a model-filled doc_id, must NOT force review --
because `needs_review` is a corpus-gate EXEMPTION. The ruling reverses both (clauses 1
and 2) and accepts that cost. The reversal is written into those two tests rather than
edited out of them. The ruling's four fields together are sealed in
tests/test_header_identity_precedence.py.

Fixture copied from tests/test_second_witness_wiring.py (same reasoning as that file).
"""
from types import SimpleNamespace

import pytest

from doc_tools.plugins.sustainment import SustainmentPlugin
from doc_tools.utils import notice_identity
from doc_tools.utils import sustainment_header_trust as header_trust
from doc_tools.utils import sustainment_normalize as norm

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

PRINTED = "PCN-24-210412"


def _el(text, etype="NarrativeText"):
    return {"type": etype, "text": text,
            "metadata": {"page_number": 1,
                         "coordinates": {"points": [[0, 0], [100, 0], [100, 20], [0, 20]],
                                         "layout_width": 612, "layout_height": 792}}}


def _elements(healthy=True, printed=None):
    paras = _CONTROL_PARAGRAPHS if healthy else [
        p.replace("ti", "") for p in _CONTROL_PARAGRAPHS]
    els = [_el(p, etype="Title" if i < 2 else "NarrativeText")
           for i, p in enumerate(paras)]
    if printed:
        els.append(_el(f"Product Change Notification: {printed}"))
    return els


def _text(els):
    return " ".join(e["text"] for e in els)


class _FakeB:
    def __init__(self, header):
        self.header = header

    def ExtractHeader(self, doc, system_instructions, baml_options=None):
        return self.header


def _header(doc_id):
    return SimpleNamespace(
        doc_id=doc_id, doc_type="PCN", revision=None,
        pub_date=None, pub_date_source=None,
        mfr="TE Connectivity", mfr_source="TE Connectivity", categories=[], summary=None,
        doc_level_ltb_date=None, doc_level_ltb_date_source=None,
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "file")
    monkeypatch.delenv("VISION_LLM_BASE_URL", raising=False)


def _run(monkeypatch, model_doc_id, healthy=True, printed=None):
    from doc_tools.baml_client import sync_client as sync_client_module
    monkeypatch.setattr(sync_client_module, "b", _FakeB(_header(model_doc_id)))
    els = _elements(healthy=healthy, printed=printed)
    plugin = SustainmentPlugin(domain_type="sustainment")
    nodes = plugin._extract_fulltext(_text(els), "doc-1", elements=els)
    return nodes[0].domain_augmentation


def _doc_id_reasons(aug):
    return [r for r in aug.review_reasons if "doc_id" in r]


def test_document_yields_document_wins(monkeypatch):
    aug = _run(monkeypatch, None, printed=PRINTED)
    arm = aug.stats["doc_id_arm"]
    assert arm["origin"] == "document"
    assert arm["document_value"] == PRINTED
    assert aug.notice.doc_id == norm.normalize_doc_id(PRINTED)
    # The PUBLISHED payload, not just the internal dict: `review["doc_id_raw"]` read
    # `doc_id_extracted` until 2026-10-20, which would have displayed the model's
    # reading while routing on the document's.
    assert aug.review["doc_id_raw"] == PRINTED


def test_disagreement_document_wins_reports_AND_forces_review(monkeypatch):
    """REVERSED by the architect's precedence ruling of 2026-10-24, clause 1: a
    disagreement "keeps the text-layer value and sets `needs_review` with both values in
    the reason".

    This test asserted the opposite until that ruling, and the reason it gave is still
    true rather than mistaken: `needs_review=True` is consumed by the corpus gate as an
    EXEMPTION, so a flag raised on an UNSCORED field can exempt a notice whose SCORED
    fields are wrong. The ruling accepts that cost in exchange for a human seeing the
    two readings that disagreed. Recorded here, and not quietly reversed, because the
    next person to read a flagged notice beside a green gate will need to know which of
    the two it was.
    """
    aug = _run(monkeypatch, "PCN-99-000001", printed=PRINTED)
    arm = aug.stats["doc_id_arm"]
    assert arm["origin"] == "document"
    assert arm["agrees"] is False
    assert aug.notice.doc_id == norm.normalize_doc_id(PRINTED)
    reasons = _doc_id_reasons(aug)
    assert len(reasons) == 1
    assert PRINTED in reasons[0] and "PCN-99-000001" in reasons[0]
    # The display field follows the claim that WON. A payload showing the model's
    # number beside a doc_id keyed on the document's is the exact split this reads for.
    assert aug.review["doc_id_raw"] == PRINTED
    # Clause 1. The healthy fixture needs no review otherwise, so the True came from
    # this block -- the baseline proves it rather than the comment asserting it.
    baseline = _run(monkeypatch, None, printed=PRINTED)
    assert baseline.needs_review is False
    assert aug.needs_review is True


def test_document_silent_model_yields_origin_model_AND_forces_review(monkeypatch):
    """Clause 2 of the same ruling: "the model pass fills only what the text layer did
    not yield, and every model-filled field marks needs_review=true". The value is
    still WRITTEN -- clause 2 flags, it does not blank."""
    aug = _run(monkeypatch, "PCN-99-000001")
    arm = aug.stats["doc_id_arm"]
    assert arm["origin"] == "model"
    assert arm["document_value"] is None
    assert arm["agrees"] is None
    assert aug.notice.doc_id == norm.normalize_doc_id("PCN-99-000001")
    assert aug.review["doc_id_raw"] == "PCN-99-000001"
    reasons = _doc_id_reasons(aug)
    assert len(reasons) == 1
    assert "filled by the header pass" in reasons[0]
    assert aug.needs_review is True


def test_neither_yields_key_only_and_no_identity_claim(monkeypatch):
    aug = _run(monkeypatch, None)
    arm = aug.stats["doc_id_arm"]
    assert arm["origin"] is None
    assert aug.notice.doc_id == norm.normalize_doc_id("doc-1")
    assert aug.review["doc_id_raw"] is None
    assert aug.stats["notice_identity"] == notice_identity.build_identity(
        "TE Connectivity", None, None)


def test_degraded_layer_gates_the_arm_off(monkeypatch):
    def _boom(index):
        raise AssertionError("doc_id_from_document must not run on a degraded layer")
    monkeypatch.setattr(header_trust, "doc_id_from_document", _boom)
    aug = _run(monkeypatch, "PCN-99-000001", healthy=False, printed=PRINTED)
    assert aug.stats["text_layer_degraded"] is True
    arm = aug.stats["doc_id_arm"]
    assert arm["gated_off_degraded"] is True
    assert arm["origin"] == "model"
    assert arm["document_value"] is None


def test_agreement_is_true_and_silent(monkeypatch):
    aug = _run(monkeypatch, PRINTED, printed=PRINTED)
    arm = aug.stats["doc_id_arm"]
    assert arm["origin"] == "document"
    assert arm["agrees"] is True
    assert not _doc_id_reasons(aug)
