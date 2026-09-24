"""Tests for the corpus scorer.

The scorer exists because a count could not see a substitution, so the case that
matters most here is the substitution case: one part out, one wrong part in,
count unchanged. If `test_substitution_is_not_a_pass` ever goes green while
reporting a clean run, the instrument has regressed to what it replaced.

Imported by path rather than as a package: `scripts/` is not importable, and
adding an `__init__.py` to it would make a measurement harness look like library
code.
"""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pcn_score = _load("pcn_score")


def _gt(mpns, count=None, malformed=()):
    return {"count": count if count is not None else len(mpns),
            "mpns": list(mpns), "malformed": list(malformed)}


def test_perfect_run_is_clean():
    s = pcn_score.score_notice(["A-1", "B-2"], _gt(["A-1", "B-2"]))
    assert s["exact"] == 2
    assert s["spurious"] == [] and s["missing"] == [] and s["malformed"] == []
    assert s["clean"] is True


def test_substitution_is_not_a_pass():
    """The 2026-09-23 PCN23-002 case: SYTX9 missing, SYTYD emitted, count 18 both ways."""
    gt = _gt([f"P-{i}" for i in range(17)] + ["SYTX9-122HP-1+"])
    emitted = [f"P-{i}" for i in range(17)] + ["SYTYD-122HP-1+"]
    s = pcn_score.score_notice(emitted, gt)

    assert s["emitted"] == 18 and s["count"] == 18      # the count balances...
    assert s["exact"] == 17                             # ...and the score does not
    assert s["spurious"] == ["SYTYD-122HP-1+"]
    assert s["missing"] == ["SYTX9-122HP-1+"]
    assert s["clean"] is False


def test_missing_and_spurious_are_independent():
    s = pcn_score.score_notice(["A-1", "X-9"], _gt(["A-1", "B-2", "C-3"]))
    assert s["exact"] == 1
    assert s["spurious"] == ["X-9"]
    assert s["missing"] == ["B-2", "C-3"]


def test_duplicate_emission_is_not_credited_twice():
    s = pcn_score.score_notice(["A-1", "A-1"], _gt(["A-1", "B-2"]))
    assert s["exact"] == 1
    assert s["emitted"] == 2 and s["distinct"] == 1
    assert s["missing"] == ["B-2"]


@pytest.mark.parametrize("mpn,bad", [
    ("TYC1056344-1,\n9501815SP-1", True),   # two part numbers in one cell
    ("160303P1,160303P001", True),          # same, comma only
    ("A-1\tB-2", True),
    ("A-1  B-2", True),                     # concatenated cell text
    ("SYTX9-122HP-1+", False),              # plus signs are legitimate
    ("NSR20F30WC1NXT5G", False),
    ("BYV34-400", False),
    ("1052926-1", False),
    ("ABC/DEF.1", False),                   # slashes and dots are legitimate
])
def test_malformed_markers(mpn, bad):
    assert pcn_score.is_malformed(mpn) is bad


def test_malformed_is_reported_without_being_called_spurious():
    """Real content, wrong shape: it is in ground truth, so it is not spurious."""
    composite = "TYC1056344-1,\n9501815SP-1"
    s = pcn_score.score_notice(["A-1", composite], _gt(["A-1", composite]))
    assert s["exact"] == 2
    assert s["spurious"] == [] and s["missing"] == []
    assert s["malformed"] == [composite]
    assert s["clean"] is False          # still not a clean run


def test_failed_notice_counts_every_part_as_missing():
    gt = {"n.pdf": _gt(["A-1", "B-2"])}
    scored = pcn_score.score_run({"n.pdf": {"ok": False, "error": "boom"}}, gt)
    p = scored["per_notice"]["n.pdf"]
    assert p["exact"] == 0 and p["missing"] == ["A-1", "B-2"]
    assert scored["totals"]["exact"] == 0


def test_absent_notice_is_not_silently_skipped():
    scored = pcn_score.score_run({}, {"n.pdf": _gt(["A-1"])})
    assert scored["per_notice"]["n.pdf"]["error"] == "notice absent from run"
    assert scored["totals"]["missing"] == 1


def test_shipped_ground_truth_is_self_consistent():
    gt = pcn_score.load_ground_truth()
    assert len(gt) == 9
    for fn, e in gt.items():
        assert len(e["mpns"]) == e["count"], fn
        assert len(set(e["mpns"])) == e["count"], f"{fn} has duplicate MPNs"
        assert all(m and m.strip() for m in e["mpns"]), fn
    assert sum(e["count"] for e in gt.values()) == 896


def test_shipped_ground_truth_declares_its_provenance():
    raw = json.loads((SCRIPTS / "pcn_ground_truth.json").read_text(encoding="utf-8"))
    assert raw["_construction"].strip()
    for fn, e in raw["notices"].items():
        assert e.get("source"), f"{fn} does not say where its ground truth came from"
