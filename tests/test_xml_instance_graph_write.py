"""The second RDF write on the XML path: content triples into the DOMAIN
instance graph (architect ruling 2026-10-16).

No network. The real ``upload_to_jena`` body runs against a fake JenaResource
whose ``get_client()`` returns a stub that captures the update, and a stubbed
``httpx.Client`` for the primary ``urn:doc:`` PUT. The input is a real fixture
(the 421A module carries the fault-code content), not a hand-written snippet.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rdflib import Dataset, Graph

from doc_tools.assets import semantic_assets, xml_ingestion
from doc_tools.parsers.s1000d_rdf import S1000dGraphBuilder
from doc_tools.utils import jena_client
from doc_tools.utils.content_kind import domain_label_for_kind

FIXTURE = (
    Path(__file__).parent / "fixtures" / "s1000d" / "mrad"
    / "DMC-ODMRAD-A-34-10-01-00A-421A-A_001-00_EN-US.xml"
)
INSTANCE_GRAPH = "http://internal/MAINTENANCE_INSTANCES"


class _StubClient:
    def __init__(self):
        self.calls = []

    def execute_update(self, query, graph_uri=None):
        self.calls.append((query, graph_uri))


class _FakeJena:
    url = "http://jena.invalid"
    dataset = "ds"
    username = "u"
    password = "p"

    def __init__(self):
        self.client = _StubClient()

    def get_client(self):
        return self.client


class _FakeHttpx:
    """Stands in for httpx.Client in the primary PUT."""

    puts = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def put(self, url, content=None, headers=None):
        _FakeHttpx.puts.append(url)
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        return resp


def _build(path: Path = FIXTURE):
    """Build a module the way production does, returning what the asset gets.

    ``doc_id`` is the EXACT production derivation (xml_ingestion.py:232 --
    ``os.path.splitext(basename)[0]``), not a hand-shortened "421A". That
    matters for the supersede: with the real doc_id the slug
    ("DMC-ODMRAD-A-34-10-01-00A-421A-A_001-00_EN-US") does NOT appear in the
    module's own subject ("mil:dmc-ODMRAD-A-34-10-01-00A-421A-A"), so the two
    legs of the DELETE filter are genuinely independent -- which is the
    production shape. A shortened "421A" would be a substring of both and
    would quietly make one leg look redundant.
    """
    doc_id = path.stem
    b = S1000dGraphBuilder(doc_id=doc_id)
    root_uri = b.parse_data_module(path.read_bytes())
    return b.serialize(format="turtle"), str(root_uri), b.doc_slug


def _rdf_string() -> str:
    return _build()[0]


def _run(monkeypatch, extract: dict):
    jena = _FakeJena()
    _FakeHttpx.puts = []
    monkeypatch.setattr(semantic_assets.httpx, "Client", _FakeHttpx)
    fn = semantic_assets.upload_to_jena.op.compute_fn.decorated_fn
    ctx = MagicMock()
    fn(ctx, extract, jena)
    return jena, ctx


def _extract(**over) -> dict:
    rdf_string, root_uri, doc_slug = _build()
    d = {
        "rdf_string": rdf_string,
        "root_uri": root_uri,
        "s3_key": "ingress-user/s1000d-data-module/abc/421A.xml",
        "chunks": [],
        "domain": "MAINTENANCE",
        "content_kind": "s1000d-data-module",
        "doc_id": FIXTURE.stem,
        "doc_slug": doc_slug,
    }
    d.update(over)
    return d


def test_kind_label_agrees_with_prefix_constant():
    assert domain_label_for_kind("s1000d-data-module") == "MAINTENANCE"
    assert domain_label_for_kind("s1000d-data-module") == xml_ingestion._XML_INGEST_DOMAIN
    assert domain_label_for_kind("no-such-kind") is None


def test_body_targets_instances_graph_only(monkeypatch):
    jena, _ = _run(monkeypatch, _extract())
    ((body, graph_uri),) = jena.client.calls
    assert graph_uri == INSTANCE_GRAPH
    assert f"<{INSTANCE_GRAPH}>" in body
    # exact <...> form: the _INSTANCES name must not satisfy this by substring
    assert "<http://internal/MAINTENANCE>" not in body
    assert jena_client.update_is_graph_scoped(body)


def test_body_supersedes_and_never_drops_the_shared_graph(monkeypatch):
    """Architect ruling 2 (2026-10-17): DMC-keyed supersede, not a bare insert.

    Replaces the former ``test_body_is_additive``. The additive contract was
    deliberately broken: a module can be re-dropped with new bytes, so the
    graph must hold the CURRENT state of the module, not the union of every
    version ever dropped.
    """
    extract = _extract()
    jena, _ = _run(monkeypatch, extract)
    body = jena.client.calls[0][0]
    assert body.startswith("DELETE")
    assert "INSERT DATA" in body
    # The delete is SCOPED. A whole-graph wipe would take the sibling modules,
    # which share this graph -- that is the failure this must never become.
    for word in ("DROP", "CLEAR"):
        assert word not in body.upper()
    assert "DELETE WHERE" not in body.upper()
    # Both legs of the scope, and they are independent strings in production.
    assert f"<{extract['root_uri']}>" in body
    assert f'"-{extract["doc_slug"]}-"' in body
    assert extract["doc_slug"] not in extract["root_uri"]


def test_supersede_is_a_single_atomic_request(monkeypatch):
    """One request, so Fuseki applies it in one transaction.

    Issued as two calls, a DELETE that commits and an INSERT that then fails
    would leave the module with NO triples -- strictly worse than the
    duplication being fixed.
    """
    jena, _ = _run(monkeypatch, _extract())
    assert len(jena.client.calls) == 1
    body, graph_uri = jena.client.calls[0]
    assert body.count("DELETE") == 1
    assert body.count("INSERT DATA") == 1
    assert " ;\n" in body
    assert body.index("DELETE") < body.index("INSERT DATA")
    # and it still ships byte-for-byte (already self-scoped, never re-wrapped)
    assert jena_client.update_is_graph_scoped(body)
    assert graph_uri == INSTANCE_GRAPH


def test_idempotent_and_byte_stable(monkeypatch):
    extract = _extract()
    jena1, _ = _run(monkeypatch, extract)
    jena2, _ = _run(monkeypatch, extract)
    body1 = jena1.client.calls[0][0]
    assert body1 == jena2.client.calls[0][0]

    src = Graph()
    src.parse(data=extract["rdf_string"], format="turtle")
    ds = Dataset()
    ds.update(body1)
    first = len(ds.graph(INSTANCE_GRAPH))
    ds.update(body1)
    second = len(ds.graph(INSTANCE_GRAPH))
    print(f"MEASURED triples source={len(src)} after_1={first} after_2={second}")
    assert first == second == len(src) > 0


def test_missing_domain_raises_and_never_calls_client(monkeypatch):
    extract = _extract()
    del extract["domain"]
    jena = _FakeJena()
    monkeypatch.setattr(semantic_assets.httpx, "Client", _FakeHttpx)
    fn = semantic_assets.upload_to_jena.op.compute_fn.decorated_fn
    ctx = MagicMock()
    with pytest.raises(ValueError):
        fn(ctx, extract, jena)
    assert jena.client.calls == []
    ctx.log.error.assert_called()


# --------------------------------------------------------------------------
# Supersede semantics, executed rather than string-matched. These run the real
# update body through rdflib's SPARQL engine over a Dataset, so they measure
# what Fuseki would do, not what the body looks like.
# --------------------------------------------------------------------------

PROCEDURAL = (
    Path(__file__).parent / "fixtures" / "s1000d" / "mrad"
    / "DMC-ODMRAD-A-34-10-01-00A-720A-A_001-00_EN-US.xml"
)
SIBLING = (
    Path(__file__).parent / "fixtures" / "s1000d" / "mrad"
    / "DMC-ODMRAD-A-34-10-01-00A-520A-A_001-00_EN-US.xml"
)


def _bytes_with_fewer_steps(path: Path, keep: int) -> bytes:
    """The same module re-authored with only the first `keep` steps.

    A real re-drop, not a trimmed RDF graph: the XML is edited and re-parsed,
    so the step-/proclist- subjects that disappear are exactly the ones a
    shorter revision of the module would stop minting.
    """
    from lxml import etree

    root = etree.fromstring(path.read_bytes())
    procs = root.xpath("//mainProcedure")
    assert procs, "fixture has no mainProcedure; pick another"
    for proc in procs:
        steps = proc.xpath("./proceduralStep")
        for extra in steps[keep:]:
            proc.remove(extra)
    return etree.tostring(root)


def _body_for(monkeypatch, rdf_string, root_uri, doc_slug):
    jena, _ = _run(
        monkeypatch,
        _extract(rdf_string=rdf_string, root_uri=root_uri, doc_slug=doc_slug),
    )
    return jena.client.calls[0][0]


def _subjects(ds):
    return {str(s) for s in ds.graph(INSTANCE_GRAPH).subjects()}


def test_redrop_with_fewer_steps_leaves_no_orphan(monkeypatch):
    """The defect the ruling exists to close.

    Under the former bare INSERT, a module re-dropped with FEWER steps left
    its old step-/proclist- subjects in the graph for ever, and no reader
    could tell them from current ones.
    """
    doc_id = PROCEDURAL.stem

    b1 = S1000dGraphBuilder(doc_id=doc_id)
    root_uri = str(b1.parse_data_module(PROCEDURAL.read_bytes()))
    v1 = b1.serialize(format="turtle")

    b2 = S1000dGraphBuilder(doc_id=doc_id)
    root2 = str(b2.parse_data_module(_bytes_with_fewer_steps(PROCEDURAL, 1)))
    v2 = b2.serialize(format="turtle")
    assert root2 == root_uri, "same DMC must give the same module subject"

    slug = b1.doc_slug
    body1 = _body_for(monkeypatch, v1, root_uri, slug)
    body2 = _body_for(monkeypatch, v2, root2, slug)

    ds = Dataset()
    ds.update(body1)
    after_v1 = _subjects(ds)
    steps_v1 = {s for s in after_v1 if "step-" in s or "proclist-" in s}

    ds.update(body2)
    after_v2 = _subjects(ds)
    steps_v2 = {s for s in after_v2 if "step-" in s or "proclist-" in s}

    g2 = Graph()
    g2.parse(data=v2, format="turtle")
    print(
        f"MEASURED v1_subjects={len(after_v1)} v1_steps={len(steps_v1)} "
        f"v2_subjects={len(after_v2)} v2_steps={len(steps_v2)} "
        f"v2_source_triples={len(g2)} graph_triples={len(ds.graph(INSTANCE_GRAPH))}"
    )

    assert len(steps_v1) > len(steps_v2), "fixture must actually shrink"
    # The whole point: nothing from v1 survives that v2 does not re-assert.
    orphans = steps_v1 - steps_v2
    assert orphans, "test is vacuous unless v1 minted subjects v2 does not"
    assert not (orphans & after_v2), f"orphaned after supersede: {sorted(orphans)}"
    # And the graph is exactly v2, not v1 + v2.
    assert len(ds.graph(INSTANCE_GRAPH)) == len(g2)


def test_supersede_leaves_a_sibling_module_untouched(monkeypatch):
    """The blast-radius proof.

    The instance graph is shared by every module of the domain. Measured
    separately (scratchpad/dmc_supersede_predicate.py): 0 shared subjects and
    0 shared triples across the six MRAD modules. This pins that the DELETE
    honours it.
    """
    sib_id = SIBLING.stem
    bs = S1000dGraphBuilder(doc_id=sib_id)
    sib_root = str(bs.parse_data_module(SIBLING.read_bytes()))
    sib_rdf = bs.serialize(format="turtle")

    doc_id = PROCEDURAL.stem
    b1 = S1000dGraphBuilder(doc_id=doc_id)
    root_uri = str(b1.parse_data_module(PROCEDURAL.read_bytes()))
    v1 = b1.serialize(format="turtle")

    ds = Dataset()
    ds.update(_body_for(monkeypatch, sib_rdf, sib_root, bs.doc_slug))
    sib_before = {
        (str(s), str(p), str(o)) for s, p, o in ds.graph(INSTANCE_GRAPH)
    }
    assert sib_before

    ds.update(_body_for(monkeypatch, v1, root_uri, b1.doc_slug))
    # re-run the target module's supersede; the sibling must not notice
    ds.update(_body_for(monkeypatch, v1, root_uri, b1.doc_slug))
    after = {(str(s), str(p), str(o)) for s, p, o in ds.graph(INSTANCE_GRAPH)}

    print(
        f"MEASURED sibling_triples={len(sib_before)} "
        f"surviving={len(sib_before & after)} total_after={len(after)}"
    )
    assert sib_before <= after, "the supersede took a sibling module's triples"


def test_no_slug_prefix_collision_among_the_fixtures():
    """Pins the one hazard the filter cannot defend against by construction.

    The filter matches "-<slug>-", and "-" also occurs INSIDE a slug, so if
    one slug extended another at a hyphen the shorter module's supersede would
    delete the longer one's rows. Measured 0 among the six; a well-formed DMC
    does not extend another DMC. If a future naming scheme breaks that, this
    fails instead of silently over-deleting in production.
    """
    import os

    slugs = []
    for path in sorted(PROCEDURAL.parent.glob("*.xml")):
        b = S1000dGraphBuilder(doc_id=os.path.splitext(path.name)[0])
        slugs.append(b.doc_slug)
    assert len(slugs) >= 6
    collisions = [
        (a, b) for a in slugs for b in slugs if a != b and b.startswith(a + "-")
    ]
    print(f"MEASURED slugs={len(slugs)} collisions={len(collisions)}")
    assert collisions == []


def test_no_doc_slug_stays_additive_and_warns(monkeypatch):
    """iads/dita/40051 do not scope subjects per document, so they must NOT
    arm the delete -- it would take a sibling DOCUMENT's triples. Additive,
    and loud about it."""
    jena, ctx = _run(monkeypatch, _extract(doc_slug=None))
    body = jena.client.calls[0][0]
    assert body.startswith("INSERT DATA")
    assert "DELETE" not in body.upper()
    ctx.log.warning.assert_called()
    assert "ADDITIVE" in ctx.log.warning.call_args[0][0]


@pytest.mark.parametrize(
    "over",
    [
        {"root_uri": "urn:x<evil>"},
        {"root_uri": "urn:x evil"},
        {"root_uri": 'urn:x"evil'},
        {"doc_slug": 'evil" ) || CONTAINS(STR(?s), "'},
        {"doc_slug": "evil\\"},
    ],
)
def test_unsafe_scope_refuses_and_sends_nothing(monkeypatch, over):
    """An over-broad DELETE against a shared graph is not recoverable, so a
    scope that cannot be trusted is refused BEFORE any request is made."""
    jena = _FakeJena()
    monkeypatch.setattr(semantic_assets.httpx, "Client", _FakeHttpx)
    fn = semantic_assets.upload_to_jena.op.compute_fn.decorated_fn
    with pytest.raises(ValueError):
        fn(MagicMock(), _extract(**over), jena)
    assert jena.client.calls == []
