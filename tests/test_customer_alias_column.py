"""The customer-alias column: `customer_mpn`, ruled 2026-10-29.

A "Customer Part Number" column is never an affected part. It is the customer's own
id for the affected part printed beside it. The ruling makes it a row field, paired
positionally to `affected_mpn`, reviewable, exportable through the catalogue, and
scored by the corpus scorer as its OWN column with its own denominator.

What is pinned here:

  * the SPLIT, because a customer cell can hold two ids for one affected part and
    tier 1 carries such a cell verbatim on purpose -- splitting it in the extractor
    would duplicate the affected part and move the parts denominator;
  * the DENOMINATOR, which counts only the notices that declare the column (8 of
    the 10 have no customer column at all, which is not a zero);
  * and the thing the ruling turns on: that this column is ADVISORY and cannot
    fail the corpus gate. TI's eleven aliases sit on a page `find_tables()` returns
    zero tables for under both the `lines` and the `text` strategy, so a blocking
    term would be a red no change to the extractor could clear.

The column veto itself (`pair_columns` / `customer_columns`) is pinned in
tests/test_table_text_layer.py, and the real pages in tests/test_ti_pcn_live_miss.py.

No cluster, no S3, no network. The scripts are loaded by path, as the sibling
corpus-gate tests do.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


score = _load("pcn_score")
gate = _load("pcn_corpus_gate")

TYC = "TYC-PCN-24-210412.pdf"
TI = "TI_PCN_20210316000.pdf"


# --------------------------------------------------------------------------- #
# The shipped ground truth, not a copy of it.

def _gt():
    return score.load_ground_truth()


def test_exactly_two_notices_declare_a_customer_column():
    """8 of the 10 have no such column. That is ABSENT, not zero -- the distinction
    the denominator below rests on."""
    gt = _gt()
    declaring = sorted(fn for fn, e in gt.items() if e.get("customer_mpns"))
    assert declaring == sorted([TI, TYC]), declaring
    assert len(gt[TYC]["customer_mpns"]) == 10
    assert len(gt[TI]["customer_mpns"]) == 11


def test_no_value_is_both_an_affected_part_and_a_customer_alias():
    """The whole ruling in one assertion. Before it, TYC's 10 were counted as
    affected parts and TI's same-shaped 11 were ruled out -- one column meaning two
    things in one corpus."""
    for fn, e in _gt().items():
        both = set(e["mpns"]) & set(e.get("customer_mpns") or ())
        assert not both, f"{fn}: {sorted(both)}"


def test_the_corpus_denominator_counts_affected_parts_only():
    gt = _gt()
    assert sum(e["count"] for e in gt.values()) == 512
    # The 10 that moved are still IN the file -- a re-label, not a recall loss.
    assert len(gt[TYC]["customer_mpns"]) == 10
    assert gt[TYC]["count"] == 16


# --------------------------------------------------------------------------- #
# The split. The reason the scorer sees ids and the extractor emits cells.

def test_a_two_id_customer_cell_is_split_by_the_scorer_not_the_extractor():
    """TYC prints cells holding two customer ids for ONE affected part. Tier 1 keeps
    such a cell whole; the ids are separated here, at the one place that compares
    them to a list of ids. Without this TYC reads 6 exact / 2 spurious / 4 missing
    against a ground truth of 10 it in fact emitted in full."""
    assert score.split_customer_cell("TYC1052982-1,\nTYC1056344-1") == [
        "TYC1052982-1", "TYC1056344-1"]
    assert score.split_customer_cell("A-1; B-2") == ["A-1", "B-2"]
    assert score.split_customer_cell("  160303P1  ") == ["160303P1"]
    # Not a reading at all, and not an id:
    assert score.split_customer_cell(None) == []
    assert score.split_customer_cell("") == []
    assert score.split_customer_cell(" , ") == []


def test_the_split_applies_no_shape_floor():
    """The floor belongs to the extractor. A scorer that dropped a badly-shaped id
    would hide the misread it exists to show."""
    assert score.split_customer_cell("see note 4") == ["see note 4"]


# --------------------------------------------------------------------------- #
# score_customer: its own column, its own denominator.

def test_a_notice_with_no_customer_column_is_not_scored_at_all():
    """None, not a zeroed block. `clean: False` on the 8 notices that have no such
    column would be 8 invented failures."""
    assert score.score_customer([], {"mpns": ["A"], "count": 1}) is None


def test_an_empty_declaration_is_a_claim_and_not_an_absence():
    """A MISSING `customer_mpns` key means "this notice has no customer column".
    An `customer_mpns: []` means "it was examined and has none" -- a positive
    claim, so an alias emitted against it is spurious and must be reported. The two
    are kept apart deliberately: the second is how a future notice records that its
    customer-looking column was checked and holds nothing."""
    declared_empty = {"mpns": ["A"], "count": 1, "customer_mpns": []}
    out = score.score_customer(["X"], declared_empty)
    assert out is not None
    assert out["count"] == 0
    assert out["spurious"] == ["X"]
    assert out["clean"] is False
    # And with nothing emitted it is clean, not vacuously absent.
    assert score.score_customer([], declared_empty)["clean"] is True


def test_tycs_ten_aliases_score_clean_from_its_eight_cells():
    """The end-to-end shape of the TYC case: 8 cells, 10 ids, all 10 declared."""
    gt = _gt()[TYC]
    ids = list(gt["customer_mpns"])
    # Two cells carry two ids each, as the page prints them.
    cells = [f"{ids[0]},\n{ids[1]}", f"{ids[2]};{ids[3]}"] + ids[4:]
    assert len(cells) == 8
    out = score.score_customer(cells, gt)
    assert out["advisory"] is True
    assert out["cells"] == 8
    assert out["distinct"] == 10
    assert out["exact"] == 10
    assert out["spurious"] == [] and out["missing"] == []
    assert out["clean"] is True


def test_an_undeclared_customer_id_is_spurious_and_a_declared_one_missing():
    gt = {"mpns": ["DEV-1"], "count": 1, "customer_mpns": ["CUST-1", "CUST-2"]}
    out = score.score_customer(["CUST-1", "WHO-9"], gt)
    assert out["exact"] == 1
    assert out["spurious"] == ["WHO-9"]
    assert out["missing"] == ["CUST-2"]
    assert out["clean"] is False


def test_tis_eleven_are_missing_today_and_that_is_the_measured_truth():
    """No tier can read TI page 2: `find_tables()` returns zero tables for it under
    both strategies. So TI's customer block is all-missing, by measurement, and this
    is exactly why the column is advisory rather than blocking."""
    gt = _gt()[TI]
    out = score.score_customer([], gt)
    assert out["exact"] == 0
    assert out["missing"] == sorted(gt["customer_mpns"])
    assert out["clean"] is False


def test_a_ground_truth_that_calls_one_value_both_things_raises():
    """Not scored around, raised on: the conflation the ruling exists to end must
    not be re-introducible by an edit to the JSON."""
    bad = {"mpns": ["X-1"], "count": 1, "customer_mpns": ["X-1"]}
    with pytest.raises(ValueError, match="both `mpns` and `customer_mpns`"):
        score.score_customer(["X-1"], bad)


def test_a_duplicate_in_the_declaration_raises():
    with pytest.raises(ValueError, match="duplicate ids"):
        score.score_customer([], {"mpns": ["A"], "count": 1,
                                  "customer_mpns": ["D-1", "D-1"]})


# --------------------------------------------------------------------------- #
# customer_totals: the denominator excludes the notices that have no column.

def test_the_totals_denominator_is_the_declaring_notices_only():
    per = {
        "a.pdf": {"customer": {"advisory": True, "count": 10, "cells": 8,
                               "distinct": 10, "exact": 10, "spurious": [],
                               "missing": [], "clean": True}},
        "b.pdf": {"customer": {"advisory": True, "count": 11, "cells": 0,
                               "distinct": 0, "exact": 0, "spurious": [],
                               "missing": ["x"] * 11, "clean": False}},
        "c.pdf": {},  # no customer column: absent from the denominator entirely
    }
    t = score.customer_totals(per)
    assert t["notices"] == 2
    assert t["gt"] == 21
    assert t["exact"] == 10
    assert t["missing"] == 11
    assert t["clean"] is False


def test_no_declaring_notice_means_not_scored_rather_than_zero():
    assert score.customer_totals({"a.pdf": {}, "b.pdf": {}}) is None


def test_score_run_attaches_the_block_to_the_declaring_notices_only():
    gt = _gt()
    results = {fn: {"ok": True, "mpns": list(e["mpns"]), "customer_mpns": []}
               for fn, e in gt.items()}
    results[TYC]["customer_mpns"] = list(gt[TYC]["customer_mpns"])
    scored = score.score_run(results, gt)
    assert "customer" in scored["per_notice"][TYC]
    assert "customer" in scored["per_notice"][TI]
    others = [fn for fn in gt if fn not in (TI, TYC)]
    assert others, "the corpus must still hold the other eight"
    for fn in others:
        assert "customer" not in scored["per_notice"][fn], fn
    ct = scored["customer_totals"]
    assert ct["notices"] == 2 and ct["gt"] == 21 and ct["exact"] == 10


def test_the_customer_column_never_touches_the_parts_verdict():
    """The parts score is unchanged by a customer red. `main`'s verdict names its
    own keys, and this proves the two do not share a `clean`."""
    gt = _gt()
    results = {fn: {"ok": True, "mpns": list(e["mpns"]), "customer_mpns": ["JUNK-1"]}
               for fn, e in gt.items()}
    scored = score.score_run(results, gt)
    assert scored["totals"]["exact"] == 512
    assert scored["totals"]["spurious"] == 0 and scored["totals"]["missing"] == 0
    assert scored["customer_totals"]["clean"] is False
    assert scored["per_notice"][TYC]["clean"] is True
    assert scored["per_notice"][TYC]["customer"]["clean"] is False


def test_the_rendered_report_says_advisory_out_loud():
    gt = _gt()
    results = {fn: {"ok": True, "mpns": list(e["mpns"]), "customer_mpns": []}
               for fn, e in gt.items()}
    text = score.render(score.score_run(results, gt))
    assert "CUSTOMER ALIASES" in text
    assert "ADVISORY" in text
    assert "0 / 21 customer aliases by exact id" in text


# --------------------------------------------------------------------------- #
# The gate. The block is reported and CANNOT block.

def _fire(tmp_path, n, customer_totals):
    corpus = {TYC: {"ok": True, "needs_review": False, "content_hash": "sha256:aaa",
                    "written_header": {"mfr": "TE Connectivity"}}}
    cp, sp = tmp_path / f"corpus_f{n}.json", tmp_path / f"score_f{n}.json"
    cp.write_text(json.dumps(corpus), encoding="utf-8")
    body = {"totals": {"exact": 1, "gt": 1, "spurious": 0, "missing": 0,
                       "malformed": 0}}
    if customer_totals is not None:
        body["customer_totals"] = customer_totals
    sp.write_text(json.dumps(body), encoding="utf-8")
    return {"n": n, "exit": 0, "started_at": "t", "ended_at": "t", "elapsed_s": 1,
            "log": f"f{n}.log", "log_path": str(tmp_path / f"f{n}.log"),
            "corpus_path": str(cp), "score_path": str(sp), "seal_path": None}


def _report(tmp_path, monkeypatch, customer_totals):
    # Isolate this arm: the other terms are other instruments' business and have
    # their own tests. Everything NOT stubbed here is the code under test.
    monkeypatch.setattr(gate, "run_header_agreement", lambda base_dir, logs: (0, ""))
    monkeypatch.setattr(gate, "check_header_correctness",
                        lambda totals, corpus: ({}, [], []))
    monkeypatch.setattr(gate, "check_declared_bytes", lambda a, b: [])
    fires = [_fire(tmp_path, n, customer_totals) for n in (1, 2, 3)]
    report, _ = gate.score_fires(str(tmp_path), fires)
    return report


RED = {"advisory": True, "notices": 2, "gt": 21, "exact": 0, "spurious": 4,
       "missing": 21, "cells": 0, "clean": False}


def test_a_red_customer_column_does_not_block_the_gate(tmp_path, monkeypatch):
    """THE LOAD-BEARING ASSERTION of the advisory ruling. If this inverts, the gate
    is red on a page no tier can read and no extractor change can clear it."""
    report = _report(tmp_path, monkeypatch, RED)
    assert report["customer_aliases"]["advisory"] is True
    assert report["customer_aliases"]["fires"][1] == RED
    assert report["blocking"] == []
    assert report["exempted"] == []
    assert report["verdict"] == "pass"
    assert report["strict_verdict"] == "pass"


def test_a_score_json_without_the_key_reads_as_not_scored(tmp_path, monkeypatch):
    """A score written before the ruling has no `customer_totals` at all. That is
    NOT SCORED, never a zero -- the same rule the header block follows."""
    report = _report(tmp_path, monkeypatch, None)
    assert report["customer_aliases"]["fires"] == {1: None, 2: None, 3: None}
    text = gate._render_customer_block(report["customer_aliases"])
    assert "NOT SCORED" in text
    assert "Not a zero" in text
    assert report["verdict"] == "pass"


def test_the_rendered_gate_block_prints_the_numbers_and_the_disclaimer():
    text = gate._render_customer_block({"advisory": True, "fires": {1: RED}})
    assert "ADVISORY" in text
    assert "0/21" in text
    assert "does NOT fail this gate" in text


def test_an_absent_block_is_an_older_gate_not_a_pass():
    text = gate._render_customer_block(None)
    assert "NOT PRESENT" in text
