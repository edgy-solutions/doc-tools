# -*- coding: utf-8 -*-
"""EOL-36 reads `SEMELAB` on every fire, whatever the model says.

WHAT WENT WRONG. `EOL-36_BYV34-400,-BYV34-500` is a Semelab notice. Semelab is a brand of
TT Electronics, and the page shows it: the masthead rasterises to `[Image] @ Electronics`,
a parts table is headed `TT Series`, the recommendation says "discuss with TT sales", the
footer prints five `ttelectronics.com/brands/semelab/` URLs, and `SEMELAB` appears as a
standalone title. Asked for "the issuing manufacturer" and told to "use ONLY information
present", the model answered three different reasonable ways over six fires on
byte-identical input:

  * `SEMELAB`, the brand printed as a title — quotable, kept (1 fire);
  * `TT Electronics`, the company inferred from `TT sales` and the URLs, with an honest
    `mfr_source: null` because that exact string is printed nowhere (3 fires);
  * `TT Electronics` with the footer URL as its source — a citation that RESOLVES wrapped
    around a value the page never states (2 fires);
  * `null`, because "don't invent" and "issuing manufacturer" conflict on this page (1
    fire) — which under the old non-nullable schema raised `BamlValidationError` and
    failed the WHOLE header pass, losing doc_id, pub_date, categories and summary over one
    unfound field.

That is an underspecified question, not a misbehaving model, and the unseeded sampler only
exposed it: a deterministic model would pick one of the three forever and might pick
differently on the next acquired-brand notice. So the fix removes the model's discretion
on this field rather than trying to make it answer more reliably:

  1. SCHEMA + PROMPT — `mfr` is the name AS PRINTED, `mfr_source` is mandatory with it,
     and `mfr string?` makes a null an ANSWER instead of a validation crash.
  2. DOCUMENT WINS — when the nominated value is not printed, the document's own
     standalone name is written, with that element as the source.
  3. `mfr_parent`, verbatim only — a parent company is written only when its name is
     printed AS A NAME. `ttelectronics.com` is a domain, so on this notice the field stays
     empty; the brand-vs-owner distinction is kept without inventing either half.

The element list and all six measured answers are in
`tests/fixtures/sustainment/eol36_header.json`, transcribed from the raw BAML I/O captured
out of the sandbox pod (`sessions/2026-09-29-eol36-raw-baml-io.md`). Pure, no LLM.
"""
import json
import os

import pytest

from doc_tools.baml_client.types import NoticeHeader
from doc_tools.utils import provenance
from doc_tools.utils.sustainment_header_trust import (
    mfr_from_document,
    refuse_unsourced_header_values,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sustainment",
                       "eol36_header.json")


def _fixture():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def _eol36_index():
    """The real 22 elements, in order. Bboxes are synthesised — nothing in the mfr path
    reads geometry, and the rendered prompt carried type and text only."""
    return provenance.build_positioned_index([
        {"type": e["type"], "text": e["text"],
         "metadata": {"page_number": e["page_number"],
                      "coordinates": {"points": [[0, 0], [100, 0], [100, 20], [0, 20]],
                                      "layout_width": 612, "layout_height": 792}}}
        for e in _fixture()["elements"]
    ])


def _el(text, etype="Title", page=1):
    return {"type": etype, "text": text,
            "metadata": {"page_number": page,
                         "coordinates": {"points": [[0, 0], [100, 0], [100, 20], [0, 20]],
                                         "layout_width": 612, "layout_height": 792}}}


# --------------------------------------------------------------------------- #
# part 1 — a null mfr is an answer, not a crash
# --------------------------------------------------------------------------- #
def test_the_fire_that_crashed_the_whole_header_pass_now_validates():
    """THE FIXTURE THE ORDER ASKED FOR. This is run A fire 3's raw response, byte for
    byte. Under `mfr string` it raised `BamlValidationError: mfr: Expected string, got
    null` and the header pass failed WHOLE — doc_id, pub_date, categories and summary
    discarded because one field could not be found. Under `mfr string?` the null is the
    answer to that one field and everything else survives, which is the property being
    pinned: a header pass can never fail whole on one unfound field again."""
    header = NoticeHeader(**_fixture()["run_a_fire_3_raw_response"])

    assert header.mfr is None
    assert header.mfr_source is None
    # the rest of the pass, which the crash used to take with it
    assert header.doc_id == "BED.PCN-36"
    assert header.pub_date == "2024-04-19"
    assert header.categories == ["Discontinuation", "Material"]
    assert header.summary


def test_mfr_and_the_parent_pair_are_all_four_optional_on_the_schema():
    """A header naming NOBODY is constructible. If any of these four were required, the
    nullable-mfr fix would only have moved the crash one field over — `mfr_parent` in
    particular is null on most notices, so making it required would have turned the common
    case into the crash.

    `pub_date` is deliberately NOT included: it is still `string`, so a notice printing no
    date anywhere would still fail the pass whole. That is the same SHAPE of defect but not
    the same defect — what broke here was the prompt permitting a null the schema forbade,
    and the prompt does not invite a null date (see `prompts/sustainment_header_instructions.md`
    line 11, which states the field flatly). Left alone rather than widened silently."""
    header = NoticeHeader(doc_id="X", doc_type="PCN", revision=None,
                          pub_date="2024-01-01", pub_date_source=None,
                          mfr=None, mfr_source=None,
                          categories=[], summary="s", doc_level_ltb_date=None,
                          doc_level_ltb_date_source=None)
    assert header.mfr is None and header.mfr_source is None
    assert header.mfr_parent is None and header.mfr_parent_source is None


# --------------------------------------------------------------------------- #
# part 2 — the seal: every measured answer ends at SEMELAB
# --------------------------------------------------------------------------- #
def test_the_document_names_semelab_and_nothing_else():
    """Document-wins over the real element list. Three `SEMELAB` elements are candidates;
    every other standalone heading is rejected — see the per-candidate test below."""
    assert mfr_from_document(_eol36_index()) == ("SEMELAB", "SEMELAB")


@pytest.mark.parametrize("answer", _fixture()["model_answers"],
                         ids=[a["fire"] for a in _fixture()["model_answers"]])
def test_every_measured_fire_ends_at_semelab(answer):
    """THE SEAL. All five distinct measured answers — the quotable brand, the inferred
    parent with an honest null source, the inferred parent with a resolving URL as its
    source, and the null that used to crash — converge on the one name the page prints.
    The model's answer no longer determines the value; it only determines whether a
    substitution is recorded in the narrative."""
    header_d = {"mfr": answer["mfr"], "mfr_source": answer["mfr_source"]}
    reasons = refuse_unsourced_header_values(header_d, _eol36_index())

    assert header_d["mfr"] == "SEMELAB", answer["fire"]
    assert header_d["mfr_source"] == "SEMELAB", answer["fire"]

    if answer["mfr"] == "SEMELAB":
        # already supported: verified in place, no substitution to report
        assert not [r for r in reasons if "header.mfr" in r], reasons
    else:
        assert [r for r in reasons if r.startswith("header.mfr recovered")], reasons


def test_the_two_substitutions_are_worded_differently_in_the_narrative():
    """A human reading review.json must be able to tell "the model said something the page
    does not print" from "the model said nothing" — they call for different follow-up, and
    only the first is evidence about the model."""
    overridden = {"mfr": "TT Electronics", "mfr_source": None}
    refused_none = {"mfr": None, "mfr_source": None}
    r_over = refuse_unsourced_header_values(overridden, _eol36_index())
    r_none = refuse_unsourced_header_values(refused_none, _eol36_index())

    assert any("model value 'TT Electronics' is not printed" in r for r in r_over), r_over
    assert any("the header pass returned none" in r for r in r_none), r_none


def test_the_sealed_value_survives_a_second_pass_of_the_check_that_wrote_it():
    """Idempotence. The recovered value is written BY the refusal, so if it could not
    itself pass the refusal a later re-check would blank it and the seal would come
    undone silently."""
    header_d = {"mfr": "TT Electronics", "mfr_source": None}
    refuse_unsourced_header_values(header_d, _eol36_index())
    first = dict(header_d)

    reasons = refuse_unsourced_header_values(header_d, _eol36_index())
    assert header_d == first
    assert not [r for r in reasons if "refused" in r], reasons


def test_every_other_standalone_heading_on_the_page_is_rejected():
    """The per-candidate verdict, named rather than counted. EOL-36 carries thirteen
    standalone Title/UncategorizedText elements; twelve distinct forms must NOT be read as
    a manufacturer, and each is rejected for a stated reason. If any of these became a
    second candidate the uniqueness rule would refuse the field — failing SAFE, to today's
    empty value, never to a wrong name."""
    from doc_tools.utils.sustainment_header_trust import _is_name_shaped

    assert _is_name_shaped("SEMELAB")

    rejected = {
        # a tagline: four tokens, over the name-length ceiling
        "SENSORS AND SPECIALIST COMPONENTS": "too many tokens",
        # document furniture, whatever its capitalisation
        "Power Solutions Product Change Notification": "furniture words",
        "Products": "furniture word",
        "Products Affected": "furniture words",
        "Change Detail": "furniture words",
        # a page number: digits
        "Page 2 of 2": "digits and furniture",
        # THE regression guard: the footer URL must not become `ttelectronics`
        "https://www.ttelectronics.com/brands/semelab/": "url",
    }
    for form, why in rejected.items():
        assert not _is_name_shaped(form), "%r must be rejected (%s)" % (form, why)


def test_a_second_unrelated_name_refuses_rather_than_choosing():
    """Two names that are not truncations of each other mean the document is ambiguous
    about who issued it, and an ambiguous document gets an empty field. Guessing between
    rival readings is the failure mode this whole change exists to remove — it must not be
    reintroduced by the step that replaced it."""
    index = provenance.build_positioned_index([
        _el("SEMELAB"), _el("Vishay"), _el("Some body text", etype="NarrativeText"),
    ])
    assert mfr_from_document(index) == (None, None)


def test_a_name_shaped_heading_that_is_not_actually_in_the_text_is_not_written():
    """Document-wins re-verifies its own answer through `provenance.resolve_value` before
    writing. The element list and the resolvable text are built by different code paths,
    and a value this function writes is one a later refusal pass must be able to confirm
    (see the idempotence test above)."""
    index = provenance.build_positioned_index([_el("")])
    assert mfr_from_document(index) == (None, None)


# --------------------------------------------------------------------------- #
# part 3 — mfr_parent, verbatim only, and a domain is not a name
# --------------------------------------------------------------------------- #
def test_the_parent_field_stays_empty_on_eol36_because_only_a_domain_is_printed():
    """The point of part 3, and the reason `mode="name"` rejects domains explicitly. This
    notice's footer really does print `ttelectronics.com`, so a plain verbatim check WOULD
    pass it and write a web address as the owning company's name. The parent is real and
    the page does not name it; the honest field is empty."""
    header_d = {"mfr": "SEMELAB", "mfr_source": "SEMELAB",
                "mfr_parent": "ttelectronics.com",
                "mfr_parent_source": "https://www.ttelectronics.com/brands/semelab/"}
    reasons = refuse_unsourced_header_values(header_d, _eol36_index())

    assert header_d["mfr"] == "SEMELAB"
    assert header_d["mfr_parent"] is None
    assert header_d["mfr_parent_source"] is None
    assert any("domain, not a name" in r for r in reasons), reasons


def test_a_parent_name_printed_as_a_name_is_written():
    """The other half: the field is not decorative. When the page prints the owner AS A
    NAME it is kept, with its source, so the brand-vs-owner pair survives on notices that
    state both."""
    index = provenance.build_positioned_index([
        _el("SEMELAB"),
        _el("Semelab is a brand of TT Electronics plc.", etype="NarrativeText"),
    ])
    header_d = {"mfr": "SEMELAB", "mfr_source": "SEMELAB",
                "mfr_parent": "TT Electronics", "mfr_parent_source": "TT Electronics"}
    reasons = refuse_unsourced_header_values(header_d, index)

    assert header_d["mfr_parent"] == "TT Electronics"
    assert header_d["mfr_parent_source"]
    assert not [r for r in reasons if "mfr_parent" in r], reasons


def test_an_unprinted_parent_is_refused_to_none_not_empty_string():
    """`HEADER_SOURCED_FIELDS` declares None as this field's blank, unlike `mfr`'s "".
    An absent parent is the COMMON case, and "" would read downstream as a parent the
    extractor lost rather than one the document never had."""
    header_d = {"mfr": "SEMELAB", "mfr_source": "SEMELAB",
                "mfr_parent": "Berkshire Hathaway", "mfr_parent_source": None}
    refuse_unsourced_header_values(header_d, _eol36_index())

    assert header_d["mfr_parent"] is None


def test_the_parent_field_has_no_document_wins_step():
    """Deliberate asymmetry. `mfr` is recoverable from the document because a notice
    always has an issuer and the page prints it; ownership is a corporate fact a notice
    need not state, and there is no heading shape that means "our parent". So the parent
    is verbatim-or-nothing: an empty value here is a fact about the document, not a gap to
    be filled."""
    from doc_tools.utils.sustainment_header_trust import _DOCUMENT_WINS

    assert "mfr" in _DOCUMENT_WINS
    assert "mfr_parent" not in _DOCUMENT_WINS

    header_d = {"mfr_parent": None, "mfr_parent_source": None}
    reasons = refuse_unsourced_header_values(header_d, _eol36_index())
    assert header_d["mfr_parent"] is None
    assert not [r for r in reasons if "mfr_parent" in r], reasons


# --------------------------------------------------------------------------- #
# the wiring — a field nobody carries is a field nobody sees
# --------------------------------------------------------------------------- #
def test_mfr_parent_survives_the_merge_helpers_to_review_json():
    """`mfr_parent` is extracted, refused and persisted by three different modules, and a
    field dropped by any one of them is invisible downstream while every unit test above
    still passes. So the carriers are pinned explicitly: the BAML->dict conversion, the
    blank header the plugin falls back to when the header pass raises, and the review
    payload a human reads."""
    from doc_tools.utils import sustainment_merge as merge

    h = NoticeHeader(doc_id="X", doc_type="PCN", revision=None, pub_date="2024-01-01",
                     pub_date_source="01/01/2024", mfr="SEMELAB", mfr_source="SEMELAB",
                     mfr_parent="TT Electronics", mfr_parent_source="TT Electronics",
                     categories=[], summary="s", doc_level_ltb_date=None,
                     doc_level_ltb_date_source=None)
    d = merge.header_to_dict(h)
    assert d["mfr_parent"] == "TT Electronics"
    assert d["mfr_parent_source"] == "TT Electronics"

    # the fallback the plugin uses when the header pass raises: the key must EXIST, or
    # the refusal's `header_d.get(field)` and every downstream reader see a silent absence
    blank = merge.empty_header("X")
    assert "mfr_parent" in blank and blank["mfr_parent"] is None
    assert "mfr_parent_source" in blank and blank["mfr_parent_source"] is None

    index = provenance.build_positioned_index([
        _el("SEMELAB"),
        _el("Semelab is a brand of TT Electronics.", etype="NarrativeText"),
        _el("Dated 01/01/2024.", etype="NarrativeText"),
    ])
    items, _ = merge.build_review_items(d, [], index, "")
    parent = [i for i in items if i["field_path"] == "header.mfr_parent"]
    assert len(parent) == 1, [i["field_path"] for i in items]
    assert parent[0]["value"] == "TT Electronics"
    assert parent[0]["needs_review"] is False, parent[0]
