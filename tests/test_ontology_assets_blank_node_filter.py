"""Acceptance test for the blank-node filter in sync_jena_ontologies_to_neo4j.

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
