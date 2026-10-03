"""ADR-0041 ingest-provenance stamp builder — for the ingress-user sensor.

NOT `doc_tools/utils/provenance.py`: that module is the UNRELATED Phase-5
value -> (page, bbox) / crop-URL resolver used by sustainment extraction.
This module builds the ADR-0041 provenance BLOCK (who-obtained-it,
how-far-from-truth) that gets stamped onto a manifest; it has nothing to
do with element bounding boxes.

The block's shape — required fields, validation, wire format — is OWNED by
`iagent_mesh.provenance` (SDK v0.9.5+). This module is a thin adapter over
that SDK, never a second implementation: the SDK is the one writer and one
validator, and a parallel copy of its rules here is exactly the drift the
v0.9.5 pin exists to avoid.
"""
from datetime import datetime, timezone
from typing import Literal, Optional

from iagent_mesh.provenance import AS_OF_UNKNOWN, OBTAINED_VIA, ProvenanceBlock

from doc_tools.utils.ingest_id import canonical_ingest_id

# Mirrors `ObtainedVia = Literal[OBTAINED_VIA]` inside iagent_mesh.provenance —
# the SDK's own "one tuple is both the runtime membership check and the
# static type" pattern, kept visible at this call site rather than re-typed.
_ObtainedVia = Literal[OBTAINED_VIA]  # type: ignore[valid-type]


def build_ingest_provenance(*, obtained_via: "_ObtainedVia", authoritative_source: str,
                             ingest_run: str, standing: str,
                             ingest_id: Optional[str] = None,
                             as_of: Optional[str] = None) -> dict:
    """Build the ADR-0041 provenance block for one ingest and return it as a
    plain dict — this value is JSON-serialized into the manifest and passed
    between Dagster assets, so a `ProvenanceBlock` instance itself would not
    survive that round trip.

    `as_of=None` becomes `AS_OF_UNKNOWN` ("unknown"), never "". The sentinel
    distinguishes "we could not know the truth-date" (a user drop with
    nothing attached genuinely has no knowable truth-date) from "we forgot
    to record it" — collapsing the two would make an unknown vintage read as
    a data-entry omission instead of a fact about the pipeline.

    Constructs a real `ProvenanceBlock` so the SDK's own validators run, and
    lets any `ValueError` it raises propagate uncaught: a claim that cannot
    say where it came from must not be written, and catching that here would
    silently let one through.

    `ingest_id`, when supplied, is forced to the canonical ``sha256:<64 hex>``
    spelling (architect ruling 2026-10-02). The SDK itself does NOT enforce
    this — `provenance.py`'s `ingest_id` is a bare `Optional[str]` with no
    validator — so a defective spelling would ride the SDK's validation all
    the way onto the manifest and only fail far away, at Lane 1's promotion
    guard. It is checked HERE, at the one place the block is built, because
    this block's `ingest_id` IS the join key the cleanup sweep scopes an
    `EdgeIdentityFilter` to. `None` stays `None`: the SDK declares it
    optional, and the paths that have no ingest at all (non-user-drop
    sources) legitimately have no id to spell. Refusing a None belongs at the
    call site that KNOWS one was required — see `document_parser`'s sidecar
    guard — not here.
    """
    if ingest_id is not None:
        ingest_id = canonical_ingest_id(
            ingest_id, where=f"build_ingest_provenance(ingest_run={ingest_run!r})"
        )

    block = ProvenanceBlock(
        authoritative_source=authoritative_source,
        obtained_via=obtained_via,
        as_of=as_of if as_of is not None else AS_OF_UNKNOWN,
        # Not a parameter: the spec for this builder takes no `ingested_at`
        # input, yet `ProvenanceBlock.ingested_at` is required (non-empty)
        # by the SDK's own field validator. The only fact this function can
        # supply on its own is "now" — the moment this stamp is built — so
        # it is generated here rather than left for a caller who has no way
        # to pass it in.
        ingested_at=datetime.now(timezone.utc).isoformat(),
        ingest_run=ingest_run,
        standing=standing,
        ingest_id=ingest_id,
    )
    return block.as_dict()
