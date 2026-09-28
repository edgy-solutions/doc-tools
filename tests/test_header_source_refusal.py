"""A header value that is not verbatim in the document must be REFUSED, not flagged.

`ExtractHeader` fabricated `mfr` = "TT Electronics" against a SEMELAB document — a value
that is nowhere in the PDF under any reading. Before this change, an unsourced/hallucinated
header value survived into `review.json` as a review ITEM with `needs_review=True`: still
present, still readable as "probably right, just double-check". That is the wrong shape for
a value the document flatly does not contain — it should not be written at all, the same
identity standard the parts side already holds MPNs to.

Pure, no LLM: builds a small positioned index by hand (the same element shape
`provenance.build_positioned_index` produces — see `tests/test_sustainment_extraction.py`)
and exercises `refuse_unsourced_header_values` / `locate_header_source` directly.
"""
from doc_tools.utils import provenance
from doc_tools.utils import sustainment_merge as merge
from doc_tools.utils.sustainment_header_trust import (
    HEADER_SOURCED_FIELDS,
    locate_header_source,
    refuse_unsourced_header_values,
)


def _el(text, page=1, html=""):
    return {"type": "NarrativeText", "text": text,
            "metadata": {"page_number": page,
                         "coordinates": {"points": [[0, 0], [100, 0], [100, 20], [0, 20]],
                                         "layout_width": 612, "layout_height": 792},
                         "text_as_html": html}}


def _index():
    return provenance.build_positioned_index([
        _el("This notice is issued by SEMELAB PLC regarding discontinuance."),
        _el("Genuine Manufacturer Corp is the issuing entity."),
        _el("Pub Date: 05–Dec 2023"),  # en-dash + NBSP, not an ASCII hyphen/space
    ])


# --------------------------------------------------------------------------- #
# refuse_unsourced_header_values
# --------------------------------------------------------------------------- #
def test_fabricated_value_with_no_source_is_refused_and_named_in_the_reason():
    """The exact live defect: mfr with no source snippet, and the value itself is nowhere
    in the document (SEMELAB is in the document; TT Electronics is not)."""
    header_d = {"mfr": "TT Electronics", "mfr_source": None,
                "pub_date": None, "pub_date_source": None,
                "doc_level_ltb_date": None, "doc_level_ltb_date_source": None}
    reasons = refuse_unsourced_header_values(header_d, _index())

    assert header_d["mfr"] == "", "a fabricated value must be DROPPED, not merely flagged"
    assert header_d["mfr_source"] is None
    assert len(reasons) == 1, f"expected exactly one refusal reason, got {reasons!r}"
    assert "header.mfr" in reasons[0], "the reason must name the refused field"
    assert "TT Electronics" in reasons[0], \
        "the dropped value must appear in the reason or the record is no longer lossless"


def test_genuine_value_with_verbatim_source_is_untouched():
    header_d = {"mfr": "SEMELAB PLC", "mfr_source": "SEMELAB PLC",
                "pub_date": None, "pub_date_source": None,
                "doc_level_ltb_date": None, "doc_level_ltb_date_source": None}
    reasons = refuse_unsourced_header_values(header_d, _index())

    assert reasons == [], "a value with a verbatim source must not be refused"
    assert header_d["mfr"] == "SEMELAB PLC"
    assert header_d["mfr_source"] == "SEMELAB PLC"


def test_value_self_sourced_when_source_is_missing_but_value_is_verbatim():
    """No source snippet offered, but the bare VALUE is verbatim in the document. The
    field is KEPT: the operative rule is the value being in the document, not whether a
    source snippet was also supplied. `mfr_source` is backfilled to the value itself so
    downstream (build_review_items, the review UI) sees a normal sourced field."""
    header_d = {"mfr": "SEMELAB PLC", "mfr_source": None,
                "pub_date": None, "pub_date_source": None,
                "doc_level_ltb_date": None, "doc_level_ltb_date_source": None}
    reasons = refuse_unsourced_header_values(header_d, _index())

    assert reasons == [], "a self-sourced value must not be refused"
    assert header_d["mfr"] == "SEMELAB PLC", "the value itself must survive"
    assert header_d["mfr_source"] == "SEMELAB PLC", \
        "a missing source must be backfilled to the verbatim value that proved it"

    ok, method, effective_source = locate_header_source("SEMELAB PLC", None, _index())
    assert ok and method == "value_self_sourced" and effective_source == "SEMELAB PLC"


def test_typographic_fold_saves_a_source_that_differs_only_by_dash_and_nbsp():
    """`pub_date_source` as extracted ('05-Dec 2023', ASCII hyphen + space) differs from
    the document's own typography ('05–Dec 2023', en-dash + NBSP) only in ways a
    human reader would call identical. Proven NOT resolvable by the exact matcher alone,
    so the fold — not a coincidence — is what keeps the field."""
    index = _index()
    source = "05-Dec 2023"

    exact = provenance.resolve_value(source, index, prefer_region="narrative")
    assert not exact["found"], \
        "the exact matcher must miss this pair, or the fold isn't actually being exercised"

    header_d = {"mfr": None, "mfr_source": None,
                "pub_date": "2023-12-05", "pub_date_source": source,
                "doc_level_ltb_date": None, "doc_level_ltb_date_source": None}
    reasons = refuse_unsourced_header_values(header_d, index)

    assert reasons == [], "a typographically-folded match must not be refused"
    assert header_d["pub_date"] == "2023-12-05"
    assert header_d["pub_date_source"] == source

    ok, method, _ = locate_header_source("2023-12-05", source, index)
    assert ok and method == "typographic_fold"


def test_doc_level_ltb_date_refused_to_none_not_empty_string():
    """`HEADER_SOURCED_FIELDS` declares a different blank sentinel per field
    (None for doc_level_ltb_date, "" for mfr/pub_date) — a refused date must not
    silently become the empty string, which downstream code could mistake for
    'known to be blank' rather than 'never verified'."""
    header_d = {"mfr": None, "mfr_source": None, "pub_date": None, "pub_date_source": None,
                "doc_level_ltb_date": "2099-01-01", "doc_level_ltb_date_source": None}
    reasons = refuse_unsourced_header_values(header_d, _index())

    assert len(reasons) == 1 and "header.doc_level_ltb_date" in reasons[0]
    assert header_d["doc_level_ltb_date"] is None, \
        "the refused date must become None, matching its declared blank sentinel"
    assert header_d["doc_level_ltb_date_source"] is None


def test_field_table_declares_the_right_blank_sentinel_per_field():
    by_field = {f: blank for f, _src, blank in HEADER_SOURCED_FIELDS}
    assert by_field["mfr"] == "" and by_field["pub_date"] == ""
    assert by_field["doc_level_ltb_date"] is None


# --------------------------------------------------------------------------- #
# The refusal does not force review — and the mutation check that pins WHY.
# --------------------------------------------------------------------------- #
def test_refusal_does_not_set_needs_review_and_leaves_no_review_item():
    """This is a REFUSAL, not a review flag (see the module docstring). A refused field
    must not appear in build_review_items' output at all, and must contribute no reason
    of its own to that function's output — it was already fully explained by
    `refuse_unsourced_header_values`'s own reason string."""
    header_d = {"mfr": "TT Electronics", "mfr_source": None,
                "pub_date": None, "pub_date_source": None,
                "doc_level_ltb_date": None, "doc_level_ltb_date_source": None,
                "summary": None, "categories": None}
    index = _index()

    refusal_reasons = refuse_unsourced_header_values(header_d, index)
    assert refusal_reasons, "the fabricated mfr must produce a refusal reason"

    items, item_reasons = merge.build_review_items(header_d, [], index, "")
    by_fp = {it["field_path"]: it for it in items}
    assert "header.mfr" not in by_fp, \
        "a refused (now-blank) field must not resurface as a review item"
    assert not any("mfr" in r for r in item_reasons), \
        "build_review_items must contribute no reason of its own for an already-refused field"


def test_mutation_check_without_refusal_the_review_item_would_have_appeared():
    """Pins the BEHAVIOUR CHANGE, not the implementation: if refusal were removed (a
    no-op), the exact same fabricated value would have surfaced as a review item flagged
    needs_review=True — 'probably right, just double check' — instead of being dropped.
    If this test ever fails, `refuse_unsourced_header_values` has stopped changing anything
    observable and the whole feature has silently regressed to a no-op."""
    unrefused_header_d = {"mfr": "TT Electronics", "mfr_source": None,
                          "pub_date": None, "pub_date_source": None,
                          "doc_level_ltb_date": None, "doc_level_ltb_date_source": None,
                          "summary": None, "categories": None}
    index = _index()

    items, _reasons = merge.build_review_items(unrefused_header_d, [], index, "")
    by_fp = {it["field_path"]: it for it in items}
    assert "header.mfr" in by_fp, \
        "expected the unrefused fabricated value to surface as a review item"
    assert by_fp["header.mfr"]["needs_review"] is True, \
        "expected the unrefused fabricated value to be flagged for review"


# --------------------------------------------------------------------------- #
# ORDERING: the refusal must precede the LTB backfill
# --------------------------------------------------------------------------- #

def test_a_refused_doc_level_ltb_never_reaches_a_part():
    """A refused date must not survive on the parts that inherited it.

    `reconcile_ltb` backfills every part lacking its own LTB date from
    `header_d["doc_level_ltb_date"]`. So the refusal has to happen FIRST: refuse after the
    backfill and the header's copy is nulled while every inheriting part keeps the value
    the document does not contain. The field would read clean and the data would not.
    """
    header_d = {"mfr": "", "mfr_source": None,
                "pub_date": "", "pub_date_source": None,
                "doc_level_ltb_date": "2099-01-01", "doc_level_ltb_date_source": None}
    parts = [{"affected_mpn": "A-1", "ltb_date": None},
             {"affected_mpn": "B-2", "ltb_date": "2024-05-01"}]

    reasons = refuse_unsourced_header_values(header_d, _index())
    assert header_d["doc_level_ltb_date"] is None
    assert any("doc_level_ltb_date" in r for r in reasons)

    out = merge.reconcile_ltb(parts, header_d.get("doc_level_ltb_date"))
    assert out[0].get("ltb_date") in (None, ""), \
        ("a part inherited a doc-level LTB date that was refused for having no verbatim "
         "source — the refusal ran too late to matter")
    assert out[1].get("ltb_date") == "2024-05-01", \
        "a part's OWN date is evidence in its own right and must survive the refusal"


def test_mutation_check_the_late_order_does_leak_the_refused_date():
    """Proves the ordering is what protects the parts, not the refusal alone.

    Same inputs, refusal deliberately run AFTER the backfill — the pre-fix order. If this
    ever stops leaking, the test above has stopped testing anything.
    """
    header_d = {"mfr": "", "mfr_source": None,
                "pub_date": "", "pub_date_source": None,
                "doc_level_ltb_date": "2099-01-01", "doc_level_ltb_date_source": None}
    parts = [{"affected_mpn": "A-1", "ltb_date": None}]

    out = merge.reconcile_ltb(parts, header_d.get("doc_level_ltb_date"))
    refuse_unsourced_header_values(header_d, _index())

    assert header_d["doc_level_ltb_date"] is None
    assert out[0]["ltb_date"] == "2099-01-01", \
        "expected the pre-fix order to leak the refused date onto the part"


def test_the_plugin_refuses_before_it_backfills():
    """The invariant above, asserted where it can actually regress.

    The two calls are ~100 lines apart in `_extract_fulltext` and neither raises if they swap,
    so nothing but their ORDER enforces this. Checked at the source level because the
    method cannot run without S3, a pod and two models.
    """
    import inspect

    from doc_tools.plugins import sustainment as sustainment_module

    src = inspect.getsource(sustainment_module.SustainmentPlugin._extract_fulltext)
    refuse_at = src.index("refuse_unsourced_header_values(")
    backfill_at = src.index("reconcile_ltb(")
    assert refuse_at < backfill_at, \
        ("refuse_unsourced_header_values must run BEFORE reconcile_ltb, or a refused "
         "doc-level LTB date stays written on every part that inherited it")


def test_an_overreaching_source_does_not_refuse_a_value_the_document_prints():
    """A citation error is not a fabrication.

    Models quote too much: the notice prints "SEMELAB PLC" in one element and the town in
    another, and the model offers "SEMELAB PLC, Coventry" as the source. That snippet
    resolves nowhere. Refusing on it would drop a manufacturer that is plainly on page 1 —
    the value is what has to be in the document, and it is.
    """
    ok, method, eff = locate_header_source(
        "SEMELAB PLC", "SEMELAB PLC, Coventry, United Kingdom", _index())
    assert ok, "a value printed in the document must survive an unresolvable source snippet"
    assert method == "value_over_bad_source", \
        "the weaker grounding must be reported distinctly, not laundered as a clean match"
    assert eff == "SEMELAB PLC", \
        "the effective source must be narrowed to what actually resolves, not the bad quote"


def test_a_bad_source_does_not_rescue_a_value_that_is_also_absent():
    """The relaxation must not become a way in for fabrications."""
    ok, method, eff = locate_header_source(
        "TT Electronics", "TT Electronics plc, Woking", _index())
    assert not ok and method == "not_found" and eff is None
