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
    assert len(gt) == 10
    for fn, e in gt.items():
        assert len(e["mpns"]) == e["count"], fn
        assert len(set(e["mpns"])) == e["count"], f"{fn} has duplicate MPNs"
        assert all(m and m.strip() for m in e["mpns"]), fn
    # 522, and there are exactly THREE legitimate reasons for this number to move.
    #
    # A CORRECTION, where a count in the JSON was wrong. 898 is the standing example:
    # two tier-1 cells in TYC-PCN-24-210412.pdf each held two real MPNs glued by
    # comma+newline and were carried here as one string apiece, so splitting them into
    # their four parts on 2026-09-24 raised TYC's count 24 -> 26 and took the corpus
    # 896 -> 898. Reports dated before that keep their 896. Note the direction a
    # correction moves the score: 895/896 became 893/898. A correction lowers it; a
    # tune raises it, which is the thing this assert exists to catch.
    #
    # A WIDENING, where documents are ADDED. 898 -> 924 on 2026-10-10 is that case:
    # TI_PCN_20210316000.pdf (9) and IDT_PDN_OV-19-05.pdf (17). A widening raises the
    # denominator by exactly the new entries' counts and says nothing whatever about
    # the numerator, so a score measured at 924 is NOT comparable to one measured at
    # 898 -- cite the denominator with every figure.
    #
    # A DEDUP, where ground truth double-counted one document. 924 -> 522 on 2026-10-12:
    # Diodes_PCN_2683_FULLGREEN.pdf is byte-identical to Diodes_PCN_2683_Rev1_EOL.pdf
    # (one sha256), so its 402 parts were counted twice. Every part number stayed;
    # only the denominator fell, so a score at 522 is NOT comparable to one at 924.
    #
    # If you are here because this assert went red, say which of the three you did. An
    # edit that is neither is a tune, and the number was right before you touched it.
    assert sum(e["count"] for e in gt.values()) == 522


def test_shipped_ground_truth_declares_its_provenance():
    raw = json.loads((SCRIPTS / "pcn_ground_truth.json").read_text(encoding="utf-8"))
    assert raw["_construction"].strip()
    for fn, e in raw["notices"].items():
        assert e.get("source"), f"{fn} does not say where its ground truth came from"


# ------------------------------------------------------------------------- #
# `expect_absent_mpns` -- a part ground truth ANTICIPATED being wrongly
# emitted. Added 2026-10-10 for TI's page-2 customer part numbers, which the
# DEVICES-ONLY ruling excludes while NOTHING IN THE EXTRACTOR implements that
# ruling: page 2 is excluded only because find_tables() sees no table there.
# The class exists so that change failing is legible, not so it fails at all --
# `spurious` already failed it.
# ------------------------------------------------------------------------- #

def test_a_ruled_out_part_is_named_and_still_counts_as_spurious():
    """The whole point: naming it must not EXCUSE it.

    If `ruled_out` were carved out of `spurious`, this scorer would report a run
    that emitted all 11 of TI's customer part numbers as having nothing spurious,
    and `main`'s verdict -- `not t["spurious"]` -- would go green on it. So the
    part is counted in both, and this test is what stops that regression.
    """
    gt = _gt(["A-1", "B-2"])
    gt["expect_absent_mpns"] = ["RULED-1", "RULED-2"]
    s = pcn_score.score_notice(["A-1", "B-2", "RULED-1"], gt)

    assert s["ruled_out"] == ["RULED-1"]
    assert "RULED-1" in s["spurious"], "a named part must still be spurious"
    assert s["clean"] is False
    assert s["exact"] == 2, "the ruling violation must not cost real recall"


def test_a_clean_run_reports_no_ruled_out_parts():
    gt = _gt(["A-1"])
    gt["expect_absent_mpns"] = ["RULED-1"]
    s = pcn_score.score_notice(["A-1"], gt)
    assert s["ruled_out"] == [] and s["clean"] is True


def test_a_notice_without_the_key_scores_exactly_as_before():
    s = pcn_score.score_notice(["A-1", "X-9"], _gt(["A-1"]))
    assert s["ruled_out"] == [] and s["spurious"] == ["X-9"]


def test_requiring_and_ruling_out_the_same_part_is_a_ground_truth_defect():
    """Not a scoring outcome -- an abort. Either state is scoreable; both at once
    is a contradiction in the file, and silently preferring one hides it."""
    gt = _gt(["A-1"])
    gt["expect_absent_mpns"] = ["A-1"]
    with pytest.raises(ValueError, match="ground truth defect"):
        pcn_score.score_notice(["A-1"], gt)


def test_a_ruled_out_emission_is_rendered_under_its_own_name():
    gt = _gt(["A-1"])
    gt["expect_absent_mpns"] = ["RULED-1"]
    scored = {"per_notice": {"n.pdf": pcn_score.score_notice(["A-1", "RULED-1"], gt)},
              "totals": {"gt": 1, "exact": 1, "spurious": 1, "missing": 0,
                         "malformed": 0, "ruled_out": 1, "emitted": 2},
              "header_totals": None}
    text = pcn_score.render(scored)
    assert "RULED OUT by ground truth" in text
    assert "RULED-1" in text


def test_the_shipped_ruling_on_ti_page_two_is_carried_as_data():
    """The DEVICES-ONLY ruling, asserted against the shipped file.

    11 distinct customer part numbers, disjoint from the 9 devices. If someone
    decides the ruling the other way, this test is the place that says so out
    loud -- and `source` and `_expect_absent_why` must be edited with it.
    """
    raw = json.loads((SCRIPTS / "pcn_ground_truth.json").read_text(encoding="utf-8"))
    ti = raw["notices"]["TI_PCN_20210316000.pdf"]
    ruled = ti["expect_absent_mpns"]

    assert len(ruled) == len(set(ruled)) == 11
    assert not set(ruled) & set(ti["mpns"])
    assert ti["count"] == 9 and len(ti["mpns"]) == 9
    assert ti["_expect_absent_why"].strip()


def test_every_ruled_out_list_in_the_file_is_disjoint_from_its_own_parts():
    raw = json.loads((SCRIPTS / "pcn_ground_truth.json").read_text(encoding="utf-8"))
    for fn, e in raw["notices"].items():
        ruled = set(e.get("expect_absent_mpns") or ())
        assert not ruled & set(e["mpns"]), f"{fn} both requires and rules out a part"
        if ruled:
            assert e.get("_expect_absent_why"), f"{fn} rules parts out without saying why"
