"""Observe the contract's never_written clause for given Course ids (in-pod, READ-ONLY).

    python tr_never_written.py <out.json> <course_id> [<course_id> ...]

For each Course: any node with a forbidden label, and any forbidden relation,
reachable within 2 hops of the Course in either direction. Prints counts only.
Contract v5 also counts the alignment names only concepts.normalise may write,
on the Concepts this Course's Slides teach; under TRAINING_CONCEPT_ALIGNMENT=dry
the run writes none, so a non-zero count is a legacy edge or a broken dry mode.
"""
import json
import os
import sys

# Contract v5 never_written: the workbench-owned names.
LABELS = ["Project", "TargetNode", "User"]
RELS = ["OWNS", "SUGGESTED_SOURCE", "DERIVED_FROM"]
# Contract v5 written_only_by concepts.normalise.
ALIGN_RELS = ["ALIGNS_TO", "PROPOSED_ALIGNS_TO"]


def main(out_path, ids):
    from neo4j import GraphDatabase
    drv = GraphDatabase.driver(os.environ["NEO4J_URI"],
                               auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]))
    res = {}
    with drv.session(default_access_mode="READ") as s:
        for cid in ids:
            lab = s.run(
                "MATCH (c:Course {id: $id})-[*1..2]-(n) WHERE any(l IN labels(n) WHERE l IN $labels) "
                "RETURN count(DISTINCT n) AS n", id=cid, labels=LABELS).single()["n"]
            rel = s.run(
                "MATCH p=(c:Course {id: $id})-[*1..2]-() UNWIND relationships(p) AS r "
                "WITH r WHERE type(r) IN $rels RETURN count(DISTINCT r) AS n",
                id=cid, rels=RELS).single()["n"]
            courses = s.run("MATCH (c:Course {id: $id}) RETURN count(c) AS n", id=cid).single()["n"]
            align = s.run(
                "MATCH (c:Course {id: $id})-[:HAS_SLIDE]->(:Slide)-[:TEACHES]->(k:Concept) "
                "WITH DISTINCT k MATCH (k)-[r]-() WHERE type(r) IN $rels "
                "RETURN type(r) AS t, count(DISTINCT r) AS n", id=cid, rels=ALIGN_RELS).data()
            res[cid] = {"course_nodes": courses, "forbidden_label_nodes": lab, "forbidden_rels": rel,
                        "alignment_rels": {r["t"]: r["n"] for r in align}}
            print(cid[:15], res[cid], flush=True)
    drv.close()
    with open(out_path, "w") as f:
        json.dump(res, f, indent=2)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
