"""The batch-fixture scrubber, end to end on a real notice's text layer.

The measured input is ``tests/fixtures/sustainment/diodes_rev1_eol_text.txt``.
Design: invincible-agent/sessions/2026-10-22-design-from-7f-batch-fixture-
scrubber-for-chris-review.md. The guard that matters most is the first: the
allowlist wins over shape, and inverting that destroys the headers.
"""
from __future__ import annotations

import os
import re

import pytest

from doc_tools.scrub.allowlist import Allowlist
from doc_tools.scrub.ledger import (REDACTION_RE, AllowlistRule, CheckName,
                                    CheckResult, MappingPolicy, PolicyAnswer,
                                    SubstitutionClass, shape_of, shapes_equal)
from doc_tools.scrub.draw import RESERVED_LEADING_UPPER
from doc_tools.scrub.element_text import read_blocks
from doc_tools.scrub.scrubber import (RECOMMENDED_POLICY, Block, _is_candidate,
                                      describe_source, scrub)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIODES = os.path.join(ROOT, "tests", "fixtures", "sustainment",
                      "diodes_rev1_eol_text.txt")
YAML_PATH = os.path.join(ROOT, "registry", "scrub_allowlist.yaml")
SALT = b"doc-tools-test-salt"
SALT_REF = "SCRUB_BATCH_SALT"




@pytest.fixture(scope="module")
def allowlist():
    return Allowlist.load(YAML_PATH)


@pytest.fixture(scope="module")
def blocks():
    return read_blocks(DIODES)


def _run(blocks, allowlist, **kw):
    kw.setdefault("strict", False)
    source = describe_source(blocks, bucket="b", key="k", data=b"x")
    return scrub(blocks, salt=SALT, salt_ref=SALT_REF, fixture_id="t",
                 source=source, allowlist=allowlist, **kw)


@pytest.fixture(scope="module")
def diodes(blocks, allowlist):
    return _run(blocks, allowlist)


def _originals(blocks, outcome):
    """Re-derive the originals from the source for the tests that need values.
    The ledger itself never carries them."""
    out = set()
    for b in blocks:
        for tok in re.split(r"[\s|,;()\[\]<>]+", b.text):
            tok = tok.rstrip(".,;:")
            if tok and outcome.ledger.substitution_for(tok):
                out.add(tok)
    return out


# ---------------------------------------------------------------- THE GUARD
def test_the_allowlist_wins_over_shape_and_inverting_the_precedence_destroys_the_headers(
        blocks, allowlist, diodes):
    """Design 3.3. Normal run: header and caption strings survive verbatim with
    unchanged counts. Inverted run: the same input loses them. The precedence is
    load-bearing, not decorative."""
    src_text = "\n".join(b.text for b in blocks)
    for survivor in ("Table 3 - EOL Devices with No Life-time Buy Opportunity "
                     "and No Replacement Parts", "06/25/2024", "12/22/2024",
                     "Diodes Incorporated"):
        assert diodes.text.count(survivor) == src_text.count(survivor) > 0
    assert diodes.ledger.verification.checks[
        CheckName.ALLOWLIST_INTEGRITY].result is CheckResult.PASS

    inverted = _run(blocks, allowlist, _allowlist_first=False)
    for destroyed in ("Table 3 - EOL Devices with No Life-time Buy Opportunity "
                      "and No Replacement Parts", "06/25/2024", "12/22/2024"):
        assert destroyed not in inverted.text
    integrity = inverted.ledger.verification.checks[CheckName.ALLOWLIST_INTEGRITY]
    assert integrity.result is CheckResult.FAIL
    assert integrity.measurements["lost"] > 0


def test_inverted_precedence_destroys_headers_dates_and_the_notice_number_together(
        allowlist):
    row = Block("Part Number Affected Part PCN-2683 06/25/2024 FJ3330013", 1,
                "table_cell", row=0, col=0,
                scrub_class=SubstitutionClass.MPN_AFFECTED)
    ok = _run([row], allowlist)
    assert ok.text.startswith("Part Number Affected Part PCN-2683 06/25/2024 ")
    bad = _run([row], allowlist, _allowlist_first=False)
    for gone in ("Part Number", "Affected Part", "PCN-2683", "06/25/2024"):
        assert gone not in bad.text


def test_what_the_allowlist_alone_buys_with_the_production_floor_left_intact(
        allowlist):
    """The two guards above invert the precedence AND drop the floor to
    shape-only, because "scrub everything identifier-shaped" is one decision.
    That bundling is honest about the simplification but it cannot say what the
    ALLOWLIST alone buys, since the production floor (letter AND digit, length
    >= 4) already refuses a bare header word or a date.

    These three are the answer: each one PASSES the production floor, so shape
    alone would substitute it, and each survives verbatim. A future change that
    weakens the allowlist loses exactly these -- a package code, a qualification
    standard, and the notice number that is also the corpus doc_id.
    """
    for tok in ("SOT-23", "AEC-Q200", "PCN-2683"):
        assert _is_candidate(tok), f"{tok} no longer reaches the allowlist test"
    row = Block("SOT-23 AEC-Q200 PCN-2683 FJ3330013", 1, "table_cell", row=0,
                col=0, scrub_class=SubstitutionClass.MPN_AFFECTED)
    out = _run([row], allowlist)
    assert out.text.startswith("SOT-23 AEC-Q200 PCN-2683 ")
    assert "FJ3330013" not in out.text


# ---------------------------------------------------------------- shape, ids
def test_shape_equality_holds_for_every_substitution_on_the_diodes_text(
        blocks, diodes):
    for orig in _originals(blocks, diodes):
        sub = diodes.ledger.substitution_for(orig)
        assert shapes_equal(shape_of(orig), sub.replacement)
        assert sub.shape == shape_of(orig)
    check = diodes.ledger.verification.checks[CheckName.SHAPE_EQUALITY]
    assert check.result is CheckResult.PASS and check.measurements["mismatches"] == 0


def test_the_same_original_in_a_table_cell_and_in_prose_gets_one_replacement(
        allowlist):
    bs = [Block("FJ3330013 FJ4800016", 1, "table_cell", row=0, col=0,
                scrub_class=SubstitutionClass.MPN_AFFECTED),
          Block("The part FJ3330013 is affected.", 2, "body_text")]
    out = _run(bs, allowlist)
    sub = out.ledger.substitution_for("FJ3330013")
    assert sub.occurrences == len(sub.sites) == 2
    assert {s.kind for s in sub.sites} == {"table_cell", "body_text"}
    assert sub.replacement in out.blocks[0].text
    assert sub.replacement in out.blocks[1].text
    again = _run(bs, allowlist)
    assert again.text == out.text


def test_no_two_originals_share_a_replacement(diodes):
    reps = [s.replacement for s in diodes.ledger.substitutions]
    assert len(set(reps)) == len(reps)


def test_every_leading_uppercase_run_is_drawn_from_the_reserved_letters(
        blocks, diodes):
    for orig in _originals(blocks, diodes):
        sub = diodes.ledger.substitution_for(orig)
        if orig[0].isupper():
            lead = 0
            while orig[lead].isupper():
                lead += 1
            assert set(sub.replacement[:lead]) <= set(RESERVED_LEADING_UPPER)
            assert sub.reserved_space == "leading uppercase from {Q,X,Z}"
        else:
            assert sub.reserved_space.startswith("none:")


def test_a_digit_first_original_records_the_none_measurement(allowlist):
    out = _run([Block("2683A", 1, "table_cell", row=0, col=0,
                      scrub_class=SubstitutionClass.MPN_AFFECTED)], allowlist)
    sub = out.ledger.substitution_for("2683A")
    assert sub.reserved_space == (
        "none: no leading uppercase run; collision_check carries this one alone")


def test_a_replacement_that_would_collide_with_a_known_mpn_forces_a_redraw(
        allowlist):
    bs = [Block("FJ3330013", 1, "table_cell", row=0, col=0,
                scrub_class=SubstitutionClass.MPN_AFFECTED)]
    first = _run(bs, allowlist).ledger.substitution_for("FJ3330013")
    assert first.redraws == 0
    out = _run(bs, allowlist, known_mpns=frozenset({first.replacement}))
    sub = out.ledger.substitution_for("FJ3330013")
    assert sub.redraws > 0 and sub.replacement != first.replacement
    coll = out.ledger.verification.checks[CheckName.COLLISION_CHECK]
    assert coll.measurements["redraws"] == sub.redraws
    assert coll.measurements["known_mpns"] == 1
    assert "proves nothing" in coll.detail


# ---------------------------------------------------------------- the ledger
def test_the_ledger_carries_no_original_value_anywhere(blocks, diodes):
    doc = diodes.ledger.model_dump_json()
    originals = _originals(blocks, diodes)
    assert len(originals) == len(diodes.ledger.substitutions)
    for sub in diodes.ledger.substitutions:
        assert REDACTION_RE.match(sub.original)
    leaked = [o for o in originals if o in doc]
    assert leaked == [], f"{len(leaked)} original(s) appear in the ledger"


def test_the_ledger_is_not_committable_and_names_the_equivalence_seal(diodes):
    assert diodes.ledger.committable is False
    assert "equivalence_seal" in diodes.ledger.why_not_committable()
    seal = diodes.ledger.verification.checks[CheckName.EQUIVALENCE_SEAL]
    assert seal.result is CheckResult.NOT_RUN and "TEXT LAYER" in seal.detail


def test_leak_test_names_what_a_text_layer_scrub_does_not_cover(diodes):
    detail = diodes.ledger.verification.checks[CheckName.LEAK_TEST].detail
    for gap in ("annotations", "XMP", "attachments", "image"):
        assert gap.lower() in detail.lower()


def test_structure_is_invariant_per_block(blocks, diodes):
    assert len(diodes.blocks) == len(blocks)
    for a, b in zip(blocks, diodes.blocks):
        assert (a.page, a.kind, a.row, a.col, len(a.text)) == (
            b.page, b.kind, b.row, b.col, len(b.text))
    check = diodes.ledger.verification.checks[CheckName.STRUCTURE_INVARIANCE]
    assert check.result is CheckResult.PASS
    assert check.measurements == {"blocks": len(blocks), "length_deltas": 0}


def test_occurrences_equal_sites_across_pages(diodes):
    pages = set()
    for sub in diodes.ledger.substitutions:
        assert sub.occurrences == len(sub.sites)
        pages.update(s.page for s in sub.sites)
    assert pages == {3, 4, 5}


# ---------------------------------------------------------------- unclassified
def test_a_form_number_outside_every_classed_block_is_reported_not_substituted(
        blocks, allowlist):
    assert "DIC-034" in "\n".join(b.text for b in blocks)
    lenient = _run(blocks, allowlist, strict=False)
    assert "DIC-034" in lenient.unclassified
    assert "DIC-034" in lenient.text
    assert lenient.ledger.substitution_for("DIC-034") is None
    strict = _run(blocks, allowlist, strict=True)
    leak = strict.ledger.verification.checks[CheckName.LEAK_TEST]
    assert leak.result is CheckResult.REFUSED
    assert "unclassified" in leak.detail
    assert strict.ledger.committable is False


def test_page_furniture_is_not_a_candidate(allowlist):
    out = _run([Block("Page 2 of 6 DIC-034 R5", 1, "body_text")], allowlist)
    assert out.unclassified == ("DIC-034",)
    assert out.text == "Page 2 of 6 DIC-034 R5"


# ---------------------------------------------------------------- the measured run
def test_the_measured_diodes_run(blocks, allowlist, diodes):
    src_text = "\n".join(b.text for b in blocks)
    ledger = diodes.ledger
    # every [Table] MPN substituted: none of the originals survives in the text
    leak = ledger.verification.checks[CheckName.LEAK_TEST]
    assert leak.measurements["hits"] == 0
    assert leak.measurements["originals"] == len(ledger.substitutions) == 491
    assert len(diodes.unclassified) == 9
    # the captions, dates and manufacturer verbatim under RECOMMENDED_POLICY
    for n, tail in ((1, "Life-time Buy Opportunity and Replacement Parts"),
                    (2, "Life-time Buy Opportunity and No Replacement Parts"),
                    (3, "No Life-time Buy Opportunity and No Replacement Parts")):
        cap = f"Table {n} - EOL Devices with {tail}"
        assert diodes.text.count(cap) == src_text.count(cap) >= 1
    for date in ("06/25/2024", "6/16/2021"):
        assert diodes.text.count(date) == src_text.count(date) >= 1
    assert diodes.text.count("Diodes Incorporated") == \
        src_text.count("Diodes Incorporated") >= 1
    by_rule = {}
    for a in ledger.allowlisted:
        by_rule[a.rule.value] = by_rule.get(a.rule.value, 0) + a.count
    assert by_rule == {"caption": 6, "date": 10, "header_vocabulary": 9,
                       "manufacturer_name": 22, "notice_type_or_status": 21}
    assert sum(s.occurrences for s in ledger.substitutions) >= 491


# ---------------------------------------------------------------- policy honoured
def test_policy_manufacturer_scrubbed_drops_the_manufacturer_rule(
        blocks, allowlist, tmp_path):
    """Honoured at run time, not merely stored. A manufacturer name that is also
    part-shaped survives under ALLOWLISTED and is substituted under SCRUBBED."""
    body = open(YAML_PATH, encoding="utf-8").read().replace(
        '      - "Diodes"\n', '      - "Diodes"\n      - "Acme2Corp"\n')
    p = tmp_path / "al.yaml"
    p.write_bytes(body.encode("utf-8"))
    al = Allowlist.load(p)
    row = Block("Acme2Corp FJ3330013", 1, "table_cell", row=0, col=0,
                scrub_class=SubstitutionClass.MPN_AFFECTED)
    kept = _run([row], al)
    assert kept.text.startswith("Acme2Corp ")
    assert any(a.rule is AllowlistRule.MANUFACTURER_NAME
               for a in kept.ledger.allowlisted)
    pol = RECOMMENDED_POLICY.model_copy(
        update={"manufacturer_name": PolicyAnswer.SCRUBBED})
    gone = _run([row], al, policy=pol)
    assert not gone.text.startswith("Acme2Corp")
    assert gone.ledger.policy.manufacturer_name is PolicyAnswer.SCRUBBED
    assert not any(a.rule is AllowlistRule.MANUFACTURER_NAME
                   for a in gone.ledger.allowlisted)


def test_policy_dates_scrubbed_drops_the_date_rule(blocks, allowlist):
    pol = RECOMMENDED_POLICY.model_copy(update={"dates": PolicyAnswer.SCRUBBED})
    out = _run(blocks, allowlist, policy=pol)
    assert not any(a.rule is AllowlistRule.DATE for a in out.ledger.allowlisted)
    assert "LTB scoring cannot come off" in \
        out.ledger.verification.checks[CheckName.LEAK_TEST].detail
    on = _run(blocks, allowlist)
    assert any(a.rule is AllowlistRule.DATE for a in on.ledger.allowlisted)


def test_policy_one_way_keeps_no_mapping_and_retained_does(allowlist):
    row = Block("FJ3330013", 1, "table_cell", row=0, col=0,
                scrub_class=SubstitutionClass.MPN_AFFECTED)
    one_way = _run([row], allowlist)
    assert one_way.mapping is None
    assert one_way.ledger.scrub.mapping_ref is None
    kept_policy = RECOMMENDED_POLICY.model_copy(
        update={"mapping": MappingPolicy.RETAINED})
    with pytest.raises(ValueError, match="mapping_ref"):
        _run([row], allowlist, policy=kept_policy)
    kept = _run([row], allowlist, policy=kept_policy,
                mapping_ref="secret-store/mapping-key-name")
    assert kept.mapping == {
        "FJ3330013": kept.ledger.substitutions[0].replacement}
    assert kept.ledger.scrub.mapping_ref == "secret-store/mapping-key-name"
    with pytest.raises(ValueError, match="one-way"):
        _run([row], allowlist, mapping_ref="x")


def test_enters_scored_corpus_is_recorded(allowlist):
    assert _run([Block("FJ3330013", 1, "table_cell", row=0, col=0,
                       scrub_class=SubstitutionClass.MPN_AFFECTED)],
                allowlist).ledger.policy.enters_scored_corpus is False


# ---------------------------------------------------------------- reuse seal
def test_the_candidate_tokeniser_is_the_table_text_layer_one(blocks):
    """Reused, not copied: the two cannot disagree on the diodes fixture."""
    from doc_tools.scrub import scrubber
    from doc_tools.utils.table_text_layer import _DOC_TOKEN, _TOKEN_TRAILERS

    for b in blocks:
        expect = [t.rstrip(_TOKEN_TRAILERS) for t in _DOC_TOKEN.findall(b.text)]
        expect = [t for t in expect if t]
        assert [t for _s, _e, t in scrubber._tokens(b.text)] == expect


def test_the_salt_never_reaches_the_ledger(diodes):
    assert SALT.decode() not in diodes.ledger.model_dump_json()
    assert diodes.ledger.scrub.salt_ref == SALT_REF
