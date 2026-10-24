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
