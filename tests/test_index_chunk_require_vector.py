"""require_vector: a TRAINING chunk must carry a vector or the run fails (contract §6)."""
import json
from unittest.mock import MagicMock

import pytest

from doc_tools.assets import semantic_assets as sa
from tests.test_training_workbench_golden import BUCKET, FakeWeaviate, _graph_run


def _client(exists=False):
    client = MagicMock()
    data = client.collections.get.return_value.data
    data.exists.return_value = exists
    return client, data


def _embed_raises(monkeypatch):
    def boom(_t):
        raise RuntimeError("gateway down")
    monkeypatch.setattr("doc_tools.utils.embed.embed_document", boom)


PROPS = {"text": "hello", "doc_id": "d", "chunk_id": "d_p1", "domain": "TRAINING"}


def test_require_vector_raises_before_any_write(monkeypatch):
    _embed_raises(monkeypatch)
    client, data = _client()
    with pytest.raises(sa.MissingVectorError, match="d_p1") as ei:
        sa._index_chunk(client, "C", dict(PROPS), require_vector=True)
    assert "gateway down" in str(ei.value)
    assert isinstance(ei.value.__cause__, RuntimeError)
    data.exists.assert_not_called()
    data.insert.assert_not_called()
    data.replace.assert_not_called()


def test_require_vector_raises_on_empty_text(monkeypatch):
    monkeypatch.setattr("doc_tools.utils.embed.embed_document", lambda t: [1.0])
    client, data = _client()
    with pytest.raises(sa.MissingVectorError):
        sa._index_chunk(client, "C", {**PROPS, "text": ""}, require_vector=True)
    data.insert.assert_not_called()


def test_default_still_writes_without_vector(monkeypatch):
    _embed_raises(monkeypatch)
    client, data = _client(exists=False)
    assert sa._index_chunk(client, "C", dict(PROPS)) == "written_without_vector"
    assert "vector" not in data.insert.call_args.kwargs


def test_default_still_skips_when_row_exists(monkeypatch):
    _embed_raises(monkeypatch)
    client, data = _client(exists=True)
    assert sa._index_chunk(client, "C", dict(PROPS)) == "skipped_would_strip_vector"
    data.replace.assert_not_called()


def test_require_vector_with_embed_ok_writes_the_vector(monkeypatch):
    monkeypatch.setattr("doc_tools.utils.embed.embed_document", lambda t: [0.25] * 768)
    client, data = _client()
    assert sa._index_chunk(client, "C", dict(PROPS), require_vector=True) == "written"
    assert data.insert.call_args.kwargs["vector"] == [0.25] * 768


# --- the asset: smallest seam is the whole graph asset on a hand-built manifest ---

def _manifest(client, domain, cid):
    text_key = f"x/generated/{cid[-8:]}/text.json"
    elements = [
        {"type": "Title", "text": "Slide one", "metadata": {"page_number": 1}},
        {"type": "PageBreak", "text": "", "metadata": {"page_number": 1}},
        {"type": "Title", "text": "BOOM slide two", "metadata": {"page_number": 2}},
        {"type": "PageBreak", "text": "", "metadata": {"page_number": 2}},
        {"type": "Title", "text": "Slide three", "metadata": {"page_number": 3}},
    ]
    client.put_object(Bucket=BUCKET, Key=text_key, Body=json.dumps(elements).encode())
    return {"doc_id": cid, "ingest_id": cid, "filename": "d.pptx", "text_location": text_key,
            "metadata": ({"domain_type": "training"} if domain == "training"
                         else {"content_kind": "work-instructions"}),
            "embedded_images": {"figure-page1-1.png": "s3://b/x/images/figure-page1-1.png"},
            "current_key": f"x/generated/{cid[-8:]}/current.json"}


def _embed_fails_on_boom(monkeypatch):
    def embed(text):
        if "BOOM" in text:
            raise RuntimeError("gateway down")
        return [0.5] * 768
    monkeypatch.setattr("doc_tools.utils.embed.embed_document", embed)


def test_training_asset_fails_the_run_but_indexes_the_other_slides(monkeypatch):
    from tests.test_document_parser_versioning import _FakeS3Client

    _embed_fails_on_boom(monkeypatch)
    cid = "sha256:" + "c" * 64
    client = _FakeS3Client()
    weaviate = FakeWeaviate()
    # `_graph_run` stubs `augment` to raise on every chunk, so the run now fails
    # first as failed:concept_parse (AugmentationError, raised ahead of the
    # MissingVectorError block). It used to swallow that and reach
    # MissingVectorError; the indexing of the other slides, which is what this
    # test is about, is unchanged and still asserted below.
    with pytest.raises(sa.AugmentationError, match="failed:concept_parse"):
        _graph_run(_manifest(client, "training", cid), client, monkeypatch,
                   weaviate=weaviate, reraise=True)
    ids = [o["properties"]["chunk_id"] for o in weaviate.objects]
    assert ids == [f"{cid}_p1", f"{cid}_p3"]
    assert all(len(o["vector"]) == 768 for o in weaviate.objects)


def test_non_training_asset_does_not_raise_and_keeps_figure_objects(monkeypatch):
    from tests.test_document_parser_versioning import _FakeS3Client

    _embed_fails_on_boom(monkeypatch)
    cid = "sha256:" + "d" * 64
    client = _FakeS3Client()
    weaviate = FakeWeaviate()
    _graph_run(_manifest(client, "manufacturing", cid), client, monkeypatch,
               weaviate=weaviate, reraise=True)
    by_id = {o["properties"]["chunk_id"]: o for o in weaviate.objects}
    assert f"{cid}_fig_figure-page1-1" in by_id
    assert "vector" not in by_id[f"{cid}_p2"]  # written_without_vector, unchanged
