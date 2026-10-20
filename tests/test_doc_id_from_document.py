# -*- coding: utf-8 -*-
"""`doc_id_from_document` — the text-layer arm for the notice number.

THIS FILE IS THE ONLY PROOF THIS FUNCTION WILL EVER HAVE. Nothing in the corpus gate
scores doc_id: `scripts/pcn_ground_truth.json` carries header ground truth for three
notices (TYC, TI, IDT) and three other fields each (`mfr`, `pub_date`,
`doc_level_ltb_date`), which are the nine scored header fields. There is no doc_id
expectation anywhere, so a wrong value written by this function would be silent all the
way into the graph. The refusals below are therefore pinned as carefully as the
successes, and `(None, None)` is a correct, intended answer throughout.

WHY THE SHAPE RULE IS WHAT IT IS. A first draft of this rule was case-insensitive and
allowed any two characters as the value. Measured against the printed runs of the three
text fixtures, it read the prose fragments `PCN and`, `PCN Team`, `PCN form.`,
`PCN Title`, `PCN Date` and `EOL Devices` as notice numbers, and on TYC line 8 it
returned `PCN Date` while the real `PCN-24-210412` printed in the same run was invisible
to it. A sourcing check cannot catch that — the fragment is printed on the page, so it
resolves. It also could not read five of the ten code-bearing doc_ids the corpus has
actually written, because a `\\b` after the code token cannot match a glued form such as
`PCN20250409000.1`. Both defects have a regression test here
(`test_a_prose_fragment_after_the_code_is_not_a_notice_number`,
`test_a_glued_code_and_value_is_a_notice_number`).

Pure, no LLM. Index shape and element keys follow `tests/test_mfr_document_wins_eol36.py`.
"""
import pytest

from doc_tools.utils import provenance
from doc_tools.utils.sustainment_header_trust import doc_id_from_document


def _el(text, etype="UncategorizedText", page=1):
    """One positioned element, in the shape `test_mfr_document_wins_eol36.py` builds.

    Bboxes are synthesised: nothing in the doc_id path reads geometry, and the
    coordinates exist only so `build_positioned_index` records a page and a box the way
    it does for a real element."""
    return {"type": etype, "text": text,
            "metadata": {"page_number": page,
                         "coordinates": {"points": [[0, 0], [100, 0], [100, 20], [0, 20]],
                                         "layout_width": 612, "layout_height": 792}}}


def _index(*elements):
    return provenance.build_positioned_index(list(elements))


# --------------------------------------------------------------------------- #
# the successes — one per printed form the corpus actually uses
# --------------------------------------------------------------------------- #
def test_a_footer_band_repeated_on_five_pages_is_read_with_the_whole_run_as_source():
    """The TI shape: the number is printed in a page footer, not a heading, and the
    label-ish company name and the number are ONE run. Protects two things at once — that
    a footer is in scope at all, and that the source stays whole so provenance resolves
    against the element while the value is only the number."""
    run = "Texas Instruments Incorporated PCN#20210316000.1"
    index = _index(*[_el(run, etype="Footer", page=p) for p in range(1, 6)])

    value, source = doc_id_from_document(index)
    assert value == "PCN#20210316000.1"
    assert source == run
    # the source must resolve, or a later sourcing pass would blank what this wrote
    assert provenance.resolve_value(source, index, prefer_region="narrative")["found"]


def test_a_single_right_hand_field_is_read():
    """The common shape: one short run carrying nothing but the number. Protects the
    base case — a single candidate with no competition still has to be written."""
    assert doc_id_from_document(_index(_el("PCN 23-002"))) == ("PCN 23-002", "PCN 23-002")


def test_underscores_and_spaces_survive_into_the_value():
    """`PDN 23_0120` is a real written doc_id, and both its space and its underscore are
    part of the printed form. Protects against a value char class that quietly truncates
    at the underscore — an earlier draft returned `PDN 23`."""
    assert doc_id_from_document(_index(_el("PDN 23_0120"))) == ("PDN 23_0120", "PDN 23_0120")


def test_a_bare_code_with_no_separator_is_read():
    """`IPCN25300X` is a real written doc_id with no separator and a two-letter prefix.
    Protects the dropped word boundary: with a `\\b` after the code this form matched
    nothing at all, because `N` and `2` are both word characters."""
    assert doc_id_from_document(_index(_el("IPCN25300X", etype="Title"))) == (
        "IPCN25300X", "IPCN25300X")


def test_a_glued_code_and_value_is_a_notice_number():
    """REGRESSION GUARD, from the measurement. Five of the ten code-bearing doc_ids the
    corpus has written are glued forms, so this is the majority shape and not an edge
    case. `FPCN26191XA` also pins the open prefix set: the code is a 0-2 letter prefix
    plus a family, never a fixed alternation of literals."""
    for printed in ("PCN20250409000.1", "PDN20231212001.3", "FPCN26191XA"):
        assert doc_id_from_document(_index(_el(printed, etype="Footer"))) == (
            printed, printed), printed


def test_a_hyphen_is_a_separator_and_the_value_may_open_on_a_letter():
    """The three forms that matter most in this corpus print a bare hyphen straight after
    the code — `PCN-2683` is Diodes' own title, `PCN-36` is EOL-36, `PCN-24-210412` is
    TYC — and `PTN-DD-026-2023-REV-0` is a written doc_id whose value opens on letters.
    A rule that cannot read these is not worth having."""
    for printed in ("PCN-2683", "PCN-36", "PCN-24-210412", "PTN-DD-026-2023-REV-0"):
        assert doc_id_from_document(_index(_el(printed, etype="Title"))) == (
            printed, printed), printed


def test_two_printed_spacings_of_one_number_unify_rather_than_refusing():
    """`PCN23-002` and `PCN 23-002` are one number at two spacings: they share the key
    `PCN23002`, so this must yield the most frequent printed form, not a refusal.

    NOTE: this case was green before the shape rule was corrected, and green for the
    wrong reason — `PCN23-002` matched nothing at all, so no unification was being
    tested. Both forms are now candidates, which is what makes the assertion real."""
    index = _index(_el("PCN23-002", etype="Title"),
                   _el("PCN 23-002"), _el("PCN 23-002", page=2))
    assert doc_id_from_document(index) == ("PCN 23-002", "PCN 23-002")


def test_a_trailing_full_stop_is_not_part_of_the_number():
    """Greedy matching swallows the sentence's full stop. `PCN 2016-119-A` is a real
    written doc_id and `PCN 2016-119-A.` is not."""
    run = "This device is superseded per PCN 2016-119-A."
    value, source = doc_id_from_document(_index(_el(run, etype="NarrativeText")))
    assert value == "PCN 2016-119-A"
    assert source == run


# --------------------------------------------------------------------------- #
# the refusals — each one is the intended answer, not a gap
# --------------------------------------------------------------------------- #
def test_two_unrelated_numbers_refuse_rather_than_choosing():
    """THE SAFETY. Two keys means the document names two notices, and picking one would
    write one notice's number onto another's record. No prefix rule may soften this and
    no preference rule may break the tie: `PCN-36` is not a truncation of `PCN-3600`, it
    is a different notice — which is exactly where this function differs from
    `mfr_from_document`, where two truncations of one name do collapse."""
    assert doc_id_from_document(_index(
        _el("PCN23-002", etype="Title"), _el("PDN 23_0120"))) == (None, None)
    assert doc_id_from_document(_index(
        _el("PCN-36", etype="Title"), _el("PCN-3600"))) == (None, None)


def test_a_prose_fragment_after_the_code_is_not_a_notice_number():
    """REGRESSION GUARD, and the reason the shape rule is case-sensitive and digit-bound.
    TYC line 8 verbatim prints the real number and the words `PCN Date` in the SAME run.
    An earlier draft returned `PCN Date` — a fabricated doc_id that the sourcing check
    could not catch, because those words are genuinely printed on the page. The real
    number must be read and the fragment must not even be a candidate."""
    run = "Product Change Notification: PCN-24-210412 PCN Date: 07-JUN-24"
    value, source = doc_id_from_document(_index(_el(run, etype="NarrativeText")))
    assert value == "PCN-24-210412"
    assert value != "PCN Date"
    assert source == run


def test_every_measured_prose_fragment_is_refused_outright():
    """The other five fragments the earlier draft read, each printed on a real notice.
    Named rather than counted: every one of these alone in a document must leave the
    field empty. `EOL Devices` is a table caption, `PCN Team` a sign-off, `PCN form.`
    and `PCN and` ordinary prose, `PCN Title` a form label without its colon."""
    fragments = {
        "Diodes Incorporated PCN Team": "a sign-off",
        "PCN Title: Device End of Life (EOL)": "a form label",
        "Please refer to the attached PCN form. Please contact your local sales "
        "representative to acknowledge receipt of this PCN and for any samples.":
            "two prose mentions",
        "Table 1 - EOL Devices with Life-time Buy Opportunity and Replacement Parts":
            "a table caption",
        "PCN Attributes:": "a section heading",
    }
    for run, why in fragments.items():
        assert doc_id_from_document(_index(_el(run, etype="NarrativeText"))) == (
            None, None), "%s (%s) must not be read as a number" % (run[:40], why)


def test_a_label_echo_yields_no_candidate():
    """The measured Diodes trap `PCN #: 2683`. Answered structurally: a colon is not in
    the separator set, so the engine cannot cross it and no candidate is produced. The
    bare label `PCN #:` with no value at all must also yield nothing, and `2683` on its
    own is covered by the next test. `is_field_label_echo` remains wired as the second
    guard, for a spacing that reaches a candidate some other way."""
    for run in ("PCN #: 2683", "PCN #:2683", "PCN #:", "PCN Number:"):
        assert doc_id_from_document(_index(_el(run, etype="NarrativeText"))) == (
            None, None), run


def test_a_bare_number_is_not_a_doc_id_claim():
    """The code token is mandatory. `2683` is the Diodes number and `P1306028a` is a real
    written doc_id, but neither string says on the page that it IS the notice number
    rather than a part, a drawing or a page number — so reading them would be a guess.
    Declining `P1306028a` is deliberate, not an oversight."""
    for run in ("2683", "P1306028a", "06/25/2024", "Page 2 of 2"):
        assert doc_id_from_document(_index(_el(run, etype="NarrativeText"))) == (
            None, None), run


def test_a_number_printed_only_inside_a_table_is_not_read():
    """A SCOPE DECISION, pinned so it is visible rather than accidental. `Table` is out of
    scope, and that costs a real notice: measured on the EOL-36 element list, `PCN-36` is
    printed ONLY inside the header-grid Table run below, so this function refuses there
    and the model's value plus the region witness stand. The safe direction of the trade
    — admitting Table would put every parts grid in scope — but a trade, and the wiring
    step is where it should be revisited."""
    run = ("PCN Number BED.PCN-36 PCN Title EOL - Dual Fast Recovery Rectifiers "
           "(BYV34-400/500 series) PCN Date 19/04/2024")
    assert doc_id_from_document(_index(_el(run, etype="Table"))) == (None, None)
    # the same run in a body type IS read, so the refusal above is about scope only
    assert doc_id_from_document(_index(_el(run, etype="NarrativeText")))[0] == "PCN-36"


def test_an_empty_index_refuses():
    """No document, no statement. Also covers an index of elements with no text."""
    assert doc_id_from_document(_index()) == (None, None)
    assert doc_id_from_document(_index(_el(""), _el("   ", etype="Title"))) == (None, None)


def test_a_value_the_sourcing_check_cannot_find_is_refused_monkeypatched(monkeypatch):
    """The self-verification guard, exercised the only way it can be.

    MECHANISM, stated because the test would otherwise look artificial:
    `provenance.resolve_value` does `_norm`-ed substring containment against each
    element's own text, and the source this function returns IS an element's own text, so
    the guard is unreachable through any real index — the source always resolves. It is
    load-bearing for idempotency all the same: a value this function supplies is one a
    later sourcing pass must be able to confirm, and if it could not, that pass would
    blank the field and the substitution would be silently undone. Monkeypatching proves
    the branch exists and refuses, which is the only thing a real index cannot show."""
    from doc_tools.utils import sustainment_header_trust as trust

    index = _index(_el("PCN 23-002"))
    assert doc_id_from_document(index) == ("PCN 23-002", "PCN 23-002")

    monkeypatch.setattr(trust.provenance, "resolve_value",
                        lambda *a, **k: {"found": False})
    assert doc_id_from_document(index) == (None, None)


# --------------------------------------------------------------------------- #
# the registries — this function is NOT wired yet, and that is deliberate
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("registry", ["_DOCUMENT_WINS", "_RECOVERABLE"])
def test_doc_id_is_not_registered_yet(registry):
    """Pinned so the wiring is a deliberate, reviewed step rather than a side effect of
    this one. Registering `doc_id` here would subject every notice's doc_id to the
    unsourced refusal at once, and since the model emits no `doc_id_source` at all, every
    doc_id in the corpus would be refused and re-derived in a single unmeasured move — on
    a field nothing scores."""
    import doc_tools.utils.sustainment_header_trust as trust

    assert "doc_id" not in getattr(trust, registry)


def test_doc_id_is_not_in_the_header_sourced_fields():
    """The same guard on the refusal's own field list. `HEADER_SOURCED_FIELDS` holds
    `mfr`, `mfr_parent`, `pub_date` and `doc_level_ltb_date`; `doc_id` is absent and
    `NoticeHeader` has no `doc_id_source` field for it to be checked against."""
    from doc_tools.utils.sustainment_header_trust import HEADER_SOURCED_FIELDS

    assert "doc_id" not in [f[0] for f in HEADER_SOURCED_FIELDS]
