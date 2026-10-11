"""The MRAD-ARR-0417 walk seal: can SPARQL get from a symptom to a part?

`tests/test_parsers_rdf.py` scores the S1000D builder one module at a time,
which is the right shape for unit tests and cannot see the thing the graph
exists for. This file builds the SIX-module MRAD corpus the way the ingest path
does — one builder per document, each with its own `doc_id`, merged into one
graph — then enters the graph ONLY on the BIT code as a maintainer would type
it, and asks whether SPARQL alone reaches the procedure and the parts list.

Why a corpus and not a fixture string: the load-bearing property is that a
`dmRef` target URI assembled by the REFERRING module equals the subject the
REFERENCED module coins for itself. That is unobservable in a single-module
test — it holds only if both sides go through `assemble_canonical_dmc`, and an
inline join would pass every label assertion in the unit-test file while
leaving the walk returning nothing.

Expectations come from `GROUND-TRUTH.json`, not from literals written here, so
the seal cannot quietly agree with itself. That file is a DRAFT with two open
questions — see the fixtures README.
"""
import json
import pathlib

import pytest
from rdflib import Graph

from doc_tools.parsers.dmc_canonicalizer import canonicalize_dmc
from doc_tools.parsers.s1000d_rdf import S1000dGraphBuilder

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "s1000d" / "mrad"
MIL = "http://edgy-solutions.com/ontology/mil#"

PREFIXES = f"""
PREFIX mil: <{MIL}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""


@pytest.fixture(scope="module")
def ground_truth():
    return json.loads((FIXTURES / "GROUND-TRUTH.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def corpus():
    """All six modules in one graph, each parsed by its OWN builder.

    One builder per document is not incidental: the builders scope part, tool,
    figure, fault-code and item subjects by `doc_id`, so parsing six modules
    through a single builder would hide every cross-document collision this
    corpus is here to detect.
    """
    g = Graph()
    paths = sorted(FIXTURES.glob("DMC-ODMRAD-*.xml"))
    assert len(paths) == 6, f"expected 6 modules, found {len(paths)}"
    for p in paths:
        b = S1000dGraphBuilder(bucket="fixtures", doc_id=p.name)
        b.parse_data_module(p.read_bytes())
        g += b.graph
    return g


def expect_dmc(raw: str) -> str:
    """Normalize a ground-truth DMC through the SAME canonicalizer the writer
    used. Ground truth writes the authored `DMC-...` form; the graph keys the
    canonical form. Without this, a formatting difference between two files
    reads as a disagreement about the data."""
    s = raw[4:] if raw.startswith("DMC-") else raw
    return canonicalize_dmc(s) or s


def dmcs(rows, col=0):
    return sorted({str(r[col]).split("#dmc-")[-1] for r in rows})


def ask(corpus, sparql):
    return list(corpus.query(PREFIXES + sparql))


# --------------------------------------------------------------------------- #
# Entry: the BIT code alone
# --------------------------------------------------------------------------- #
def test_the_bit_code_reaches_exactly_the_fault_isolation_module(corpus, ground_truth):
    rows = ask(corpus, """
      SELECT DISTINCT ?fiDm WHERE {
        ?fc mil:hasFaultCodeValue "%s" .
        ?fiDm mil:hasFaultCode ?fc .
      }""" % ground_truth["bit_code"])
    want = expect_dmc(ground_truth["citations"]["fault_isolation"]["dmc"])
    assert dmcs(rows) == [want]


def test_the_fault_code_carries_its_printed_text(corpus, ground_truth):
    rows = ask(corpus, """
      SELECT ?text WHERE {
        ?fc mil:hasFaultCodeValue "%s" ; mil:hasFaultCodeText ?text .
      }""" % ground_truth["bit_code"])
    assert rows, "the fault code node carries no text"
    got = str(rows[0][0]).lower().rstrip(".")
    assert ground_truth["bit_text"].lower().rstrip(".") in got


# --------------------------------------------------------------------------- #
# The walk
# --------------------------------------------------------------------------- #
def test_the_walk_reaches_the_remove_and_install_procedures(corpus, ground_truth):
    """Typed on BOTH ends. `?procDm a mil:ProcedureDataModule` can only bind if
    the referenced module coined the same subject for itself, which is the
    same-canonicalizer-both-sides property."""
    rows = ask(corpus, """
      SELECT DISTINCT ?procDm WHERE {
        ?fc mil:hasFaultCodeValue "%s" .
        ?fiDm mil:hasFaultCode ?fc ;
              a mil:FaultIsolationDataModule ;
              mil:refersToDataModule ?procDm .
        ?procDm a mil:ProcedureDataModule .
      }""" % ground_truth["bit_code"])
    ri = ground_truth["citations"]["remove_install"]["dmc"]
    want = sorted(expect_dmc(d) for d in (ri if isinstance(ri, list) else [ri]))
    assert dmcs(rows) == want


def test_the_walk_reaches_the_parts_list_and_the_cited_part(corpus, ground_truth):
    """`?icn` and `?hotspot_id` are OPTIONAL on purpose — this is
    load-bearing, do not change either to a required pattern. The real
    corpus has no hotspots at all; a required `?hotspot_id` would take the
    walk from 3 rows to 0 and the seal would read a data absence as a
    broken parser (the same failure mode as the dead-BIT-code trap in
    HANDOFF.md). The ICN comes via the FIGURE, not the item, hence the
    extra `?fig mil:hasCatalogItem ?item` hop."""
    rows = ask(corpus, """
      SELECT DISTINCT ?ipdDm ?pn ?qty ?icn ?hotspot_id WHERE {
        ?fc mil:hasFaultCodeValue "%s" .
        ?fiDm mil:hasFaultCode ?fc ;
              a mil:FaultIsolationDataModule ;
              mil:refersToDataModule ?procDm .
        ?procDm a mil:ProcedureDataModule ;
                mil:refersToDataModule ?ipdDm .
        ?ipdDm a mil:IllustratedPartsDataModule ;
               mil:hasCatalogItem ?item .
        ?item mil:hasPartNumber ?pn ; mil:hasQuantity ?qty .
        OPTIONAL { ?fig mil:hasCatalogItem ?item ; mil:hasICN ?icn . }
        OPTIONAL { ?item mil:hasHotspotId ?hotspot_id . }
      }""" % ground_truth["bit_code"])
    ipd = ground_truth["citations"]["ipd"]
    assert dmcs(rows) == [expect_dmc(ipd["dmc"])]
    pairs = {(str(r[1]), str(r[2])) for r in rows}
    assert (ipd["part_number"], str(ipd["quantity"])) in pairs

    assert len(rows) == 3, f"expected 3 rows, got {len(rows)}"
    want_icn = ground_truth["citations"]["ipd"]["icn"]
    for row in rows:
        assert row[3] is not None, "every real-corpus row should bind ?icn"
        assert str(row[3]) == want_icn

    # The real corpus has NO <hotspot> markup at all (measured 2026-10-02).
    # This records that absence as a tracked fact, not an xfail/skip, so it
    # is expected to change — and should be revisited — the day a
    # hotspot-bearing publication is ingested.
    assert all(row[4] is None for row in rows), (
        "no real-corpus row should bind ?hotspot_id: the MRAD fixture "
        "carries no <hotspot> markup, so a bound value here would mean "
        "either the fixture changed or the join is over-matching"
    )


# --------------------------------------------------------------------------- #
# The planning interval. NOT forward-reachable from the BIT code: the 320
# module names the fault only in PROSE, so it coins no fault-code node. It is
# reachable BACKWARD, through a procedure the isolation module also cites.
# GROUND-TRUTH flags as an open question whether option 4 should cite 320 at
# all, so the reverse hop is asserted as a graph property and NOT as an answer
# to that question.
# --------------------------------------------------------------------------- #
def test_the_planning_interval_is_on_the_cited_module_with_the_cited_value(
    corpus, ground_truth
):
    pi = ground_truth["citations"]["planning_interval"]
    rows = ask(corpus, """
      SELECT DISTINCT ?planDm ?label WHERE {
        ?planDm mil:hasPlanningInterval ?iv . ?iv rdfs:label ?label .
      }""")
    got = {(str(r[0]).split("#dmc-")[-1], str(r[1])) for r in rows}
    assert (expect_dmc(pi["dmc"]), pi["interval"]) in got


def test_the_plan_is_reverse_reachable_from_the_bit_code(corpus, ground_truth):
    pi = ground_truth["citations"]["planning_interval"]
    rows = ask(corpus, """
      SELECT DISTINCT ?planDm WHERE {
        ?fc mil:hasFaultCodeValue "%s" .
        ?fiDm mil:hasFaultCode ?fc ; mil:refersToDataModule ?procDm .
        ?planDm mil:refersToDataModule ?procDm ; mil:hasPlanningInterval ?iv .
      }""" % ground_truth["bit_code"])
    assert dmcs(rows) == [expect_dmc(pi["dmc"])]


# --------------------------------------------------------------------------- #
# Negative controls. A walk that reaches the right answer for the wrong reason
# is not a result, and the brexDmRef leak is the specific wrong reason here.
# --------------------------------------------------------------------------- #
def test_an_unknown_bit_code_reaches_nothing(corpus):
    rows = ask(corpus, """
      SELECT ?x WHERE {
        ?fc mil:hasFaultCodeValue "MRAD-ARR-9999" . ?x mil:hasFaultCode ?fc .
      }""")
    assert rows == []


def test_no_module_cross_references_itself(corpus):
    """Six of the 11 `<dmRef>` elements in this corpus are
    `identAndStatusSection/dmStatus/brexDmRef/dmRef`, and each names its OWN
    module's dmCode. Harvesting `//dmRef` turns all six into self-loops."""
    rows = ask(corpus, "SELECT ?s WHERE { ?s mil:refersToDataModule ?s }")
    assert rows == [], f"{len(rows)} self-loops: brexDmRef leaked into the edges"


def test_the_corpus_has_five_cross_references_not_eleven(corpus):
    """320->520, 320->720, 421->520, 421->720, 720->941. Counted from the XML,
    not from the parser's own output. Eleven would mean the brexDmRef
    self-references were harvested as content edges."""
    rows = ask(corpus, "SELECT ?s ?o WHERE { ?s mil:refersToDataModule ?o }")
    assert len(rows) == 5, f"{len(rows)} cross-reference edges, expected 5"


def test_no_subject_is_named_after_a_loop_index(corpus):
    """`fig-{scope}-fig_0` was named after an enumerate() index, so every
    id-less figure in every document collided on one subject. The IPD figure in
    this corpus has no `id` attribute, so it is the case that regressed."""
    bad = [str(s) for s in set(corpus.subjects()) if "fig_0" in str(s)]
    assert bad == [], f"loop-index subjects: {bad}"
