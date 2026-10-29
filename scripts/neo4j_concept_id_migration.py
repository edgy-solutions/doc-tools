#!/usr/bin/env python
"""Give every existing `:Concept` node its `id = hash(domain, normalized name)`, merge
the duplicates that re-keying exposes, and put the uniqueness constraint on the id.

The architect's ruling of 2026-10-24, after lane tr found Neo4j carries no uniqueness on
Concept at all:

    *"Do not add a name constraint -- the same name legitimately exists in different
    domains. Give Concept an id = hash(domain, normalized name), MERGE on the id, and a
    uniqueness constraint on the id. Migration for the existing nodes, with a count
    before and after."*

and the follow-up ruling on how the merge itself must behave:

    *"The migration must re-point every edge on the merged nodes -- including wb's
    ALIGNS_TO, which are user data. Run it under the roll lock with wb told to pause
    writes; counts of nodes and of each edge type before and after must match except for
    the intended merges, or it aborts and restores. Dry run on sandbox first with the
    report, then the real one."*

The writer side is `doc_tools/plugins/training.py`; the id itself is
`doc_tools/utils/concept_identity.py`, imported here rather than reimplemented. A
migration that computes ids differently from the writer does not fix duplicates, it
starts a second generation of them.

ORDER MATTERS AND THE SCRIPT ENFORCES IT: the constraint is created LAST. Creating it
first fails outright on any existing duplicate pair, and creating it between the id
assignment and the merge would fail on the pair the assignment just made collide.
Neo4j forbids schema and data operations in one transaction, so the constraint is
issued after the data transaction has committed, in its own call.

DRY RUN BY DEFAULT, AND THE DRY RUN EXECUTES. Nothing is committed without `--apply`,
but a dry run is not a prediction: it does the whole migration inside one transaction,
takes the census inside that same transaction, and then ROLLS BACK instead of
committing. Its numbers are actual numbers. The one thing it cannot execute is the
constraint (schema DDL cannot share the transaction, so it could not be rolled back); it
prints `would create constraint` instead.

EVERY EDGE IS RELINKED, FOUND BY MEASUREMENT. The first version relinked an enumerated
pair (TEACHES, COVERS) and aborted on anything else. That is the wrong shape for a
ruling that says every edge: wb's `ALIGNS_TO` is user data and carries properties
doc-tools has never seen. So the edge types incident on each loser are read FROM THE
GRAPH, and one static query is built per (type, direction) pair actually found. A
relationship type cannot be a Cypher parameter, which is the only reason the earlier
version enumerated; building the text from found types is safe because the types come
from the database, are checked to be plain identifiers, and are backtick-quoted.
`apoc.refactor.mergeNodes` is still not assumed present. Both directions are handled:
every known Concept edge is incoming today, and the migration must not depend on that
staying true. Every property is carried (`ON CREATE SET new += properties(old)`); where
the survivor already has the edge, its own values are kept.

ONE TRANSACTION, AND ROLLBACK IS THE RESTORE. Every data write goes through one explicit
transaction, and the census that verifies the result runs inside it before the commit.
On any mismatch or exception the transaction is rolled back: nothing half-done, no
journal to replay, elementIds intact.

THE COUNT SEAL. `census` counts every node, every label and every edge type, globally,
not just Concept -- a seal that only counts what the migration meant to touch cannot see
collateral damage. `predict` turns "except for the intended merges" into arithmetic:
nodes drop by the number of losers, labels by the losers' labels, and an edge type drops
by the number of edges that COLLAPSE onto an identical (type, direction, other endpoint)
edge the survivor already has, simulated sequentially per group. After is compared to
predicted field by field, including every type the migration never touched.

WHAT IT REFUSES TO DO, before any write (a dry run reports both, so they are known
before an apply is attempted):
  * a loser carries a label the survivor lacks. Merging would drop it; no ruling says to
    union labels, and unioning could make a survivor `:Deprecated`.
  * an edge between two members of one duplicate group. Relinking would turn it into a
    self-loop on the survivor, which nobody asked for.

THE REPORT IS THE AUDIT TRAIL for anything already committed. Rollback covers an
in-flight failure; once a merge is committed the report is the only record, so for every
loser it holds elementId, all labels, all properties and every incident edge as
(type, direction, other elementId, properties) -- enough to rebuild the node by hand --
plus any property key the survivor lacks, which is recorded rather than aborted on.

THE ROLL LOCK IS ASSERTED BY THE OPERATOR, NOT VERIFIED BY THIS SCRIPT. `--apply`
requires `--under-lock LANE/ISO8601`, the lane that holds `sandbox/roll-lock` and the
start time it recorded. The script checks that the lane is non-empty, that the time
parses, and that it is not more than 90 minutes old (the lock's own staleness rule); it
cannot read the ConfigMap from inside the pod. The flag's value is that running without
the lock now requires lying in a recorded field. A dry run does not need it.

WB'S PAUSED WRITES. The in-transaction seal proves OUR writes are exactly as planned; it
cannot see a concurrent commit, because the transaction does not see it. So after the
commit the census is taken again and compared with `predicted`. A difference there means
someone wrote while we held the transaction. It is reported as `post_commit_census`,
`ok` is set False, and NOTHING is undone: that is wb's new data, not ours to roll back.
That is why this check is separate from the in-transaction one.

Usage, from the pod (the NEO4J_* env is already there):

    /opt/venv/bin/python /app/scripts/neo4j_concept_id_migration.py          # dry run
    /opt/venv/bin/python /app/scripts/neo4j_concept_id_migration.py \\
        --apply --under-lock LANE/2026-10-25T09:30:00Z --out /tmp/concept-migration.json
"""
import argparse
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from doc_tools.utils.concept_identity import (  # noqa: E402
    CONCEPT_ID_CONSTRAINT,
    CONCEPT_ID_VERSION,
    CREATE_CONCEPT_ID_CONSTRAINT,
    concept_node_id,
    normalize_concept_name,
)

LOCK_MAX_AGE = timedelta(minutes=90)   # the roll lock's own staleness rule

EXIT_ABORT_BEFORE_WRITE = 4
EXIT_SEAL_FAILED = 5
EXIT_LOCK_REFUSED = 2
# A committed, sealed migration that nonetheless saw someone else write during its
# window. ITS OWN CODE, not folded into the generic failure: the census is global, so
# any unrelated ingest writing PCN nodes trips it, and reporting that as a failed
# migration is a false red of exactly the kind this repo keeps paying for. The
# migration's verdict (`ok`) stays what the in-transaction seal said; this code says
# the operational precondition -- wb and everyone else paused -- was not honoured.
EXIT_CONCURRENT_WRITE = 6


class LockError(ValueError):
    pass


def parse_lock(value, now=None):
    """`LANE/ISO8601` -> {lane, started, age_minutes}. Raises LockError.

    Naive timestamps are read as UTC. A start more than five minutes in the FUTURE is
    refused too: a negative age would otherwise pass the staleness test trivially.
    """
    now = now or datetime.now(timezone.utc)
    lane, sep, stamp = (value or "").partition("/")
    if not sep or not lane.strip() or not stamp.strip():
        raise LockError("--under-lock must be LANE/ISO8601, e.g. 7f/2026-10-25T09:30:00Z")
    try:
        started = datetime.fromisoformat(stamp.strip().replace("Z", "+00:00"))
    except ValueError:
        raise LockError("--under-lock timestamp %r is not ISO 8601" % stamp)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    age = now - started
    if age > LOCK_MAX_AGE:
        raise LockError("the asserted lock start is %d minutes old; a lock older than "
                        "90 minutes is stale, not a lock" % (age.total_seconds() // 60))
    if age < -timedelta(minutes=5):
        raise LockError("the asserted lock start is in the future")
    return {"lane": lane.strip(), "started": started.isoformat(),
            "age_minutes": round(age.total_seconds() / 60, 1),
            "verified": False}


def check_lock(value, apply_it, now=None):
    """The lock record for the report, or None. `--apply` without a good one raises."""
    if not value:
        if apply_it:
            raise LockError("--apply requires --under-lock LANE/ISO8601 (asserted, "
                            "not verified, by this script)")
        return None
    return parse_lock(value, now)


def connect():
    from doc_tools.utils.neo4j_client import Neo4jClient

    # The chart sets NEO4J_USERNAME; Neo4jClient reads NEO4J_USER and would otherwise
    # fall back to its hardcoded default. Both are accepted here so the script works
    # from the pod env as it actually is.
    user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME")
    client = Neo4jClient(user=user) if user else Neo4jClient()
    return client


class TxRunner:
    """Gives a transaction the `execute_query` shape the helpers already speak, so a
    read taken for the plan sees the same snapshot the writes and the census do."""

    def __init__(self, tx):
        self.tx = tx

    def execute_query(self, query, parameters=None, db=None):
        return [r.data() for r in self.tx.run(query, parameters or {})]


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


# --------------------------------------------------------------------------- #
# The census and the seal. Pure functions over plain dicts, so they are testable
# without a database -- the job itself cannot be run locally.
# --------------------------------------------------------------------------- #

def census(client):
    """Global counts: every node, every label, every edge type. Not just Concept."""
    total = client.execute_query("MATCH (n) RETURN count(n) AS n")
    labels = client.execute_query(
        "MATCH (n) UNWIND labels(n) AS l RETURN l AS l, count(*) AS n")
    edges = client.execute_query(
        "MATCH ()-[r]->() RETURN type(r) AS t, count(r) AS n")
    return {
        "nodes_total": total[0]["n"] if total else 0,
        "nodes_by_label": {r["l"]: r["n"] for r in labels},
        "edges_by_type": {r["t"]: r["n"] for r in edges},
    }


def edge_key(e):
    """What makes two edges the same edge once relinked onto the survivor."""
    return (e["type"], bool(e["outgoing"]), e["other"])


def simulate_collapses(survivor, losers):
    """{type: collapsed edge count}, simulated SEQUENTIALLY.

    An edge collapses iff the survivor already has an edge with the same (type,
    direction, other endpoint) -- its own, or one a previous loser in this group just
    relinked. A naive per-loser count compares each loser to the survivor only, and so
    misses two losers pointing at the same node, which end as ONE edge, not two.
    """
    seen = {edge_key(e) for e in survivor["edges"]}
    collapsed = {}
    for loser in losers:
        for e in loser["edges"]:
            k = edge_key(e)
            if k in seen:
                collapsed[e["type"]] = collapsed.get(e["type"], 0) + 1
            else:
                seen.add(k)
    return collapsed


def plan_effects(plan):
    """(losers, label drops, collapses by type) over every group in the plan."""
    losers = 0
    label_drops = {}
    collapses = {}
    for g in plan:
        losers += len(g["losers"])
        for l in g["losers"]:
            for label in l["labels"]:
                label_drops[label] = label_drops.get(label, 0) + 1
        for t, n in simulate_collapses(g["survivor"], g["losers"]).items():
            collapses[t] = collapses.get(t, 0) + n
    return losers, label_drops, collapses


def _drop(base, drops):
    out = dict(base)
    for k, n in drops.items():
        out[k] = out.get(k, 0) - n
    return {k: v for k, v in out.items() if v}   # a census omits what has count 0


def predict(before, plan):
    """The after-census the merges alone would produce."""
    losers, label_drops, collapses = plan_effects(plan)
    return {
        "nodes_total": before["nodes_total"] - losers,
        "nodes_by_label": _drop(before["nodes_by_label"], label_drops),
        "edges_by_type": _drop(before["edges_by_type"], collapses),
    }


def compare_census(after, predicted):
    """Every difference, by name, with both numbers. Checks every label and edge type
    on EITHER side, so a type the migration never touched must be unchanged and a type
    that appeared from nowhere fails too."""
    out = []
    if after["nodes_total"] != predicted["nodes_total"]:
        out.append({"field": "nodes_total", "expected": predicted["nodes_total"],
                    "actual": after["nodes_total"]})
    for part in ("nodes_by_label", "edges_by_type"):
        for k in sorted(set(after[part]) | set(predicted[part])):
            a, p = after[part].get(k, 0), predicted[part].get(k, 0)
            if a != p:
                out.append({"field": "%s[%s]" % (part, k), "expected": p, "actual": a})
    return out


# --------------------------------------------------------------------------- #
# The plan: what each group would do, and the two deliberate aborts.
# --------------------------------------------------------------------------- #

def label_problems(survivor, loser):
    """Labels the loser carries that the survivor lacks. Empty means mergeable."""
    return sorted(set(loser["labels"]) - set(survivor["labels"]))


def internal_edges(group_records):
    """Edges between two members of the same duplicate group (a loser's self-loop
    included). Relinked, each would become a self-loop on the survivor."""
    eids = {r["eid"] for r in group_records}
    seen = {}
    for r in group_records:
        for e in r["edges"]:
            if e["other"] in eids:
                seen[e["rid"]] = {"type": e["type"], "from_or_to": r["eid"],
                                  "other": e["other"], "rid": e["rid"]}
    return sorted(seen.values(), key=lambda e: str(e["rid"]))


def lost_properties(survivor, loser):
    """Loser properties whose KEY the survivor lacks. Recorded, never an abort: `name`
    differs on purpose, but a value must not vanish unrecorded."""
    return {k: v for k, v in loser["props"].items() if k not in survivor["props"]}


def abort_reasons(plan):
    reasons = []
    for g in plan:
        for l in g["losers"]:
            for label in label_problems(g["survivor"], l):
                reasons.append("group %s: loser %s carries label %r the survivor %s "
                               "lacks; merging would drop it"
                               % (g["new_id"], l["eid"], label, g["survivor"]["eid"]))
        for e in internal_edges([g["survivor"]] + g["losers"]):
            reasons.append("group %s: edge %s (%s) joins %s and %s, two members of "
                           "one duplicate group; relinking makes a self-loop"
                           % (g["new_id"], e["rid"], e["type"], e["from_or_to"],
                              e["other"]))
    return reasons


def load_record(client, eid):
    """One node, verbatim: labels, properties, and every incident edge."""
    head = client.execute_query(
        "MATCH (c:Concept) WHERE elementId(c) = $eid "
        "RETURN labels(c) AS labels, properties(c) AS props", {"eid": eid})
    rows = client.execute_query(
        "MATCH (c:Concept) WHERE elementId(c) = $eid MATCH (c)-[r]-(o) "
        "RETURN type(r) AS t, startNode(r) = c AS outgoing, elementId(o) AS other, "
        "       properties(r) AS props, elementId(r) AS rid", {"eid": eid})
    return {
        "eid": eid,
        "labels": head[0]["labels"] if head else [],
        "props": head[0]["props"] if head else {},
        "edges": [{"type": r["t"], "outgoing": r["outgoing"], "other": r["other"],
                   "props": r["props"], "rid": r["rid"]} for r in rows],
    }


def build_plan(client, dups):
    plan = []
    for new_id, group in sorted(dups.items()):
        survivor = pick_survivor(group)
        losers = [n for n in group if n["eid"] != survivor["eid"]]
        plan.append({
            "new_id": new_id,
            "survivor": dict(load_record(client, survivor["eid"]),
                             name=survivor["name"]),
            "losers": [dict(load_record(client, l["eid"]), name=l["name"])
                       for l in losers],
        })
    return plan


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ]*$")


def relink_query(rel_type, outgoing):
    """The static relink query for one (type, direction) pair found in the graph.

    The type is spliced into the text because Cypher cannot parameterise it; it came
    from `type(r)` on the database, is checked to be a plain identifier, and is
    backtick-quoted. `ON CREATE SET new += properties(old)` carries EVERY property, so
    one nobody enumerated (wb's ALIGNS_TO has several) is not dropped, while an edge the
    survivor already has keeps its own values: it is the higher-degree node, and
    overwriting from the loser would make the result depend on merge order.
    """
    if not _IDENT.match(rel_type or ""):
        raise ValueError("refusing to build a query for relationship type %r" % rel_type)
    if outgoing:
        old, new = "(lose)-[old:`%s`]->(other)" % rel_type, "(surv)-[new:`%s`]->(other)" % rel_type
    else:
        old, new = "(other)-[old:`%s`]->(lose)" % rel_type, "(other)-[new:`%s`]->(surv)" % rel_type
    return (
        "MATCH (surv:Concept) WHERE elementId(surv) = $surv "
        "MATCH (lose:Concept) WHERE elementId(lose) = $lose "
        "MATCH %s "
        "MERGE %s "
        "ON CREATE SET new += properties(old) "
        "DELETE old "
        "RETURN count(old) AS moved" % (old, new)
    )


def relink(client, survivor_rec, loser_rec):
    """Move every edge of the loser onto the survivor, one (type, direction) at a time."""
    moved = []
    pairs = sorted({(e["type"], bool(e["outgoing"])) for e in loser_rec["edges"]})
    for rel_type, outgoing in pairs:
        res = client.execute_query(relink_query(rel_type, outgoing),
                                   {"surv": survivor_rec["eid"],
                                    "lose": loser_rec["eid"]})
        moved.append({"type": rel_type, "outgoing": outgoing,
                      "edges": res[0]["moved"] if res else 0})
    return moved


def _loser_report(survivor, loser, moved):
    return {"eid": loser["eid"], "name": loser.get("name"), "labels": loser["labels"],
            "properties": loser["props"],
            "edges": [{"type": e["type"], "direction": "out" if e["outgoing"] else "in",
                       "other": e["other"], "properties": e["props"]}
                      for e in loser["edges"]],
            "properties_survivor_lacks": lost_properties(survivor, loser),
            "moved": moved}


def _print_census(title, c):
    print("  %s" % title)
    print("    nodes_total %s" % c["nodes_total"])
    for part in ("nodes_by_label", "edges_by_type"):
        for k in sorted(c[part]):
            print("    %s[%s] %s" % (part, k, c[part][k]))


def migrate(args, client, summary):
    """The whole migration inside one transaction. Returns an exit code."""
    apply_it = bool(args.apply)
    with client.driver.session() as session:
        tx = session.begin_transaction()
        try:
            run = TxRunner(tx)
            nodes = inventory(run)
            before_counts = counts(client, nodes)
            before = census(run)
            summary["before_concepts"] = before_counts
            summary["before"] = before
            print("\nBEFORE")
            for k, v in before_counts.items():
                print("  %-26s %s" % (k, v))
            _print_census("census", before)
            for n in nodes:
                if n["skip"]:
                    print("  SKIP (%s): eid=%s labels=%s name=%r"
                          % (n["skip"], n["eid"], n["labels"], n["name"]))

            dups, _ = group_duplicates(nodes)
            plan = build_plan(run, dups)
            summary["plan"] = plan
            predicted = predict(before, plan)
            summary["predicted"] = predicted
            summary["collapses_by_type"] = plan_effects(plan)[2]

            reasons = abort_reasons(plan)
            if reasons:
                summary["abort_reasons"] = reasons
                print("\nABORT: refusing before any write:")
                for r in reasons:
                    print("  - %s" % r)
                tx.rollback()
                return EXIT_ABORT_BEFORE_WRITE

            print("\nDUPLICATE GROUPS: %d" % len(plan))
            merges = []
            loser_eids = set()
            for g in plan:
                s = g["survivor"]
                print("  %s  <- %d nodes" % (g["new_id"], 1 + len(g["losers"])))
                print("    survivor: eid=%s name=%r edges=%d"
                      % (s["eid"], s.get("name"), len(s["edges"])))
                record = {"new_id": g["new_id"], "survivor": s["eid"],
                          "survivor_name": s.get("name"), "losers": []}
                for l in g["losers"]:
                    moved = relink(run, s, l)
                    # A plain DELETE (never DETACH): if any edge was missed the delete
                    # raises, the transaction rolls back, and the loser is left whole.
                    run.execute_query(
                        "MATCH (c:Concept) WHERE elementId(c) = $eid DELETE c",
                        {"eid": l["eid"]})
                    loser_eids.add(l["eid"])
                    print("    merged: eid=%s name=%r edges %s"
                          % (l["eid"], l.get("name"), moved or "none"))
                    record["losers"].append(_loser_report(s, l, moved))
                merges.append(record)
            summary["merges"] = merges

            # The id assignment. Runs for survivors and for every untouched node alike; a
            # node already carrying the right id is set to the same value, a no-op write
            # that keeps this loop free of special cases.
            assigned = 0
            for n in nodes:
                if n["skip"] or n["eid"] in loser_eids:
                    continue
                run.execute_query(
                    "MATCH (c:Concept) WHERE elementId(c) = $eid "
                    "SET c.id = $id, c.name_normalized = $norm, c.domain = $domain",
                    {"eid": n["eid"], "id": n["new_id"],
                     "norm": n["name_normalized"], "domain": n["domain"]})
                assigned += 1
            summary["assigned"] = assigned
            print("\nassigned %d node ids (inside the transaction)" % assigned)

            after = census(run)
            summary["after"] = after
            summary["mismatches"] = compare_census(after, predicted)
            print("\nAFTER (measured inside the transaction)")
            _print_census("census", after)
            if summary["mismatches"]:
                print("\nSEAL FAILED, rolling back:")
                for m in summary["mismatches"]:
                    print("  %-40s expected %s, got %s"
                          % (m["field"], m["expected"], m["actual"]))
                tx.rollback()
                return EXIT_SEAL_FAILED
            print("\nseal: after == predicted on every count (%d merged)"
                  % plan_effects(plan)[0])

            if args.apply:
                tx.commit()
                summary["applied"] = True
                print("committed.")
            else:
                tx.rollback()
                print("rolled back (dry run).")
        except BaseException:
            try:
                tx.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="commit. Without it the script executes, reports, and rolls back.")
    ap.add_argument("--under-lock", metavar="LANE/ISO8601",
                    help="required with --apply: the lane holding sandbox/roll-lock and "
                         "its recorded start. ASSERTED, not verified, by this script.")
    ap.add_argument("--out", help="write the JSON summary here as well as to stdout")
    args = ap.parse_args()

    try:
        lock = check_lock(args.under_lock, args.apply)
    except LockError as e:
        print("REFUSED: %s" % e)
        return EXIT_LOCK_REFUSED

    client = connect()
    print("concept id migration, version %d, %s"
          % (CONCEPT_ID_VERSION, "APPLY" if args.apply else
             "DRY RUN (executed in a transaction, then rolled back)"))
    print("  neo4j: %s" % os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    if lock:
        print("  lock: %s since %s (asserted by the operator, NOT verified by this "
              "script; wb must have paused writes)" % (lock["lane"], lock["started"]))

    summary = {"version": CONCEPT_ID_VERSION, "applied": False, "lock": lock,
               "before": None, "after": None, "predicted": None, "mismatches": [],
               "plan": [], "collapses_by_type": {}, "post_commit_census": None,
               "ok": False}
    try:
        code = migrate(args, client, summary)
        ok = code == 0
        if args.apply and ok:
            # The constraint is schema DDL: it cannot share the data transaction, so it
            # follows a successful commit, last.
            client.execute_query(CREATE_CONCEPT_ID_CONSTRAINT)
            print("constraint: %s" % CONCEPT_ID_CONSTRAINT)
            # The in-transaction seal cannot see a concurrent commit. This one can. A
            # difference is wb's write landing during our transaction: reported, never
            # undone, because it is their data.
            post = census(client)
            drift = compare_census(post, summary["predicted"])
            present = constraint_present(client)
            summary["post_commit_census"] = {"census": post, "drift": drift,
                                             "constraint_on_id": present}
            summary["concurrent_writes"] = drift
            if drift:
                # NOT `ok = False`. The migration committed and its seal passed
                # inside the transaction; this is somebody else's write, which we do
                # not undo and did not cause. Folding it into `ok` would make an
                # unrelated ingest read as a broken migration -- so it gets its own
                # exit code and says which it is.
                code = EXIT_CONCURRENT_WRITE
                print("\nCONCURRENT WRITE DURING THE MIGRATION WINDOW. The migration "
                      "itself committed and its in-transaction seal passed on every "
                      "count; what follows is someone ELSE's write, reported and NOT "
                      "undone, because it is their data. It does mean the window was "
                      "not held exclusively -- wb, or another lane, was still "
                      "writing:")
                for m in drift:
                    print("  %-40s expected %s, got %s"
                          % (m["field"], m["expected"], m["actual"]))
            if present is False:
                print("\nFAIL: the uniqueness constraint on Concept.id is not present")
                ok = False
            elif present is None:
                # `constraint_present` returns None when SHOW CONSTRAINTS could not be
                # read at all. UNKNOWN IS NOT ABSENT: the CREATE above would have
                # raised if it had failed, and reading "could not check" as "not there"
                # is the absence-as-evidence mistake. Loud, and not a verdict.
                print("\nWARNING: could not read SHOW CONSTRAINTS, so the presence of "
                      "%s is UNVERIFIED (not absent -- unknown). The CREATE above "
                      "returned without error." % CONCEPT_ID_CONSTRAINT)
        elif not args.apply and ok:
            print("would create constraint: %s" % CONCEPT_ID_CONSTRAINT)
        summary["ok"] = ok
        if not ok and code == 0:
            code = 1
    finally:
        if args.out:
            io.open(args.out, "w", encoding="utf-8", newline="\n").write(
                json.dumps(summary, indent=2, ensure_ascii=False, default=str))
            print("\nsummary: %s" % args.out)
        client.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
