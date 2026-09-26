"""The XML chunker must satisfy `_index_chunk`'s identity contract.

These tests exist because of a near-miss. `_index_chunk` grew a hard
requirement for a non-empty `properties["chunk_id"]` (it derives the row
uuid from it, so a chunk with no stable identity is the duplicate-row
defect it was written to fix). Two of its three callers build a chunk_id;
the third — `index_xml_chunks_to_weaviate` — did not, and its own
per-chunk `except Exception` would have swallowed the resulting ValueError
and written ZERO DocumentChunk rows for every XML data module while still
logging a warning per chunk and materializing successfully.

Nothing in the suite covered `extract_chunks_from_graph` at all, which is
why the seam was invisible. The point of these tests is the seam, not the
hash: the important assertion is that what the chunker emits is accepted
by the thing that consumes it.
"""

import hashlib

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDFS

from doc_tools.utils.xml_chunks import extract_chunks_from_graph

_MIL = "http://edgy-solutions.com/ontology/mil#"
_ROOT = "urn:doc:dm-test-0001"


def _graph() -> Graph:
    """A small graph exercising every chunk kind the chunker emits."""
    g = Graph()
    root = URIRef(_ROOT)
    g.add((root, RDFS.label, Literal("Hydraulic Pump Removal")))
    g.add((root, URIRef(_MIL + "hasInstructionText"),
           Literal("Depressurize the system before loosening any fitting.")))
    g.add((root, URIRef(_MIL + "hasInstructionText"),
           Literal("Remove the four retaining bolts in a crosswise order.")))
    g.add((root, URIRef(_MIL + "hasWarning"),
           Literal("Residual pressure can eject the fitting at high speed.")))
    fig = URIRef(_MIL + "figure/FIG-3")
    g.add((root, URIRef(_MIL + "hasFigure"), fig))
    g.add((fig, RDFS.label, Literal("FIG-3")))
    g.add((root, URIRef(_MIL + "hasDescription"),
           Literal("Applies to all airframes after block 40 retrofit.")))
    return g


def test_every_chunk_carries_a_non_empty_chunk_id():
    """The contract `_index_chunk` enforces with a ValueError."""
    chunks = extract_chunks_from_graph(_graph(), _ROOT, "MAINTENANCE")
    assert chunks, "fixture graph should produce chunks"
    for chunk in chunks:
        assert chunk.get("chunk_id"), f"chunk without identity: {chunk}"


def test_chunk_ids_are_unique_within_a_document():
    chunks = extract_chunks_from_graph(_graph(), _ROOT, "MAINTENANCE")
    ids = [c["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids))


def test_chunk_ids_are_stable_across_two_builds_of_the_same_graph():
    """The whole reason for a deterministic id: a re-ingest must land on
    the same uuids, so the write replaces rather than duplicates."""
    first = extract_chunks_from_graph(_graph(), _ROOT, "MAINTENANCE")
    second = extract_chunks_from_graph(_graph(), _ROOT, "MAINTENANCE")
    assert {c["chunk_id"] for c in first} == {c["chunk_id"] for c in second}


def test_identity_follows_text_not_position():
    """Keyed on content, so reordering the graph's triples cannot re-mint
    a chunk's uuid. rdflib iteration order is only reliably stable for an
    unchanged in-memory graph; an ordinal key would make a re-parse that
    reorders two steps look like two brand-new chunks."""
    g = _graph()
    step = "Depressurize the system before loosening any fitting."
    chunks = extract_chunks_from_graph(g, _ROOT, "MAINTENANCE")
    ids_by_text = {c["text"]: c["chunk_id"] for c in chunks}

    digest = hashlib.sha1(step.encode("utf-8")).hexdigest()[:12]
    assert ids_by_text[step].endswith(digest)


def test_editing_a_chunks_text_gives_it_a_new_identity():
    """The corollary: revised text is a different chunk, so the stale row
    is not silently overwritten in place with no trace. The XML asset's
    pre-delete sweep is what removes the superseded row."""
    g = _graph()
    chunks_before = extract_chunks_from_graph(g, _ROOT, "MAINTENANCE")

    g2 = _graph()
    old = Literal("Residual pressure can eject the fitting at high speed.")
    g2.remove((URIRef(_ROOT), URIRef(_MIL + "hasWarning"), old))
    g2.add((URIRef(_ROOT), URIRef(_MIL + "hasWarning"),
            Literal("Residual pressure can eject the fitting. Stand clear.")))
    chunks_after = extract_chunks_from_graph(g2, _ROOT, "MAINTENANCE")

    assert ({c["chunk_id"] for c in chunks_before}
            != {c["chunk_id"] for c in chunks_after})


def test_chunker_output_is_accepted_by_index_chunk():
    """The seam itself. Feed real chunker output through `_index_chunk`
    with a stubbed client: no ValueError, and each row is written at the
    uuid derived from its chunk_id.

    This is the test that would have caught the zero-write regression —
    the two sides were each self-consistent and only the join was wrong.
    """
    weaviate = pytest.importorskip("weaviate.util")
    from doc_tools.assets import semantic_assets

    chunks = extract_chunks_from_graph(_graph(), _ROOT, "MAINTENANCE")

    written: dict[str, dict] = {}

    class _Data:
        def exists(self, uuid):
            return uuid in written

        def insert(self, uuid, properties, vector=None):
            written[uuid] = properties

        def replace(self, uuid, properties, vector=None):
            written[uuid] = properties

    class _Collection:
        data = _Data()

    class _Client:
        class collections:
            @staticmethod
            def get(name):
                return _Collection()

    def _fake_embed(text):
        return [0.1, 0.2, 0.3]

    import doc_tools.utils.embed as embed_mod
    original = embed_mod.embed_document
    embed_mod.embed_document = _fake_embed
    try:
        verdicts = [
            semantic_assets._index_chunk(_Client(), "DocumentChunk", c)
            for c in chunks
        ]
    finally:
        embed_mod.embed_document = original

    assert verdicts == ["written"] * len(chunks)
    assert len(written) == len(chunks)
    for chunk in chunks:
        assert weaviate.generate_uuid5(chunk["chunk_id"]) in written


def test_a_reingest_of_the_same_graph_does_not_add_rows():
    """Idempotence end to end: run the same document twice through
    `_index_chunk` and the row count must not move."""
    weaviate = pytest.importorskip("weaviate.util")
    assert weaviate  # imported for the uuid helper's availability
    from doc_tools.assets import semantic_assets

    written: dict[str, dict] = {}

    class _Data:
        def exists(self, uuid):
            return uuid in written

        def insert(self, uuid, properties, vector=None):
            written[uuid] = properties

        def replace(self, uuid, properties, vector=None):
            written[uuid] = properties

    class _Collection:
        data = _Data()

    class _Client:
        class collections:
            @staticmethod
            def get(name):
                return _Collection()

    import doc_tools.utils.embed as embed_mod
    original = embed_mod.embed_document
    embed_mod.embed_document = lambda text: [0.1, 0.2, 0.3]
    try:
        for _ in range(2):
            for chunk in extract_chunks_from_graph(
                _graph(), _ROOT, "MAINTENANCE"
            ):
                semantic_assets._index_chunk(
                    _Client(), "DocumentChunk", chunk
                )
    finally:
        embed_mod.embed_document = original

    expected = len(extract_chunks_from_graph(_graph(), _ROOT, "MAINTENANCE"))
    assert len(written) == expected
