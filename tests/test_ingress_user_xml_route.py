"""User-dropped XML: sensor gate, no crossover, router, halts.

S3 is stubbed; the S1000D parser is real. Proven against the committed fixture
only -- NOT against live MinIO.
"""
import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from dagster import build_asset_context
from rdflib import Graph, RDF, URIRef

from doc_tools import definitions
from doc_tools.assets.xml_ingestion import XmlIngestConfig, extract_rdf_from_xml
from doc_tools.utils.content_kind import UnclassifiableContentKindError

FIXDIR = Path(__file__).resolve().parent / "fixtures" / "s1000d" / "mrad"
FILES = sorted(FIXDIR.glob("DMC-*.xml"))
SHA = "a" * 64
MIL = "http://edgy-solutions.com/ontology/mil#"


def _key(name, sha=SHA):
    return f"ingress-user/xml/{sha}/{name}"


def _s3(xml: bytes, manifest):
    """manifest: dict -> served JSON; None -> NoSuchKey."""
    s3 = MagicMock()

    def get_object(Bucket, Key):
        if Key.endswith("/manifest.json"):
            if manifest is None:
                err = Exception("missing")
                err.response = {"Error": {"Code": "NoSuchKey"}}
                raise err
            body = MagicMock()
            body.read.return_value = json.dumps(manifest).encode()
            return {"Body": body}
        body = MagicMock()
        body.read.return_value = xml
        return {"Body": body}

    s3.get_client.return_value.get_object.side_effect = get_object
    return s3


def _run(path: Path, manifest):
    cfg = XmlIngestConfig(s3_bucket="processing-artifacts", s3_key=_key(path.name))
    return extract_rdf_from_xml(
        build_asset_context(), config=cfg, s3=_s3(path.read_bytes(), manifest))


def test_fixture_has_six_files():
    assert len(FILES) == 6


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_gate_accepts_all_six(path):
    assert re.match(definitions.ingress_user_xml_sensor.s3_filter, _key(path.name))


@pytest.mark.parametrize("key", [
    f"ingress-user/xml/{SHA}/manifest.json",
    f"ingress-user/xml/{SHA}/x.pdf",
    f"ingress-user/cad/{SHA}/part.step",
    f"ingress-user/xml/{'a' * 63}/x.xml",
    "ingress-user/xml/" + "g" * 64 + "/x.xml",
    "ingress-user/xml/short/x.xml",
])
def test_gate_rejects(key):
    assert not re.match(definitions.ingress_user_xml_sensor.s3_filter, key)


def test_no_crossover_both_ways():
    pdf_f = definitions.ingress_user_sensor.s3_filter
    xml_f = definitions.ingress_user_xml_sensor.s3_filter
    assert not re.match(pdf_f, f"ingress-user/xml/{SHA}/a.xml")
    assert not re.match(xml_f, f"ingress-user/pdf/{SHA}/a.pdf")
    assert re.match(pdf_f, f"ingress-user/pdf/{SHA}/a.pdf")


def _canon(path: Path) -> str:
    # DMC-<code>_<issue>_<lang>.xml -> <code>
    return path.stem.split("_")[0][len("DMC-"):]


MANIFEST = {"content_kind": "s1000d-data-module", "domain_type": "maintenance",
            "metadata": {"content_kind": "s1000d-data-module"}}


def test_router_resolves_and_six_distinct_data_modules():
    g = Graph()
    for p in FILES:
        out = _run(p, MANIFEST)
        assert out["rdf_string"]
        assert out["s3_key"] == _key(p.name)
        g.parse(data=out["rdf_string"], format="turtle")
    subjects = set(g.subjects(RDF.type, URIRef(MIL + "DataModule")))
    expected = {URIRef(f"{MIL}dmc-{_canon(p)}") for p in FILES}
    assert len(expected) == 6
    assert subjects == expected, (
        f"expected six identifiers {sorted(map(str, expected))}, "
        f"got {sorted(map(str, subjects))}")


def test_metadata_fallback_for_content_kind():
    assert _run(FILES[0], {"metadata": {"content_kind": "s1000d-data-module"}})["rdf_string"]


def test_halt_missing_manifest():
    with pytest.raises(ValueError, match="manifest"):
        _run(FILES[0], None)


def test_halt_no_declared_kind():
    with pytest.raises(ValueError, match="content_kind"):
        _run(FILES[0], {"domain_type": "maintenance"})


def test_halt_generic_xml_kind_names_key_and_kind():
    with pytest.raises(ValueError) as ei:
        _run(FILES[0], {"content_kind": "xml"})
    msg = str(ei.value)
    assert _key(FILES[0].name) in msg and "'xml'" in msg


def test_halt_unresolvable_kind_propagates():
    with pytest.raises(UnclassifiableContentKindError):
        _run(FILES[0], {"content_kind": "nonsense"})


def test_non_ingress_keys_unchanged():
    cfg = XmlIngestConfig(s3_bucket="b", s3_key="unknown/x.xml")
    with pytest.raises(ValueError, match="Unsupported doc_type"):
        extract_rdf_from_xml(build_asset_context(), config=cfg, s3=_s3(b"<x/>", None))
