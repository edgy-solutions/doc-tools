"""Seal: a swallowed per-chunk `plugin.augment` failure fails the run.

Lane tr measured it (steps d+e, 20-deck rerun): 2 of 20 runs logged
`Plugin augmentation failed ... Missing required field: summary`, posted
SUCCESS, and left the slide with no TEACHES edges -- indistinguishable from a
slide that teaches nothing. Architect ruling: a per-slide concept-parse failure
is `failed:concept_parse`, never success. Domain-generic on purpose.

Builds on the harness in test_graph_write_seal.py (mocked resources, captured
IngestStatusResource).
"""
from unittest.mock import MagicMock, patch

from dagster import build_asset_context

from doc_tools.assets import semantic_assets
from doc_tools.assets.semantic_assets import (
    AugmentationError,
    GraphWriteError,
    LinkWriteError,
    _augment_failure_detail,
    build_knowledge_graph,
)
from doc_tools.config import IngestionConfig
from doc_tools.plugins.manufacturing import ManufacturingPlugin
from doc_tools.utils.ingest_failure import (
    EMITTABLE_CODES, REASON_CODE_SLUG_RE, REASON_CODES,
)

from tests.test_graph_write_seal import _failed_posts, _manifest


class _ReviewAug:
    review = {}


def _drive(manifest, *, fail_chunks=(), cypher_raises=False, rollup_raises=False,
           review_unit_zero_rows=False):
    """Drive the impl; augment raises for the chunk ids in `fail_chunks`.

    `review_unit_zero_rows` adds a global-pass node declaring a `review` block
    and forces zero part rows -- the `extraction_empty` trigger.
    Returns (exception, status mock, chunk ids augment was called with).
    """
    cfg = IngestionConfig(graph_node_label="WorkInstruction", graph_child_label="Page",
                          vector_collection_name="DocumentChunk", bucket="b")
    neo4j = MagicMock()
    if cypher_raises:
        calls = {"n": 0}

        def _fail_after_parent(*a, **k):
            calls["n"] += 1
            if calls["n"] > 1:
                raise RuntimeError("cypher boom")

        neo4j.get_client.return_value.execute_query.side_effect = _fail_after_parent
    status = MagicMock()
    seen = []
    real_aug = ManufacturingPlugin.augment
    real_full = ManufacturingPlugin.process_fulltext

    def _augment(self, section, config):
        seen.append(section.node_id)
        if section.node_id in fail_chunks:
            raise ValueError("Missing required field: summary")
        return real_aug(self, section, config)

    def _full(self, *a, **k):
        nodes = list(real_full(self, *a, **k) or [])
        if review_unit_zero_rows:
            n = MagicMock()
            n.domain_augmentation = _ReviewAug()
            nodes.append(n)
        return nodes

    rollup = MagicMock(side_effect=RuntimeError("rollup boom")) if rollup_raises else MagicMock()
    patches = [
        patch("doc_tools.utils.dagster_resources.IngestStatusResource", return_value=status),
        patch.object(ManufacturingPlugin, "execute_pass2_rollup", rollup),
        patch.object(ManufacturingPlugin, "augment", _augment),
        patch.object(ManufacturingPlugin, "process_fulltext", _full),
    ]
    if review_unit_zero_rows:
        patches.append(patch.object(semantic_assets, "_part_row_count", return_value=0))
    caught = None
    for p in patches:
        p.start()
    try:
        build_knowledge_graph(
            build_asset_context(), cfg, manifest,
            s3=MagicMock(), neo4j=neo4j, weaviate=MagicMock(),
            llm=MagicMock(), jena=MagicMock())
    except Exception as e:  # noqa: BLE001
        caught = e
    finally:
        for p in reversed(patches):
            p.stop()
    return caught, status, seen


def _first_chunk():
    """A chunk id the harness really augments (probe with nothing failing)."""
    err, _status, seen = _drive(_manifest())
    assert err is None and seen, (err, seen)
    return seen[0]


def test_one_chunk_raising_fails_the_run():
    err, _s, _ = _drive(_manifest(), fail_chunks=(_first_chunk(),))
    assert isinstance(err, AugmentationError), repr(err)
    assert str(err).startswith("failed:concept_parse")


def test_the_stage_post_is_failed_concept_parse_with_a_detail():
    _e, status, _ = _drive(_manifest(), fail_chunks=(_first_chunk(),))
    posts = _failed_posts(status)
    assert len(posts) == 1
    kw = posts[0].kwargs
    assert kw["reason_code"] == "concept_parse"
    # a `failed` post with a blank detail is refused on the wire
    assert kw["detail"].strip() and kw["detail"] == kw["reason"]
    assert not [c for c in status.update.call_args_list if c.args[1:2] == ("review",)]


def test_the_detail_names_the_chunk_and_the_count():
    chunk = _first_chunk()
    _e, status, seen = _drive(_manifest(), fail_chunks=(chunk,))
    detail = _failed_posts(status)[0].kwargs["detail"]
    assert chunk in detail
    assert f"1 of {len(seen)}" in detail
    assert "Missing required field: summary" in detail


def test_detail_is_stable_capped_and_keeps_the_error():
    fails = [f"d_p{i}: ValueError: boom" for i in range(60, 0, -1)]
    d = _augment_failure_detail(fails, 80)
    assert len(d) <= 500 and "(+55 more)" in d and "ValueError: boom" in d
    assert "d_p1, d_p10," in d  # sorted
    assert "60 of 80" in d
    assert len(_augment_failure_detail(["c: E: " + "x" * 5000], 1)) <= 500


def test_graph_write_wins_over_concept_parse():
    err, status, _ = _drive(_manifest(), fail_chunks=(_first_chunk(),), cypher_raises=True)
    assert isinstance(err, GraphWriteError), repr(err)
    posts = _failed_posts(status)
    assert len(posts) == 1 and posts[0].kwargs["reason_code"] == "graph_write"


def test_link_write_wins_over_concept_parse():
    err, status, _ = _drive(_manifest(), fail_chunks=(_first_chunk(),), rollup_raises=True)
    assert isinstance(err, LinkWriteError), repr(err)
    posts = _failed_posts(status)
    assert len(posts) == 1 and posts[0].kwargs["reason_code"] == "link_write"


def test_concept_parse_beats_extraction_empty():
    # Sanity: with every chunk fine, this setup posts extraction_empty.
    _e, status0, _ = _drive(_manifest(), review_unit_zero_rows=True)
    assert [c.kwargs["reason_code"] for c in _failed_posts(status0)] == ["extraction_empty"]
    # The raised augmentation is the cause, zero rows the symptom.
    err, status, _ = _drive(_manifest(), fail_chunks=(_first_chunk(),),
                            review_unit_zero_rows=True)
    assert isinstance(err, AugmentationError), repr(err)
    posts = _failed_posts(status)
    assert len(posts) == 1 and posts[0].kwargs["reason_code"] == "concept_parse"


def test_every_chunk_augmenting_is_unchanged():
    err, status, seen = _drive(_manifest())
    assert err is None and seen
    assert not _failed_posts(status)
    assert [c for c in status.update.call_args_list if c.args[1:2] == ("review",)]


def test_no_ingest_id_still_raises():
    err, status, _ = _drive(_manifest(with_id=False), fail_chunks=(_first_chunk(),))
    assert isinstance(err, AugmentationError), repr(err)
    assert not _failed_posts(status)


def test_concept_parse_is_emittable():
    assert "concept_parse" in REASON_CODES
    assert "concept_parse" in EMITTABLE_CODES
    assert REASON_CODE_SLUG_RE.match("concept_parse")
