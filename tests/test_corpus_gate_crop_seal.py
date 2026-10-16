"""The crop seal has to be READABLE from the gate's authority artifact.

Three fires on pin sha256:85ad4c9d exited 1 while fire 1 scored 522/522 parts: the
term that failed was the crop seal's `repaired_cut_tables`, and `docs/corpus-gate/
latest.json` carried no copy of that number at all. It recorded `seal_checked`, which
says the term was *evaluated*, and nothing about what the seal *measured* -- so the
report could show a red fire without saying the crops, not the parts, made it red.

The assertions here are about what survives and what a zero is allowed to mean, not
about layout:

  * an unread seal is UNMEASURED, never clean (the same None-vs-{} rule the rates
    block already enforces),
  * the maximum per counter is the number that decided the verdict, since the exit
    criterion must hold on EVERY fire,
  * fires that disagree on a counter say so, and the per-fire detail is kept.
"""

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load("pcn_corpus_gate")


def _totals(repaired_tables=0, repaired_words=0, errors=0,
            stored_tables=2, stored_words=17, n_tables=37):
    """A seal document's `totals`, shaped as pcn_crop_seal.seal_corpus emits it.

    The defaults are the real GREEN corpus measurement with rule 7 in place:
    37 tables, 2 stored cuts, both repaired, nothing cut after the repair.
    """
    return {
        "n_tables": n_tables,
        "stored_cut_tables": stored_tables, "stored_cut_words": stored_words,
        "repaired_cut_tables": repaired_tables, "repaired_cut_words": repaired_words,
        "errors": errors,
        # The by_edge companions ride along in the real file and are deliberately
        # NOT aggregated: a per-edge maximum across fires would be a figure no
        # single fire measured. They must not break the aggregation.
        "repaired_cut_tables_by_edge": {"left": 0, "top": repaired_tables,
                                        "right": 0, "bottom": 0},
        "stored_cut_tables_by_edge": {"left": 0, "top": 1, "right": 0, "bottom": 1},
    }


def test_no_seal_read_is_unmeasured_not_zero():
    block = gate.aggregate_seal_totals({1: None, 2: None, 3: None})
    assert block["fires"] == []
    assert block["fires_missing"] == [1, 2, 3]
    # The crux: NO counter is reported. A `totals` of all-zeros here would read as
    # "the seal found nothing wrong" about a seal that was never opened.
    assert block["totals"] == {}
    text = gate._render_crop_seal_block(block)
    assert "not observed" in text
    assert "UNMEASURED, not clean" in text
    assert "f1, f2, f3" in text


def test_worst_case_per_counter_is_what_decided_the_verdict():
    block = gate.aggregate_seal_totals({
        1: _totals(),                                    # green
        2: _totals(repaired_tables=1, repaired_words=4),  # the fire that failed
        3: _totals(),
    })
    assert block["fires"] == [1, 2, 3]
    assert block["totals"]["repaired_cut_tables"] == 1
    assert block["totals"]["repaired_cut_words"] == 4
    assert block["totals"]["errors"] == 0
    # Context survives next to the gate terms.
    assert block["totals"]["stored_cut_tables"] == 2
    assert block["totals"]["n_tables"] == 37
    # And the fire that produced the max is still identifiable.
    assert block["by_fire"]["repaired_cut_tables"] == {1: 0, 2: 1, 3: 0}
    assert block["agreement"] is False


def test_a_read_seal_alongside_an_unread_one_keeps_both_facts():
    block = gate.aggregate_seal_totals({1: _totals(), 2: None})
    assert block["fires"] == [1]
    assert block["fires_missing"] == [2]
    # Fire 2 contributes nothing -- not a zero that would drag a maximum down, and
    # not a denominator.
    assert block["by_fire"]["repaired_cut_tables"] == {1: 0}
    text = gate._render_crop_seal_block(block)
    assert "fires NOT read: f2" in text
    assert "unmeasured, not zero" in text


def test_agreement_is_true_only_when_every_counter_matches():
    agree = gate.aggregate_seal_totals({1: _totals(), 2: _totals()})
    assert agree["agreement"] is True
    # A fire that saw a different TABLE POPULATION is a disagreement too: the two
    # fires did not measure the same thing, and the maximum is then not a shared
    # denominator.
    differ = gate.aggregate_seal_totals({1: _totals(), 2: _totals(n_tables=36)})
    assert differ["agreement"] is False
    assert differ["totals"]["n_tables"] == 37


def test_the_rendered_block_marks_the_two_gate_terms():
    text = gate._render_crop_seal_block(
        gate.aggregate_seal_totals({1: _totals(), 2: _totals()}))
    lines = {ln.split()[0]: ln for ln in
             (x.strip() for x in text.splitlines()) if ln.split()}
    # Only `repaired_cut_tables` and `errors` are allowed to be nonzero-fatal, and a
    # reader must not have to know which of the six numbers those are.
    assert "GATE TERM" in lines["repaired_cut_tables"]
    assert "GATE TERM" in lines["errors"]
    assert "GATE TERM" not in lines["stored_cut_tables"]
    assert "GATE TERM" not in lines["n_tables"]
    # stored_cut_* must not read as a failure: it counts cuts the repair FIXED.
    assert "work done, not a failure" in text


def test_every_seal_counter_reaches_the_report():
    """SEAL_COUNTERS is the report's contract with pcn_crop_seal's totals.

    A counter named here but absent from the seal document would silently render 0 --
    the clean-looking zero this whole file exists to prevent -- so the two lists are
    checked against each other rather than trusted.
    """
    sealed = _totals()
    for counter in gate.SEAL_COUNTERS:
        assert counter in sealed, f"{counter} is not a key pcn_crop_seal emits"
    # Both exit terms of pcn_corpus_run.py's criterion are carried.
    assert "repaired_cut_tables" in gate.SEAL_COUNTERS
    assert "errors" in gate.SEAL_COUNTERS
