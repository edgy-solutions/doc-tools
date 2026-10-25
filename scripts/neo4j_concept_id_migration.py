#!/usr/bin/env python
"""Give every existing `:Concept` node its `id = hash(domain, normalized name)`, merge
the duplicates that re-keying exposes, and put the uniqueness constraint on the id.

The architect's ruling of 2026-10-24, after lane tr found Neo4j carries no uniqueness on
Concept at all:

    *"Do not add a name constraint -- the same name legitimately exists in different
    domains. Give Concept an id = hash(domain, normalized name), MERGE on the id, and a
    uniqueness constraint on the id. Migration for the existing nodes, with a count
    before and after."*

The writer side is `doc_tools/plugins/training.py`; the id itself is
`doc_tools/utils/concept_identity.py`, imported here rather than reimplemented. A
migration that computes ids differently from the writer does not fix duplicates, it
starts a second generation of them.

ORDER MATTERS AND THE SCRIPT ENFORCES IT: the constraint is created LAST. Creating it
first fails outright on any existing duplicate pair, and creating it between the id
assignment and the merge would fail on the pair the assignment just made collide.

DRY RUN BY DEFAULT. Nothing is written without `--apply`. A dry run reports exactly what
an apply would do -- the before counts, every duplicate group with its survivor and the
edges that would move, and the after counts it predicts.

WHAT IT REFUSES TO DO: a duplicate group whose nodes carry an edge type this script does
not know how to relink (anything but `TEACHES` and `COVERS`) aborts the whole migration
before any write. Relinking by enumerated type is deliberate -- `apoc.refactor.mergeNodes`
is not assumed present, and a dynamic-type relink would silently drop an edge type nobody
had thought about. An abort here is a request to extend `RELINKABLE` on purpose.

Usage, from the pod (the NEO4J_* env is already there):

    /opt/venv/bin/python /app/scripts/neo4j_concept_id_migration.py          # dry run
    /opt/venv/bin/python /app/scripts/neo4j_concept_id_migration.py --apply
    ... --apply --out /tmp/concept-migration.json
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from doc_tools.utils.concept_identity import (  # noqa: E402
    CONCEPT_ID_CONSTRAINT,
    CONCEPT_ID_VERSION,
    CREATE_CONCEPT_ID_CONSTRAINT,
    concept_node_id,
    normalize_concept_name,
)

# The edge types a duplicate's relationships may have. Both are written by
# `TrainingPlugin`: TEACHES from a Slide, COVERS from a Section (its pass-2 rollup).
RELINKABLE = ("TEACHES", "COVERS")


def connect():
    from doc_tools.utils.neo4j_client import Neo4jClient

    # The chart sets NEO4J_USERNAME; Neo4jClient reads NEO4J_USER and would otherwise
    # fall back to its hardcoded default. Both are accepted here so the script works
    # from the pod env as it actually is.
    user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME")
    client = Neo4jClient(user=user) if user else Neo4jClient()
    return client


def inventory(client):
    """Every Concept node, with what it would be re-keyed to.

    `domain` comes from `c.domain` when the node has one (the writer has set it since
    #163) and otherwise from the node's own labels, which is where the domain lived
    before that: `:Concept:TRAINING`. A node with neither is reported and skipped, never
    guessed into a domain.
    """
    rows = client.execute_query(
        "MATCH (c:Concept) "
        "OPTIONAL MATCH (c)-[r]-() "
        "RETURN elementId(c) AS eid, c.id AS id, c.name AS name, "
        "       c.domain AS domain, labels(c) AS labels, "
        "       count(r) AS degree, collect(distinct type(r)) AS rel_types "
        "ORDER BY eid"
    )
    nodes = []
    for r in rows:
        labels = [l for l in (r["labels"] or []) if l != "Concept"]
        domain = r["domain"] or (labels[0] if labels else "")
        name = r["name"]
        node = {
            "eid": r["eid"], "stored_id": r["id"], "name": name,
            "domain": domain, "labels": r["labels"],
            "degree": r["degree"], "rel_types": [t for t in r["rel_types"] if t],
        }
        if not name or not str(name).strip() or not domain:
            node["new_id"] = None
            node["skip"] = "no name" if not (name and str(name).strip()) else "no domain"
        else:
            node["new_id"] = concept_node_id(domain, name)
            node["name_normalized"] = normalize_concept_name(name)
            node["skip"] = None
        nodes.append(node)
    return nodes


def group_duplicates(nodes):
    by_id = {}
    for n in nodes:
        if n["new_id"]:
            by_id.setdefault(n["new_id"], []).append(n)
    return {k: v for k, v in by_id.items() if len(v) > 1}, by_id


def pick_survivor(group):
    """Most relationships wins; `eid` breaks the tie.

    Degree, because the survivor keeps its own edges for free and only the loser's have
    to be moved -- fewer writes and fewer chances to drop one. The tie-break is there so
    a dry run and the apply that follows it name the SAME survivor.
    """
    return sorted(group, key=lambda n: (-n["degree"], str(n["eid"])))[0]


def constraint_present(client):
    try:
        rows = client.execute_query(
            "SHOW CONSTRAINTS YIELD name, labelsOrTypes, properties "
            "RETURN name, labelsOrTypes, properties")
    except Exception as e:  # noqa: BLE001
        print("  ! could not read constraints: %s" % e)
        return None
    for r in rows:
        if r.get("name") == CONCEPT_ID_CONSTRAINT:
            return True
        if (r.get("labelsOrTypes") or []) == ["Concept"] and \
                (r.get("properties") or []) == ["id"]:
            return True
    return False


def counts(client, nodes=None):
    nodes = inventory(client) if nodes is None else nodes
    dups, by_id = group_duplicates(nodes)
    return {
        "concept_nodes": len(nodes),
        "with_an_id": sum(1 for n in nodes if n["stored_id"]),
        "with_the_right_id": sum(1 for n in nodes
                                 if n["new_id"] and n["stored_id"] == n["new_id"]),
        "with_a_domain": sum(1 for n in nodes if n["domain"]),
        "distinct_new_ids": len(by_id),
        "duplicate_groups": len(dups),
        "nodes_in_duplicate_groups": sum(len(v) for v in dups.values()),
        "skipped": sum(1 for n in nodes if n["skip"]),
        "constraint_on_id": constraint_present(client),
    }


def relink(client, survivor, loser, apply_it):
    """Move the loser's edges onto the survivor, one known type at a time.

    `MERGE` on the target edge rather than `CREATE`, so a slide that taught both
    spellings of the same concept ends with one TEACHES rather than two. The salience /
    score of an edge that already exists is KEPT: the survivor is the node with more
    edges, so its values are the ones more of the graph already agrees with, and
    overwriting them from the loser would make the result depend on merge order.
    """
    moved = []
    for rel in RELINKABLE:
        q = (
            "MATCH (surv:Concept) WHERE elementId(surv) = $surv "
            "MATCH (lose:Concept) WHERE elementId(lose) = $lose "
            "MATCH (other)-[old:%s]->(lose) "
            "MERGE (other)-[new:%s]->(surv) "
            "SET new.salience = coalesce(new.salience, old.salience), "
            "    new.score = coalesce(new.score, old.score), "
            "    new.frequency = coalesce(new.frequency, old.frequency) "
            "DELETE old "
            "RETURN count(*) AS moved" % (rel, rel)
        )
        if not apply_it:
            probe = client.execute_query(
                "MATCH (other)-[old:%s]->(lose:Concept) "
                "WHERE elementId(lose) = $lose RETURN count(old) AS moved" % rel,
                {"lose": loser["eid"]})
            n = probe[0]["moved"] if probe else 0
        else:
            res = client.execute_query(q, {"surv": survivor["eid"],
                                           "lose": loser["eid"]})
            n = res[0]["moved"] if res else 0
        if n:
            moved.append({"type": rel, "edges": n})
    return moved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write. Without it the script only reports.")
    ap.add_argument("--out", help="write the JSON summary here as well as to stdout")
    args = ap.parse_args()

    client = connect()
    print("concept id migration, version %d, %s"
          % (CONCEPT_ID_VERSION, "APPLY" if args.apply else "DRY RUN"))
    print("  neo4j: %s" % os.getenv("NEO4J_URI", "bolt://localhost:7687"))

    nodes = inventory(client)
    before = counts(client, nodes)
    print("\nBEFORE")
    for k in ("concept_nodes", "with_an_id", "with_the_right_id", "with_a_domain",
              "distinct_new_ids", "duplicate_groups", "nodes_in_duplicate_groups",
              "skipped", "constraint_on_id"):
        print("  %-26s %s" % (k, before[k]))

    for n in nodes:
        if n["skip"]:
            print("  SKIP (%s): eid=%s labels=%s name=%r"
                  % (n["skip"], n["eid"], n["labels"], n["name"]))

    dups, _ = group_duplicates(nodes)

    # Refuse before writing anything if a duplicate carries an edge we cannot move.
    unknown = sorted({t for g in dups.values() for n in g for t in n["rel_types"]
                      if t not in RELINKABLE})
    if unknown:
        print("\nABORT: duplicate groups carry edge types this script cannot relink: %s"
              % ", ".join(unknown))
        print("Extend RELINKABLE deliberately, with the merge semantics for each type, "
              "and re-run. Nothing was written.")
        client.close()
        return 2

    merges = []
    print("\nDUPLICATE GROUPS: %d" % len(dups))
    for new_id, group in sorted(dups.items()):
        survivor = pick_survivor(group)
        losers = [n for n in group if n["eid"] != survivor["eid"]]
        print("  %s  <- %d nodes" % (new_id, len(group)))
        print("    survivor: eid=%s name=%r degree=%d"
              % (survivor["eid"], survivor["name"], survivor["degree"]))
        record = {"new_id": new_id, "survivor": survivor["eid"],
                  "survivor_name": survivor["name"], "losers": []}
        for loser in losers:
            moved = relink(client, survivor, loser, args.apply)
            print("    %s: eid=%s name=%r degree=%d edges %s"
                  % ("merged" if args.apply else "would merge", loser["eid"],
                     loser["name"], loser["degree"],
                     moved or "none"))
            if args.apply:
                left = client.execute_query(
                    "MATCH (c:Concept) WHERE elementId(c) = $eid "
                    "OPTIONAL MATCH (c)-[r]-() "
                    "RETURN collect(distinct type(r)) AS types", {"eid": loser["eid"]})
                remaining = [t for t in (left[0]["types"] if left else []) if t]
                if remaining:
                    print("    ABORT: eid=%s still has %s after relinking; left in "
                          "place." % (loser["eid"], remaining))
                    client.close()
                    return 3
                client.execute_query(
                    "MATCH (c:Concept) WHERE elementId(c) = $eid DELETE c",
                    {"eid": loser["eid"]})
            record["losers"].append({"eid": loser["eid"], "name": loser["name"],
                                     "moved": moved})
        merges.append(record)

    # The id assignment. Runs for survivors and for every untouched node alike; a node
    # already carrying the right id is set to the same value, which is a no-op write and
    # keeps this loop free of special cases.
    assigned = 0
    for n in nodes:
        if n["skip"] or any(n["eid"] in [l["eid"] for l in m["losers"]]
                            for m in merges):
            continue
        if args.apply:
            client.execute_query(
                "MATCH (c:Concept) WHERE elementId(c) = $eid "
                "SET c.id = $id, c.name_normalized = $norm, c.domain = $domain",
                {"eid": n["eid"], "id": n["new_id"],
                 "norm": n["name_normalized"], "domain": n["domain"]})
        assigned += 1
    print("\n%s %d node ids" % ("assigned" if args.apply else "would assign", assigned))

    if args.apply:
        client.execute_query(CREATE_CONCEPT_ID_CONSTRAINT)
        print("constraint: %s" % CONCEPT_ID_CONSTRAINT)
    else:
        print("would create constraint: %s" % CONCEPT_ID_CONSTRAINT)

    after = counts(client) if args.apply else dict(
        before,
        concept_nodes=before["concept_nodes"] - before["nodes_in_duplicate_groups"]
        + before["duplicate_groups"],
        with_an_id=assigned,
        with_the_right_id=assigned,
        duplicate_groups=0,
        nodes_in_duplicate_groups=0,
        constraint_on_id=True,
    )
    print("\nAFTER%s" % ("" if args.apply else " (predicted)"))
    for k in ("concept_nodes", "with_an_id", "with_the_right_id", "with_a_domain",
              "distinct_new_ids", "duplicate_groups", "nodes_in_duplicate_groups",
              "skipped", "constraint_on_id"):
        print("  %-26s %s" % (k, after[k]))

    summary = {"version": CONCEPT_ID_VERSION, "applied": bool(args.apply),
               "before": before, "after": after, "merges": merges,
               "assigned": assigned}
    ok = True
    if args.apply:
        # The two checks worth failing on: every concept keyed, and no pair left sharing
        # an id. The constraint makes the second one impossible to reintroduce, but it is
        # asserted here too -- a constraint that silently failed to create would
        # otherwise read as success.
        if after["duplicate_groups"]:
            print("\nFAIL: %d duplicate groups remain" % after["duplicate_groups"])
            ok = False
        if after["with_the_right_id"] + after["skipped"] != after["concept_nodes"]:
            print("\nFAIL: %d of %d nodes do not carry their computed id"
                  % (after["concept_nodes"] - after["with_the_right_id"]
                     - after["skipped"], after["concept_nodes"]))
            ok = False
        if not after["constraint_on_id"]:
            print("\nFAIL: the uniqueness constraint on Concept.id is not present")
            ok = False
    summary["ok"] = ok

    if args.out:
        io.open(args.out, "w", encoding="utf-8", newline="\n").write(
            json.dumps(summary, indent=2, ensure_ascii=False, default=str))
        print("\nsummary: %s" % args.out)
    client.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
