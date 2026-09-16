"""The MeshCollectionMeta writer — every stamped value is an OBSERVATION.

THE DEFECT. DEFAULT_EMBED_MODEL and EXPECTED_EMBED_DIM are hand-copied between this
repo and invincible-agent, enforced by "code review catches drift". doc-tools writes
the vectors, engine-o embeds the query, and nothing asserted the two agree. Weaviate
locks the DIMENSION on first write and is blind to the MODEL: a swap between two
768-dim models writes cleanly, reads cleanly, and returns neighbours from a
different space.

WHY THE TESTS BELOW ARE ALL ABOUT PROVENANCE OF VALUES. A marker built from the
constants would be the defect wearing the fix's clothes — writer stamps its
constant, reader compares its constant, the two agree while both disagree with the
vectors on disk. So the load-bearing property is not "a marker is written" but
"the marker records what was OBSERVED", and that is what these pin.
"""
from unittest.mock import MagicMock

import pytest

from doc_tools.utils.collection_marker import WRITTEN_BY, write_collection_marker


def _client(exists=False):
    c = MagicMock()
    c.collections.exists.return_value = exists
    return c


def _probe(model="served-by-the-endpoint", dim=768):
    return lambda: (model, dim)


def _written(client):
    """The properties dict handed to Weaviate for the marker row."""
    meta = client.collections.get.return_value
    if meta.data.replace.call_args:
        return meta.data.replace.call_args.kwargs["properties"]
    return meta.data.insert.call_args.kwargs["properties"]


# ---------------------------------------------------------------------------
# Every value is observed
# ---------------------------------------------------------------------------

def test_the_marker_records_the_SERVED_model_not_a_constant():
    """THE FIELD THE WHOLE MECHANISM TURNS ON. `LLM_EMBED_MODEL` overrides the
    default at runtime on both sides, so a writer stamping DEFAULT_EMBED_MODEL and
    a reader comparing DEFAULT_EMBED_MODEL agree with each other while both
    disagree with the vectors. Only the served identity records an outcome."""
    client = _client()
    marker = write_collection_marker(client, "OntologyClass", probe=_probe(model="actually-served"))

    assert marker is not None
    assert marker["model"] == "actually-served"
    from doc_tools.utils.embed import DEFAULT_EMBED_MODEL
    assert marker["model"] != DEFAULT_EMBED_MODEL, "stamped the constant, not the observation"


def test_the_marker_records_the_OBSERVED_dimension_not_EXPECTED_EMBED_DIM():
    """Same reasoning, and it buys the reader a second independent witness: a stored
    vector's own length is checkable with no marker at all, so marker-says-N and
    vectors-are-N become two facts whose disagreement is detectable. Stamping the
    constant would make them one belief restated twice."""
    client = _client()
    marker = write_collection_marker(client, "OntologyClass", probe=_probe(dim=1024))

    assert marker["dimension"] == 1024
    from doc_tools.utils.embed import EXPECTED_EMBED_DIM
    assert marker["dimension"] != EXPECTED_EMBED_DIM


def test_an_unexpected_dimension_is_RECORDED_not_refused():
    """A marker's job is to record what IS, including a dimension nobody expected.
    Refusing to write in exactly the case the marker was built to make visible would
    be the check muting itself — which is why this does not reuse
    probe_embedding_dim, whose raise-on-mismatch is right for a pre-flight and
    wrong here."""
    client = _client()
    assert write_collection_marker(client, "C", probe=_probe(dim=384))["dimension"] == 384


def test_version_is_ABSENT_not_a_placeholder():
    """There is no version source in this repo, and a fabricated one is worse than
    none: `version` is a field the marker exists to COMPARE, so a placeholder makes
    the reader report agreement where neither side ever knew anything — a green seal
    for the wrong reason, built in on day one. A declared sentinel was refused for a
    sharper reason still: a sentinel is a string and `==` matches it happily."""
    marker = write_collection_marker(_client(), "C", probe=_probe())
    assert marker["version"] is None


def test_written_by_is_the_repo_not_the_asset():
    """Three sites write collections; the reader's question on a mismatch is WHICH
    SIDE CHANGES, which 'doc-tools' answers and 'doc-tools/ontology_assets' does
    not answer any better."""
    assert WRITTEN_BY == "doc-tools"
    assert write_collection_marker(_client(), "C", probe=_probe())["written_by"] == "doc-tools"


def test_the_marker_names_the_collection_it_describes():
    marker = write_collection_marker(_client(), "Predicate", probe=_probe())
    assert marker["collection"] == "Predicate"


# ---------------------------------------------------------------------------
# One marker per collection, and never fatal
# ---------------------------------------------------------------------------

def test_the_marker_row_is_deterministic_on_the_collection_name():
    """One marker per described collection, replaced rather than accumulated. Two
    markers for one collection makes 'which is current' a question with no answer in
    the data."""
    from weaviate.util import generate_uuid5

    client = _client()
    write_collection_marker(client, "OntologyClass", probe=_probe())
    meta = client.collections.get.return_value
    call = meta.data.replace.call_args or meta.data.insert.call_args
    assert call.kwargs["uuid"] == generate_uuid5("OntologyClass")


def test_a_failed_probe_writes_NOTHING_rather_than_the_constants():
    """THE REFUSAL THAT MATTERS. If the endpoint cannot be observed, falling back to
    DEFAULT_EMBED_MODEL would produce a confident marker asserting something nobody
    measured — and it would compare EQUAL to the reader's constant, reporting
    agreement about vectors neither side has seen."""
    def boom():
        raise RuntimeError("embedding gateway down")

    client = _client()
    assert write_collection_marker(client, "C", probe=boom) is None
    assert not client.collections.get.return_value.data.replace.called
    assert not client.collections.get.return_value.data.insert.called


def test_a_weaviate_failure_is_NOT_fatal():
    """A marker is a record ABOUT the ingest, not part of it. Taking an ingest down
    because its annotation could not be written trades a diagnostic for the thing
    being diagnosed — and the reader already treats absent as its own state, so a
    failed write degrades to exactly the situation that existed before this code."""
    client = _client()
    client.collections.get.return_value.data.replace.side_effect = RuntimeError("weaviate down")
    client.collections.get.return_value.data.insert.side_effect = RuntimeError("weaviate down")

    assert write_collection_marker(client, "C", probe=_probe()) is None  # no raise


def test_a_missing_sdk_is_NOT_fatal():
    """iagent_mesh may be absent or under-installed. Same reasoning."""
    import sys

    saved = sys.modules.get("iagent_mesh.interfaces")
    sys.modules["iagent_mesh.interfaces"] = None  # forces an ImportError on `from ... import`
    try:
        assert write_collection_marker(_client(), "C", probe=_probe()) is None
    finally:
        if saved is None:
            sys.modules.pop("iagent_mesh.interfaces", None)
        else:
            sys.modules["iagent_mesh.interfaces"] = saved


# ---------------------------------------------------------------------------
# The SDK's own admission check
# ---------------------------------------------------------------------------

def test_what_we_write_passes_the_SDKs_writer_conformance_arm():
    """ADMISSION IS PASSING THE SUITE, NOT BEING NAMED IN IT. check_writer_marker
    round-trips our exact field set through the contract's own reader — so the two
    implementations cannot drift by separately agreeing on a shape, and a field we
    got wrong fails here rather than in a cluster."""
    conformance = pytest.importorskip("iagent_mesh.conformance")

    conformance.check_writer_marker(
        collection="OntologyClass",
        model="served-by-the-endpoint",
        dimension=768,
        written_by=WRITTEN_BY,
        collection_created_unix_ms=1_757_000_000_000,
        version=None,
    )


def test_the_marker_this_writer_produces_is_readable_by_the_contracts_reader():
    """The same property asserted over THIS writer's actual output rather than a
    hand-built kwargs set — the arm above proves the contract round-trips, this
    proves we feed it what we think we do."""
    interfaces = pytest.importorskip("iagent_mesh.interfaces")

    marker = write_collection_marker(_client(), "OntologyClass", probe=_probe())
    back = interfaces.read_collection_marker(marker)

    assert back is not None
    assert back.collection == "OntologyClass"
    assert back.model == "served-by-the-endpoint"
    assert back.dimension == 768
    assert back.written_by == "doc-tools"
    assert back.version is None
