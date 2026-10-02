"""ADR-0041 provenance as an invariant of the WRITE PATH, not a per-domain opt-in.

ARCHITECT RULING 2026-10-02: *"provenance persists for every domain; it's an
invariant of the write path, not an opt-in."* This module is what makes that
sentence mechanical. It supersedes
``semantic_assets.DOMAINS_THAT_PERSIST_PROVENANCE`` — a frozenset naming the
one domain whose plugin happened to persist the block, with a halt for every
other domain.

WHY A HELPER AND NOT A FIFTH PLUGIN METHOD. The old design put the stamp
inside ``to_graph_queries()``, which is per-plugin, so "every domain" would
have meant five independent implementations of the same eight properties and
five chances to spell one of them differently. There is exactly ONE Cypher
write that runs for every domain regardless of plugin: the parent-document
``MERGE`` in ``build_knowledge_graph`` (``semantic_assets.py``, "Create Parent
Node"). The stamp belongs there, and this module holds the property names so
the generic site and ``SustainmentPlugin``'s own notice-node stamp cannot
drift apart unnoticed — pinned by
``tests/test_provenance_invariant.py::test_sustainment_stamp_uses_the_same_property_names``.

THE RESIDUAL, NAMED RATHER THAN HIDDEN. This makes the NEO4J stamp universal.
The RDF side is still plugin-keyed: only ``SustainmentPlugin`` emits the
PROV-term triples (``PROV_DERIVED_FROM``/``PROV_GENERATED_AT`` into
``<http://internal/{DOMAIN}_INSTANCES>``), because triples are emitted by
``to_graph_queries()`` and there is no generic RDF write to hang them on the
way there is a generic Cypher one. So after this change: a provenance-bearing
document in ANY domain is distinguishable from vetted content in Neo4j, and
only a sustainment one is distinguishable in Jena. That gap is a real one and
is tracked as such — see the PR body — not papered over by claiming the
invariant covers both stores.
"""

from typing import Optional

#: The eight ADR-0041 block fields that reach the graph, in the order
#: ``SustainmentPlugin`` already writes them. Property name on the node is
#: ``provenance_<field>``; this tuple is the single spelling of the set.
PROVENANCE_FIELDS = (
    "obtained_via",
    "authoritative_source",
    "as_of",
    "ingested_at",
    "ingest_run",
    "standing",
    "derived_from",
    "ingest_id",
)

#: Prefix for the Cypher PARAMETER names, so a stamp can be appended to a
#: write that already binds ``$id``/``$title`` without colliding with them.
PARAM_PREFIX = "prov_"


def provenance_set_fragment(alias: str = "n", param_prefix: str = PARAM_PREFIX) -> str:
    """The ``SET`` assignments for the stamp, WITHOUT the leading ``SET``.

    Returned as a fragment rather than a whole statement because the one site
    that runs for every domain already has a ``SET n.title = $title`` to
    append to. ``alias`` and ``param_prefix`` are both interpolated into
    Cypher, which is why neither is ever caller data: the alias is a literal
    in the calling f-string and the prefix is this module's constant. Every
    VALUE is parameterised (AGENTS.md §Safety Guardrails — bounded f-strings
    only, parameterise the rest).
    """
    return ", ".join(
        f"{alias}.provenance_{field} = ${param_prefix}{field}"
        for field in PROVENANCE_FIELDS
    )


def provenance_params(
    provenance: Optional[dict], param_prefix: str = PARAM_PREFIX
) -> dict:
    """Bind values for :func:`provenance_set_fragment`, defaulting to ``""``.

    ``""`` and NOT ``None``, for the reason already documented at
    ``sustainment.py``'s stamp: a Cypher null DROPS the property, which
    collapses "this optional field was genuinely absent from the block" into
    "this document was never stamped at all" — and telling those two apart is
    the entire point of the stamp.
    """
    block = provenance or {}
    return {
        f"{param_prefix}{field}": (block.get(field) or "")
        for field in PROVENANCE_FIELDS
    }
