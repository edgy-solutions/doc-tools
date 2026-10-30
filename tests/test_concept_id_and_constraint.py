"""`:Concept` is keyed by `id = hash(domain, normalized name)`, and the constraint is on
that id and NOT on the name.

The architect's ruling of 2026-10-24, after lane tr found Neo4j has no uniqueness on
Concept at all:

    *"Do not add a name constraint -- the same name legitimately exists in different
    domains. Give Concept an id = hash(domain, normalized name), MERGE on the id, and a
    uniqueness constraint on the id."*

Both halves are tested here, and the prohibition is tested as a prohibition: a name
constraint would not merely be a different design, it would collapse `Torque Control` the
training concept into `Torque Control` the manufacturing concept and leave one node whose
edges span two domains.

The third thing tested is the one that makes the migration trustworthy: the writer and
`scripts/neo4j_concept_id_migration.py` compute the id through the SAME module. A
migration with its own copy of the hash does not fix duplicates, it starts a second
generation of them.
"""
import importlib.util
import io
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from doc_tools.plugins.models import BaseSection, DocumentNode
from doc_tools.plugins.training import Concept, SlideAugmentation, TrainingPlugin
from doc_tools.utils.concept_identity import (
    CONCEPT_ID_CONSTRAINT,
    CREATE_CONCEPT_ID_CONSTRAINT,
    ID_PREFIX,
    concept_node_id,
    normalize_concept_name,
)

ROOT = Path(__file__).resolve().parents[1]


def _migration():
    scripts = ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(
        "neo4j_concept_id_migration", scripts / "neo4j_concept_id_migration.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# The id
# --------------------------------------------------------------------------- #

def test_the_same_concept_spelled_differently_gets_one_id():
    """The duplicates that merging on a raw name could not prevent: a double space, a
    trailing space, a non-breaking space, a different capitalization."""
    canonical = concept_node_id("TRAINING", "Torque Control")
    for variant in ("torque control", "Torque  Control", "  Torque Control ",
                    "TORQUE CONTROL", "Torque Control", "Torque\tControl"):
        assert concept_node_id("TRAINING", variant) == canonical, variant


def test_the_same_name_in_two_domains_gets_two_ids():
    """The ruling's whole reason for refusing a name constraint. These are two concepts
    that share a label, and they must stay two nodes."""
    assert concept_node_id("TRAINING", "Torque Control") != \
        concept_node_id("MANUFACTURING", "Torque Control")


def test_two_different_concepts_keep_two_ids():
    assert concept_node_id("TRAINING", "Torque Control") != \
        concept_node_id("TRAINING", "Torque Wrench")
    # Punctuation is NOT normalized away: `pre-flight` and `pre flight` may genuinely be
    # distinct, and a normalizer that guesses merges concepts nobody asked it to merge.
    assert concept_node_id("TRAINING", "pre-flight") != \
        concept_node_id("TRAINING", "pre flight")


def test_the_domain_separator_cannot_be_forged():
    """The pair is joined by \\x1f, which no domain label or concept name contains, so no
    pair of inputs can be reassembled into another pair's digest input."""
    assert concept_node_id("TRAINING", "x") != concept_node_id("TRAININGx", "")
    assert concept_node_id("A", "B C") != concept_node_id("A B", "C")


def test_the_id_shape_is_stable():
    cid = concept_node_id("TRAINING", "Torque Control")
    assert cid.startswith(ID_PREFIX)
    assert re.fullmatch(r"concept_[0-9a-f]{16}", cid), cid
    # Pinned literal: a change to the hash or the normalizer re-keys every Concept node
    # in the database and needs a migration pass, so it must not happen by accident.
    assert cid == "concept_" + \
        __import__("hashlib").sha256(b"TRAINING\x1ftorque control").hexdigest()[:16]


def test_the_normalizer_does_what_the_id_claims():
    assert normalize_concept_name("  Torque  Control ") == "torque control"
    assert normalize_concept_name("") == ""
    assert normalize_concept_name(None) == ""


def test_an_empty_name_still_yields_a_deterministic_id():
    """Not a licence to write one -- the writer never does, and the migration skips a
    nameless node rather than keying it. This pins that the helper itself does not
    raise, so a caller's guard is the only guard and it is visible."""
    assert concept_node_id("TRAINING", "") == concept_node_id("TRAINING", "   ")


# --------------------------------------------------------------------------- #
# The constraint
# --------------------------------------------------------------------------- #

def test_the_constraint_is_on_the_id_and_not_on_the_name():
    stmt = CREATE_CONCEPT_ID_CONSTRAINT
    assert "FOR (c:Concept)" in stmt
    assert "REQUIRE c.id IS UNIQUE" in stmt
    assert "IF NOT EXISTS" in stmt, "the constraint must be idempotent"
    assert "name" not in stmt, "the ruling forbids a name constraint: " + stmt
    assert CONCEPT_ID_CONSTRAINT in stmt


# --------------------------------------------------------------------------- #
# The writer
# --------------------------------------------------------------------------- #

def _concept_query():
    sec = BaseSection(title="Torque Basics", level=2, page_start=4, content="Body",
                      node_id="slide-1")
    aug = SlideAugmentation(concepts=[Concept(name="Torque  control", salience=0.9)])
    node = DocumentNode(base_extraction=sec, domain_augmentation=aug)
    config = SimpleNamespace(graph_node_label="Course", graph_child_label="Slide")
    cypher, _ = TrainingPlugin(domain_type="training").to_graph_queries([node], config)
    return [q for q in cypher if "concept_id" in q["params"]][0]


def test_the_writer_merges_the_concept_on_the_id_alone():
    q = _concept_query()
    merge = re.search(r"MERGE\s*\(\s*\w*\s*:Concept[^{)]*\{([^}]*)\}", q["query"])
    assert merge, q["query"]
    assert re.findall(r"(\w+)\s*:", merge.group(1)) == ["id"]


def test_the_writer_computes_the_id_through_the_shared_helper():
    q = _concept_query()
    assert q["params"]["concept_id"] == concept_node_id("TRAINING", "Torque  control")
    assert q["params"]["c_name_normalized"] == "torque control"


def test_the_display_name_is_set_on_create_only():
    """The id comes from the NORMALIZED name, so two spellings share a node. A plain
    `SET c.name` would make the node's display name depend on which slide was processed
    last."""
    q = _concept_query()["query"]
    assert re.search(r"ON CREATE SET[^\n]*c\.name\s*=", q), q
    assert not re.search(r"(?<!ON CREATE )SET c\.name\s*=", q), q


def test_the_node_stores_what_the_id_was_computed_from():
    """`name_normalized` and `domain` are both on the node, so the id can be recomputed
    FROM the node -- by an audit, or by the migration -- instead of trusting that
    whatever wrote it used this module."""
    q = _concept_query()["query"]
    assert "c.name_normalized" in q
    assert "c.domain" in q


def test_salience_is_still_off_the_concept_key():
    """#163's fix, which this must not undo: salience in the node key meant one node per
    salience, and TEACHES carried none."""
    q = _concept_query()
    merge = re.search(r"MERGE\s*\(\s*\w*\s*:Concept[^{)]*\{([^}]*)\}", q["query"])
    assert "salience" not in merge.group(1)
    assert re.search(r"\w+\.salience\s*=", q["query"].split("TEACHES")[1])


# --------------------------------------------------------------------------- #
# The migration
# --------------------------------------------------------------------------- #

def test_the_migration_shares_the_writers_id_function():
    mod = _migration()
    assert mod.concept_node_id is concept_node_id
    assert mod.CREATE_CONCEPT_ID_CONSTRAINT is CREATE_CONCEPT_ID_CONSTRAINT


def test_the_migration_relinks_by_types_read_from_the_graph_not_a_literal_list():
    """The writer points only TEACHES, COVERS and (v4) ALIAS_OF at a Concept -- true and useful, kept.
    But the ruling says EVERY edge on a merged node, wb's ALIGNS_TO included, so the
    relink must be driven by what `type(r)` finds in the graph. A documentary allowlist
    is the trap here, not the fix: leaving `RELINKABLE` in place as documentation would
    be a list nothing reads, and the next edge type would be silently missing from it.
    """
    src = io.open(ROOT / "doc_tools" / "plugins" / "training.py",
                  encoding="utf-8").read()
    concept_vars = set(re.findall(r"\((\w+):Concept", src))
    assert concept_vars, "no Concept pattern in training.py"
    # `(sec)-[r:COVERS]->(con)` binds `con` to a Concept earlier in the same query, so
    # the target variable is what identifies a Concept edge, not the label.
    pointed = {m.group(1) for m in re.finditer(r"\[\s*\w*\s*:(\w+)\s*\]->\((\w+)\)", src)
               if m.group(2) in concept_vars}
    assert pointed == {"TEACHES", "COVERS", "ALIAS_OF"}, pointed

    mig = io.open(ROOT / "scripts" / "neo4j_concept_id_migration.py",
                  encoding="utf-8").read()
    assert not hasattr(_migration(), "RELINKABLE")
    assert not re.search(r"^[A-Z_]+\s*=\s*[(\[]\s*[\"'][A-Z_]+[\"']", mig, re.M)
    assert "type(r) AS t" in mig


def test_the_survivor_choice_is_degree_then_a_stable_tie_break():
    """A dry run and the apply that follows it must name the same survivor, or the
    report is not a report of what happened."""
    mod = _migration()
    group = [{"eid": "4:b", "degree": 2}, {"eid": "4:a", "degree": 7},
             {"eid": "4:c", "degree": 7}]
    assert mod.pick_survivor(group)["eid"] == "4:a"
    assert mod.pick_survivor(list(reversed(group)))["eid"] == "4:a"


def test_the_migration_groups_only_real_duplicates():
    mod = _migration()
    nodes = [
        {"eid": "1", "new_id": "concept_aaaa", "degree": 1},
        {"eid": "2", "new_id": "concept_aaaa", "degree": 3},
        {"eid": "3", "new_id": "concept_bbbb", "degree": 1},
        {"eid": "4", "new_id": None, "degree": 0},          # skipped, never grouped
    ]
    dups, by_id = mod.group_duplicates(nodes)
    assert list(dups) == ["concept_aaaa"]
    assert sorted(by_id) == ["concept_aaaa", "concept_bbbb"]


def test_the_migration_commits_only_under_apply_and_a_dry_run_rolls_back():
    """It deletes nodes. The default must not. `tx.commit()` is reachable only inside an
    `args.apply` branch; the dry run reaches `tx.rollback()`."""
    src = io.open(ROOT / "scripts" / "neo4j_concept_id_migration.py",
                  encoding="utf-8").read()
    assert '"--apply", action="store_true"' in src
    for write in ("DELETE c", "SET c.id = $id"):
        assert write in src
    assert "CREATE CONSTRAINT" in CREATE_CONCEPT_ID_CONSTRAINT
    lines = src.splitlines()
    sites = [i for i, l in enumerate(lines) if re.search(r"\.commit\(\)", l)
             and not l.lstrip().startswith("#")]
    assert sites, "no commit call found"
    for i in sites:
        indent = len(lines[i]) - len(lines[i].lstrip())
        j = i - 1
        while j >= 0 and (not lines[j].strip()
                          or len(lines[j]) - len(lines[j].lstrip()) >= indent):
            j -= 1
        assert lines[j].strip() == "if args.apply:", (i + 1, lines[j])
    assert "tx.rollback()" in src
    # the constraint is issued after the commit, and only under apply
    assert src.index("client.execute_query(CREATE_CONCEPT_ID_CONSTRAINT)") \
        > src.index("tx.commit()")


# --------------------------------------------------------------------------- #
# The hardened migration: pure logic, no database
# --------------------------------------------------------------------------- #

def _edge(t, other, outgoing=False, rid=None, props=None):
    return {"type": t, "other": other, "outgoing": outgoing,
            "rid": rid or "r:%s:%s:%s" % (t, other, outgoing), "props": props or {}}


def _rec(eid, edges=(), labels=("Concept", "TRAINING")):
    return {"eid": eid, "labels": list(labels), "props": {}, "edges": list(edges)}


def _before():
    return {"nodes_total": 10,
            "nodes_by_label": {"Concept": 4, "TRAINING": 4, "Slide": 6},
            "edges_by_type": {"TEACHES": 5, "ALIGNS_TO": 3, "NEXT": 7}}


def test_a_collapse_is_predicted_for_the_same_direction_and_not_a_different_one():
    mod = _migration()
    surv = _rec("s", [_edge("TEACHES", "slide1")])
    same = _rec("l", [_edge("TEACHES", "slide1")])
    flipped = _rec("l", [_edge("TEACHES", "slide1", outgoing=True)])
    assert mod.simulate_collapses(surv, [same]) == {"TEACHES": 1}
    assert mod.simulate_collapses(surv, [flipped]) == {}


def test_two_losers_pointing_at_one_node_collapse_to_one_edge():
    """The sequential simulation. Each loser compared to the survivor alone sees no
    collision; the second one collapses onto the first's relinked edge."""
    mod = _migration()
    surv = _rec("s")
    l1 = _rec("l1", [_edge("COVERS", "sec1")])
    l2 = _rec("l2", [_edge("COVERS", "sec1")])
    assert mod.simulate_collapses(surv, [l1, l2]) == {"COVERS": 1}
    plan = [{"new_id": "x", "survivor": surv, "losers": [l1, l2]}]
    p = mod.predict(_before(), plan)
    assert p["nodes_total"] == 8
    assert p["nodes_by_label"]["Concept"] == 2
    assert p["edges_by_type"]["TEACHES"] == 5      # untouched types carry over


def test_an_untouched_edge_type_must_be_unchanged():
    mod = _migration()
    plan = [{"new_id": "x", "survivor": _rec("s"), "losers": [_rec("l")]}]
    predicted = mod.predict(_before(), plan)
    after = {"nodes_total": 9,
             "nodes_by_label": {"Concept": 3, "TRAINING": 3, "Slide": 6},
             "edges_by_type": {"TEACHES": 5, "ALIGNS_TO": 2, "NEXT": 7}}
    bad = mod.compare_census(after, predicted)
    assert [m["field"] for m in bad] == ["edges_by_type[ALIGNS_TO]"]
    assert (bad[0]["expected"], bad[0]["actual"]) == (3, 2)
    after["edges_by_type"]["ALIGNS_TO"] = 3
    assert mod.compare_census(after, predicted) == []
    # a type that appeared from nowhere fails as well
    after["edges_by_type"]["NEW"] = 1
    assert mod.compare_census(after, predicted)[0]["field"] == "edges_by_type[NEW]"


def test_a_loser_label_the_survivor_lacks_aborts():
    mod = _migration()
    surv = _rec("s", labels=("Concept", "TRAINING"))
    same = _rec("l", labels=("Concept", "TRAINING"))
    extra = _rec("l", labels=("Concept", "TRAINING", "Deprecated"))
    assert mod.abort_reasons([{"new_id": "x", "survivor": surv, "losers": [same]}]) == []
    reasons = mod.abort_reasons([{"new_id": "x", "survivor": surv, "losers": [extra]}])
    assert len(reasons) == 1 and "Deprecated" in reasons[0]


def test_an_edge_between_two_members_of_one_group_aborts():
    mod = _migration()
    surv = _rec("s")
    loser = _rec("l", [_edge("RELATED", "s", outgoing=True, rid="r1")])
    reasons = mod.abort_reasons([{"new_id": "x", "survivor": surv, "losers": [loser]}])
    assert len(reasons) == 1 and "self-loop" in reasons[0]


def test_the_roll_lock_is_required_for_apply_and_must_be_fresh():
    from datetime import datetime, timedelta, timezone
    mod = _migration()
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)

    def stamp(minutes_ago):
        return (now - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")

    assert mod.check_lock("7f/" + stamp(10), True, now)["lane"] == "7f"
    with pytest.raises(mod.LockError):
        mod.check_lock("7f/" + stamp(91), True, now)
    with pytest.raises(mod.LockError):
        mod.check_lock(None, True, now)
    with pytest.raises(mod.LockError):
        mod.check_lock("/" + stamp(1), True, now)
    with pytest.raises(mod.LockError):
        mod.check_lock("7f/not-a-time", True, now)
    assert mod.check_lock(None, False, now) is None     # a dry run needs none


def test_the_relink_query_carries_every_property_of_the_old_edge():
    """A property wb invented on ALIGNS_TO is not dropped."""
    mod = _migration()
    q = mod.relink_query("ALIGNS_TO", False)
    assert "ON CREATE SET new += properties(old)" in q
    assert "`ALIGNS_TO`" in q and "DELETE old" in q
    with pytest.raises(ValueError):
        mod.relink_query("X`) DETACH DELETE (n", False)


def test_the_relink_query_exists_for_both_directions():
    mod = _migration()
    incoming = mod.relink_query("TEACHES", False)
    outgoing = mod.relink_query("TEACHES", True)
    assert "(other)-[old:`TEACHES`]->(lose)" in incoming
    assert "(other)-[new:`TEACHES`]->(surv)" in incoming
    assert "(lose)-[old:`TEACHES`]->(other)" in outgoing
    assert "(surv)-[new:`TEACHES`]->(other)" in outgoing


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
