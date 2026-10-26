#!/usr/bin/env python
"""One-time backfill: mirror Section-HAS_CHILD->Slide into Section-HAS_SLIDE->Slide.

Contract training-workbench.md 4.1 / 4.2. ``TrainingPlugin.execute_pass2_rollup``
now writes the overlay edge (HAS_SLIDE) beside HAS_CHILD; courses ingested before
that carry only HAS_CHILD. This mirrors the existing edges under the SAME course
and the SAME page range, in one statement.

Run by hand in the sandbox doc-tools pod (NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD
come from the pod env and are never printed; this prints counts only):

    python /tmp/training_has_slide_backfill.py            # dry run, writes nothing
    python /tmp/training_has_slide_backfill.py --apply    # write, then verify

Exit: 0 ok, 1 a post-apply check failed, 2 refused (R1 or X1 > 0).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from doc_tools.utils.graph_overlay import overlay_for  # noqa: E402

EDGE = overlay_for("training").edge

# The plugin's link-query predicate, verbatim modulo whitespace. A test compares it.
RANGE_PREDICATE = "s.number >= sec.start_page AND (sec.end_page = 0 OR s.number <= sec.end_page)"

_REACH = ("MATCH (c:Course:TRAINING)-[:HAS_SECTION*]->(sec:Section:TRAINING)"
          "-[:HAS_CHILD]->(s:Slide:TRAINING)")

COUNT_QUERIES = {
    "B1": "MATCH (:Section:TRAINING)-[r:HAS_CHILD]->(:Slide:TRAINING) RETURN count(r) AS n",
    "B2": f"MATCH (:Section:TRAINING)-[r:{EDGE}]->(:Slide:TRAINING) RETURN count(r) AS n",
    "B3": f"MATCH (:Course:TRAINING)-[r:{EDGE}]->(:Slide:TRAINING) RETURN count(r) AS n",
    "B4": "MATCH (:Course:TRAINING)-[r:HAS_CHILD]->(:Slide:TRAINING) RETURN count(r) AS n",
    "B5": "MATCH (:Slide:TRAINING)-[r:TEACHES]->(:Concept:TRAINING) RETURN count(r) AS n",
    "B6": "MATCH (:Section:TRAINING)-[r:COVERS]->(:Concept:TRAINING) RETURN count(r) AS n",
    "B7": "MATCH (n:Course:TRAINING) RETURN count(n) AS n",
    "B8": "MATCH (n:Section:TRAINING) RETURN count(n) AS n",
    "B9": "MATCH (n:Slide:TRAINING) RETURN count(n) AS n",
}
# Must not move across an --apply.
UNCHANGED = ("B1", "B3", "B4", "B5", "B6", "B7", "B8", "B9")

# R1: in-reach pairs outside the range (expected 0).
R1_QUERY = f"""
{_REACH}
WHERE (c)-[:HAS_CHILD]->(s)
  AND NOT ({RANGE_PREDICATE})
WITH DISTINCT sec, s
RETURN count(*) AS n
"""

# X1: pairs whose slide is not a HAS_CHILD of any course reaching the section (expected 0).
X1_QUERY = """
MATCH (sec:Section:TRAINING)-[:HAS_CHILD]->(s:Slide:TRAINING)
WHERE NOT EXISTS {
  MATCH (c:Course:TRAINING)-[:HAS_SECTION*]->(sec)
  WHERE (c)-[:HAS_CHILD]->(s)
}
WITH DISTINCT sec, s
RETURN count(*) AS n
"""

# In-range pairs lacking a twin: the dry run's "would create"; 0 after --apply.
MISSING_QUERY = f"""
{_REACH}
WHERE (c)-[:HAS_CHILD]->(s)
  AND {RANGE_PREDICATE}
  AND NOT (sec)-[:{EDGE}]->(s)
WITH DISTINCT sec, s
RETURN count(*) AS n
"""

# Distinct Section->Slide overlay pairs vs raw edges (equal when no duplicate edge).
PAIRS_QUERY = f"""
MATCH (sec:Section:TRAINING)-[r:{EDGE}]->(s:Slide:TRAINING)
WITH sec, s, count(r) AS k
RETURN count(*) AS pairs, sum(k) AS edges
"""

# THE single write.
WRITE_QUERY = f"""
MATCH (c:Course:TRAINING)-[:HAS_SECTION*]->(sec:Section:TRAINING)-[:HAS_CHILD]->(s:Slide:TRAINING)
WHERE (c)-[:HAS_CHILD]->(s)
  AND {RANGE_PREDICATE}
WITH DISTINCT sec, s
MERGE (sec)-[:{EDGE}]->(s)
RETURN count(*) AS mirrored
"""


def _n(client, query, key="n") -> int:
    rows = client.execute_query(query)
    return int(rows[0][key]) if rows else 0


def _counts(client) -> dict:
    return {k: _n(client, q) for k, q in COUNT_QUERIES.items()}


def _show(label: str, d: dict) -> None:
    print(label + " " + " ".join(f"{k}={v}" for k, v in d.items()))


def main(argv=None, client=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    args = ap.parse_args(argv)

    if client is None:
        from doc_tools.utils.neo4j_client import Neo4jClient
        client = Neo4jClient()  # credentials from the environment, never printed

    before = _counts(client)
    r1 = _n(client, R1_QUERY)
    x1 = _n(client, X1_QUERY)
    missing = _n(client, MISSING_QUERY)
    _show("BEFORE", before)
    print(f"R1 out-of-range pairs={r1} (expect 0)  X1 cross-course pairs={x1} (expect 0)")
    print(f"HAS_CHILD pairs lacking a {EDGE} twin (would create)={missing}")

    if not args.apply:
        print("DRY RUN: nothing written")
        return 0
    if r1 > 0 or x1 > 0:
        print(f"REFUSED: R1={r1} X1={x1}; the mirror would not equal HAS_CHILD. Nothing written.")
        return 2

    rows = client.execute_query(WRITE_QUERY)
    mirrored = int(rows[0]["mirrored"]) if rows else 0
    after = _counts(client)
    pairs = client.execute_query(PAIRS_QUERY)
    pairs_n = int(pairs[0]["pairs"]) if pairs else 0
    edges_n = int(pairs[0]["edges"]) if pairs and pairs[0]["edges"] is not None else 0
    lacking = _n(client, MISSING_QUERY)
    _show("AFTER ", after)
    print(f"mirrored (matched/merged pairs)={mirrored} created={after['B2'] - before['B2']}")

    checks = [(f"B2_after == distinct {EDGE} pairs ({after['B2']} vs {pairs_n}, edges {edges_n})",
               after["B2"] == pairs_n == edges_n),
              (f"in-range HAS_CHILD pairs lacking a twin == 0 (got {lacking})", lacking == 0)]
    checks += [(f"{k} unchanged ({before[k]} -> {after[k]})", before[k] == after[k])
               for k in UNCHANGED]
    ok = True
    for name, passed in checks:
        print(("PASS " if passed else "FAIL ") + name)
        ok = ok and passed
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
