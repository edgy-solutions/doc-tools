"""Response shapes must not enter the Weaviate grounding pool — and MUST stay in Neo4j.

HISTORY (2026-09-01, measured on a one-cell PROGRAM_FINANCE user at 12/20). ADR-0019
Contract D requires BOTH ends of a verb edge to pre-exist as ``owl:Class``, so every verb's
OUTPUT shape becomes an ``OntologyClass`` — and every ``OntologyClass`` is a candidate in
Engine O's ``/resolve`` grounding pool. A verb's output therefore competes with its own
input subject for the question that invokes it:

    "what is our burn rate"  ->  fin:BurnRateSeries   (no predicate edge: DEAD END)
                             ->  fin:PerformanceMeasurementBaseline -> finBurnRate

Right concept, wrong END of Contract D. Routing dies while ``/resolve`` reports success and
every component is healthy. Two prose fixes were tried and measured first: narrowing the
domain pool did nothing (12/20 both ways), and rewriting all six output definitions to
describe answer STRUCTURE instead of the question moved it only 11 -> 12. The residue is the
class NAME — "Burn Rate Series" will always match "what is our burn rate" — so the fix has
to be structural.

WHY THE FILTER IS ASYMMETRIC, which is the one thing to not "clean up" here.
``_is_meta_ontology_iri`` is deliberately applied to BOTH the Weaviate and Neo4j paths.
This filter is applied to WEAVIATE ONLY, and making it symmetric would take down all of
routing:

  * Contract D refuses a registration whose output class is not an ``:OntologyClass``, so
    filtering Neo4j un-registers every verb at its next registration; and
  * ``find_compatible_verbs`` matches ``(scope)-[r]->(o:OntologyClass)``. With the output
    node gone the pattern does not match and EVERY verb vanishes from the compat walk —
    including verbs whose subjects ground perfectly.

The last test in this file is the guard on exactly that, checked structurally rather than
by grepping for a string, so a mention in a comment cannot satisfy it.

THE LOADING STRATEGY. The neighbouring blank-node test mirrors its SPARQL verbatim and
relies on a comment to keep the copy honest. This file loads the REAL function out of the
source instead, so the copy cannot drift at all — same goal, one fewer thing to remember.
"""
from __future__ import annotations

import ast
import pathlib

import rdflib

_SRC = (pathlib.Path(__file__).resolve().parents[1]
        / "doc_tools" / "assets" / "ontology_assets.py")

MESH = "http://invincible-agent/mesh#"
FIN = "http://invincible-agent/fin#"
IDP = "http://invincible-agent/idp#"


def _load(*names: str) -> dict:
    """Exec only the named top-level defs/assigns, so the test needs neither dagster
    nor a weaviate client to exercise the real code."""
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    ns: dict = {}
    wanted = set(names)
    for node in tree.body:
        got = None
        if isinstance(node, ast.FunctionDef):
            got = node.name
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            got = node.target.id
        elif isinstance(node, ast.Assign) and node.targets and isinstance(node.targets[0], ast.Name):
            got = node.targets[0].id
        if got in wanted:
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(_SRC), "exec"), ns)
    missing = wanted - set(ns)
    assert not missing, f"could not load {missing} from {_SRC.name}"
    return ns


_NS = _load("_RESPONSE_SHAPE_ROOTS", "response_shape_uris")
_response_shape_uris = _NS["response_shape_uris"]


def _graph(ttl: str) -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    return g


_TTL = f"""
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix mesh: <{MESH}> .
@prefix fin:  <{FIN}> .
@prefix idp:  <{IDP}> .

mesh:Response  a owl:Class .
mesh:Archetype a owl:Class .

# --- response shapes: what a verb PRODUCES ---
fin:BurnRateSeries a owl:Class ; rdfs:subClassOf mesh:Response ;
    rdfs:label "Burn Rate Series" .
fin:FundingStatusGrid a owl:Class ; rdfs:subClassOf mesh:Response .
# transitive: a refinement of a response is still a response
fin:MonthlyBurnRateSeries a owl:Class ; rdfs:subClassOf fin:BurnRateSeries .

# --- an archetype: a presentation shape, also never a subject ---
mesh:TimeSeriesChart a owl:Class ; rdfs:subClassOf mesh:Archetype .

# --- domain nouns: what a user ACTUALLY asks about ---
fin:PerformanceMeasurementBaseline a owl:Class ; rdfs:label "PMB" .
idp:Portfolio a owl:Class .
# no verb, but a drill-down referent the variance tree needs resolvable
fin:WorkPackage a owl:Class .
"""


def test_response_shapes_are_identified():
    got = _response_shape_uris(_graph(_TTL))
    assert FIN + "BurnRateSeries" in got
    assert FIN + "FundingStatusGrid" in got


def test_the_identification_is_TRANSITIVE():
    """A refinement of a response shape is still an answer, not a question."""
    assert FIN + "MonthlyBurnRateSeries" in _response_shape_uris(_graph(_TTL))


def test_archetypes_are_identified_too():
    assert MESH + "TimeSeriesChart" in _response_shape_uris(_graph(_TTL))


def test_domain_nouns_SURVIVE():
    """THE NEGATIVE CONTROL. fin:PerformanceMeasurementBaseline is the class
    "what is our burn rate" is supposed to ground to; removing it would replace the bug
    with a worse one."""
    got = _response_shape_uris(_graph(_TTL))
    assert FIN + "PerformanceMeasurementBaseline" not in got
    assert IDP + "Portfolio" not in got


def test_a_NO_VERB_BY_DESIGN_referent_survives():
    """fin:WorkPackage has no verb and IS a drill-down referent the variance tree needs
    resolvable. The rule is `exists only as a response shape -> filter`, and must never
    become `has no verb -> filter`."""
    assert FIN + "WorkPackage" not in _response_shape_uris(_graph(_TTL))


def test_the_roots_themselves_are_not_swept_up():
    """`subClassOf+` is strict, so mesh:Response is not a subclass of itself. If the roots
    were caught, they would stop being resolvable as the abstract classes they are."""
    got = _response_shape_uris(_graph(_TTL))
    assert MESH + "Response" not in got
    assert MESH + "Archetype" not in got


def test_an_empty_or_broken_graph_filters_NOTHING():
    """Degraded, never destructive: a graph with no response declarations must return an
    empty set (filter nothing), not raise and not swallow the sync."""
    assert _response_shape_uris(_graph("@prefix owl: <http://www.w3.org/2002/07/owl#> .")) == set()


def test_the_filter_is_NOT_applied_to_the_Neo4j_sync():
    """THE ASYMMETRY GUARD, and the most important test here.

    Checked on the AST rather than by grepping the file: a substring search cannot tell
    code from the long comment above that explains why the code must not exist, so it
    would pass on the prose it is supposed to be policing.
    """
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    target = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "sync_jena_ontologies_to_neo4j"),
        None,
    )
    assert target is not None, "sync_jena_ontologies_to_neo4j not found — did it get renamed?"
    used = {
        n.id for n in ast.walk(target) if isinstance(n, ast.Name)
    } | {
        kw.arg for n in ast.walk(target) if isinstance(n, ast.Call) for kw in n.keywords
    }
    leaked = used & {"response_shape_uris", "response_shapes", "_RESPONSE_SHAPE_ROOTS"}
    assert not leaked, (
        "the response-shape filter has been applied to the Neo4j sync: "
        f"{sorted(leaked)}. Neo4j MUST keep response shapes as :OntologyClass nodes — "
        "Contract D refuses registrations whose output class is missing, and "
        "find_compatible_verbs matches (scope)-[r]->(o:OntologyClass), so removing the "
        "output node deletes EVERY verb from the compat walk."
    )
