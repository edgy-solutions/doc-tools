"""Score a PCN corpus run by PART NUMBER IDENTITY, never by count.

WHY THIS EXISTS. The 2026-09-23 run printed `TOTAL 896 / 896` and was recorded
as hitting ground truth exactly. It had not. `PCN23-002.pdf` returned eighteen
parts whose eighteenth was `SYTYD-122HP-1+`, a misread of `SYTX9-122HP-1+`
produced by a table crop cut 47% of the way through the glyphs of its last row.
The real part was missing and a wrong string stood in its place, so the count
balanced and the miss was reported as a pass.

A counting instrument cannot see a substitution: one out, one in, total
unchanged. That makes it worse than no instrument, because it converts a miss
into a pass and does so silently. Scoring here is therefore set comparison
against `pcn_ground_truth.json`, and `len(parts)` is never the score.

Every notice reports four numbers:

    exact     emitted MPNs that are in ground truth
    spurious  emitted MPNs that are NOT in ground truth   <- the SYTYD class
    missing   ground-truth MPNs that were not emitted     <- the SYTX9 class
    malformed emitted MPNs whose CONTENT is real but whose SHAPE is not:
              one cell carrying two part numbers, embedded newlines, stray
              enclosing punctuation. Reported separately because the value is
              on the page — it is the extraction that has not finished the job.

`exact` is the score. `spurious` and `missing` move independently and a run
where both rise by one is precisely the failure this file was written for.

USAGE

    # score a run that has just finished, or one saved earlier
    python scripts/pcn_score.py /tmp/pcn_corpus.json
    python scripts/pcn_score.py /tmp/pcn_corpus.json --json /tmp/score.json

Exit status is 0 only when every notice scores exact == count with nothing
spurious, missing or malformed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

GT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "pcn_ground_truth.json")

# A part number that arrives carrying one of these has not been cleanly
# extracted even when every character of it is real: a comma or a newline means
# the cell held more than one value and was never split, and a run of interior
# whitespace means cell text was concatenated. Kept deliberately narrow — an
# MPN legitimately contains hyphens, plus signs, slashes and dots, so none of
# those appear here.
_MALFORMED_MARKERS = ("\n", "\r", "\t", ",", "  ")


def is_malformed(mpn: str) -> bool:
    return any(m in (mpn or "") for m in _MALFORMED_MARKERS)


def load_ground_truth(path: str = GT_PATH) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["notices"]


def score_notice(emitted: List[str], gt_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Set comparison between what a notice emitted and what it should have.

    Multiplicity is deliberately ignored: ground truth is a set of distinct part
    numbers, so a notice that emits the same MPN twice is not credited twice.
    The duplicate still shows up, as `emitted` exceeding `exact + spurious`.
    """
    gt = list(gt_entry["mpns"])
    gt_set = set(gt)
    emitted_set = set(emitted)

    exact = sorted(emitted_set & gt_set)
    spurious = sorted(emitted_set - gt_set)
    missing = sorted(gt_set - emitted_set)
    malformed = sorted(m for m in emitted_set if is_malformed(m))

    return {
        "count": gt_entry["count"],
        "emitted": len(emitted),
        "distinct": len(emitted_set),
        "exact": len(exact),
        "spurious": spurious,
        "missing": missing,
        "malformed": malformed,
        "clean": not spurious and not missing and not malformed
                 and len(exact) == gt_entry["count"],
    }


def score_run(results: Dict[str, Any], gt: Dict[str, Any]) -> Dict[str, Any]:
    per: Dict[str, Any] = {}
    for fn, entry in gt.items():
        res = results.get(fn)
        if res is None:
            per[fn] = {"count": entry["count"], "error": "notice absent from run",
                       "exact": 0, "spurious": [], "missing": list(entry["mpns"]),
                       "malformed": [], "emitted": 0, "distinct": 0, "clean": False}
            continue
        if not res.get("ok"):
            per[fn] = {"count": entry["count"],
                       "error": res.get("error", "run reported failure"),
                       "exact": 0, "spurious": [], "missing": list(entry["mpns"]),
                       "malformed": [], "emitted": 0, "distinct": 0, "clean": False}
            continue
        per[fn] = score_notice([m for m in (res.get("mpns") or []) if m], entry)

    totals = {
        "gt": sum(e["count"] for e in gt.values()),
        "exact": sum(p["exact"] for p in per.values()),
        "spurious": sum(len(p["spurious"]) for p in per.values()),
        "missing": sum(len(p["missing"]) for p in per.values()),
        "malformed": sum(len(p["malformed"]) for p in per.values()),
        "emitted": sum(p["emitted"] for p in per.values()),
    }
    return {"per_notice": per, "totals": totals}


def render(scored: Dict[str, Any]) -> str:
    per, t = scored["per_notice"], scored["totals"]
    out = [f"{'notice':38} {'gt':>4} {'emit':>5} {'exact':>6} {'spur':>5} "
           f"{'miss':>5} {'malf':>5}", "-" * 72]
    for fn, p in per.items():
        out.append(f"{fn:38} {p['count']:>4} {p['emitted']:>5} {p['exact']:>6} "
                   f"{len(p['spurious']):>5} {len(p['missing']):>5} "
                   f"{len(p['malformed']):>5}"
                   + ("" if p.get("clean") else "  <<"))
    out += ["-" * 72,
            f"{'TOTAL':38} {t['gt']:>4} {t['emitted']:>5} {t['exact']:>6} "
            f"{t['spurious']:>5} {t['missing']:>5} {t['malformed']:>5}", ""]
    out.append(f"SCORE {t['exact']} / {t['gt']} by exact part number")
    if t["emitted"] != t["exact"]:
        out.append(f"      ({t['emitted']} parts emitted - that is NOT the score)")
    for fn, p in per.items():
        if p.get("error"):
            out.append(f"\n{fn}: ERROR {p['error']}")
            continue
        if p["spurious"]:
            out.append(f"\n{fn} spurious (emitted, not a real part):")
            out += [f"    {m!r}" for m in p["spurious"]]
        if p["missing"]:
            out.append(f"\n{fn} missing (real part, not emitted):")
            out += [f"    {m!r}" for m in p["missing"]]
        if p["malformed"]:
            out.append(f"\n{fn} malformed (real content, unusable shape):")
            out += [f"    {m!r}" for m in p["malformed"]]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("results", help="pcn_corpus.json from a run")
    ap.add_argument("--ground-truth", default=GT_PATH)
    ap.add_argument("--json", dest="json_out", help="also write the scored dict here")
    a = ap.parse_args()

    with open(a.results, encoding="utf-8") as f:
        results = json.load(f)
    scored = score_run(results, load_ground_truth(a.ground_truth))
    print(render(scored))
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(scored, f, indent=2)
        print(f"\nWROTE {a.json_out}")

    t = scored["totals"]
    return 0 if (t["exact"] == t["gt"] and not t["spurious"]
                 and not t["missing"] and not t["malformed"]) else 1


if __name__ == "__main__":
    sys.exit(main())
