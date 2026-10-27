"""Seal: the ingest stage post is a run's LAST act, and a failed graph write
posts `failed:graph_write` instead of `review`.

Architect ruling: the stage post comes after every store write has succeeded
or failed; stages never move backwards. Before this, `review` was posted in
front of the cypher loop, the SPARQL loop and the Pass 2 roll-up, each of
which logs-and-continues, so a steward could be handed a document the graph
did not hold.

What is sealed here, without driving the whole impl (it needs S3, Neo4j,
Weaviate, an LLM and Jena, and no existing test stands those up):

  * `graph_write` is a known reason code. `IngestStatusResource` coerces any
    code outside REASON_CODES to `unexpected_error`, so an unlisted code never
    reaches the row.
  * the detail names only the stores that failed, with counts, within 500 chars.
  * in the impl's source, every write precedes the stage post.
"""
import inspect

from doc_tools.assets import semantic_assets
from doc_tools.assets.semantic_assets import (
    GraphWriteError,
    _build_knowledge_graph_impl,
    _graph_write_detail,
)
from doc_tools.utils.ingest_failure import REASON_CODE_SLUG_RE, REASON_CODES


def test_graph_write_is_a_known_reason_code_and_will_not_be_coerced():
    assert "graph_write" in REASON_CODES
    assert REASON_CODE_SLUG_RE.match("graph_write")


def test_detail_for_a_neo4j_only_failure_names_neo4j_and_not_jena():
    d = _graph_write_detail({"neo4j": ["RuntimeError: a", "RuntimeError: b"]},
                            {"neo4j": 5, "jena": 3})
    assert "neo4j" in d and "jena" not in d
    assert "2 of 5" in d


def test_detail_for_a_jena_only_failure_names_jena_and_not_neo4j():
    d = _graph_write_detail({"jena": ["OSError: down"]}, {"neo4j": 5, "jena": 3})
    assert "jena" in d and "neo4j" not in d
    assert "1 of 3" in d


def test_detail_for_both_stores_names_both_with_counts():
    d = _graph_write_detail(
        {"neo4j": ["RuntimeError: a"], "jena": ["OSError: b"]},
        {"neo4j": 5, "jena": 3})
    assert "neo4j (1 of 5 queries)" in d and "jena (1 of 3 queries)" in d
    assert "first error:" in d


def test_detail_is_capped_at_500_chars():
    d = _graph_write_detail({"neo4j": ["RuntimeError: " + "x" * 5000]}, {"neo4j": 1})
    assert len(d) <= 500


def test_every_store_write_precedes_the_stage_post_in_the_impl():
    src = inspect.getsource(_build_knowledge_graph_impl)
    # Stable substrings: the cypher loop header, the SPARQL loop header, the
    # roll-up call, and the post's own error log line (the last statement of
    # the post block's try/except).
    post = src.index("Failed to post ingest stage")
    for marker in (
        "for idx, c_query in enumerate(cypher_queries)",
        "for idx, s_query in enumerate(sparql_queries)",
        "plugin.execute_pass2_rollup(",
    ):
        assert src.index(marker) < post, f"{marker!r} must come before the stage post"
    assert src.index("# Phase 5b") < post
    assert src.index("plugin.execute_pass2_rollup(") < src.index("# Phase 5b")


def test_graph_write_error_is_an_exception():
    assert issubclass(GraphWriteError, Exception)
    assert semantic_assets.GraphWriteError is GraphWriteError
    try:
        raise GraphWriteError("graph write failed: neo4j (1 of 1 queries)")
    except Exception as e:
        assert "neo4j" in str(e)


# --------------------------------------------------------------------------- #
# failed:link_write -- the Pass 2 link/roll-up used to be swallowed by the
# plugin's own try/except (print + success). It now propagates, is recorded
# apart from `_graph_failures`, and fails the run with its own reason code.
# --------------------------------------------------------------------------- #
import contextlib
from unittest.mock import MagicMock, patch

import pytest
from dagster import build_asset_context

from doc_tools.assets.semantic_assets import LinkWriteError
from doc_tools.config import IngestionConfig
from doc_tools.plugins.manufacturing import ManufacturingPlugin
from doc_tools.plugins.training import TrainingPlugin

_CANON = "sha256:" + "ab" * 32


def test_link_write_is_a_known_reason_code_and_will_not_be_coerced():
    assert "link_write" in REASON_CODES
    assert REASON_CODE_SLUG_RE.match("link_write")


def test_training_rollup_propagates_a_failed_query_and_prints_nothing(capsys):
    client = MagicMock()
    client.execute_query.side_effect = RuntimeError("neo4j down")
    cfg = IngestionConfig(graph_node_label="Course", graph_child_label="Slide",
                          vector_collection_name="DocumentChunk", bucket="b")
    with pytest.raises(RuntimeError, match="neo4j down"):
        TrainingPlugin("TRAINING").execute_pass2_rollup(client, "doc-1", cfg)
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def _manifest(with_id=True):
    m = {
        "doc_id": "doc-1",
        "text_location": "x/text.json",
        "metadata": {"content_kind": "work-instructions"},
    }
    if with_id:
        m["ingest_id"] = _CANON
        m["provenance"] = {
            "obtained_via": "user-drop", "authoritative_source": "user-upload",
            "as_of": "unknown", "ingested_at": "2026-10-02T00:00:00+00:00",
            "ingest_run": "run-1", "standing": "unverified",
            "ingest_id": _CANON,
        }
    return m


def _drive(manifest, *, rollup_raises, cypher_raises=False):
    """Drive the impl with mocked resources; return (exception, status mock)."""
    from doc_tools.assets.semantic_assets import build_knowledge_graph

    cfg = IngestionConfig(graph_node_label="WorkInstruction",
                          graph_child_label="Page",
                          vector_collection_name="DocumentChunk", bucket="b")
    neo4j = MagicMock()
    if cypher_raises:
        # The first write is the stamped parent MERGE, whose failure HALTS the
        # ingest (ADR-0041); the domain cypher loop after it is what swallows.
        calls = {"n": 0}

        def _fail_after_parent(*a, **k):
            calls["n"] += 1
            if calls["n"] > 1:
                raise RuntimeError("cypher boom")

        neo4j.get_client.return_value.execute_query.side_effect = _fail_after_parent
    status = MagicMock()
    rollup = MagicMock(side_effect=RuntimeError("rollup boom")) if rollup_raises else MagicMock()
    caught = None
    with patch("doc_tools.utils.dagster_resources.IngestStatusResource",
               return_value=status), \
         patch.object(ManufacturingPlugin, "execute_pass2_rollup", rollup):
        try:
            build_knowledge_graph(
                build_asset_context(), cfg, manifest,
                s3=MagicMock(), neo4j=neo4j, weaviate=MagicMock(),
                llm=MagicMock(), jena=MagicMock())
        except Exception as e:  # noqa: BLE001
            caught = e
    return caught, status


def _failed_posts(status):
    return [c for c in status.update.call_args_list if c.args[1:2] == ("failed",)]


def test_a_failed_rollup_raises_link_write_error_and_posts_link_write():
    err, status = _drive(_manifest(), rollup_raises=True)
    assert isinstance(err, LinkWriteError), repr(err)
    assert str(err).startswith("failed:link_write")
    posts = _failed_posts(status)
    assert len(posts) == 1
    kw = posts[0].kwargs
    assert kw["reason_code"] == "link_write"
    assert kw["detail"].strip() and "rollup boom" in kw["detail"]


def test_a_failed_rollup_still_fails_the_run_without_an_ingest_id():
    err, status = _drive(_manifest(with_id=False), rollup_raises=True)
    assert isinstance(err, LinkWriteError), repr(err)
    assert not _failed_posts(status)


def test_graph_write_wins_when_both_the_cypher_and_the_rollup_fail():
    err, status = _drive(_manifest(), rollup_raises=True, cypher_raises=True)
    assert isinstance(err, GraphWriteError), repr(err)
    posts = _failed_posts(status)
    assert len(posts) == 1 and posts[0].kwargs["reason_code"] == "graph_write"
