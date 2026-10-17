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


def _rdf_string() -> str:
    b = S1000dGraphBuilder(doc_id="421A")
    b.parse_data_module(FIXTURE.read_bytes())
    return b.serialize(format="turtle")


def _run(monkeypatch, extract: dict):
    jena = _FakeJena()
    _FakeHttpx.puts = []
    monkeypatch.setattr(semantic_assets.httpx, "Client", _FakeHttpx)
    fn = semantic_assets.upload_to_jena.op.compute_fn.decorated_fn
    ctx = MagicMock()
    fn(ctx, extract, jena)
    return jena, ctx


def _extract(**over) -> dict:
    d = {
        "rdf_string": _rdf_string(),
        "root_uri": "urn:x",
        "s3_key": "ingress-user/s1000d-data-module/abc/421A.xml",
        "chunks": [],
        "domain": "MAINTENANCE",
        "content_kind": "s1000d-data-module",
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


def test_body_is_additive(monkeypatch):
    jena, _ = _run(monkeypatch, _extract())
    body = jena.client.calls[0][0]
    assert body.startswith("INSERT DATA")
    for word in ("DELETE", "DROP", "CLEAR", "PUT"):
        assert word not in body.upper().split("{", 1)[0]
        assert f"\n{word} " not in body.upper()


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
