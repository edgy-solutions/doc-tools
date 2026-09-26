"""Tests for _index_chunk's stable-identity + no-vector-stripping contract
(doc_tools/assets/semantic_assets.py).

Two defects, one fix:
  1. No uuid was ever passed to Weaviate, so Weaviate minted a random one on
     every insert -> re-ingesting the same document DUPLICATED every chunk
     row.
  2. On embed failure, the old code always wrote the row (even when a row
     already existed), and .data.replace() with no vector is a whole-object
     PUT that STRIPS an existing vector.

A deterministic uuid (generate_uuid5(chunk_id)) is what makes case 2
reachable/detectable at all, hence testing both here.

Uses fakes, not a live Weaviate, matching the MagicMock-based fake-client
style already used in tests/test_semantic_assets.py.
"""
from unittest.mock import MagicMock, patch

import pytest
from weaviate.util import generate_uuid5

from doc_tools.assets.semantic_assets import _index_chunk


def _fake_client(exists: bool):
    """A MagicMock client shaped like client.collections.get(name) ->
    object with .data.exists/.insert/.replace, matching the real v4 API
    surface _index_chunk calls."""
    client = MagicMock()
    client.collections.get.return_value.data.exists.return_value = exists
    return client


def _props(chunk_id="doc1_p1", text="hello world"):
    return {"text": text, "doc_id": "doc1", "chunk_id": chunk_id, "domain": "MANUFACTURING"}


# --------------------------------------------------------------------------- #
# 1. Same chunk_id twice -> same uuid (anti-duplication claim).
# --------------------------------------------------------------------------- #
def test_same_chunk_id_produces_the_same_uuid_both_times():
    client = _fake_client(exists=False)
    with patch("doc_tools.utils.embed.embed_document", return_value=[0.1, 0.2]):
        _index_chunk(client, "Chunks", _props(chunk_id="doc1_p1"))
        client.collections.get.return_value.data.exists.return_value = True
        _index_chunk(client, "Chunks", _props(chunk_id="doc1_p1"))

    insert_uuid = client.collections.get.return_value.data.insert.call_args.kwargs["uuid"]
    replace_uuid = client.collections.get.return_value.data.replace.call_args.kwargs["uuid"]
    assert insert_uuid == replace_uuid == generate_uuid5("doc1_p1")


# --------------------------------------------------------------------------- #
# 2. Different chunk_id -> different uuid.
# --------------------------------------------------------------------------- #
def test_different_chunk_id_produces_different_uuid():
    client = _fake_client(exists=False)
    with patch("doc_tools.utils.embed.embed_document", return_value=[0.1, 0.2]):
        _index_chunk(client, "Chunks", _props(chunk_id="doc1_p1"))
        uuid_a = client.collections.get.return_value.data.insert.call_args.kwargs["uuid"]

        client.collections.get.return_value.data.insert.reset_mock()
        _index_chunk(client, "Chunks", _props(chunk_id="doc1_p2"))
        uuid_b = client.collections.get.return_value.data.insert.call_args.kwargs["uuid"]

    assert uuid_a != uuid_b
    assert uuid_a == generate_uuid5("doc1_p1")
    assert uuid_b == generate_uuid5("doc1_p2")


# --------------------------------------------------------------------------- #
# 3. vector present, object absent -> insert(uuid=..., vector=...); "written"
# --------------------------------------------------------------------------- #
def test_vector_present_object_absent_inserts_with_vector():
    client = _fake_client(exists=False)
    props = _props()
    with patch("doc_tools.utils.embed.embed_document", return_value=[0.1, 0.2, 0.3]):
        verdict = _index_chunk(client, "Chunks", props)

    client.collections.get.return_value.data.insert.assert_called_once_with(
        uuid=generate_uuid5(props["chunk_id"]), properties=props, vector=[0.1, 0.2, 0.3]
    )
    client.collections.get.return_value.data.replace.assert_not_called()
    assert verdict == "written"


# --------------------------------------------------------------------------- #
# 4. vector present, object exists -> replace(uuid=..., vector=...);
#    insert NOT called; "written"
# --------------------------------------------------------------------------- #
def test_vector_present_object_exists_replaces_with_vector():
    client = _fake_client(exists=True)
    props = _props()
    with patch("doc_tools.utils.embed.embed_document", return_value=[0.4, 0.5]):
        verdict = _index_chunk(client, "Chunks", props)

    client.collections.get.return_value.data.replace.assert_called_once_with(
        uuid=generate_uuid5(props["chunk_id"]), properties=props, vector=[0.4, 0.5]
    )
    client.collections.get.return_value.data.insert.assert_not_called()
    assert verdict == "written"


# --------------------------------------------------------------------------- #
# 5. vector None (embed raises), object absent -> insert with NO vector kwarg;
#    "written_without_vector"
# --------------------------------------------------------------------------- #
def test_embed_failure_on_new_row_writes_without_vector():
    client = _fake_client(exists=False)
    props = _props()
    with patch("doc_tools.utils.embed.embed_document", side_effect=RuntimeError("gateway down")):
        verdict = _index_chunk(client, "Chunks", props)

    client.collections.get.return_value.data.insert.assert_called_once_with(
        uuid=generate_uuid5(props["chunk_id"]), properties=props
    )
    call_kwargs = client.collections.get.return_value.data.insert.call_args.kwargs
    assert "vector" not in call_kwargs
    client.collections.get.return_value.data.replace.assert_not_called()
    assert verdict == "written_without_vector"


# --------------------------------------------------------------------------- #
# 6. vector None, object EXISTS -> neither insert nor replace called at all;
#    "skipped_would_strip_vector". This is the load-bearing case: the whole
#    point is that we must NOT call .data.replace() with no vector, because
#    that documented whole-object PUT would strip the existing vector.
# --------------------------------------------------------------------------- #
def test_embed_failure_on_existing_row_does_not_strip_its_vector():
    client = _fake_client(exists=True)
    props = _props()
    with patch("doc_tools.utils.embed.embed_document", side_effect=RuntimeError("gateway down")):
        verdict = _index_chunk(client, "Chunks", props)

    client.collections.get.return_value.data.insert.assert_not_called()
    client.collections.get.return_value.data.replace.assert_not_called()
    assert verdict == "skipped_would_strip_vector"


# --------------------------------------------------------------------------- #
# 7. missing/empty chunk_id -> ValueError.
# --------------------------------------------------------------------------- #
def test_missing_chunk_id_raises_value_error():
    client = _fake_client(exists=False)
    props = {"text": "hi", "doc_id": "doc1", "domain": "MANUFACTURING"}
    with pytest.raises(ValueError):
        _index_chunk(client, "Chunks", props)


def test_empty_chunk_id_raises_value_error():
    client = _fake_client(exists=False)
    props = {"text": "hi", "doc_id": "doc1", "chunk_id": "", "domain": "MANUFACTURING"}
    with pytest.raises(ValueError):
        _index_chunk(client, "Chunks", props)
