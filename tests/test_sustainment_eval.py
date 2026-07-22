"""Eval harness for sustainment affected-part extraction: precision/recall.

The scoring is pure-Python and tested now (self-tests below). `score_run()`
scores real model output against the labeled eval set once (a) the eval labels
are finalized under tests/fixtures/sustainment/eval.json and (b) an extraction
run has written extraction.json files — until then the fixture test skips.

Ground-truth independence: eval labels are produced by an independent strong
model + human verification, NEVER by the gpt-oss/Gemma systems under test (see
the eval fixture's _meta.label_provenance). Do not regenerate labels with the
pipeline being evaluated — that makes the eval circular.
"""
import json
import os

import pytest


def part_pr(expected_mpns, predicted_mpns):
    """Precision / recall / f1 on affected_mpn sets (exact string match)."""
    exp, pred = set(expected_mpns), set(predicted_mpns)
    tp = len(exp & pred)
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(exp) if exp else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"tp": tp, "fp": len(pred - exp), "fn": len(exp - pred),
            "precision": precision, "recall": recall, "f1": f1}


def score_run(eval_path, extraction_dir):
    """Aggregate part precision/recall of a run against the eval set.

    extraction_dir holds one <doc_id>.json (an extraction.json) per eval doc,
    keyed by a sanitized doc_id. Reported per-doc AND micro-averaged over
    part-rows (one 3,000-row doc must not be drowned out by singletons — we
    report both). Returns (per_doc, aggregate).
    """
    data = json.load(open(eval_path, encoding="utf-8"))
    per_doc, all_exp, all_pred = [], set(), set()
    for d in data["docs"]:
        exp = d["expected"]
        gold = exp.get("impacted_parts") or exp.get("impacted_parts_sample_unverified") or []
        gold_mpns = [p["affected_mpn"] for p in gold]
        did = exp["header"]["doc_id"]
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in did)
        pred_path = os.path.join(extraction_dir, f"{safe}.json")
        pred_mpns = []
        if os.path.exists(pred_path):
            pj = json.load(open(pred_path, encoding="utf-8"))
            for aug in pj.get("augmentations", []):
                notice = aug.get("notice", aug)
                for p in notice.get("impacted_parts", []):
                    pred_mpns.append(p.get("affected_mpn"))
        r = part_pr(gold_mpns, pred_mpns)
        r["doc_id"] = did
        per_doc.append(r)
        all_exp |= {(did, m) for m in gold_mpns}
        all_pred |= {(did, m) for m in pred_mpns}
    aggregate = part_pr(all_exp, all_pred)
    return per_doc, aggregate


# --------------------------------------------------------------------------- #
# self-tests of the metric (run now)
# --------------------------------------------------------------------------- #
def test_part_pr_math():
    r = part_pr(["A", "B", "C"], ["A", "B", "D"])
    assert r["tp"] == 2 and r["fp"] == 1 and r["fn"] == 1
    assert abs(r["precision"] - 2 / 3) < 1e-9 and abs(r["recall"] - 2 / 3) < 1e-9


def test_part_pr_edge_cases():
    assert part_pr([], [])["precision"] == 0.0
    assert part_pr(["A"], [])["recall"] == 0.0
    assert part_pr(["A", "A", "B"], ["A", "B"])["recall"] == 1.0  # set-dedup


# --------------------------------------------------------------------------- #
# fixture well-formedness (skips until the labeled set is moved into place)
# --------------------------------------------------------------------------- #
_EVAL = os.path.join(os.path.dirname(__file__), "fixtures", "sustainment", "eval.json")


@pytest.mark.skipif(not os.path.exists(_EVAL), reason="labeled eval set not present yet")
def test_eval_fixture_is_well_formed():
    data = json.load(open(_EVAL, encoding="utf-8"))
    assert "docs" in data and data["docs"]
    for d in data["docs"]:
        exp = d["expected"]
        assert exp["header"]["doc_type"] in ("PCN", "PDN")
        assert ("impacted_parts" in exp) or ("impacted_parts_sample_unverified" in exp)
