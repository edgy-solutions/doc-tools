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
    aug = SlideAugmentation(concepts=[Concept(name="Torque  control", salience=0.9)],
                            objectives=[])
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


def test_the_migration_can_relink_every_edge_the_writer_points_at_a_concept():
    """A drift guard with teeth. The migration relinks by ENUMERATED type, because
    `apoc.refactor.mergeNodes` is not assumed present and a dynamic relink would drop an
    edge type nobody had thought about. So a new edge type written at a Concept must be
    added to `RELINKABLE` deliberately -- and until it is, this fails here rather than
    aborting a migration against the live graph.
    """
    src = io.open(ROOT / "doc_tools" / "plugins" / "training.py",
                  encoding="utf-8").read()
    concept_vars = set(re.findall(r"\((\w+):Concept", src))
    assert concept_vars, "no Concept pattern in training.py"
    # `(sec)-[r:COVERS]->(con)` binds `con` to a Concept earlier in the same query, so
    # the target variable is what identifies a Concept edge, not the label.
    pointed = {m.group(1) for m in re.finditer(r"\[\s*\w*\s*:(\w+)\s*\]->\((\w+)\)", src)
               if m.group(2) in concept_vars}
    assert pointed == {"TEACHES", "COVERS"}, pointed
    assert pointed <= set(_migration().RELINKABLE), pointed


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


def test_the_migration_is_a_dry_run_unless_apply_is_passed():
    """It deletes nodes. The default must not."""
    src = io.open(ROOT / "scripts" / "neo4j_concept_id_migration.py",
                  encoding="utf-8").read()
    assert '"--apply", action="store_true"' in src
    for write in ("DELETE c", "SET c.id = $id", "CREATE CONSTRAINT"):
        assert write in src or write in CREATE_CONCEPT_ID_CONSTRAINT
    # every write is behind `args.apply`
    assert src.count("if args.apply:") >= 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
