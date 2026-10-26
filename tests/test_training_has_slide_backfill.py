"""The HAS_SLIDE backfill: dry run writes nothing, --apply refuses on R1/X1,
and the write mirrors the plugin's own link query so the two cannot drift."""
import importlib.util
import re
from pathlib import Path
from unittest.mock import MagicMock

from doc_tools.plugins.training import TrainingPlugin
from doc_tools.utils.graph_overlay import overlay_for

_SPEC = importlib.util.spec_from_file_location(
    "training_has_slide_backfill",
    Path(__file__).resolve().parents[1] / "scripts" / "training_has_slide_backfill.py")
bf = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bf)


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()


def _client(r1=0, x1=0, missing=3):
    """Answers each script query by its identity; records every query."""
    c = MagicMock()
    seen = []

    def run(query, parameters=None, db=None):
        seen.append(query)
        if query == bf.R1_QUERY:
            return [{"n": r1}]
        if query == bf.X1_QUERY:
            return [{"n": x1}]
        if query == bf.MISSING_QUERY:
            return [{"n": missing}]
        if query == bf.PAIRS_QUERY:
            return [{"pairs": 5, "edges": 5}]
        if query == bf.WRITE_QUERY:
            return [{"mirrored": 5}]
        return [{"n": 5}]

    c.execute_query.side_effect = run
    c.seen = seen
    return c


def test_dry_run_issues_no_write():
    c = _client()
    assert bf.main([], client=c) == 0
    assert bf.WRITE_QUERY not in c.seen
    assert not any("MERGE" in q for q in c.seen)


def test_apply_refuses_when_r1_is_positive():
    c = _client(r1=2)
    assert bf.main(["--apply"], client=c) == 2
    assert bf.WRITE_QUERY not in c.seen


def test_apply_refuses_when_x1_is_positive():
    c = _client(x1=1)
    assert bf.main(["--apply"], client=c) == 2
    assert bf.WRITE_QUERY not in c.seen


def test_apply_writes_once_and_passes_when_counts_hold():
    c = _client(missing=0)
    assert bf.main(["--apply"], client=c) == 0
    assert c.seen.count(bf.WRITE_QUERY) == 1


def test_write_merges_the_overlay_edge_over_the_training_course():
    edge = overlay_for("training").edge
    q = _norm(bf.WRITE_QUERY)
    assert f"MERGE (sec)-[:{edge}]->(s)" in q
    assert "(c:Course:TRAINING)" in q and "(sec:Section:TRAINING)" in q
    assert "(s:Slide:TRAINING)" in q
    assert q.count("MERGE") == 1


def test_write_range_predicate_is_the_plugins_link_query_predicate():
    queries = []
    client = MagicMock()
    client.execute_query.side_effect = lambda q, p=None: queries.append(q)
    cfg = MagicMock(graph_node_label="Course", graph_child_label="Slide")
    TrainingPlugin("TRAINING").execute_pass2_rollup(client, "doc-1", cfg)
    plugin_link = _norm(queries[0])
    pred = _norm(bf.RANGE_PREDICATE)
    assert pred in plugin_link
    assert pred in _norm(bf.WRITE_QUERY)
