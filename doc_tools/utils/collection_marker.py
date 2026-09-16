"""Stamp a `MeshCollectionMeta` marker beside every vector collection doc-tools writes.

THE DEFECT. `DEFAULT_EMBED_MODEL` and `EXPECTED_EMBED_DIM` are hand-copied between
this repo and invincible-agent, enforced by "code review on either constant catches
drift". doc-tools writes the vectors; engine-o embeds the query at read time; and
nothing asserted the two agree. Weaviate locks the DIMENSION on first write and
rejects a different one loudly — which covers the dim and is blind to the model. A
swap between two 768-dim models writes cleanly, reads cleanly, and returns
neighbours computed in a different space: plausible results, not an error.

THE MARKER IS THE CONTRACT, NOT THE CONSTANTS. Once both sides stamp and compare an
OBSERVATION next to the vectors, the two `embed.py` constants stop being the
agreement — a witness that has seen what was actually written replaces two beliefs
that were never checked against it.

EVERY VALUE HERE IS OBSERVED, AND THAT IS THE WHOLE POINT:

  model      what the endpoint SAID IT SERVED, from the embeddings response — not the
             requested name and not the constant. `LLM_EMBED_MODEL` overrides the
             default at runtime on BOTH sides, so a writer stamping its constant and
             a reader comparing its constant agree with each other while both
             disagree with the vectors on disk.
  dimension  the length of a vector actually returned, never EXPECTED_EMBED_DIM. This
             buys the reader a second independent witness: a stored vector's own
             length is checkable with no marker at all, so marker-says-N and
             vectors-are-N are two facts whose disagreement is detectable.
  version    ABSENT unless an immutable identity is available. Measured: the
             embeddings response carries no version, and the provider's tag route
             returns `nomic-embed-text:latest` — a MUTABLE POINTER, so stamping it
             would record a name that can point at different content tomorrow. A
             declared sentinel was refused for a sharper reason: a sentinel is still
             a string and `==` matches it happily, so the contract could say a
             sentinel match is not evidence while the type could not enforce it.
             Absent is a STATE. doc-tools has no digest source, so it reports absence.

THE MARKER DICT IS BUILT BY THE SDK, NOT HERE. `collection_marker()` is one
implementation shared with the reader, so the two cannot drift by separately
agreeing on a shape. This module decides WHEN and WHERE to write; it does not
decide WHAT the marker looks like.

⚠ A LIMIT THIS WRITER DOES NOT MEET, STATED RATHER THAN DISCOVERED. The contract
requires that on re-ingest the objects' creation times MOVE FORWARD, because the
reader proxies a collection's age with its oldest object (no vector store here
exposes a collection-level creation timestamp). doc-tools does NOT satisfy that: it
writes on deterministic UUIDs via replace/upsert, and the store preserves
`creationTimeUnix` across a replace — measured 2026-09-15, 132 of 132 sampled
`Predicate` objects carry an update time later than their creation time, widest gap
81 days. So `marker_is_stale` over a doc-tools collection is UNPROVEN, never
evidence of freshness, and the SDK ships that function saying so.

The fix is NOT to churn object identities so an external proxy keeps working — that
is the data model serving the measurement, and it would cost the idempotent
deterministic-uuid property several things here rely on. The durable repair is for
the marker to be refreshed in the same act that writes VECTORS, not only at
creation, which makes staleness unrepresentable rather than detectable. Recorded in
the contract as preferred; not yet the declared shape.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: This repo, not the asset. Three sites write collections and the reader's question
#: on a mismatch is "which side changes", which "doc-tools" answers and
#: "doc-tools/ontology_assets" does not answer any better.
WRITTEN_BY = "doc-tools"


def _now_unix_ms() -> int:
    return int(time.time() * 1000)


def write_collection_marker(
    client,
    collection: str,
    *,
    created_unix_ms: Optional[int] = None,
    probe: Any = None,
) -> Optional[dict]:
    """Record what produced `collection`'s vectors, in the same act that creates it.

    FOLD, NOT HAND-RUN. A marker written by a separate step is one that can be
    forgotten, and a forgotten marker reads as ABSENT while the collection is
    perfectly real — which is the state this mechanism exists to distinguish from.

    BEST-EFFORT BY DESIGN. Returns the marker on success and None on any failure,
    and never raises. A marker is a record ABOUT the ingest, not part of it: taking
    an ingest down because its annotation could not be written would trade a
    diagnostic for the thing being diagnosed. The reader already treats an absent
    marker as its own state — reported once, never read as agreement — so failing
    to write one degrades to exactly the state that existed before this code.
    """
    try:
        from iagent_mesh.interfaces import MESH_COLLECTION_META, collection_marker
    except Exception as e:  # SDK absent or under-installed
        logger.warning(
            "collection marker NOT written for %r: iagent_mesh unavailable (%s). "
            "The collection is fine; it carries no record of what embedded it.",
            collection, e,
        )
        return None

    try:
        observe = probe
        if observe is None:
            from doc_tools.utils.embed import probe_embedding_identity as observe
        model, dimension = observe()
    except Exception as e:
        logger.warning(
            "collection marker NOT written for %r: could not observe the embedding "
            "identity (%s). Refusing to stamp the CONSTANTS instead — a marker built "
            "from what this code believes is the defect the marker exists to remove.",
            collection, e,
        )
        return None

    marker = collection_marker(
        collection=collection,
        model=model,
        dimension=dimension,
        written_by=WRITTEN_BY,
        collection_created_unix_ms=created_unix_ms or _now_unix_ms(),
        # version stays absent: no digest source in this repo. See the module docstring.
    )

    try:
        if not client.collections.exists(MESH_COLLECTION_META):
            import weaviate.classes as wvc

            client.collections.create(
                name=MESH_COLLECTION_META,
                properties=[
                    wvc.config.Property(name="collection", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="model", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="version", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="dimension", data_type=wvc.config.DataType.INT),
                    wvc.config.Property(name="written_by", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(
                        name="collection_created_unix_ms", data_type=wvc.config.DataType.INT
                    ),
                ],
            )

        from weaviate.util import generate_uuid5

        # DETERMINISTIC ON THE COLLECTION NAME: one marker per described collection,
        # replaced rather than accumulated. A second marker for the same collection
        # would make "which one is current" a question with no answer in the data.
        meta = client.collections.get(MESH_COLLECTION_META)
        uuid = generate_uuid5(collection)
        try:
            meta.data.replace(uuid=uuid, properties=marker)
        except Exception:
            meta.data.insert(uuid=uuid, properties=marker)

        logger.info(
            "collection marker written for %r: model=%r dimension=%d version=%s",
            collection, model, dimension,
            "absent" if marker.get("version") is None else repr(marker["version"]),
        )
        return marker
    except Exception as e:
        logger.warning(
            "collection marker NOT written for %r (%s). The collection is fine; it "
            "carries no record of what embedded it.", collection, e,
        )
        return None
