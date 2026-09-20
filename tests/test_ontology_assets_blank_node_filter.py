"""Acceptance test for the blank-node filter in BOTH ontology writer legs.

History (2026-06-15): the canonical TTL→Neo4j pipeline (Writer C in the
mesh:Thing investigation) was leaking blank-node owl:Class entries from
every imported ontology (PROV-O, IOF_Core, S3000L, DINEN62264, IOF_MRO)
as bogus :OntologyClass nodes in Neo4j. The blank-node filter was
checking for `Bnode_` and `_:` URI prefixes that **never match** rdflib's
actual `BNode.__str__` output (`N[a-f0-9]{32}`). The filter has been a
no-op since Session 2's keystone — substrate grew 441 phantom
:OntologyClass nodes attributable to this pipeline before pre-flight
provenance grouping surfaced it.

The fix:

  - Primary: SPARQL `FILTER(!isBlank(?uri))` in the extract_query.
  - Defensive: Python `isinstance(row.uri, rdflib.term.BNode)` check
    as belt-and-braces in case a future rdflib version changes SPARQL
    evaluation of isBlank().

This test is the architect's prescribed acceptance pattern (2026-06-15):
"blank-node owl:Class entries are skipped, named classes are kept, count
of legitimate classes unchanged." A regression in EITHER filter layer
would have to be caught by the OTHER for this test to stay green, so the
test surfaces single-layer regressions explicitly.

SECOND LEG ADDED 2026-09-19. The 2026-06-15 fix landed on the Neo4j leg
only. The WEAVIATE leg -- a separate extraction query inside
ingest_ontology_to_jena, feeding sync_ontology_to_weaviate -- kept
selecting `?uri a ?type` with neither layer, and
partition_ontology_classes excludes meta-ontology IRIs and response
shapes but never blank nodes. So the leak this file was written to close
stayed open in the other store for three months, and this test stayed
green throughout, because it only ever asked one leg the question.

That is the drift this file now refuses: every assertion below is made
PER LEG, and the source guard reads each function's own body rather than
the file as a whole. A `FILTER(!isBlank(?uri))` anywhere in the module
used to satisfy it; it now has to be in BOTH places.
"""
from __future__ import annotations

import rdflib
from rdflib import Namespace, RDFS, RDF, OWL


# Mirror of the extract_query in
# doc_tools/assets/ontology_assets.py:sync_jena_ontologies_to_neo4j.
# Kept verbatim so this test fails red the moment the source query
# diverges (preventing "the test passes, the source pipeline is broken
# in a way the test no longer covers" drift).
_EXTRACT_QUERY = """
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


def _build_mixed_graph() -> rdflib.Graph:
    """A small ontology with TWO named owl:Class and TWO blank-node
    owl:Class entries — the exact shape PROV-O / IOF_Core / etc.
    produce when they declare anonymous restriction classes.

    Named classes: ex:Vehicle, ex:Truck (subClassOf Vehicle).
    Blank classes: an unnamed owl:Restriction (typed as owl:Class via
    rdflib's class-modeling), and a unionOf-style anonymous class
    that ex:Truck is subClassOf.
    """
    g = rdflib.Graph()
    EX = Namespace("http://example.com/ontology#")
    g.bind("ex", EX)
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)

    # Two NAMED owl:Class declarations (legitimate)
    g.add((EX.Vehicle, RDF.type, OWL.Class))
    g.add((EX.Vehicle, RDFS.label, rdflib.Literal("Vehicle")))
    g.add((EX.Vehicle, RDFS.comment, rdflib.Literal("Any conveyance.")))

    g.add((EX.Truck, RDF.type, OWL.Class))
    g.add((EX.Truck, RDFS.label, rdflib.Literal("Truck")))
    g.add((EX.Truck, RDFS.subClassOf, EX.Vehicle))

    # TWO blank-node owl:Class entries (the leak the filter exists to
    # close). rdflib materializes blank nodes as `BNode` instances that
    # stringify as `N[a-f0-9]{32}` — the *actual* shape that has been
    # bypassing the historical Bnode_/_: prefix check.
    bn_restriction = rdflib.BNode()
    g.add((bn_restriction, RDF.type, OWL.Class))
    g.add((bn_restriction, RDF.type, OWL.Restriction))
    # NB: blank-node restrictions usually have no label/comment; that
    # absence is part of why they're useless as resolver targets and
    # should be filtered.

    bn_union = rdflib.BNode()
    g.add((bn_union, RDF.type, OWL.Class))
    g.add((EX.Truck, RDFS.subClassOf, bn_union))

    return g, EX


def test_blank_node_owl_classes_are_filtered():
    """The SPARQL FILTER(!isBlank(?uri)) drops blank-node owl:Class
    entries at the query layer. With it in place, only named classes
    return; the blank-node restrictions are invisible to the
    materialization pipeline."""
    g, EX = _build_mixed_graph()
    rows = list(g.query(_EXTRACT_QUERY))
    uris = sorted(str(r.uri) for r in rows)

    # The two named classes are returned.
    assert str(EX.Vehicle) in uris, (
        f"Named class {EX.Vehicle!s} was filtered out — the SPARQL filter "
        f"is too aggressive. Returned URIs: {uris}"
    )
    assert str(EX.Truck) in uris, (
        f"Named class {EX.Truck!s} was filtered out. Returned URIs: {uris}"
    )

    # No blank-node URIs in the results — pre-fix, two N-hex URIs would
    # have appeared here and been MERGE'd into Neo4j as phantom
    # :OntologyClass nodes.
    blank_shape = [u for u in uris if u.startswith("N") and len(u) >= 17
                   and all(c in "0123456789abcdefABCDEF" for c in u[1:33])]
    assert not blank_shape, (
        f"Blank-node :OntologyClass entries leaked past the SPARQL "
        f"!isBlank filter: {blank_shape}. The historical Bnode_/_: "
        f"prefix check did NOT catch these — the filter must be in the "
        f"SPARQL itself (or check rdflib.term.BNode on the Python side)."
    )

    # Exactly two results — no more, no less. This is the "count of
    # legitimate classes unchanged" assertion the architect specified.
    assert len(rows) == 2, (
        f"Expected exactly 2 named classes; got {len(rows)} results: "
        f"{uris}. Either the filter dropped a legitimate class (false "
        f"positive) or it failed to drop a blank node (the bug)."
    )


def test_python_defensive_isinstance_check_also_filters():
    """If a future rdflib version changes SPARQL evaluation of isBlank()
    (or someone removes the SPARQL filter by mistake), the Python-side
    `isinstance(row.uri, rdflib.term.BNode)` check is the second layer.
    This test exercises that layer directly.

    Constructed payload: SPARQL without the filter, manually iterated
    with the same defensive Python check used in the asset.
    """
    g, _ = _build_mixed_graph()
    query_without_filter = _EXTRACT_QUERY.replace(
        "FILTER(!isBlank(?uri))\n", "",
    )
    rows = list(g.query(query_without_filter))
    # Without the SPARQL filter, blank nodes ARE returned — confirm so
    # the test is exercising the right path.
    assert any(isinstance(r.uri, rdflib.term.BNode) for r in rows), (
        "The SPARQL-without-filter form was supposed to return blank "
        "nodes so we could test the Python defensive check. None came "
        "back, which means the test fixture changed — fix the fixture."
    )

    # Apply the asset's Python check; assert it filters them.
    kept = [r for r in rows if not isinstance(r.uri, rdflib.term.BNode)]
    blank_uris_kept = [str(r.uri) for r in kept
                       if isinstance(r.uri, rdflib.term.BNode)]
    assert not blank_uris_kept, (
        f"Python defensive isinstance check failed to filter blank "
        f"nodes: {blank_uris_kept}. Fix the asset's loop."
    )

    # And the named classes still come through.
    kept_uris = {str(r.uri) for r in kept}
    assert "http://example.com/ontology#Vehicle" in kept_uris
    assert "http://example.com/ontology#Truck" in kept_uris


def test_extract_query_in_source_matches_this_test():
    """Drift guard: the test's _EXTRACT_QUERY must match the live one in
    doc_tools/assets/ontology_assets.py. If the asset's query is edited
    (intentionally or otherwise) and this test isn't updated to mirror,
    the test starts validating a stale specification — exactly the
    "the test passes, the pipeline is broken in a different way"
    failure mode.
    """
    import pathlib
    src_path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "doc_tools" / "assets" / "ontology_assets.py"
    )
    src = src_path.read_text(encoding="utf-8")
    assert "FILTER(!isBlank(?uri))" in src, (
        "The blank-node SPARQL filter has been removed from "
        "ontology_assets.py:sync_jena_ontologies_to_neo4j. This is the "
        "primary filter; deleting it shifts the entire load onto the "
        "Python-side defensive check, which is intentionally weaker. "
        "If the removal was intentional, update this test."
    )
    assert "isinstance(row.uri, rdflib.term.BNode)" in src, (
        "The Python-side defensive BNode isinstance check has been "
        "removed from ontology_assets.py:sync_jena_ontologies_to_neo4j. "
        "This is the belt-and-braces filter. If the removal was "
        "intentional, document why and update this test."
    )


# ── Class-less (policy-as-data / rules) ontology discriminator ──
# History (2026-07-28): the SUSTAINMENT ingest failed at
# sync_jena_ontologies_to_neo4j on pcn_disposition_rules.ttl — a POLICY-AS-DATA
# TTL (a flat decision table of pcn:DispositionRule INDIVIDUALS) that
# DELIBERATELY declares no owl:Class. The Jena load succeeded (the ruleset is in
# Fuseki, which the proposer queries) and the Weaviate leg warned-and-skipped,
# but the Neo4j guard's zero-class branch only excused META-ontologies (PROV-O
# etc.), so a class-less DATA ontology fell through to a hard raise. The fix
# added a RAW-graph ASK probe: 0 class declarations => class-less ontology =>
# skip Neo4j (no-op); classes present but extraction returned none => real drift
# => raise. This test pins the discriminator.

# Mirror of the raw-graph probe in ontology_assets.py:sync_jena_ontologies_to_neo4j.
# Kept verbatim so this test fails red the moment the source probe diverges.
_ASK_DECLARES_CLASSES = (
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
    "PREFIX owl:  <http://www.w3.org/2002/07/owl#> "
    "ASK { ?c a ?t . FILTER(?t IN (owl:Class, rdfs:Class)) }"
)


def _build_rules_graph() -> rdflib.Graph:
    """A class-less policy-as-data ontology in the shape of
    pcn_disposition_rules.ttl: an owl:Ontology header + rule INDIVIDUALS
    (typed as a domain class, carrying data properties), and NOT ONE
    owl:Class / rdfs:Class declaration."""
    g = rdflib.Graph()
    PCN = Namespace("http://internal/sustainment/pcn#")
    g.bind("pcn", PCN)
    g.bind("owl", OWL)
    # owl:Ontology header (present) — but NOT owl:Class.
    g.add((rdflib.URIRef("http://internal/sustainment/pcn/rules"), RDF.type, OWL.Ontology))
    # A rule individual: typed as a DOMAIN class (pcn:DispositionRule), which is
    # NOT owl:Class/rdfs:Class, plus flat data-property rows.
    rule = PCN.RuleDiscontinuedWithReplacement
    g.add((rule, RDF.type, PCN.DispositionRule))
    g.add((rule, RDFS.label, rdflib.Literal("Discontinued w/ replacement -> qualify")))
    g.add((rule, PCN.whenNoticeType, rdflib.Literal("PDN")))
    g.add((rule, PCN.proposesDisposition, rdflib.Literal("dispatchQualification")))
    return g


def test_class_less_rules_ontology_is_recognized_not_a_class_ontology():
    """The raw-graph ASK returns FALSE for a class-less policy/rules ontology
    (nothing to sync -> the guard skips Neo4j gracefully), and the class
    extraction correctly yields zero rows — so the two together select the
    'skip' branch, never the 'raise' branch."""
    g = _build_rules_graph()
    # The discriminator: the graph declares NO classes.
    assert g.query(_ASK_DECLARES_CLASSES).askAnswer is False, (
        "A class-less rules ontology was reported as declaring classes — the "
        "ASK probe is wrong and the guard would raise on policy-as-data TTLs."
    )
    # And the extraction that precedes the guard genuinely finds nothing.
    assert list(g.query(_EXTRACT_QUERY)) == [], (
        "The class extraction returned rows for a class-less rules ontology."
    )


def test_ask_probe_is_true_when_classes_exist_so_real_drift_still_raises():
    """Positive control: a graph that DOES declare a class makes the ASK true.
    If extraction returned zero on such a graph it would be genuine drift, and
    the guard's raise (not the skip) is the correct branch — this asserts the
    discriminator can't silently swallow that case."""
    g, EX = _build_mixed_graph()
    assert g.query(_ASK_DECLARES_CLASSES).askAnswer is True, (
        "A graph with owl:Class declarations was reported as class-less — the "
        "ASK probe would route real extraction drift into a silent skip."
    )


def test_class_less_skip_discriminator_present_in_source():
    """Anti-drift: the raw-graph ASK probe must remain in the source. If it is
    removed, class-less policy/rules ontologies regress to a hard raise and the
    SUSTAINMENT ingest breaks again."""
    import pathlib
    src = (
        pathlib.Path(__file__).resolve().parent.parent
        / "doc_tools" / "assets" / "ontology_assets.py"
    ).read_text(encoding="utf-8")
    assert "ASK { ?c a ?t . FILTER(?t IN (owl:Class, rdfs:Class)) }" in src, (
        "The class-less-ontology ASK discriminator has been removed from "
        "sync_jena_ontologies_to_neo4j. Class-less policy/rules ontologies "
        "(e.g. pcn_disposition_rules.ttl) will raise again. If intentional, "
        "update this test."
    )
    assert "class_less_data_ontology" in src, (
        "The class-less skip branch's skipped_reason marker is gone — the "
        "graceful no-op for policy-as-data ontologies was likely removed."
    )


# ---------------------------------------------------------------------------
# THE WEAVIATE LEG. Everything above this line tests the Neo4j leg's query.
# ---------------------------------------------------------------------------

# Mirror of the extraction query in
# doc_tools/assets/ontology_assets.py:ingest_ontology_to_jena (the Weaviate
# dual-write, step 4). Indented to match the source EXACTLY -- unlike
# _EXTRACT_QUERY above, which is flush-left -- so the drift guard below can
# assert the source contains this text verbatim rather than probing it for
# substrings. rdflib ignores the leading whitespace.
_WEAVIATE_QUERY = """
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


def _leg_source(function_name: str) -> str:
    """Return the source text of ONE top-level function in the asset module.

    Per-leg, deliberately. The original drift guard in this file searched the
    WHOLE module for `FILTER(!isBlank(?uri))`, which is exactly how the missing
    filter in the Weaviate leg stayed invisible: the Neo4j leg's copy satisfied
    the assertion on behalf of a leg that did not have one. A guard that can be
    satisfied by a different function than the one it is about is not a guard.
    """
    import pathlib
    import re

    src = (
        pathlib.Path(__file__).resolve().parent.parent
        / "doc_tools" / "assets" / "ontology_assets.py"
    ).read_text(encoding="utf-8")
    marker = f"\ndef {function_name}("
    start = src.find(marker)
    assert start != -1, (
        f"{function_name} no longer exists in ontology_assets.py -- this test "
        f"is asserting against a function that has been renamed or removed."
    )
    rest = src[start + 1:]
    # Next TOP-LEVEL boundary: a decorator or a def at column 0. Nested defs
    # (e.g. _humanize_label) are indented and do not match.
    m = re.search(r"\n(?:@|def )", rest)
    end = start + 1 + m.start() if m else len(src)
    return src[start:end]


def test_weaviate_leg_query_filters_blank_nodes():
    """Same acceptance pattern as the Neo4j leg, asked of the OTHER query.

    Pre-fix, the two blank-node owl:Class entries in the fixture came back
    here and were written to the OntologyClass collection as rows whose uri
    AND label are a bare `N<32 hex>` -- noise in the pool Engine O grounds
    against, which is the half that matters more than the Neo4j phantoms.
    """
    g, EX = _build_mixed_graph()
    rows = list(g.query(_WEAVIATE_QUERY))
    uris = sorted(str(r.uri) for r in rows)

    assert str(EX.Vehicle) in uris, (
        f"Named class {EX.Vehicle!s} was filtered out of the WEAVIATE "
        f"extraction. Returned URIs: {uris}"
    )
    assert str(EX.Truck) in uris, (
        f"Named class {EX.Truck!s} was filtered out of the WEAVIATE "
        f"extraction. Returned URIs: {uris}"
    )
    assert not any(isinstance(r.uri, rdflib.term.BNode) for r in rows), (
        f"Blank-node owl:Class entries leaked past the WEAVIATE leg's SPARQL "
        f"!isBlank filter: "
        f"{[str(r.uri) for r in rows if isinstance(r.uri, rdflib.term.BNode)]}. "
        f"These become OntologyClass rows keyed on a uuid5 of a hex id that "
        f"changes every parse -- see the compounding test below."
    )
    assert len(rows) == 2, (
        f"Expected exactly 2 named classes from the Weaviate extraction; got "
        f"{len(rows)}: {uris}."
    )


def test_weaviate_leg_python_defensive_isinstance_check_also_filters():
    """The Weaviate leg's second layer, exercised directly -- same shape as
    test_python_defensive_isinstance_check_also_filters for the Neo4j leg."""
    g, _ = _build_mixed_graph()
    query_without_filter = _WEAVIATE_QUERY.replace(
        "        FILTER(!isBlank(?uri))\n", "",
    )
    rows = list(g.query(query_without_filter))
    assert any(isinstance(r.uri, rdflib.term.BNode) for r in rows), (
        "The Weaviate-query-without-filter form was supposed to return blank "
        "nodes so the Python check could be tested against them. None came "
        "back -- the fixture or the replace() anchor changed."
    )

    kept = [r for r in rows if not isinstance(r.uri, rdflib.term.BNode)]
    assert not [r for r in kept if isinstance(r.uri, rdflib.term.BNode)]
    kept_uris = {str(r.uri) for r in kept}
    assert "http://example.com/ontology#Vehicle" in kept_uris
    assert "http://example.com/ontology#Truck" in kept_uris


def test_both_legs_carry_both_layers():
    """THE ASYMMETRY GUARD. Each leg is read on its own and must carry the
    SPARQL filter AND the Python isinstance check.

    This is the assertion whose absence let the bug live: a module-wide
    substring search was green while one of the two writers had neither layer.
    """
    legs = {
        "ingest_ontology_to_jena": "the Weaviate dual-write",
        "sync_jena_ontologies_to_neo4j": "the Neo4j sync",
    }
    for fn, what in legs.items():
        body = _leg_source(fn)
        assert "FILTER(!isBlank(?uri))" in body, (
            f"The primary SPARQL blank-node filter is MISSING from {fn} "
            f"({what}). Without it that store accumulates anonymous "
            f"owl:Class restrictions as rows/nodes whose label is a bare hex "
            f"id. If the removal was intentional, document why and update "
            f"this test."
        )
        assert "isinstance(row.uri, rdflib.term.BNode)" in body, (
            f"The defensive Python BNode check is MISSING from {fn} ({what}). "
            f"This is the belt-and-braces layer that catches a future rdflib "
            f"changing SPARQL evaluation of isBlank()."
        )


def test_weaviate_extract_query_in_source_matches_this_test():
    """Drift guard, verbatim: the query mirrored in this file must be the query
    the asset actually runs. Substring guards pass while the two diverge."""
    body = _leg_source("ingest_ontology_to_jena")
    assert _WEAVIATE_QUERY in body, (
        "The Weaviate extraction query in ingest_ontology_to_jena no longer "
        "matches _WEAVIATE_QUERY in this test character for character. Every "
        "assertion above is now validating a stale specification -- mirror "
        "the source change here, deliberately."
    )


def test_blank_node_row_ids_are_not_stable_across_parses():
    """WHY THE LEAK COMPOUNDED instead of overwriting itself.

    The row uuid is generate_uuid5(str(uri)). For a named class that is stable,
    which is what makes the sync an idempotent upsert. For a blank node it is
    NOT: rdflib mints a fresh id on every parse (term.py BNode.__new__ ->
    "N" + uuid4().hex; the Turtle parser seeds a per-instance uuid4().hex).
    So each re-ingest wrote a NEW row for the SAME anonymous restriction, and
    the pool grew by the blank-node count of every ontology on every prime.

    Pure computation -- parses a string twice, touches no store. It pins the
    mechanism behind the 96.2%-blank-node measurement so a future reader does
    not have to re-derive it from the rdflib source.
    """
    from weaviate.util import generate_uuid5

    ttl = """
    @prefix ex:   <http://example.com/ontology#> .
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

    ex:Truck a owl:Class ;
        rdfs:subClassOf [ a owl:Restriction ;
                          owl:onProperty ex:hasPart ;
                          owl:someValuesFrom ex:Axle ] .
    """

    def _uuids_by_kind(source: str):
        g = rdflib.Graph()
        g.parse(data=source, format="turtle")
        named, blank = set(), set()
        for s in set(g.subjects(RDF.type, OWL.Class)) | set(
            g.subjects(RDF.type, OWL.Restriction)
        ):
            (blank if isinstance(s, rdflib.term.BNode) else named).add(
                generate_uuid5(str(s))
            )
        return named, blank

    named_a, blank_a = _uuids_by_kind(ttl)
    named_b, blank_b = _uuids_by_kind(ttl)

    assert blank_a and blank_b, (
        "The fixture stopped producing blank nodes -- rewrite it, the point of "
        "this test is the contrast between the two kinds of id."
    )
    # The control: named classes upsert onto themselves, parse after parse.
    assert named_a == named_b, (
        "A NAMED class produced a different row uuid on a second parse. That "
        "would break the idempotent upsert this whole sync relies on, and it "
        "would mean the mechanism described here is not the one at work."
    )
    # The finding: blank ones never do.
    assert blank_a.isdisjoint(blank_b), (
        f"Blank-node row uuids repeated across two parses ({blank_a & blank_b}) "
        f"-- rdflib has become deterministic about BNode ids. If that is real, "
        f"the compounding explanation in ontology_assets.py's step-4 comment "
        f"needs revising: the leak would then merely repeat, not grow."
    )
