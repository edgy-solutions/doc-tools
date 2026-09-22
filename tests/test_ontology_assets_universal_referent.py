"""The universal-referent flag must ride the sync onto the Neo4j node.

THE SEAL (architect, 2026-09-19): *a class carrying the flag in the TTL carries it on the
node; a class without it does not.* Both halves, always -- the second is the one that
matters and the one a presence check cannot see.

WHY THE SECOND HALF IS THE POINT. ``mesh:Thing`` is universal because it carries
``mesh:universalReferent true``, NOT because anything is ``rdfs:subClassOf`` it. That design
was chosen over the hierarchy one deliberately: asserting ~24,000 classes subClassOf a
universal parent for one polymorphic verb's benefit would widen every class-chain query in
the system. A flag written onto every node instead of onto the declaring one recreates
exactly that widening -- and every positive assertion still passes while it happens. So the
seal here is a PARTITION, and the negative arm is a first-class test rather than an
afterthought.

WHY THE FLAG EXISTS AT ALL. ``mesh:explain``'s spoken subject is every class in the graph, so
it has no honest referent among the domain classes. ``owl:Thing`` is the obvious answer and
cannot work: that prefix is in ``_META_ONTOLOGY_IRI_PREFIXES``, so no W3C class is in the
routable pool (0 OntologyClass nodes, measured on the deployed graph 2026-09-19). The
``owl:Thing`` control below asserts that against the filter rather than against a cluster, so
it holds with no cluster and reds if the prefix is ever dropped -- at which point this whole
design wants re-arguing rather than quietly becoming redundant.

HOW THESE TESTS LOAD THE CODE. Same strategy as the response-shape file next door: the real
functions and the real SPARQL are pulled out of the source, so no copy can drift. The write
arm drives the REAL asset with fake resources and inspects what it sent to Neo4j -- the
closest a cluster-free test gets to "carries it on the node". The remaining gap (that Neo4j's
``SET c.p = null`` removes the property) is a documented store semantic, and the live node
read in the 7f handoff closes it against the real substrate.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
import rdflib

_SRC = (pathlib.Path(__file__).resolve().parents[1]
        / "doc_tools" / "assets" / "ontology_assets.py")

MESH = "http://invincible-agent/mesh#"
EX = "http://example.com/ontology#"


def _load(*names: str) -> dict:
    """Exec only the named top-level defs/assigns, so the pure arms need neither
    dagster nor a weaviate client to exercise the real code."""
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    ns: dict = {"rdflib": rdflib}
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


_NS = _load(
    "UNIVERSAL_REFERENT_PREDICATE",
    "UNIVERSAL_REFERENT_PROPERTY",
    "_universal_referent_value",
    "_META_ONTOLOGY_IRI_PREFIXES",
    "_is_meta_ontology_iri",
)
PREDICATE = _NS["UNIVERSAL_REFERENT_PREDICATE"]
PROPERTY = _NS["UNIVERSAL_REFERENT_PROPERTY"]
_value = _NS["_universal_referent_value"]
_is_meta = _NS["_is_meta_ontology_iri"]


def _live_extract_query() -> str:
    """THE query the asset runs, lifted from the source rather than mirrored.

    The blank-node test next door keeps a verbatim copy and a comment asking the
    next person to update it. Reading the assignment out of the AST cannot drift.
    """
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and node.targets
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "extract_query"
                and isinstance(node.value, ast.Constant)):
            return node.value.value
    raise AssertionError("extract_query not found in ontology_assets.py -- renamed?")


_TTL = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix mesh: <%(mesh)s> .
@prefix ex:   <%(ex)s> .

# The declaring class -- the shape mesh_system.ttl uses.
ex:Universal a owl:Class ; rdfs:label "Universal" ;
    mesh:universalReferent true .

# An ordinary domain noun. THE NEGATIVE CONTROL.
ex:Ordinary a owl:Class ; rdfs:label "Ordinary" ;
    rdfs:comment "A perfectly normal class." .

# "false" spelled out. Must be indistinguishable from absent.
ex:ExplicitlyNot a owl:Class ; rdfs:label "Explicitly Not" ;
    mesh:universalReferent false .

# The datatype omitted. A TTL author who writes a plain literal should not
# silently lose the flag.
ex:UntypedTrue a owl:Class ; rdfs:label "Untyped True" ;
    mesh:universalReferent "true" .
""" % {"mesh": MESH, "ex": EX}


def _graph(ttl: str = _TTL) -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    return g


# -- the projection ----------------------------------------------------------

def test_the_live_extract_query_projects_the_flag():
    """Before 2026-09-19 the SELECT was ``?uri ?label ?definition`` and the flag had
    nowhere to ride. A class can be extracted, merged and verified without it."""
    q = _live_extract_query()
    assert "?universal_referent" in q, (
        "the extract query no longer projects the universal-referent binding, so "
        "the flag cannot reach the node no matter what the MERGE says"
    )
    rows = {str(r.uri): r.universal_referent for r in _graph().query(q)}
    assert rows[EX + "Universal"] is not None
    assert rows[EX + "Ordinary"] is None


def test_the_projection_binds_by_the_declared_predicate_iri():
    """``http://invincible-agent/mesh#``, NOT ``http://internal/mesh#``. An unknown
    prefix parses, merges and matches nothing, with nothing red anywhere -- this
    file's namespace is the fourth instance of that class in this codebase."""
    assert str(PREDICATE) == MESH + "universalReferent"
    q = _live_extract_query()
    assert MESH in q, "the extract query no longer declares the mesh: namespace"
    wrong = _graph(_TTL.replace(MESH, "http://internal/mesh#"))
    rows = {str(r.uri): r.universal_referent for r in wrong.query(q)}
    assert rows[EX + "Universal"] is None, (
        "a class declaring the flag under the WRONG namespace was read as flagged -- "
        "the query is matching on the local name, not the IRI"
    )


# -- the value mapping: absent means false -----------------------------------

def test_a_typed_true_is_True():
    assert _value(rdflib.Literal(True)) is True


def test_an_untyped_true_is_True():
    assert _value(rdflib.Literal("true")) is True


def test_absent_is_None_not_False():
    """None, so the Cypher SET removes the property. False would put it on every
    class in the graph to say nothing, and would make "the flag was dropped" and
    "the flag is false" indistinguishable from a read."""
    assert _value(None) is None


def test_an_explicit_false_is_the_same_as_absent():
    assert _value(rdflib.Literal(False)) is None
    assert _value(rdflib.Literal("false")) is None


# -- the write: what the asset actually sends to Neo4j -----------------------

class _Recorder:
    """Stands in for Neo4jClient. Records every (query, params) and answers the
    readback the way a store that honoured the write would."""

    def __init__(self):
        self.calls: list = []
        self.readback_flag_override = None  # None = honest; set to widen/narrow

    def execute_query(self, query, parameters=None, db=None):
        self.calls.append((query, parameters or {}))
        if "OPTIONAL MATCH" in query:
            merged = self.merged_classes()
            flagged = (
                self.readback_flag_override
                if self.readback_flag_override is not None
                else {c["uri"] for c in merged if c.get(PROPERTY)}
            )
            return [
                {"asked": u, "landed": u, "domain": "TEST",
                 "universal_referent": True if u in flagged else None}
                for u in (parameters or {}).get("uris", [])
            ]
        return []

    def merged_classes(self) -> list:
        for q, p in self.calls:
            if "MERGE (c:OntologyClass" in q:
                return p["classes"]
        raise AssertionError(
            "no class MERGE was issued; calls=%s" % [q[:40] for q, _ in self.calls]
        )

    def merge_cypher(self) -> str:
        for q, _ in self.calls:
            if "MERGE (c:OntologyClass" in q:
                return q
        raise AssertionError("no class MERGE was issued")


def _run_sync(ttl: str = _TTL, recorder=None) -> "_Recorder":
    """Drive the REAL asset over ``ttl`` with fake S3 and fake Neo4j."""
    from dagster import build_asset_context
    from dag_tools.components.s3_sensor.file_component import S3FileConfig
    from doc_tools.assets.ontology_assets import sync_jena_ontologies_to_neo4j

    rec = recorder or _Recorder()

    class _S3Client:
        def head_object(self, Bucket, Key):
            return {"Metadata": {}}

        def get_object(self, Bucket, Key):
            class _Body:
                @staticmethod
                def read():
                    return ttl.encode("utf-8")
            return {"Body": _Body()}

    class _S3:
        @staticmethod
        def get_client():
            return _S3Client()

    class _Neo4j:
        @staticmethod
        def get_client():
            return rec

    ctx = build_asset_context(partition_key="mesh__mesh_system.ttl")
    sync_jena_ontologies_to_neo4j(
        context=ctx,
        config=S3FileConfig(
            file_url="s3://ontologies/mesh/mesh_system.ttl",
            extra_metadata={"domain": "MESH"},
        ),
        s3=_S3(),
        neo4j=_Neo4j(),
    )
    return rec


def test_THE_SEAL_flagged_carries_it_unflagged_does_not():
    """The whole ruling, in one assertion over both halves of the partition."""
    merged = {c["uri"]: c[PROPERTY] for c in _run_sync().merged_classes()}

    assert merged[EX + "Universal"] is True, (
        "the class that DECLARES the flag did not carry it to the write"
    )
    assert merged[EX + "UntypedTrue"] is True

    assert merged[EX + "Ordinary"] is None, (
        "an ordinary domain noun was written as a universal referent. Every "
        "positive assertion above still passes while this happens, which is why "
        "it is asserted separately: a flag on every node admits every verb to the "
        "parameterisation pool unscoped -- the hierarchy design mesh:Thing was "
        "declared as a FLAG to refuse."
    )
    assert merged[EX + "ExplicitlyNot"] is None


def test_every_class_carries_the_key_so_a_dropped_flag_is_REMOVED():
    """``SET c.p = cls.p`` with a null value deletes the property in Neo4j. That is
    what makes the flag non-sticky: a TTL that stops declaring it produces a node
    that stops carrying it on the very next sync. Omitting the key for unflagged
    classes instead would leave a stale ``true`` behind forever."""
    merged = _run_sync().merged_classes()
    assert all(PROPERTY in c for c in merged), (
        "some classes were written without the universal-referent key at all -- a "
        "class that LOSES the flag in the TTL would keep it on the node"
    )


def test_the_merge_writes_the_property_the_constant_names():
    """One spelling of the contract. Lane 1's pool leg is told to read
    ``universal_referent``; a MERGE that typed something else would succeed, and the
    read would match nothing, and nothing would go red."""
    cypher = _run_sync().merge_cypher()
    assert "c.%s = cls.%s" % (PROPERTY, PROPERTY) in cypher, (
        "the MERGE does not set c.%s from the extracted value; cypher was:\n%s"
        % (PROPERTY, cypher)
    )


def test_the_partition_seal_REFUSES_a_widened_flag():
    """THE CONTROL ON THE SEAL ITSELF. If the readback shows a class carrying the
    flag that the TTL never declared, the asset must fail -- otherwise the seal is
    a presence check wearing a partition's name and the widening ships green."""
    rec = _Recorder()
    rec.readback_flag_override = {EX + "Universal", EX + "Ordinary"}
    with pytest.raises(Exception) as err:
        _run_sync(recorder=rec)
    assert "universal-referent partition" in str(err.value).lower()
    assert EX + "Ordinary" in str(err.value)


def test_the_partition_seal_REFUSES_a_lost_flag():
    """The other direction: declared in the TTL, absent from the node."""
    rec = _Recorder()
    rec.readback_flag_override = set()
    with pytest.raises(Exception) as err:
        _run_sync(recorder=rec)
    assert "universal-referent partition" in str(err.value).lower()


def test_an_ordinary_sync_with_no_flag_anywhere_still_passes():
    """POSITIVE CONTROL on the seal: 21 of the 22 manifest TTLs declare the flag
    nowhere at all, and the partition (empty == empty) must be SATISFIED, not merely
    un-checked. A seal that only ever ran on the MESH partition would be untested on
    every other one."""
    plain = """
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex:   <%(ex)s> .
    ex:Ordinary a owl:Class ; rdfs:label "Ordinary" .
    """ % {"ex": EX}
    merged = _run_sync(plain).merged_classes()
    assert [c[PROPERTY] for c in merged] == [None]


# -- mesh:Thing itself, and the owl:Thing control ----------------------------

def test_owl_Thing_is_filtered_and_that_is_why_mesh_Thing_exists():
    """THE CONTROL THAT NEEDS NO CLUSTER. Asserted against the filter, not the graph:
    if ``http://www.w3.org/2002/07/owl#`` ever leaves _META_ONTOLOGY_IRI_PREFIXES,
    owl:Thing becomes routable and the reason for declaring a house universal
    referent goes away -- at which point this choice wants re-arguing rather than
    silently becoming redundant."""
    assert _is_meta("http://www.w3.org/2002/07/owl#Thing") is True
    assert _is_meta(MESH + "Thing") is False, (
        "mesh:Thing is being filtered as a meta-ontology term -- it would never "
        "land as a node and the flag would have nothing to ride on"
    )


_SIBLING_TTL = (pathlib.Path(__file__).resolve().parents[2]
                / "invincible-agent" / "setup" / "ontologies" / "mesh_system.ttl")


@pytest.mark.skipif(not _SIBLING_TTL.exists(),
                    reason="sibling invincible-agent checkout absent")
def test_mesh_Thing_survives_every_filter_in_the_real_TTL():
    """The precondition the 7f work order asked to be CONFIRMED before the flag was
    wired: does mesh:Thing land as a node at all? owl:Thing measured zero.

    CROSS-REPO, so it SKIPS rather than reds when the sibling is not checked out.
    That is the honest shape and not a softened assertion: the TTL is
    invincible-agent's master copy and this repo has no business holding a second
    one. The skip reason names the path so a green run cannot be mistaken for a
    measurement.
    """
    g = rdflib.Graph()
    g.parse(_SIBLING_TTL, format="turtle")
    if (rdflib.URIRef(MESH + "Thing"), PREDICATE, None) not in g:
        pytest.skip(
            "%s does not declare mesh:universalReferent -- the sibling checkout "
            "predates f16e2cd (lane/5f)" % _SIBLING_TTL
        )
    rows = {str(r.uri): r for r in g.query(_live_extract_query())}
    assert MESH + "Thing" in rows, "mesh:Thing did not survive the extraction"
    assert _value(rows[MESH + "Thing"].universal_referent) is True
    assert not _is_meta(MESH + "Thing")
    assert list(g.subjects(rdflib.RDFS.subClassOf, rdflib.URIRef(MESH + "Thing"))) == [], (
        "something was declared rdfs:subClassOf mesh:Thing. That is the change that "
        "quietly turns the flag design back into the hierarchy one -- a ratified "
        "superclass over every routable class, for one verb's benefit."
    )
