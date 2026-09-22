import re
import os
import urllib.parse
import httpx
import rdflib
import weaviate.classes as wvc
from weaviate.util import generate_uuid5
from dagster import asset, AssetExecutionContext, MaterializeResult
from dagster_aws.s3 import S3Resource
from doc_tools.utils.dagster_resources import JenaResource, Neo4jResource
from dag_tools.components.s3_sensor.file_component import S3FileConfig
from doc_tools.partitions import ontology_partitions
from doc_tools.utils.weaviate_client import get_weaviate_client


# Meta-ontology IRI prefixes — vocabularies that describe ONTOLOGIES,
# not DOMAIN CONCEPTS. Their terms should never appear in the
# OntologyClass corpus (Engine O's /resolve candidate pool). They got
# in because the SPARQL extract patterns match `owl:Class` and
# `rdfs:Class` and meta-ontologies declare their own meta-concepts as
# `owl:Class` (e.g. prov:Bundle, prov:Usage).
#
# The 2026-06-27 PROV-contamination finding banked at
# [[ontology-class-pool-prov-contamination]] documented the
# consequence: 31 PROV-O classes sat in the Weaviate OntologyClass
# collection tagged domain=DATA_ENGINEERING with rich definitions,
# competing with weakly-defined domain classes. Every routed-path
# query in the 2026-06-27 session reproducibly returned prov#*
# (Bundle, Usage, PrimarySource) and fell back to Engine A. The
# specialist routing path was effectively never exercised.
#
# Path A fix per [[failure-mode-pluralism-in-fixes]]: filter at
# ingest time so meta-ontology terms never enter the corpus. Same
# shape as [[mesh-thing-retired]]. Paired cleanup deletes the
# existing 31 polluted entries (separate operation; this filter
# prevents the next ingest from re-polluting).
_META_ONTOLOGY_IRI_PREFIXES: tuple[str, ...] = (
    "http://www.w3.org/ns/prov#",          # PROV-O
    "http://www.w3.org/2000/01/rdf-schema#",  # RDFS
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",  # RDF
    "http://www.w3.org/2002/07/owl#",      # OWL
    "http://www.w3.org/2004/02/skos/core#",  # SKOS
    "http://purl.org/dc/terms/",           # Dublin Core terms
    "http://purl.org/dc/elements/1.1/",    # Dublin Core elements
    "http://xmlns.com/foaf/0.1/",          # FOAF
    "http://www.w3.org/ns/dcat#",          # DCAT (data catalog vocabulary)
    "http://www.w3.org/2006/vcard/ns#",    # vCard
)


# ---------------------------------------------------------------------------
# Derived class labels — S3000L is primed, loads, and is invisible
# ---------------------------------------------------------------------------
# `/classes` (and everything behind it: the SPO interview's authorized-subject
# menu, /operable_subjects, the router's OntologyClass candidate pool) selects
# `?cls a owl:Class ; rdfs:label ?label` with the LABEL REQUIRED. S3000L declares
# no labels at all — measured from source, not taken from a packet: 6206 triples,
# 773 URIRef owl:Class subjects all in http://www.lksoft.com/s3kl#, and ZERO
# rdfs:label / skos:prefLabel / dcterms:title / rdfs:comment among them. So the
# domain's largest standard loads correctly and reaches no consumer. Nothing
# errors; a caller asking about a failure mode gets a clean "no such subject",
# which is indistinguishable from the term genuinely not existing.
#
# THE FIX IS NOT LOOSENING THE QUERY. A menu needs names; admitting an unlabelled
# class puts a bare IRI in front of a user and degrades every consumer in order to
# raise one consumer's count. The label is DERIVED HERE, at the seed step, and
# written as a triple carrying its own provenance — so a reader can always tell a
# name the spec authored from one this function made up.
#
# THREE STATES, because two would relabel a real limit as a success. Same
# discipline as PRESENT/ABSENT/UNREAD on `_tool_urn` in assets/aitool_linker.py:
#
#   authored        the ontology gave the name. Never overwritten. Without this
#                   state a seal cannot tell "derivation worked" from "derivation
#                   overwrote everything" — it is the positive control.
#   derived         no authored name; the URI fragment yields a real one.
#                   `LSAFailureMode` -> "LSA Failure Mode".
#   derived-opaque  no authored name, and the fragment CANNOT yield one, because a
#                   segment is a bare code whose meaning lives in another triple.
#                   `BreakdownElementEssentiality_1` humanizes to "Breakdown
#                   Element Essentiality 1", which READS informative and tells the
#                   reader nothing. Marking it separately is the honest move: the
#                   class becomes visible (better than invisible) while saying out
#                   loud that its name is a placeholder, not a definition.
#
# MEASURED SHAPES, because the obvious heuristic is wrong for the majority case.
# Of the 773 fragments: 377 contain an underscore (the DOMINANT shape, e.g.
# `AggregatedElementType_Family`); only 396 are plain camelCase; 36 carry a leading
# acronym (`ASDSystemHardwareBreakdown`, `LSACandidate...`) which a naive camel
# splitter mangles; 3 are bare boolean operators (`AND`, `OR`, `NOT`). No fragment
# is empty and none is duplicated, so derivation is total and collision-free —
# that is what makes this viable rather than a guess.
#
# NOTE ON xsdCode: 384 of the 773 carry `s3kl:xsdCode`, but their fragments are
# overwhelmingly informative (`DocumentType_Drawing` xsdCode='DRW'). "Has a code"
# is therefore NOT the opaqueness test — only 7 fragments actually hide their
# meaning in the code (3 numeric tails `_1/_2/_3`, 4 single-letter tails `_A`..`_D`).
# Testing on the code would have marked 384 good names as placeholders.

#: Provenance predicate for the above. CROSS-REPO CONTRACT — the seal in
#: invincible-agent queries this IRI, so a mismatch does not fail: it reads zero
#: and reports a clean graph.
#:
#: THE NAMESPACE IS `http://invincible-agent/mesh#`, NOT `http://internal/mesh#`,
#: and the difference is not cosmetic. The served graph uses
#: `http://invincible-agent/{domain}#` everywhere the HUD renders it
#: (`cost#ProductionLot`, `mesh#ContributionSequence`); that is canonical. An
#: earlier version of this constant used `http://internal/mesh#` by analogy with
#: the NAMED-GRAPH uris this asset writes (`http://internal/{domain}`) — but a
#: graph NAME and a vocabulary NAMESPACE are different axes, and reasoning from
#: one to the other is how this drift keeps happening.
#:
#: WHY IT KEEPS COSTING: an unknown prefix passes through verbatim. The triple
#: parses, the row registers, the write reports accepted, and it never matches
#: anything. Nothing goes red at any layer. This is the fourth instance of the
#: same class in this codebase; `setup/ontologies/safety_extension.ttl` in
#: invincible-agent carries a header warning about it, and
#: `product_structure_extension.ttl` in that same directory still declares the
#: wrong one.
LABEL_SOURCE_PREDICATE = rdflib.URIRef("http://invincible-agent/mesh#labelSource")

#: The namespace this contract is NOT under. Named so the pin below can assert a
#: DISTINCTION rather than a tautology — see the test for why that matters.
_REJECTED_LABEL_SOURCE_NAMESPACE = "http://internal/mesh#"

#: The universal-referent flag, carried from the TTL onto the Neo4j node.
#:
#: SAME CROSS-REPO NAMESPACE HAZARD AS `LABEL_SOURCE_PREDICATE` ABOVE, and for the
#: same reason: `http://invincible-agent/mesh#` is the vocabulary namespace the
#: served graph uses, NOT `http://internal/mesh#` (which is the named-GRAPH uri
#: shape this asset writes). An unknown prefix passes through verbatim — the
#: triple parses, the node merges, nothing goes red, and the flag never matches.
#:
#: WHY IT IS HERE AT ALL. `mesh:explain` is polymorphic: its spoken subject is
#: every class in the graph, so it has no honest referent among the domain
#: classes. `owl:Thing` is the obvious answer and cannot work — that prefix is in
#: `_META_ONTOLOGY_IRI_PREFIXES` ten lines up, so no W3C class is in the routable
#: pool (0 OntologyClass nodes, measured 2026-09-19). invincible-agent's
#: `mesh_system.ttl` therefore declares `mesh:Thing` with `mesh:universalReferent
#: true`, and the parameterisation pool admits a verb whose referent CARRIES THE
#: FLAG rather than one whose referent IRI it recognises. The pool reads the flag;
#: a second universal referent works without touching the pool.
#:
#: THE PAIR BELOW IS THE CONTRACT — the predicate read from the TTL and the
#: property written on the node. Lane 1's pool leg reads the node property, so a
#: rename on either side must move both, and neither side can infer the other:
#: the node convention is snake_case (`last_synced_at`, `synced_by`) and the
#: predicate's local name is camelCase, so they do NOT spell the same.
UNIVERSAL_REFERENT_PREDICATE = rdflib.URIRef(
    "http://invincible-agent/mesh#universalReferent"
)
UNIVERSAL_REFERENT_PROPERTY = "universal_referent"

#: The MERGE interpolates the property name into Cypher. Assert it is
#: identifier-shaped at import rather than trusting the literal above to stay
#: one — this is what makes the interpolation safe to read as safe.
assert UNIVERSAL_REFERENT_PROPERTY.isidentifier(), UNIVERSAL_REFERENT_PROPERTY


def _universal_referent_value(term):
    """Read the flag off one SPARQL binding. ``True``, or ``None`` for absent.

    NEVER ``False``. Absence is the encoding — see the comment at the call site
    — so an explicit ``mesh:universalReferent false`` in a TTL and no triple at
    all must produce the same thing, or the two spellings of "not universal"
    would read differently at the node.

    Accepts the typed literal (``"true"^^xsd:boolean`` — what ``mesh_system.ttl``
    writes, whose ``.toPython()`` is a real ``bool``) and the plain-literal
    spelling (``"true"``, which ``.toPython()`` leaves a ``str``). A TTL author
    who omits the datatype should not silently lose the flag.
    """
    if term is None:
        return None
    try:
        value = term.toPython()
    except Exception:
        value = str(term)
    if isinstance(value, bool):
        return True if value else None
    return True if str(value).strip().lower() == "true" else None


LABEL_SOURCE_AUTHORED = "authored"
LABEL_SOURCE_DERIVED = "derived"
LABEL_SOURCE_DERIVED_OPAQUE = "derived-opaque"

#: Annotations that count as an AUTHORED name. First hit wins and derivation is
#: skipped entirely.
_AUTHORED_LABEL_PREDICATES = (
    rdflib.RDFS.label,
    rdflib.URIRef("http://www.w3.org/2004/02/skos/core#prefLabel"),
    rdflib.URIRef("http://purl.org/dc/terms/title"),
)

#: Splits camelCase without mangling the two shapes a naive splitter destroys.
#: ORDER IS LOAD-BEARING — each special alternative must be tried before the
#: generic camel one, or it never fires and the bug is silent:
#:   1. alphanumeric standard codes   `S1000D` -> S1000D   (not "S1000 D")
#:   2. a leading acronym             `LSAFailureMode` -> LSA | Failure | Mode
#:   3. an all-caps run               `AND` -> AND         (not "A N D")
#:   4. ordinary camel / lower words
#: 2 and 3 are DISTINCT and both are needed: 2 uses a lookahead to stop before the
#: next word's capital, 3 must NOT require a following word. An earlier version
#: had only 2 and the generic alternative, so every bare operator came out spelled
#: letter by letter. Measured populations: 36 fragments carry a leading acronym,
#: 3 are bare boolean operators.
_CAMEL = re.compile(
    r"[A-Z]+\d+[A-Z]*"
    r"|[A-Z]+(?=[A-Z][a-z])"
    r"|[A-Z]+(?![a-z])"
    r"|[A-Z][a-z0-9]*"
    r"|[a-z0-9]+"
)


def _segment_is_bare_code(segment: str) -> bool:
    """True when an underscore-segment carries no name, only an identifier.

    Two shapes, both measured in S3000L: a purely numeric tail (`..._1`) and a
    single-letter tail (`..._A`). In both, the meaning sits in a sibling triple
    (`s3kl:xsdCode`) and the fragment segment is just an index.
    """
    return segment.isdigit() or (len(segment) == 1 and segment.isalpha())


def humanize_uri_fragment(fragment: str):
    """Derive a human label from a URI fragment. Returns ``(label, is_opaque)``.

    ``is_opaque`` is True when a segment is a bare code — the caller must NOT
    present the result as if it were a name the ontology authored.
    """
    segments = [s for s in fragment.split("_") if s]
    if not segments:
        return "", True

    opaque = any(_segment_is_bare_code(s) for s in segments)

    words = []
    for seg in segments:
        for tok in _CAMEL.findall(seg):
            # An all-caps token is an acronym (LSA, ASD, AND) — leave it alone.
            words.append(tok if tok.isupper() else tok[:1].upper() + tok[1:])
    return " ".join(words), opaque


def derive_missing_class_labels(g, context=None):
    """Give every unlabelled owl:Class a label, and stamp where the name came from.

    Mutates ``g`` in place BEFORE the Jena push and before the Weaviate extraction,
    so both consumers see the same labels from one insertion point.

    Idempotent: a second run finds the labels the first wrote, counts them as
    authored-by-presence, and adds nothing. Authored labels are never overwritten
    — that is the positive control a seal needs to tell derivation from
    obliteration.
    """
    counts = {
        LABEL_SOURCE_AUTHORED: 0,
        LABEL_SOURCE_DERIVED: 0,
        LABEL_SOURCE_DERIVED_OPAQUE: 0,
        "skipped_blank_node": 0,
        "skipped_no_fragment": 0,
    }

    subjects = set(g.subjects(rdflib.RDF.type, rdflib.OWL.Class))
    subjects |= set(g.subjects(rdflib.RDF.type, rdflib.RDFS.Class))

    for cls in subjects:
        # Blank-node owl:Class entries are anonymous restrictions, not vocabulary.
        # They have no fragment to derive from, so naming them would invent
        # thousands of hex-id "classes".
        #
        # THIS BLOCK USED TO GIVE A SECOND REASON: "they are already excluded
        # downstream". That sentence was TRUE OF ONE DOWNSTREAM AND FALSE OF THE
        # OTHER, and stayed that way for three months. The Neo4j sync filtered
        # blank nodes at two layers; the Weaviate dual-write filtered them
        # nowhere. So the file asserted as settled the exact thing that was
        # broken, in the one place a reader checking blank nodes would land
        # first — the cheapest possible way to stop the check that would have
        # found it. Flagged by Lane 74, 2026-09-19.
        #
        # Both legs now carry both layers, so the claim is true. It is written
        # as a dated statement about two NAMED call sites rather than as a fact
        # about "downstream" precisely because the vague form is what failed:
        #
        #   ingest_ontology_to_jena        step 4, the Weaviate extraction
        #   sync_jena_ontologies_to_neo4j  its extract_query
        #
        # tests/test_ontology_assets_blank_node_filter.py asserts both, PER LEG.
        if not isinstance(cls, rdflib.URIRef):
            counts["skipped_blank_node"] += 1
            continue

        if any((cls, p, None) in g for p in _AUTHORED_LABEL_PREDICATES):
            counts[LABEL_SOURCE_AUTHORED] += 1
            continue

        uri = str(cls)
        fragment = uri.split("#")[-1].split("/")[-1]
        label, opaque = humanize_uri_fragment(fragment)
        if not label:
            # Nothing to work with. Refuse rather than write an empty name: an
            # empty rdfs:label SATISFIES the consumer's query and renders as a
            # blank menu row, which is worse than the class staying absent.
            counts["skipped_no_fragment"] += 1
            continue

        source = LABEL_SOURCE_DERIVED_OPAQUE if opaque else LABEL_SOURCE_DERIVED
        g.add((cls, rdflib.RDFS.label, rdflib.Literal(label)))
        g.add((cls, LABEL_SOURCE_PREDICATE, rdflib.Literal(source)))
        counts[source] += 1

    if context is not None:
        context.log.info(
            f"Class labels: {counts[LABEL_SOURCE_AUTHORED]} authored (kept), "
            f"{counts[LABEL_SOURCE_DERIVED]} derived, "
            f"{counts[LABEL_SOURCE_DERIVED_OPAQUE]} derived-opaque (fragment is a "
            f"bare code — the name is a placeholder and the meaning lives in a "
            f"sibling triple), {counts['skipped_blank_node']} blank nodes skipped."
        )
    return counts


def _is_meta_ontology_iri(uri: str) -> bool:
    """Return True iff `uri` belongs to a meta-ontology that should
    NOT enter the OntologyClass corpus. Used by both the Weaviate
    and Neo4j sync paths to filter the SPARQL extraction's output
    before write.

    Defensive at the read-side too (Engine O could add a parallel
    filter), but the WRITE-side is where the fix belongs per
    [[writer-canonical-form-class]]: don't put pollution into the
    store you'd otherwise have to filter at every reader.
    """
    return any(uri.startswith(p) for p in _META_ONTOLOGY_IRI_PREFIXES)


# --------------------------------------------------------------------------
# RESPONSE SHAPES ARE NOT GROUNDABLE SUBJECTS
# --------------------------------------------------------------------------
#: The declared roots of "this class is an ANSWER, not a thing to ask about".
#:
#: THE DEFECT (measured 2026-09-01, a one-cell PROGRAM_FINANCE user, 12/20).
#: ADR-0019 Contract D requires BOTH ends of a verb edge to pre-exist as
#: owl:Class, so every verb's OUTPUT shape becomes an OntologyClass — and every
#: OntologyClass is a candidate in Engine O's /resolve grounding pool. A verb's
#: output therefore competes with its own input subject for the very question
#: that invokes it:
#:
#:     "what is our burn rate"  ->  fin:BurnRateSeries   (no predicate edge: DEAD END)
#:                              ->  fin:PerformanceMeasurementBaseline -> finBurnRate
#:
#: Right concept, wrong END of Contract D. Routing then finds no predicate edge
#: and dies — while /resolve reports success, the class genuinely exists, and the
#: engine is healthy with all eight verb edges live. Nothing anywhere errors.
#:
#: WHY PROSE COULD NOT FIX IT. Two hypotheses died first. Pool width: narrowing
#: seven domains to one changed nothing (12/20 both). Definition language: all six
#: fin: output definitions had been written as descriptions of the QUESTION and
#: were rewritten to describe answer STRUCTURE — worth only 11 -> 12. The residue
#: is the class NAME. fin:BurnRateSeries is labelled "Burn Rate Series" and will
#: always match "what is our burn rate". A name cannot be written around, so the
#: fix has to be structural.
#:
#: SAME SHAPE AS THE PROV-O FILTER ABOVE, one category further: a kind of class
#: whose definitions vector-outcompete the domain classes a user actually means.
#: This one is predicate-based rather than prefix-based, because a response shape
#: is identified by what it IS (rdfs:subClassOf mesh:Response) and not by which
#: namespace it happens to live in — fin:, mesh: and any future engine's
#: namespace all declare them.
_RESPONSE_SHAPE_ROOTS: tuple[str, ...] = (
    "http://invincible-agent/mesh#Response",   # any engine output payload
    "http://invincible-agent/mesh#Archetype",  # presentation archetypes
)


def response_shape_uris(g) -> set[str]:
    """Every class declared as an engine RESPONSE or a presentation ARCHETYPE.

    Transitive (``rdfs:subClassOf+``) so a subclass of a response shape is one
    too. Evaluated per-TTL against the graph being ingested, which is sound
    because every response shape declares its root DIRECTLY — a chain that
    crossed file boundaries would not be seen here, and the cross-check seal in
    invincible-agent (tests/routing/test_response_shapes_are_not_groundable.py)
    is what would catch that, by comparing this declared set against the set
    derived from the engines' registration tables.

    Returns URIs as plain strings, matching ``_is_meta_ontology_iri``'s contract.
    """
    query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT DISTINCT ?uri
    WHERE {
        ?uri rdfs:subClassOf+ ?root .
        FILTER(?root IN (%s))
    }
    """ % ", ".join(f"<{r}>" for r in _RESPONSE_SHAPE_ROOTS)
    try:
        return {str(row.uri) for row in g.query(query)}
    except Exception:
        # A malformed or empty graph must not take the whole sync down. An empty
        # set means "filter nothing", which is the pre-2026-09-01 behaviour —
        # degraded, never destructive.
        return set()


# --------------------------------------------------------------------------
# RULING 2 — EVERY CLASS A MANIFEST TTL DECLARES IS A ROW, OR IS EXCLUDED FOR A
# NAMED REASON
# --------------------------------------------------------------------------
# The class system exists to refuse a partial ingest. Ruling 1 (above, in
# `ingest_ontology_to_jena`) makes a THROWN write fail the asset. That still
# leaves the quieter shape: the leg ran, reported success, and a class that
# should be groundable is simply not in the collection. Nothing threw. This is
# the seal for that, and it runs after the write, in the same act.
#
# WHAT IT IS DERIVED FROM, AND WHY NOT THE MANIFEST.
# The ruling says "derived from the manifest". `CANONICAL_TTL_MANIFEST` lives in
# `invincible-agent/setup/prime_databases.py` and doc-tools has no copy — and
# must not grow one. Copying it would mint a SECOND MASTER: the seal would then
# be complete against its own copy and blind to the entry that exists in only
# one of them, which is the exact drift the seal is supposed to catch. Worse,
# the copy is invisible to both repos, so neither side reds.
#
# SO THE BASIS IS THE RECORD THE INGEST RUN MAKES OF WHAT IT WAS HANDED — the
# second option the ruling offers, and the stronger one here. This asset is
# PARTITIONED PER FILE: one partition IS one manifest entry, and the classes
# this function receives were extracted from the very TTL that partition was
# handed, moments ago, in this process. The union over all partitions is the
# manifest, and doc-tools never holds the list. It cannot go stale, because it
# is recomputed from the actual input on every run. A manifest copy would have
# told us what SHOULD have been ingested; this tells us what WAS.
#
# THE ONE THING IT CANNOT SEE, stated rather than hidden: a manifest entry whose
# partition never RAN at all produces no seal, because there is no run to fail.
# That gap is Ruling 3 — the per-domain readiness sentinel — and the two are
# complementary by construction, not redundant.
#
# WHY IT IS A PARTITION AND NOT A SKIP LIST. Every declared class lands in
# exactly one bucket: written, or excluded WITH THE REASON ATTACHED. Written as
# "skip the ones we filter" instead, the seal loses the ability to tell a
# deliberate exclusion from a dropped row — which is the bug it exists to catch.
# The reconciliation (written + excluded == declared) is ASSERTED, not assumed
# from the shape of the if/elif/else: an `else` branch that silently grows a
# third outcome is precisely how a partition stops being one.

#: The two deliberate exclusions, as values rather than comments, so an excluded
#: class can always say WHY it is excluded and a future third reason has to be
#: named here before it can be used.
EXCLUSION_META_ONTOLOGY = "meta_ontology_iri"
EXCLUSION_RESPONSE_SHAPE = "response_shape_weaviate_only"


def partition_ontology_classes(
    extracted_classes: list[dict],
    response_shapes: set[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Split declared classes into (written, excluded-with-a-reason).

    ONE partitioner, used by BOTH the write and the seal. That is the point: a
    seal carrying its own copy of the filter logic can agree with itself while
    disagreeing with the write, and would pass over exactly the rows the write
    dropped. Sharing the function makes this seal a statement about the STORE.
    Whether the filters are RIGHT is a different question, answered by
    tests/test_ontology_assets_response_shape_filter.py.

    Returns ``(to_write, exclusions)``; each exclusion is
    ``{"uri": str, "reason": str, "cls": dict}``.
    """
    to_write: list[dict] = []
    exclusions: list[dict] = []
    shapes = response_shapes or set()
    for cls in extracted_classes:
        uri = str(cls.get("uri", ""))
        if _is_meta_ontology_iri(uri):
            exclusions.append({"uri": uri, "reason": EXCLUSION_META_ONTOLOGY, "cls": cls})
        elif uri in shapes:
            # WEAVIATE ONLY. THIS EXCLUSION MUST NEVER BE MIRRORED INTO THE
            # NEO4J SYNC, which is the one difference between it and the
            # meta-ontology exclusion above — and the difference is load-bearing
            # enough that copying that symmetry would take down all routing.
            #
            # Neo4j MUST keep every response shape as an :OntologyClass node:
            #   * ADR-0019 Contract D refuses a registration whose OUTPUT class
            #     does not pre-exist as one, so filtering Neo4j un-registers
            #     every verb at its next registration; and
            #   * find_compatible_verbs matches `(scope)-[r]->(o:OntologyClass)`
            #     and returns `o.uri AS output_uri`. With the output node gone
            #     the pattern does not match, so EVERY verb silently vanishes
            #     from the compat walk — including the ones whose subjects are
            #     perfectly groundable.
            #
            # Response shapes are also still needed for provenance, rendersAs
            # and archetype bindings. Nothing about them stops being DECLARED.
            # The only thing that changes is what the RESOLVER may ground to.
            exclusions.append({"uri": uri, "reason": EXCLUSION_RESPONSE_SHAPE, "cls": cls})
        else:
            to_write.append(cls)

    # The reconciliation, asserted. See the block comment above for why this is
    # not redundant with the if/elif/else.
    if len(to_write) + len(exclusions) != len(extracted_classes):
        raise Exception(
            f"Class partition does not reconcile: {len(extracted_classes)} "
            f"declared, {len(to_write)} to write, {len(exclusions)} excluded. "
            f"Every declared class must land in exactly one bucket — a class "
            f"in neither is a dropped row wearing the clothes of a filter."
        )
    return to_write, exclusions


def seal_declared_classes_are_rows(
    collection,
    to_write: list[dict],
    domain: str,
    context: AssetExecutionContext,
) -> int:
    """READ BACK: every class this run said it would write IS a row. Raises if not.

    Reads by the SAME deterministic UUID the write used, in chunks, so the seal
    asks the store the same question the write answered rather than a
    count-shaped approximation of it. A count would pass on the run that wrote
    the right NUMBER of the wrong rows.
    """
    expected = {str(c["uri"]) for c in to_write}
    if not expected:
        return 0

    from weaviate.classes.query import Filter

    found: set[str] = set()
    chunk = 100
    ordered = sorted(expected)
    for i in range(0, len(ordered), chunk):
        batch_uris = ordered[i:i + chunk]
        res = collection.query.fetch_objects(
            filters=Filter.by_id().contains_any(
                [generate_uuid5(u) for u in batch_uris]
            ),
            limit=len(batch_uris),
            return_properties=["uri"],
        )
        for obj in res.objects:
            uri = (obj.properties or {}).get("uri")
            if uri:
                found.add(str(uri))

    missing = expected - found
    if missing:
        raise Exception(
            f"Weaviate row seal FAILED for domain {domain!r}: "
            f"{len(missing)} of {len(expected)} class(es) this run wrote are "
            f"NOT rows in the OntologyClass collection. Missing: "
            f"{sorted(missing)[:5]}{' ...' if len(missing) > 5 else ''}. "
            f"The batch reported no error, so this is the quiet shape of a "
            f"partial ingest: Jena is authoritative for what EXISTS and the "
            f"vector store for what can be GROUNDED, and these classes now "
            f"exist and cannot be grounded. Re-drive this partition."
        )
    return len(found)


def seal_a_written_row_is_RETRIEVABLE(
    collection,
    to_write: list[dict],
    domain: str,
    context: AssetExecutionContext,
) -> str:
    """AN OBJECT IS ITS OWN NEAREST NEIGHBOUR, OR THE INDEX IS NOT THERE.

    THE SEAL ABOVE WOULD BE GREEN ON A DEAD POOL, and this is not hypothetical — it is
    the measured state of the sandbox today. Lane 74 filed it on 2026-09-19
    (`ia-74/sessions/2026-09-19-packet-from-74-the-seam-returns-one-and-the-vector-half-
    is-dead.md`), and it names THIS function's collection as one of three affected:

        OntologyClass   vectorizer None   vectorConfig ['default']   nearObject(self) ERROR
        Predicate       vectorizer None   vectorConfig ['default']   nearObject(self) ERROR
        DocumentChunk   text2vec-ollama   vectorConfig None          nearObject(self) OK   <- control

    26,239 objects, shard READY, queue empty, and 24,924 of them carrying a readable
    768-dim vector — every row present, every row countable, and the vector half of
    every hybrid search returning NOTHING. The whole fleet has been routing on BM25
    alone, with no stemming, and no log line anywhere: the "falling back to BM25"
    message only prints when `embed_query` RAISES, and it never raises.

    WHY NO ROW-COUNTING SEAL CAN SEE THIS, which is the reason this assertion exists
    beside the other rather than instead of it. `_additional{vector}` and the client's
    `include_vector` both read the LEGACY unnamed slot, and the row does carry a vector
    there. The collection is indexed on the NAMED space `default`, which is empty. Every
    instrument that asks "does this row have a vector" says yes. Only an instrument that
    asks the server to USE it says no — and the server says it in words:

        nearObject{id:"<uuid>"} -> "vector not found for target: default"

    So the question this asks is deliberately not "is the row there" and not "does the
    row have a vector". It is "can the store RETRIEVE this row by its own vector", which
    is the only form of the question that fails on the substrate the seal is for.

    ONE ROW, not all of them: retrievability is a property of the collection's index, not
    of the row, so the first row is as diagnostic as the last and 26,239 probes would
    cost the same answer. Same shape as 74's recommendation for the census line.

    Returns the probed URI. Raises when the row cannot retrieve itself.
    """
    if not to_write:
        return ""

    # Probe a row THIS RUN wrote, chosen deterministically so a re-run asks the same
    # question. It must carry a vector: the embed fallback writes vector-less rows on
    # purpose, and asking one of those to find itself by vector would fail for a reason
    # that has nothing to do with the index.
    probe_uri = sorted(str(c["uri"]) for c in to_write)[0]
    probe_uuid = generate_uuid5(probe_uri)

    try:
        stored = collection.query.fetch_object_by_id(probe_uuid, include_vector=True)
    except Exception as e:
        raise Exception(
            f"Retrievability seal could not read back {probe_uri!r} for domain "
            f"{domain!r}: {e}"
        ) from e

    if stored is None:
        raise Exception(
            f"Retrievability seal: {probe_uri!r} is not in the collection at all. "
            f"The row seal should have caught this first — if it did not, the two "
            f"are asking different questions and one of them is wrong."
        )

    vectors = getattr(stored, "vector", None) or {}
    has_vector = bool(vectors) if isinstance(vectors, dict) else bool(vectors)
    if not has_vector:
        # NOT a failure of the index. The embed gateway was down for this row and the
        # write said so; BM25 still answers it and a backfill can populate it later.
        # Reporting it as a retrievability failure would blame the index for the
        # gateway, which is how a seal starts pointing at the wrong thing.
        context.log.warning(
            f"Retrievability seal SKIPPED for domain {domain!r}: the probe row "
            f"{probe_uri!r} carries no vector (the embed fallback fired). The "
            f"collection index is UNTESTED this run — this is a measurement that "
            f"could not be made, not a pass."
        )
        return ""

    try:
        res = collection.query.near_object(
            probe_uuid, limit=1, return_properties=["uri"]
        )
    except Exception as e:
        raise Exception(
            f"RETRIEVABILITY SEAL FAILED for domain {domain!r}: the store cannot "
            f"search by vector on this collection. Asking it to find {probe_uri!r} "
            f"by that row's OWN stored vector raised: {e}\n\n"
            f"If that error names a missing vector for target 'default', this is the "
            f"condition Lane 74 measured on 2026-09-19: the collection is created with "
            f"no vector configuration, which declares a NAMED space 'default', while "
            f"`batch.add_object(vector=...)` writes the LEGACY unnamed slot. Every row "
            f"has a vector; the index has none; every hybrid search silently degrades "
            f"to BM25 with no log line. The rows being present is not the question — "
            f"see the packet, and the `collections.create` call in this same module."
        ) from e

    returned = [str((o.properties or {}).get("uri", "")) for o in res.objects]
    if probe_uri not in returned:
        raise Exception(
            f"RETRIEVABILITY SEAL FAILED for domain {domain!r}: the store answered a "
            f"nearObject query for {probe_uri!r} without returning that row. An object "
            f"is its own nearest neighbour; anything else means the vector the index "
            f"holds for it is not the vector the row carries. Returned: {returned}"
        )

    context.log.info(
        f"Retrievability seal green for domain {domain!r}: {probe_uri} retrieves "
        f"itself by its own stored vector. The grounding pool is searchable, not "
        f"merely populated."
    )
    return probe_uri


def sync_ontology_to_weaviate(extracted_classes: list[dict], domain: str, context: AssetExecutionContext, response_shapes: set[str] | None = None, source_ontology: str | None = None):
    """
    Takes parsed ontology classes (from rdflib/Jena) and dual-writes them to Weaviate.
    extracted_classes should be a list of dicts: {"uri": str, "label": str, "definition": str}
    """
    # 🔗 Use the Fleet-Standard Connection Strategy
    client = get_weaviate_client()

    # Partition BEFORE batch open so we do not pay batch-init cost for entries
    # we would skip anyway, and so the log line below is honest about how many
    # classes are actually written. The partitioner and its two exclusion
    # reasons live above this function; the SAME call is what the row seal
    # reconciles against after the write.
    domain_classes, exclusions = partition_ontology_classes(
        extracted_classes, response_shapes
    )
    filtered_meta = [e for e in exclusions if e["reason"] == EXCLUSION_META_ONTOLOGY]
    filtered_response = [e for e in exclusions if e["reason"] == EXCLUSION_RESPONSE_SHAPE]
    if filtered_meta:
        context.log.info(
            f"Filtered {len(filtered_meta)} meta-ontology classes from "
            f"Weaviate sync (e.g. {filtered_meta[0]['uri']}). "
            f"See [[ontology-class-pool-prov-contamination]] for the "
            f"2026-06-27 finding this filter closes."
        )

    try:
        # Ensure the collection exists
        if not client.collections.exists("OntologyClass"):
            # ################################################################
            # FIX SHAPE D (ruled by the architect 2026-09-19, on 74's
            # scratch-collection result): DECLARE THE NAMED SPACE AT CREATE,
            # AND WRITE BY NAME.
            #
            # THE DEFECT THIS CLOSES, measured by Lane 74 and filed at
            # ia-74/sessions/2026-09-19-packet-from-74-the-seam-returns-one-
            # and-the-vector-half-is-dead.md:
            #
            #   OntologyClass  vectorizer None  vectorConfig ['default']
            #                  nearObject(self) -> ERROR "vector not found for
            #                                      target: default"
            #   DocumentChunk  text2vec-ollama  vectorConfig None
            #                  nearObject(self) -> OK            <- the control
            #
            # A BARE `collections.create` ON CLIENT 4.21.x DECLARES A NAMED
            # SPACE `default` ANYWAY, while `add_object(vector=[...])` writes
            # the LEGACY unnamed slot. So the collection indexes a space that
            # is never written and holds vectors in a slot that is never
            # indexed. 26,239 rows, shard READY, queue empty, 24,924 carrying a
            # readable 768-dim vector — and every vector search returning
            # nothing, fleet-wide, with no log line anywhere. The router ran on
            # BM25 alone, which does not even stem: "hazard" matched five
            # classes and "hazards" matched none.
            #
            # That mechanism was 74's INFERENCE when they filed; the
            # scratch-collection experiment has since measured it, and the
            # architect ruled shape D over the alternative (create on the
            # legacy schema). The two were never interchangeable, which is why
            # this site waited for the measurement rather than picking on the
            # guess.
            #
            # BOTH HALVES OR NEITHER. `self_provided(name="default")` declares
            # the space this collection is indexed on and says the vectors
            # arrive from us; `add_object(vector={"default": ...})` below puts
            # them there. Declaring without writing by name reproduces the
            # exact defect, and writing by name into an undeclared space is
            # refused — so the two edits are one change and must not be split.
            #
            # THIS REPAIRS NEW COLLECTIONS ONLY. `collections.exists` short-
            # circuits above, so an existing OntologyClass keeps its broken
            # schema and its legacy-slot rows until 74's backfill runs. NO
            # INGEST AND NO RE-SYNC FROM HERE — 26,239 rows of shared state are
            # not a lane's to rewrite. `seal_a_written_row_is_RETRIEVABLE`
            # above is what keeps that honest: until the backfill lands it
            # fails this asset rather than reporting a populated pool as a
            # working one.
            # ################################################################
            context.log.info("Creating OntologyClass collection in Weaviate...")
            client.collections.create(
                name="OntologyClass",
                properties=[
                    wvc.config.Property(name="uri", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="label", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="definition", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="domain", data_type=wvc.config.DataType.TEXT),
                    # WHICH MANIFEST ENTRY PUT THIS ROW HERE (the s3 key).
                    #
                    # Added 2026-09-19 for Ruling 3. Without it the readiness
                    # sentinel can only ask "does this DOMAIN have any rows",
                    # and MAINTENANCE has SIX manifest entries — five of them
                    # could fail while the sixth keeps the domain looking
                    # ingested. That is the same store-liveness-wearing-an-
                    # ingest-check-name defect one level in, and it is not an
                    # improvement worth shipping.
                    #
                    # The Neo4j node has carried the equivalent (`synced_from`)
                    # since the Option 3 fix; the Weaviate row simply never
                    # did, so the two stores could not be asked the same
                    # question. ADDITIVE and safe for existing readers — Engine
                    # O selects uri/label/definition/domain and is untouched.
                    wvc.config.Property(name="source_ontology", data_type=wvc.config.DataType.TEXT),
                ],
                # THE HALF THAT WAS MISSING. Without this the server declares
                # `default` on its own and nothing ever writes into it; with it,
                # `default` is the space the index uses AND the space
                # `add_object(vector={"default": ...})` fills. `self_provided`
                # is the honest vectorizer here: doc-tools embeds via LiteLLM
                # (see doc_tools/utils/embed.py, which owns the model and the
                # task-prefix contract) and hands Weaviate a finished vector, so
                # the collection must not be configured to vectorize anything
                # itself.
                vector_config=[
                    wvc.config.Configure.Vectors.self_provided(name="default"),
                ],
            )
            # FOLD, NOT HAND-RUN — same act as the create. Records what actually
            # embedded these vectors (the SERVED model and the OBSERVED dimension,
            # never the constants), so the two hand-copied embed.py constants stop
            # being the cross-repo contract. Best-effort; never raises.
            from doc_tools.utils.collection_marker import write_collection_marker

            write_collection_marker(client, "OntologyClass")

        collection = client.collections.get("OntologyClass")
        context.log.info(
            f"Syncing {len(domain_classes)} domain classes to Weaviate "
            f"for domain {domain} ({len(filtered_meta)} meta-ontology, "
            f"{len(filtered_response)} response-shape classes filtered)..."
        )
        if filtered_response:
            context.log.info(
                f"Filtered {len(filtered_response)} response-shape class(es) "
                f"from the Weaviate grounding pool (e.g. "
                f"{filtered_response[0]['uri']}). They REMAIN in Neo4j "
                f"— Contract D and the compat walk both require them there. See "
                f"_RESPONSE_SHAPE_ROOTS and "
                f"[[response-classes-compete-for-grounding]]."
            )

        # Batch insert for high performance (Idempotent Upsert).
        # Computes the vector via doc_tools.utils.embed.embed_document()
        # (LiteLLM /embeddings, default nomic-embed-text, search_document:
        # prefix) and passes it to batch.add_object(vector=...) so Engine O's
        # hybrid search (which calls embed_query for the search_query:-prefixed
        # query vector) can score document/query similarity correctly. The
        # embedded text is "<label> — <definition>" — labels alone are
        # often too short to embed informatively. See doc_tools/utils/embed.py
        # for the rationale: code owns the embedding-model contract AND the
        # task-prefix discipline.
        from doc_tools.utils.embed import embed_document

        def _humanize_label(label: str) -> str:
            """Split underscore/camelCase compounds into words — for the
            EMBEDDING text only (the stored label is unchanged). A
            definition-less class's name is its ENTIRE semantic signal,
            and 'SomeCompoundClassName_specifiedProperty' embeds poorly
            against the natural-language queries Engine O's hybrid
            search receives."""
            import re
            words = re.sub(r"[_\-]+", " ", label)
            words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", words)
            words = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", words)
            return re.sub(r"\s+", " ", words).strip()

        with collection.batch.dynamic() as batch:
            for cls in domain_classes:
                # Use the URI to generate a deterministic UUID
                deterministic_uuid = generate_uuid5(str(cls["uri"]))

                safe_label = str(cls["label"]) if cls.get("label") else str(cls["uri"]).split("#")[-1].split("/")[-1]
                # NO FILLER, deliberately. The old default ('No definition
                # provided.') was both EMBEDDED and STORED: hundreds of
                # definition-less classes shared the same suffix, so their
                # vectors clustered on the filler instead of their names,
                # and the stored filler leaked verbatim into Engine O's
                # candidate prompts (token noise on every /resolve).
                # Absent stays absent: empty string in the row, label-only
                # in the vector.
                safe_definition = str(cls["definition"]) if cls.get("definition") else ""

                # Embed "<humanized label> — <definition>" for richer
                # signal than label alone; definition-less classes embed
                # the humanized label by itself. Best-effort: on gateway
                # failure, write without a vector so ingestion still
                # completes (BM25 still works; backfill can populate
                # later).
                embed_input = (
                    f"{_humanize_label(safe_label)} — {safe_definition}"
                    if safe_definition
                    else _humanize_label(safe_label)
                )
                try:
                    cls_vector = embed_document(embed_input)
                except Exception as e:
                    context.log.warning(
                        f"embed_document failed for {cls.get('uri','<?>')}; "
                        f"writing without vector (BM25-only until backfill): {e}"
                    )
                    cls_vector = None

                add_kwargs: dict = {
                    "properties": {
                        "uri": str(cls["uri"]),
                        "label": safe_label,
                        "definition": safe_definition,
                        "domain": domain.upper(),
                        # Absent on rows written before 2026-09-19. The sentinel
                        # reports that as UNATTRIBUTED rather than as a missing
                        # ingest — an old row and an absent row are different
                        # facts and must not be collapsed.
                        "source_ontology": source_ontology or "",
                    },
                    "uuid": deterministic_uuid,
                }
                if cls_vector is not None:
                    # BY NAME, not `vector=cls_vector`. The bare-list form
                    # writes the legacy unnamed slot, which is the half of the
                    # defect that made every row look vectorised to every
                    # instrument while the index stayed empty. Keyed on the same
                    # space declared at create above — see the block there; the
                    # two are one change.
                    add_kwargs["vector"] = {"default": cls_vector}

                batch.add_object(**add_kwargs)

        # THE BATCH DOES NOT RAISE, AND THIS IS WHERE RULING 1 WOULD OTHERWISE
        # STOP SHORT. Making the caller's `except` re-raise closes the case
        # where the whole leg throws — a dead client, a refused connection, a
        # broken extraction. It does NOT close the likelier one. weaviate-client
        # 4.21.3's batch collects per-object failures into
        # `collection.batch.failed_objects` and LOGS them; the context manager
        # exits cleanly with every row rejected. Read against the installed
        # client (collections/batch/base.py:722): "Failed to send {n} objects in
        # a batch of {n} ... inspect client.batch.failed_objects". No exception
        # is raised at any point.
        #
        # So the shape the ruling exists to refuse — Jena full, Weaviate empty,
        # run green — survives a re-raising `except` untouched, because nothing
        # ever reaches it. A write failure only fails the asset if the write's
        # own error channel is READ. This is that read.
        #
        # ABSENT ROW, not a thinner one: a failed `add_object` means the class
        # is not in the grounding pool at all. That is the same category as the
        # leg throwing, and deliberately NOT the category of the `embed_document`
        # fallback twenty lines up, which writes the row without a vector on
        # purpose and must stay best-effort.
        failed = list(getattr(collection.batch, "failed_objects", None) or [])
        if failed:
            sample = []
            for err in failed[:3]:
                obj = getattr(err, "object_", None)
                props = getattr(obj, "properties", None) or {}
                sample.append(f"{props.get('uri', '<?>')}: {getattr(err, 'message', err)}")
            raise Exception(
                f"Weaviate batch REJECTED {len(failed)} of "
                f"{len(domain_classes)} OntologyClass row(s) for domain "
                f"{domain!r}. The batch does not raise on per-object failure — "
                f"it collects them and logs — so without this read the asset "
                f"would report a green materialisation over a grounding pool "
                f"missing those classes. First failures: {sample}"
            )

        # RULING 2, the read-back. The batch accepting a row and the store
        # HOLDING it are different claims, and only the second one is what a
        # consumer sees. See seal_declared_classes_are_rows and the block
        # comment above it for why the basis is this run rather than a copy of
        # the manifest.
        rows_found = seal_declared_classes_are_rows(
            collection, domain_classes, domain, context
        )
        # BESIDE the row seal, never instead of it, and the two ask genuinely
        # different questions: the one above is "is the row there", this one is
        # "can the store find it". On the substrate measured 2026-09-19 the first
        # is green over 26,239 rows and the second is the only thing that fails.
        probed = seal_a_written_row_is_RETRIEVABLE(
            collection, domain_classes, domain, context
        )
        context.log.info(
            f"Weaviate sync complete for domain {domain!r}: "
            f"{len(domain_classes)} row(s) accepted, 0 rejected, "
            f"{rows_found} confirmed present on read-back, "
            f"retrievability probed on {probed or '<no vector-bearing row>'}. "
            f"{len(exclusions)} declared class(es) excluded by reason: "
            f"{len(filtered_meta)} {EXCLUSION_META_ONTOLOGY}, "
            f"{len(filtered_response)} {EXCLUSION_RESPONSE_SHAPE}. "
            f"Partition reconciles: "
            f"{len(domain_classes)} + {len(exclusions)} == "
            f"{len(extracted_classes)} declared."
        )
        
    finally:
        # Crucial for Dagster: cleanly close the tunnel when the asset finishes
        client.close()

@asset(partitions_def=ontology_partitions)
def ingest_ontology_to_jena(context: AssetExecutionContext, config: S3FileConfig, s3: S3Resource, jena: JenaResource) -> MaterializeResult:
    """
    Detects RDF files in MinIO (via sensor partition) and pushes them to Jena Named Graphs.

    Domain resolution (in order of precedence):
      1. ``config.extra_metadata["domain"]`` — explicit override. Use this
         when the s3 path is the ontology's *source* and not its *semantic
         domain* — e.g. ``s3://ontologies/mro/mro_extension.ttl`` should
         classify under ``MAINTENANCE``, not ``MRO``. The path tells you
         where the file came from; the domain tells the resolver which
         classes to consider for which queries. Conflating the two breaks
         every case where one semantic domain has source TTLs under
         multiple s3 prefixes (the common case once multiple ontology
         stewards contribute).
      2. ``parts[0]`` (s3 path's first segment) — legacy default. Kept
         because existing sensor-fired ingestions rely on it, but should
         be considered deprecated for any new domain. Logs a warning so
         it's visible when the implicit path is in use.

    Reference: tests/routing/STEP1_2_EXECUTION_REPORT.md deviation #1 —
    the canonical pipeline ran to RUN_SUCCESS but landed classes at a
    domain the resolver couldn't see, requiring a runtime workaround.
    Explicit config is the fix.
    """
    file_url = config.file_url
    if file_url.startswith("s3://"):
        url_parts = file_url[5:].split("/", 1)
        bucket = url_parts[0]
        obj_key = url_parts[1]
    else:
        # Get the exact S3 key from the run tags injected by the sensor
        obj_key = context.run.tags.get("s3_key")
        if not obj_key:
            # Fallback to partition key replacing double underscores
            partition_key = context.partition_key
            obj_key = partition_key.replace("__", "/")

    parts = obj_key.split('/')

    if len(parts) < 2:
        raise Exception(f"Invalid ontology path: {obj_key}. Expected '{{path}}/{{filename}}'")

    filename = parts[-1]

    # Domain resolution (2026-06-16: explicit-per-file mechanism — see
    # standing memory feedback_path_vs_semantic_domain + STATE_GATEWAY_V02.md
    # "explicit-per-file domain fix"). The resolver queries with SEMANTIC
    # domain names (MAINTENANCE / SUSTAINMENT / DATA_ENGINEERING / MESH /
    # MANUFACTURING) and the s3 PATH is the source axis, not the semantic
    # axis. Path-derivation works correct-by-accident when the path's
    # first segment happens to match the semantic domain (mro/, idp/,
    # sustainment/, mesh/) and silently produces wrong-domain entries
    # when it doesn't (mil/, future Munitions). Removing the silent
    # fallback is the durability fix.
    #
    # Priority order:
    #   1. config.extra_metadata['domain'] — explicit dagster config
    #      (used by prime_databases.py's trigger_ingest_jobs)
    #   2. S3 object metadata 'x-amz-meta-domain' — set by
    #      prime_databases.py's upload_canonical_ttls; auto-fixes
    #      the sensor-fired path that doesn't pass dagster config
    #   3. ERROR — path-derivation as a SILENT fallback is removed;
    #      a future ingestion path that doesn't declare a domain
    #      should fail loud, not silently land at a path-derived
    #      value that will produce confidently-wrong routing.
    #
    # The error path's message names the fix path explicitly so the
    # remediation is obvious from the log.
    s3_client = s3.get_client()
    bucket = os.getenv("ONTOLOGY_BUCKET", "ontologies")

    explicit_domain = (config.extra_metadata or {}).get("domain")
    s3_metadata_domain = None
    domain_source = None

    if explicit_domain:
        domain = str(explicit_domain)
        domain_source = "config.extra_metadata"
    else:
        # Probe S3 object metadata for x-amz-meta-domain (priority 2).
        try:
            head = s3_client.head_object(Bucket=bucket, Key=obj_key)
            s3_metadata_domain = (head.get("Metadata") or {}).get("domain")
        except Exception as e:
            context.log.warning(f"head_object failed (continuing): {e}")
            s3_metadata_domain = None

        if s3_metadata_domain:
            domain = str(s3_metadata_domain)
            domain_source = "s3_object_metadata.x-amz-meta-domain"
        else:
            raise Exception(
                f"Domain not declared for ontology {obj_key!r}. "
                f"Path-derivation as a silent fallback was removed 2026-06-16 "
                f"after producing confidently-wrong routing for the mil/ path "
                f"(mil:* classes are SEMANTIC maintenance, but path-derived "
                f"'MIL' was invisible to MAINTENANCE-domain resolver queries). "
                f"Declare domain via ONE OF: "
                f"(1) config.extra_metadata={{'domain': '<SEMANTIC_DOMAIN>'}} "
                f"in dagster runConfigData (the prime_databases.py path), OR "
                f"(2) S3 object metadata 'x-amz-meta-domain' on the object "
                f"(the sensor-fired path; prime_databases.py:339-343 sets "
                f"this automatically on every upload). The path's first "
                f"segment is {parts[0]!r}, which the legacy fallback would "
                f"have used — confirm that's the intended SEMANTIC domain "
                f"before declaring it."
            )

    context.log.info(
        f"Using domain {domain!r} from {domain_source} for ontology {filename!r}"
    )

    # Derive Named Graph URI
    graph_uri = f"http://internal/{domain}"

    context.log.info(f"Ingesting ontology '{filename}' for domain '{domain}' into graph <{graph_uri}>")

    # 1. Download from MinIO
    try:
        response = s3_client.get_object(Bucket=bucket, Key=obj_key)
        rdf_content = response['Body'].read()
    except Exception as e:
        context.log.error(f"Failed to fetch ontology from MinIO: {e}")
        raise e

    # 2. Validate with rdflib
    g = rdflib.Graph()
    content_type = "text/turtle"
    if filename.endswith((".rdf", ".owl")):
        content_type = "application/rdf+xml"
        fmt = "xml"
    else:
        fmt = "turtle"
        
    try:
        g.parse(data=rdf_content, format=fmt)
        context.log.info(f"Successfully validated RDF content ({len(g)} triples).")
    except Exception as e:
        context.log.error(f"Syntax validation failed for {obj_key}: {e}")
        raise e

    # 2b. Derive labels for classes the ontology never named. MUST run here —
    # after parse, before BOTH the Jena push below and the Weaviate extraction
    # further down, which read the same `g`. See the block above for why this is
    # a seed-step concern and not a query-side one.
    derive_missing_class_labels(g, context)

    # 3. Push to Jena using Graph Store Protocol (POST = MERGE/append, NOT PUT).
    # This asset is partitioned PER FILE, and MANY files map to ONE semantic domain
    # (e.g. MAINTENANCE = IOF_Core + IOF_MRO + DINEN62264 + mro/maintenance/mil
    # extensions). PUT REPLACES the whole named graph, so N files PUT to
    # http://internal/{domain} collapsed to whichever file landed LAST — silently
    # (found 2026-07-22: MAINTENANCE held only mil_extension's 10 classes, IOF core
    # destroyed). POST merges each file's triples into the domain graph so they
    # accumulate. Idempotency across re-runs is guaranteed by the reproducible
    # orchestrator clearing each domain graph ONCE before the per-file ingests
    # (invincible-agent setup/prime_databases.py `clear_ontology_graphs`), so
    # append-only never doubles blank-node structures on a re-prime.
    jena_base = jena.url.rstrip('/')
    jena_ds = jena.dataset
    user = jena.username
    pw = jena.password

    # GSP endpoint: {host}/{dataset}/data
    target_url = f"{jena_base}/{jena_ds}/data?graph={graph_uri}"

    try:
        # TIMEOUT: httpx defaults to 5s on ALL phases — far too short for the
        # large ontologies (IOF_Core ~400KB, S3000L ~280KB) whose merge into
        # TDB2 exceeds 5s when the prime launches all partitions concurrently
        # (Fuseki write contention) on a fresh/just-compacted store → ReadTimeout,
        # a spurious partition failure that succeeds on a quieter rerun. 120s
        # read/write with a short connect covers the heavy merges without hanging
        # forever on a genuinely dead Fuseki. NB deliberately NO auto-retry here:
        # POST is a MERGE/append and a ReadTimeout is AMBIGUOUS (the server may
        # have applied it), so a blind retry could DOUBLE the graph (esp.
        # blank-node structures) — the same doubling the clear-once discipline
        # exists to prevent. A failed partition is re-driven cleanly via a
        # re-prime (clear-then-single-append), not by re-POSTing here.
        timeout = httpx.Timeout(120.0, connect=10.0)
        with httpx.Client(auth=(user, pw), verify=False, timeout=timeout) as client:
            resp = client.post(
                target_url,
                content=rdf_content,
                headers={"Content-Type": content_type}
            )
            resp.raise_for_status()
            context.log.info(f"Successfully MERGED into Jena Named Graph: {graph_uri} (POST/append)")
    except Exception as e:
        context.log.error(f"Failed to push to Fuseki: {e}")
        raise e

    # 4. DUAL-WRITE: Sync to Weaviate for fast semantic search
    context.log.info("Extracting classes for Weaviate sync...")
    #
    # BLANK-NODE FILTER, BOTH LAYERS. Mirrored here 2026-09-19 from the Neo4j
    # leg (`sync_jena_ontologies_to_neo4j` below) — read the long block above
    # its `extract_query` for the 2026-06-15 history. What follows is why THIS
    # leg needed the same thing three months later.
    #
    # THE ASYMMETRY THIS CLOSES. The 2026-06-15 fix landed on the Neo4j leg
    # ONLY. This extraction — the one that feeds `sync_ontology_to_weaviate` —
    # went on selecting `?uri a ?type` with no `!isBlank` filter and no Python
    # BNode check, and `partition_ontology_classes` excludes meta-ontology IRIs
    # and response shapes, NEVER blank nodes. So every imported ontology's
    # anonymous owl:Class restrictions (rdfs:subClassOf of a unionOf /
    # intersectionOf / Restriction expression, which rdflib materializes as a
    # blank node typed owl:Class) were written into the OntologyClass
    # collection as rows whose `uri` is a bare `N<32 hex>` and whose `label`
    # falls back to that same hex string. Unroutable, unpickable by an LLM, and
    # embedded as noise in the pool the resolver grounds against. Lane 74
    # measured the live index at 96.2% blank nodes; this is the writer that put
    # them there.
    #
    # WHY IT COMPOUNDS RATHER THAN REPEATS. The row uuid is
    # `generate_uuid5(str(uri))`, and rdflib mints a FRESH blank-node id on
    # every parse — read in the installed wheel: `rdflib/term.py`
    # `BNode.__new__` defaults `value` to `"N" + uuid4().hex`; the Turtle/N3
    # parser seeds a per-parser-instance `uuid4().hex`
    # (`plugins/parsers/notation3.py`) and the RDF/XML parser calls bare
    # `BNode()` (`plugins/parsers/rdfxml.py`). The id is therefore NOT stable
    # across runs, so the deterministic-uuid upsert that makes this sync
    # idempotent for named classes does not apply to blank ones: a re-ingest
    # does not OVERWRITE the previous run's blank rows, it ADDS a fresh set.
    # That is the growth mechanism behind the 96.2%, and it is why closing the
    # writer comes before any backfill — a backfill against a leaking writer is
    # a delete that refills on the next prime.
    #
    # Defense-in-depth, same discipline as the other leg: the SPARQL filter is
    # primary, the Python isinstance check is the second layer for a future
    # rdflib that changes SPARQL evaluation of isBlank(). Either alone closes
    # the leak; both together surface a single-layer regression.
    # `tests/test_ontology_assets_blank_node_filter.py` asserts BOTH legs.
    #
    # WRITER ONLY. This stops the leak; it deletes nothing. The blank rows
    # already in the store stay there until an authorized backfill removes
    # them, and that is Chris's call, not this asset's.
    query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

    SELECT ?uri ?label ?definition
    WHERE {
        ?uri a ?type .
        FILTER(?type IN (owl:Class, rdfs:Class))
        FILTER(!isBlank(?uri))
        OPTIONAL { ?uri rdfs:label ?label }
        OPTIONAL {
            { ?uri skos:definition ?definition }
            UNION
            { ?uri rdfs:comment ?definition }
        }
    }
    """
    try:
        qres = g.query(query)
        extracted_classes = []
        skipped_blank_nodes = 0
        for row in qres:
            # Second layer — see the block above. rdflib's BNode subclasses
            # URIRef, so a `str()`-based prefix test does not catch these (the
            # 2026-06-15 no-op filter was exactly that mistake); isinstance
            # does, and it fires even if the SPARQL layer stopped working.
            if isinstance(row.uri, rdflib.term.BNode):
                skipped_blank_nodes += 1
                continue
            extracted_classes.append({
                "uri": row.uri,
                "label": row.label,
                "definition": row.definition
            })

        if skipped_blank_nodes:
            # NON-ZERO MEANS THE PRIMARY LAYER DID NOT HOLD. The row never
            # reaches the store either way, but a silent second-layer save is
            # how a SPARQL-filter regression stays invisible until somebody
            # next counts the pool — which is how this one lasted three months.
            context.log.warning(
                f"{skipped_blank_nodes} blank-node owl:Class row(s) passed the "
                f"SPARQL !isBlank filter and were dropped by the Python "
                f"isinstance check instead. The SPARQL layer is primary and "
                f"should have caught these; check the rdflib version before "
                f"treating this as benign."
            )

        if extracted_classes:
            # Computed HERE because this is where the rdflib graph lives; the
            # SPARQL above deliberately selects only uri/label/definition and a
            # response shape is identified by its subClassOf root, not by any
            # column in that projection.
            sync_ontology_to_weaviate(
                extracted_classes, domain, context,
                response_shapes=response_shape_uris(g),
                source_ontology=obj_key,
            )
        else:
            context.log.warning("No classes found in ontology to sync to Weaviate.")
            
    except Exception as e:
        # RULING 1 (architect, 2026-09-19): A FAILED DUAL-WRITE FAILS THE ASSET.
        #
        # This `except` used to log at error and FALL THROUGH to the same
        # MaterializeResult the success path returns. Dagster saw a materialised
        # asset; Jena had the triples, Weaviate had nothing, and the run was
        # green. A partial ingest reported as a success is precisely the state
        # the class system exists to refuse — the graph is authoritative for
        # what EXISTS and the vector store for what can be GROUNDED, and a run
        # that populates one and not the other leaves the mesh in a condition no
        # consumer can detect from the outside. The MAINTENANCE domain's missing
        # work-order class was diagnosed for a day as a missing manifest row; it
        # was this, reporting green.
        #
        # THE ASYMMETRY THIS CLOSES: the Neo4j leg below
        # (`sync_jena_ontologies_to_neo4j`) has always raised on failure, and
        # says so in its docstring. One store's write failure was fatal and the
        # other's was a log line, in one pipeline, with nothing marking the
        # difference as deliberate.
        #
        # WHAT IS DELIBERATELY *NOT* WIDENED, because the distinction the ruling
        # turns on is ROW MISSING vs ROW PRESENT BUT THINNER:
        #   * `embed_document` failure inside `sync_ontology_to_weaviate` writes
        #     the row without a vector and says so. BM25 still answers and a
        #     backfill can populate the vector later. Stays best-effort.
        #   * `write_collection_marker` is metadata about the collection, not a
        #     row in it. Stays best-effort, never raises.
        # Both are degraded rows. This one is an absent row.
        raise Exception(
            f"Weaviate dual-write FAILED for domain '{domain}' "
            f"(graph {graph_uri}): {e}. The Jena push above SUCCEEDED, so the "
            f"substrate is now PARTIAL — Jena holds {len(g)} triples that the "
            f"vector store cannot ground. Re-drive this partition; do not "
            f"treat the Jena half as done. Per the 2026-09-19 ruling this "
            f"raises rather than logging, because a partial ingest reported as "
            f"a success is the failure the class system exists to refuse."
        ) from e

    return MaterializeResult(
        metadata={
            "domain": domain,
            "graph_uri": graph_uri,
            "triples": len(g),
            "s3_path": f"s3://{bucket}/{obj_key}"
        }
    )


# ===========================================================================
# RULING 3 — the readiness sentinel becomes PER DOMAIN, PER MANIFEST ENTRY
# ===========================================================================
# The rules live in `doc_tools/utils/ontology_readiness.py`, pure and testable
# without a cluster; this asset is only the I/O around them. Read that module
# first — it carries the argument for why the EXPECTATION cannot come from the
# store being checked, and what the four states are for.
#
# WHAT THIS REPLACES, since the dispatch describes the incumbent rather than
# naming it: engine-o's `/health` returns `jena_configured` / `neo4j_configured`,
# both derived from the ENVIRONMENT by
# `agent_fleet/ontology_service/substrate_posture.py`. It is a configuration
# read. It cannot see a row, so it cannot see a missing one, and it is green the
# moment the pod has its variables — including over a domain that ingested
# nothing. That endpoint stays as it is; changing it is invincible-agent's side
# of the line. THIS is the ingest check, and it lives where the ingest lives.
#
# NOT PARTITIONED, DELIBERATELY. Every other asset here is per-file, and a
# per-file readiness check is the defect restated: it can only be green or
# absent for its own partition, and an ENTRY THAT NEVER RAN has no partition run
# to be absent in. The sentinel has to stand outside the partition set and
# enumerate what SHOULD have run, or it inherits exactly the blind spot it
# exists to remove.

@asset(deps=[ingest_ontology_to_jena])
def weaviate_ontology_readiness(
    context: AssetExecutionContext,
    s3: S3Resource,
) -> MaterializeResult:
    """Per-domain, per-manifest-entry ingest posture for the OntologyClass pool.

    Enumerates the ontology bucket (prime uploads one object per manifest entry
    and stamps `x-amz-meta-domain` on it), asks Weaviate how many rows carry
    each `source_ontology`, and FAILS when any declared entry has none.

    Raises rather than warns. A sentinel whose failure mode is a log line is the
    thing this ruling is replacing.
    """
    from doc_tools.utils.ontology_readiness import (
        ontology_ingest_posture,
        format_posture,
        STATE_ABSENT,
        STATE_UNATTRIBUTED,
    )

    bucket = os.getenv("ONTOLOGY_BUCKET", "ontologies")
    s3_client = s3.get_client()

    # ----- the EXPECTATION, read off the bucket rather than off the store ----
    declared: dict[str, str] = {}
    undeclared_domain: list[str] = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []) or []:
            key = obj["Key"]
            if not key.lower().endswith((".ttl", ".rdf", ".owl")):
                continue
            head = s3_client.head_object(Bucket=bucket, Key=key)
            domain = (head.get("Metadata") or {}).get("domain")
            if not domain:
                # NOT skipped. An object with no domain stamp is a prime that
                # did not finish the job, and skipping it would hide the very
                # entry most likely to have failed.
                undeclared_domain.append(key)
                continue
            declared[key] = str(domain).upper()

    if not declared:
        raise Exception(
            f"Readiness sentinel found NO ontology objects in bucket "
            f"{bucket!r}. That is not a green substrate with nothing to check "
            f"— it is a bucket that prime never populated, and every domain "
            f"below would otherwise be vacuously ready."
        )

    # ----- what the store actually holds -------------------------------------
    rows_by_source: dict[str, int] = {}
    unattributed_by_domain: dict[str, int] = {}
    client = get_weaviate_client()
    try:
        if not client.collections.exists("OntologyClass"):
            raise Exception(
                f"Readiness sentinel: the OntologyClass collection does not "
                f"exist, while the bucket declares {len(declared)} ontology "
                f"object(s) across {len(set(declared.values()))} domain(s). "
                f"Nothing has ingested."
            )
        collection = client.collections.get("OntologyClass")
        for obj in collection.iterator(
            return_properties=["domain", "source_ontology"]
        ):
            props = obj.properties or {}
            source = str(props.get("source_ontology") or "")
            if source:
                rows_by_source[source] = rows_by_source.get(source, 0) + 1
            else:
                dom = str(props.get("domain") or "").upper()
                unattributed_by_domain[dom] = unattributed_by_domain.get(dom, 0) + 1
    finally:
        client.close()

    postures = ontology_ingest_posture(
        declared=declared,
        rows_by_source=rows_by_source,
        unattributed_rows_by_domain=unattributed_by_domain,
    )
    report = format_posture(postures)
    context.log.info("Ontology ingest posture:\n" + report)

    not_ready = [(p.domain, e) for p in postures for e in p.not_ready]
    absent = [(d, e) for d, e in not_ready if e.state == STATE_ABSENT]
    unattributed = [(d, e) for d, e in not_ready if e.state == STATE_UNATTRIBUTED]

    if undeclared_domain:
        context.log.error(
            f"{len(undeclared_domain)} ontology object(s) carry no "
            f"x-amz-meta-domain and could not be checked at all: "
            f"{undeclared_domain[:5]}"
        )

    if not_ready or undeclared_domain:
        raise Exception(
            f"Ontology substrate NOT READY. "
            f"{len(absent)} declared manifest entry/entries have ZERO rows in "
            f"the OntologyClass pool: {[k for _, e in absent for k in [e.s3_key]][:8]}. "
            f"{len(unattributed)} entry/entries could not be attributed (rows "
            f"predate source_ontology, written before 2026-09-19): "
            f"{[e.s3_key for _, e in unattributed][:8]}. "
            f"{len(undeclared_domain)} bucket object(s) carry no domain stamp. "
            f"This sentinel is per-ENTRY on purpose: the previous check "
            f"answered 'is Weaviate up', and was green across a by-hand "
            f"re-ingest of the safety classes in both directions.\n\n{report}"
        )

    return MaterializeResult(
        metadata={
            "domains_ready": len(postures),
            "entries_declared": len(declared),
            "rows_total": sum(rows_by_source.values()),
            "posture": report,
        }
    )


# ===========================================================================
# Option 3 fix — sync_jena_ontologies_to_neo4j
#
# Per the Session-1/Session-2 close (2026-06-12): the TTL→Neo4j leg of the
# canonical pipeline was unwired — `sync_jena_to_neo4j` depends on the XML
# extraction path (`upload_to_jena`), so TTL ingests reached Jena+Weaviate
# but never propagated to Neo4j's OntologyClass graph. On a fresh cluster
# every engine declaration referencing a canonical mesh:* / mil:* / idp:* /
# mro: class would Contract-D-reject (no OntologyClass node exists for the
# declared input_uri/output_uri).
#
# Option 3 (chosen over options 1 and 2 because it keeps TTL→Neo4j as a
# first-class observable seam — see invincible-agent state doc dated
# 2026-06-12): a NEW asset depending only on `ingest_ontology_to_jena`,
# partitioned identically, whose only job is "TTL classes reach the
# runtime graph." The XML pipeline keeps its own sync; this asset owns
# the canonical-ontology lane.
#
# Mechanics — WHAT THE CODE BELOW ACTUALLY DOES.
#
# CORRECTED 2026-09-19. This block used to describe the n10s route: build the
# Jena named-graph URI, SPARQL CONSTRUCT against it, `n10s.rdf.import.fetch`
# that CONSTRUCT URL, then relabel the resulting `:Resource` nodes. The
# docstring immediately below has said since Session 2 that route was ABANDONED
# and why — wrong Fuseki endpoint path, n10s's silent-zero failure mode, and a
# `:Resource`-vs-`:OntologyClass` label collision — but the comment describing
# the mechanics was never moved with the code. So the file carried BOTH
# stories, the abandoned one first and in the more authoritative-looking place.
#
# THAT IS WORSE THAN NO COMMENT, and it is worth naming as its own defect
# rather than just deleting: a reader looking for the Jena read in this asset
# does not find one and concludes the sync is broken, when in fact the asset
# never touches Jena at all. The same drift is what
# `phase5_catalog_verb_migration.py`'s docstring did about subClassOf edges,
# two paragraphs down — a comment asserting a mechanism nobody re-read after
# the mechanism moved.
#
#   1. Resolve domain + S3 key. `config.extra_metadata['domain']` >
#      S3 object metadata `x-amz-meta-domain` > RAISE. There is NO
#      path-derived default — it was removed 2026-06-16 because a silent
#      fallback produced confidently-wrong routing (the `mil/` prefix
#      derived domain 'MIL' for classes whose semantic domain is
#      MAINTENANCE). Same precedence as ingest_ontology_to_jena, which is
#      the claim `test_no_path_derived_domains` keeps true.
#   2. Fetch the RDF from MinIO and parse it with rdflib — the SAME bytes
#      `ingest_ontology_to_jena` parsed, read from S3 again. THIS ASSET DOES
#      NOT READ JENA. The dependency on the ingest is an ordering edge, not a
#      data edge; the shared source is S3.
#   3. SPARQL-extract the classes: named `owl:Class`/`rdfs:Class` with
#      OPTIONAL label, definition and `mesh:universalReferent`. Blank nodes
#      are filtered at the SPARQL layer (`!isBlank`) and again in Python;
#      meta-ontology IRIs are filtered per `_META_ONTOLOGY_IRI_PREFIXES`. The
#      response-shape filter is NOT applied here — that one is Weaviate-only,
#      and the comment in `sync_ontology_to_weaviate` says at length why
#      mirroring it would un-register every verb.
#      Three different zero-class outcomes are separated rather than collapsed:
#      an all-meta TTL and a deliberately class-less policy/rules TTL are
#      logged no-ops; a graph that DOES declare classes yet extracted none
#      raises, because that one is drift.
#   4. Direct MERGE on `uri`, SET label / definition / domain /
#      last_synced_at / synced_by / synced_from / universal_referent. No n10s,
#      no `:Resource` nodes, no relabeling step. Mirrors the validated shape
#      in `seed_mro_extension_runtime.py` and in the Weaviate leg above —
#      same source data, same extraction, same convention.
#   5. subClassOf edges: MATCH both endpoints, MERGE (child)-[:subClassOf]->
#      (parent) for every named->named `rdfs:subClassOf`. The parent is
#      MATCHed and never MERGEd, deliberately: fabricating it would mint bare
#      nodes for exactly the meta-ontology parents step 3 filtered out. THIS
#      is what makes phase5_catalog_verb_migration.py's docstring claim
#      ("subClassOf edges land at TTL ingest via the Jena→Neo4j step") TRUE —
#      before, only NODES were synced and the edges were hand-MERGEd by that
#      one-off, so a fresh cluster's class set was flat and
#      find_compatible_verbs' subClassOf* walk never formed. Source-authority
#      per ADR-0006: the ingest owns node AND hierarchy, so no hand-run is
#      needed and none can silently revert.
#   6. Verification readback, which raises on a class that MERGEd but is not
#      there, and on a universal-referent partition that does not match the
#      TTL's.
#
# Idempotency: re-running this asset on the same partition is safe — every
# write is a MERGE keyed on the canonical URI and every property write is
# SET-not-create. Re-ingest of a TTL that drops a class will leave the
# OntologyClass node behind (orphan), which is the same drift signature the
# routing layer has standing guards for (`test_no_phantom_input_classes` flags
# any verb that points at one). The one property that is NOT sticky is
# `universal_referent`: it is SET to null when the TTL stops declaring it,
# because absence is that flag's encoding of false.
#
# Acceptance test (architect's sharp form): ingest a TTL with a class that
# has NO historical N10S artifact and NO Phase 5 Cypher provenance — a
# class that has only ever existed in a TTL — and assert it materializes
# in Neo4j at full-IRI form where the resolver looks. mil_extension.ttl
# is the natural carrier; its first ingest doubles as this asset's
# acceptance test (B1 of the docs phase).
# ===========================================================================

@asset(partitions_def=ontology_partitions, deps=[ingest_ontology_to_jena])
def sync_jena_ontologies_to_neo4j(
    context: AssetExecutionContext,
    config: S3FileConfig,
    s3: S3Resource,
    neo4j: Neo4jResource,
) -> MaterializeResult:
    """Sync TTL-ingested classes AND their subClassOf hierarchy from MinIO
    to Neo4j via rdflib extraction.

    Closes the Session-1 DAG-wiring break that made TTL→Neo4j the deploy-
    blocker (see module docstring above). Depends only on
    `ingest_ontology_to_jena` so the XML pipeline's sync stays
    independent.

    Materializes BOTH the OntologyClass nodes AND their named-to-named
    `subClassOf` edges (Step 2.5 / Step 3.5). The edges were previously
    orphaned to the one-off `scripts/phase5_catalog_verb_migration.py`,
    whose docstring claimed they land here — a claim this asset now makes
    true. Without them a fresh cluster's classes are a flat set and the
    routing compat-walk (`find_compatible_verbs`, subClassOf*) never forms.

    Implementation note (Session-2 lesson): the first attempt used
    n10s.rdf.import.fetch against Jena. That ran into three layered
    problems — a wrong Fuseki endpoint path (`/ds/query` 404s instead of
    `/ds/sparql`), n10s's silent-zero failure mode (it returns success
    with triplesLoaded=0 when the fetch HTTP-errors), AND a
    :Resource-vs-:OntologyClass label collision with the historical
    direct-load shape that would have duplicated every node. Replaced
    with the simpler shape: extract classes via rdflib from the S3
    source (same RDF the ingest_ontology_to_jena step parses) and emit
    them as direct MERGEs. Mirrors the validated pattern from
    seed_mro_extension_runtime.py and from sync_ontology_to_weaviate's
    Weaviate path — same source data, same extraction, same convention.

    The seam stays first-class observable: this asset's only job is
    "TTL classes reach Neo4j's OntologyClass graph." Failures raise
    loudly. Idempotent — re-runs MERGE on URI and update label/
    definition/domain.
    """
    # ----- Resolve domain + S3 key (same precedence as ingest_ontology_to_jena) -----
    file_url = config.file_url
    if file_url.startswith("s3://"):
        url_parts = file_url[5:].split("/", 1)
        bucket = url_parts[0]
        obj_key = url_parts[1] if len(url_parts) > 1 else ""
    else:
        bucket = os.getenv("ONTOLOGY_BUCKET", "ontologies")
        obj_key = context.run.tags.get("s3_key") or ""
        if not obj_key:
            obj_key = context.partition_key.replace("__", "/")

    parts = obj_key.split("/")
    if len(parts) < 2:
        raise Exception(
            f"Invalid ontology path: {obj_key!r}. Expected '{{path}}/{{filename}}'"
        )

    # ----- Domain resolution (2026-06-16: explicit-per-file, no silent fallback).
    # Same precedence as ingest_ontology_to_jena:
    #   1. config.extra_metadata['domain']
    #   2. S3 object metadata 'x-amz-meta-domain'
    #   3. ERROR (path-derivation as silent fallback removed)
    # See ingest_ontology_to_jena's identical block for the trace.
    s3_client = s3.get_client()
    bucket_default = os.getenv("ONTOLOGY_BUCKET", "ontologies")

    explicit_domain = (config.extra_metadata or {}).get("domain")
    domain_source = None
    if explicit_domain:
        domain = str(explicit_domain)
        domain_source = "config.extra_metadata"
    else:
        try:
            head = s3_client.head_object(Bucket=bucket_default, Key=obj_key)
            s3_metadata_domain = (head.get("Metadata") or {}).get("domain")
        except Exception as e:
            context.log.warning(f"head_object failed (continuing): {e}")
            s3_metadata_domain = None

        if s3_metadata_domain:
            domain = str(s3_metadata_domain)
            domain_source = "s3_object_metadata.x-amz-meta-domain"
        else:
            raise Exception(
                f"Domain not declared for ontology {obj_key!r}. "
                f"Path-derivation as a silent fallback was removed 2026-06-16. "
                f"Declare domain via config.extra_metadata={{'domain':'<SEMANTIC>'}} "
                f"or via S3 object metadata x-amz-meta-domain. Path's first "
                f"segment {parts[0]!r} — confirm it's the intended SEMANTIC "
                f"domain before declaring it."
            )

    context.log.info(
        f"Using domain {domain!r} from {domain_source}"
    )

    # ----- Step 1: fetch + parse the RDF from MinIO -----------------------
    bucket = bucket_default
    filename = parts[-1]
    context.log.info(
        f"Fetching {filename!r} from s3://{bucket}/{obj_key} for "
        f"domain '{domain}'"
    )
    try:
        response = s3_client.get_object(Bucket=bucket, Key=obj_key)
        rdf_content = response["Body"].read()
    except Exception as e:
        raise Exception(
            f"Failed to fetch RDF from s3://{bucket}/{obj_key} for "
            f"Neo4j sync: {e}. Note ingest_ontology_to_jena (upstream "
            f"dep) succeeded so the file exists; check MinIO ACLs and "
            f"the S3 resource credentials."
        ) from e

    g = rdflib.Graph()
    fmt = "xml" if filename.endswith((".rdf", ".owl")) else "turtle"
    try:
        g.parse(data=rdf_content, format=fmt)
    except Exception as e:
        raise Exception(
            f"RDF parse failed for {filename!r} (format={fmt}): {e}. "
            f"This is downstream of ingest_ontology_to_jena which "
            f"already validated the same content — the failure here "
            f"is probably a content/MinIO drift between the two assets."
        ) from e

    # ----- Step 2: SPARQL-extract classes (same shape as the Weaviate sync) ----
    #
    # Blank-node owl:Class entries are EXCLUDED at the SPARQL layer via
    # !isBlank(?uri). Imported ontologies (PROV-O, IOF_Core, S3000L,
    # DINEN62264, etc.) declare many anonymous owl:Class restrictions
    # (rdfs:subClassOf of a unionOf / intersectionOf / Restriction expression,
    # which rdflib materializes as a fresh blank node with type owl:Class).
    # These have no human label, no semantic content, and no role as resolver
    # targets — they're RDF authoring artifacts, not concepts.
    #
    # PRE-FIX bug history (2026-06-15): this filter was Python-side and
    # checked `uri.startswith("Bnode_")` / `"_:"` which **never match**
    # rdflib's `BNode.__str__` output (`N[a-f0-9]{32}`). The filter has been
    # a no-op since Session 2's keystone — every ontology re-ingest leaked
    # ~441 blank-node :OntologyClass nodes (substrate count grew 1,191
    # blank-node phantoms across two writers, this pipeline contributing
    # 441). Surfaced by the mesh:Thing investigation's pre-flight provenance
    # grouping. Inert in routing (no verbs route through them, no LLM picks
    # them — labels are the hex IDs themselves) but cosmetic debt that ships
    # to every fresh bootstrap.
    #
    # Defense-in-depth: SPARQL filter is primary; Python isinstance check is
    # secondary belt-and-braces in case a future rdflib version changes
    # SPARQL evaluation. Either alone would close the leak; both together
    # surface the regression at two layers.
    #
    # ?universal_referent is OPTIONAL and almost always UNBOUND — see
    # UNIVERSAL_REFERENT_PREDICATE at module top. Exactly one class in the whole
    # manifest carries it today (mesh:Thing), and the flag must ride the same
    # extraction as label/definition rather than a second pass: a separate
    # traversal is a second reader of the same graph that can disagree with this
    # one about which classes were extracted at all.
    extract_query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl:  <http://www.w3.org/2002/07/owl#>
    PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
    PREFIX mesh: <http://invincible-agent/mesh#>

    SELECT ?uri ?label ?definition ?universal_referent
    WHERE {
        ?uri a ?type .
        FILTER(?type IN (owl:Class, rdfs:Class))
        FILTER(!isBlank(?uri))
        OPTIONAL { ?uri rdfs:label ?label }
        OPTIONAL {
            { ?uri skos:definition ?definition }
            UNION
            { ?uri rdfs:comment ?definition }
        }
        OPTIONAL { ?uri mesh:universalReferent ?universal_referent }
    }
    """
    rows = list(g.query(extract_query))
    classes = []
    # Diagnostics to distinguish "extraction found nothing" from
    # "extraction found N but every one was filtered out" — the two
    # produce identical empty `classes` lists but have very different
    # meanings. Without this split, a legitimately-filtered
    # meta-ontology TTL (PROV-O, RDFS, OWL, SKOS...) raises the same
    # exception as a broken extraction pattern. 2026-07-01 fix.
    seen_non_blank_uris = 0
    filtered_meta = 0
    for row in rows:
        # Defense-in-depth: rdflib's BNode subclasses URIRef; isinstance
        # check fires even if SPARQL didn't filter (e.g., future rdflib
        # behavior change). The string check is kept for legacy outputs.
        if isinstance(row.uri, rdflib.term.BNode):
            continue
        uri = str(row.uri)
        if not uri or uri.startswith("Bnode_") or uri.startswith("_:"):
            continue
        seen_non_blank_uris += 1
        # Meta-ontology filter — see _META_ONTOLOGY_IRI_PREFIXES /
        # _is_meta_ontology_iri at module top. Mirrors the Weaviate-side
        # filter in sync_ontology_to_weaviate so BOTH stores stay
        # canonical-clean of provenance/RDFS/OWL/SKOS/DC/etc. terms.
        # See [[ontology-class-pool-prov-contamination]].
        if _is_meta_ontology_iri(uri):
            filtered_meta += 1
            continue
        label = str(row.label) if row.label is not None else uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        definition = str(row.definition) if row.definition is not None else ""
        classes.append({
            "uri": uri,
            "label": label,
            "definition": definition,
            # None, NOT False. ABSENT MEANS FALSE is the encoding, and Cypher
            # `SET c.prop = null` REMOVES the property — so a class that stops
            # carrying the flag in the TTL stops carrying it on the node at the
            # next sync, and a class that never carried it never grows the
            # property at all. Writing False instead would put the property on
            # ~24,000 nodes to say nothing, and would make "the flag was
            # dropped" and "the flag is false" indistinguishable from a read.
            UNIVERSAL_REFERENT_PROPERTY: _universal_referent_value(
                row.universal_referent
            ),
        })

    if not classes:
        # Distinguish "content drift / broken extraction" (real error)
        # from "correctly filtered meta-ontology TTL" (deliberate no-op).
        # The 2026-06 [[ontology-class-pool-prov-contamination]] fix
        # added the meta-ontology filter, but this zero-check treated
        # "all filtered" the same as "nothing found" — which broke
        # substrate init any time PROV-O.ttl (or any other meta-only
        # TTL) was in the seed set. Now:
        #   - filtered_meta > 0 AND seen_non_blank_uris == filtered_meta
        #     → the TTL is entirely meta-ontology content that the
        #       corpus discipline says should NOT be in Neo4j. Log
        #       loudly and return an empty class list so the caller
        #       can decide what to do (skip vs error). Neo4j write
        #       becomes a no-op.
        #   - otherwise → real content drift or extraction bug. Raise.
        if filtered_meta > 0 and seen_non_blank_uris == filtered_meta:
            context.log.warning(
                f"Ontology {filename!r} (domain '{domain}') contained "
                f"{filtered_meta} classes but ALL were filtered as "
                f"meta-ontology terms per _META_ONTOLOGY_IRI_PREFIXES. "
                f"Skipping Neo4j write — this TTL should not be in the "
                f"seed set (its terms are corpus-noise per "
                f"[[ontology-class-pool-prov-contamination]]). Consider "
                f"removing it from the ontology upload manifest."
            )
            return MaterializeResult(
                metadata={
                    "classes_written": 0,
                    "domain": domain,
                    "filename": filename,
                    "skipped_reason": "all_meta_ontology_filtered",
                    "filtered_meta_count": filtered_meta,
                }
            )
        # THIRD case: a genuinely class-less ontology — a policy-as-data /
        # rules / vocabulary TTL (e.g. pcn_disposition_rules.ttl, a FLAT
        # decision table of rule INDIVIDUALS that DELIBERATELY declares no
        # owl:Class). Probe the RAW graph for ANY class declaration (named OR
        # blank, no filters). If it declares NONE, there was nothing to
        # extract — this is not drift, it is a class-less ontology, and the
        # Jena named-graph load (which the disposition proposer actually
        # queries) already succeeded. Skip the Neo4j write gracefully, exactly
        # as the Weaviate leg already does ("No classes found ... to sync to
        # Weaviate" is a warning there, not a raise). Only the case where the
        # graph DOES declare classes but extraction returned none is a real
        # drift / broken-pattern bug — that still raises below.
        graph_declares_classes = bool(
            g.query(
                "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
                "PREFIX owl:  <http://www.w3.org/2002/07/owl#> "
                "ASK { ?c a ?t . FILTER(?t IN (owl:Class, rdfs:Class)) }"
            ).askAnswer
        )
        if not graph_declares_classes:
            context.log.warning(
                f"Ontology {filename!r} (domain '{domain}') declares NO "
                f"owl:Class/rdfs:Class in its raw graph ({len(g)} triples) — a "
                f"class-less ontology (policy-as-data / rules / vocabulary, e.g. "
                f"a flat decision table of rule individuals). Nothing to sync to "
                f"Neo4j; the Jena named-graph load already succeeded and is what "
                f"consumers query. Skipping Neo4j write (no-op), same as the "
                f"Weaviate leg."
            )
            return MaterializeResult(
                metadata={
                    "classes_written": 0,
                    "domain": domain,
                    "filename": filename,
                    "skipped_reason": "class_less_data_ontology",
                    "raw_triples": len(g),
                }
            )
        # Real zero-extraction failure — the graph DOES declare owl:Class /
        # rdfs:Class triples yet the extraction pattern matched none of them:
        # a broken SPARQL/filter, or content drift. Genuine bug — raise.
        raise Exception(
            f"Zero classes extracted from {filename!r} (domain "
            f"'{domain}') despite the graph declaring owl:Class / rdfs:Class "
            f"triples — the extraction pattern matched none of them. A "
            f"broken-SPARQL/filter or content-drift bug (a class-less "
            f"policy/rules ontology is handled above, not here). The upstream "
            f"ingest_ontology_to_jena validated {len(g)} triples. Fix the TTL "
            f"or the extraction pattern."
        )

    context.log.info(
        f"Extracted {len(classes)} classes from {filename!r} for "
        f"domain '{domain}'. First 3: "
        f"{[c['uri'] for c in classes[:3]]}"
    )

    # ----- Step 2.5: extract subClassOf edges (the routing hierarchy) -----
    # WHY THIS IS HERE NOW. find_compatible_verbs walks
    # (subject)-[:subClassOf*]->(ancestor) in Neo4j to reach a verb typed
    # against an ANCESTOR class (e.g. idp:Dashboard -> idp:Dataset, where the
    # catalog verbs live). This asset previously MERGEd class NODES but NOT
    # these edges, so a fresh cluster had a FLAT class set: the compat-walk
    # never formed and catalog routing silently fell to the generalist. The
    # edges had to be hand-MERGEd by
    # scripts/phase5_catalog_verb_migration.py — whose docstring FALSELY
    # claimed they "land at TTL ingest via the Jena->Neo4j step." This step
    # makes that claim TRUE (source-authority, ADR-0006): the ingest that
    # owns the nodes now owns their hierarchy too, so no fresh cluster needs
    # a hand-run and none can silently revert on the next ingest.
    #
    # Named->named only — blank-node restriction/union superclasses are RDF
    # authoring artifacts, not routing ancestors (same !isBlank discipline
    # as the class extraction above).
    subclass_edges = [
        {"child": str(child), "parent": str(parent)}
        for child, _p, parent in g.triples((None, rdflib.RDFS.subClassOf, None))
        if not isinstance(child, rdflib.term.BNode)
        and not isinstance(parent, rdflib.term.BNode)
    ]
    context.log.info(
        f"Extracted {len(subclass_edges)} named subClassOf edge(s) "
        f"from {filename!r}"
    )

    # ----- Step 3: MERGE into Neo4j ---------------------------------------
    # Match the validated pattern from seed_mro_extension_runtime.py:
    # MERGE on uri; SET label / definition / domain. Idempotent. Preserves
    # any rich properties (ingest_run_id, source_ontology, provenance,
    # ingested_at) that the historical direct-load shape established —
    # this asset doesn't overwrite them, just refreshes the
    # resolver-visible label / definition / domain.
    #
    # The universal-referent SET is interpolated from
    # UNIVERSAL_REFERENT_PROPERTY rather than typed into the Cypher, so the
    # constant Lane 1's pool leg is told to read is the SAME string this write
    # uses. Two spellings of one contract is the failure this codebase keeps
    # paying for — the write succeeds, the read matches nothing, nothing reds.
    # The constant is asserted identifier-shaped at import (see module top), so
    # this is not an injection surface.
    neo4j_client = neo4j.get_client()
    try:
        neo4j_client.execute_query(
            f"""
            UNWIND $classes AS cls
            MERGE (c:OntologyClass {{uri: cls.uri}})
            SET c.label = cls.label,
                c.definition = cls.definition,
                c.domain = $domain,
                c.last_synced_at = datetime(),
                c.synced_by = 'sync_jena_ontologies_to_neo4j',
                c.synced_from = $s3_path,
                c.{UNIVERSAL_REFERENT_PROPERTY} = cls.{UNIVERSAL_REFERENT_PROPERTY}
            """,
            {
                "classes": classes,
                "domain": domain.upper(),
                "s3_path": f"s3://{bucket}/{obj_key}",
            },
        )
    except Exception as e:
        raise Exception(
            f"Neo4j MERGE failed for domain '{domain}' "
            f"({len(classes)} classes): {e}"
        ) from e

    # ----- Step 3.5: MERGE subClassOf edges -------------------------------
    # MATCH both endpoints (NOT merge the parent). The parent must ALREADY
    # be a synced OntologyClass node — this is deliberate: it stops
    # meta-ontology parents that the class extraction filters OUT
    # (prov:Entity, iof:*) from being fabricated as bare nodes here, so the
    # idp:Dataset->prov:Entity root stays correctly ABSENT (the meta-filter
    # discipline holds on the edge side too). Intra-TTL edges (e.g.
    # idp:Dashboard->idp:Dataset, both synced this run) always form;
    # cross-TTL edges form on the run after the parent's partition has
    # synced. Idempotent MERGE — re-runs converge, never duplicate.
    edges_written = 0
    if subclass_edges:
        try:
            neo4j_client.execute_query(
                """
                UNWIND $edges AS e
                MATCH (c:OntologyClass {uri: e.child})
                MATCH (p:OntologyClass {uri: e.parent})
                MERGE (c)-[:subClassOf]->(p)
                """,
                {"edges": subclass_edges},
            )
            edges_written = len(subclass_edges)
        except Exception as e:
            raise Exception(
                f"Neo4j subClassOf MERGE failed for domain '{domain}' "
                f"({len(subclass_edges)} edges): {e}"
            ) from e
        context.log.info(
            f"MERGE'd subClassOf edges (idempotent); {edges_written} "
            f"candidate edge(s) — those whose parent is a synced non-meta "
            f"class landed, meta/cross-partition parents skipped by design."
        )

    # ----- Step 4: verification read (the seam's standing assertion) ------
    # The asset's contract is "TTL classes reach Neo4j." Verify by
    # reading back. This is the analog of the saga's read-back probe.
    #
    # neo4j_client.execute_query (utils/neo4j_client.py) returns a plain
    # list[dict] — NOT a neo4j.Result with a `.records` attribute. The
    # previous code assumed .records and silently swallowed the
    # AttributeError, then logged "readback green" regardless. That made
    # verification a no-op and hid real "merged but absent" cases.
    #
    # The readback also returns the universal-referent property, and the seal
    # below is a PARTITION rather than a presence check: every class the TTL
    # flagged carries it on the node, and every class the TTL did not flag does
    # NOT. A one-sided check ("the flagged ones landed") passes just as happily
    # when the write flagged everything — which is precisely the widening the
    # flag design exists to refuse, and it would be invisible from the flagged
    # side alone.
    verify_uris = [c["uri"] for c in classes]
    expected_flagged = {
        c["uri"] for c in classes if c.get(UNIVERSAL_REFERENT_PROPERTY)
    }
    readback_ok = False
    landed_flagged: set[str] = set()
    try:
        result = neo4j_client.execute_query(
            f"""
            UNWIND $uris AS uri
            OPTIONAL MATCH (c:OntologyClass {{uri: uri}})
            RETURN uri AS asked, c.uri AS landed, c.domain AS domain,
                   c.{UNIVERSAL_REFERENT_PROPERTY} AS universal_referent
            """,
            {"uris": verify_uris},
        )
        missing = [r["asked"] for r in result if r["landed"] is None]
        landed_flagged = {
            r["asked"] for r in result if r.get("universal_referent") is True
        }
        readback_ok = True
    except Exception as e:
        context.log.warning(f"Verification readback failed: {e}")
        missing = []

    if missing:
        raise Exception(
            f"Verification readback found {len(missing)} classes that "
            f"did NOT land in Neo4j despite the MERGE returning. "
            f"Missing: {missing[:5]}{' ...' if len(missing) > 5 else ''}. "
            f"This is the read-back-probe failure mode the v0.2 saga "
            f"introduced for predicate edges; same shape applied here."
        )

    if readback_ok and landed_flagged != expected_flagged:
        raise Exception(
            f"Universal-referent partition broken for domain '{domain}'. "
            f"The TTL flags {sorted(expected_flagged)}; the nodes carry "
            f"{sorted(landed_flagged)}. Missing on the node: "
            f"{sorted(expected_flagged - landed_flagged)}. Carried but NOT "
            f"flagged in the TTL: {sorted(landed_flagged - expected_flagged)}. "
            f"The second list is the dangerous one — a flag that widened past "
            f"the classes that declared it admits every verb to the "
            f"parameterisation pool unscoped, which is the hierarchy design "
            f"mesh:Thing was declared as a FLAG to refuse. See "
            f"UNIVERSAL_REFERENT_PREDICATE at module top."
        )

    if expected_flagged:
        context.log.info(
            f"Universal referent: {len(expected_flagged)} class(es) carry "
            f"{UNIVERSAL_REFERENT_PROPERTY}=true on the node — "
            f"{sorted(expected_flagged)}. The remaining "
            f"{len(classes) - len(expected_flagged)} class(es) in this "
            f"partition carry no such property (absent means false)."
        )

    verify_msg = (
        "Verification readback green."
        if readback_ok
        else "Verification readback was skipped due to a prior error; "
             "see WARNING above."
    )
    context.log.info(
        f"Sync complete. {len(classes)} :OntologyClass nodes "
        f"materialized at full-IRI form for domain '{domain}'. "
        f"{verify_msg}"
    )

    return MaterializeResult(
        metadata={
            "domain": domain,
            "classes_merged": len(classes),
            "universal_referents_merged": len(expected_flagged),
            "universal_referent_uris": sorted(expected_flagged),
            "subclassof_edges_merged": edges_written,
            "s3_path": f"s3://{bucket}/{obj_key}",
            "partition_key": context.partition_key,
            "first_class_uris": [c["uri"] for c in classes[:5]],
            "rule": (
                "Option 3 — TTL→Neo4j is a first-class observable seam; "
                "depends only on ingest_ontology_to_jena. rdflib "
                "extraction + direct MERGE (chosen over n10s after the "
                "Session-2 first attempt revealed three layered "
                "problems). See invincible-agent state doc dated "
                "2026-06-12 for the decision history."
            ),
        }
    )
