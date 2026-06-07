"""Tests for the universal XML->RDF router asset (doc_tools/assets/xml_ingestion).

Routes by S3 directory prefix to the correct MIL parser and passes RDF in
memory. S3 is mocked; the parser integration is real.
"""
from unittest.mock import MagicMock

import pytest
from dagster import build_asset_context

from doc_tools.assets.xml_ingestion import extract_rdf_from_xml, XmlIngestConfig

S1000D_XML = (
    b"<dmodule><identAndStatusSection><dmAddress><dmIdent>"
    b'<dmCode modelIdentCode="AE" systemCode="32" infoCode="520"/>'
    b"</dmIdent></dmAddress></identAndStatusSection></dmodule>"
)


def _mock_s3(content: bytes):
    s3 = MagicMock()
    body = MagicMock()
    body.read.return_value = content
    s3.get_client.return_value.get_object.return_value = {"Body": body}
    return s3


def test_router_dispatches_s1000d_prefix_to_builder():
    cfg = XmlIngestConfig(s3_bucket="bucket", s3_key="s1000d/manual.xml")
    out = extract_rdf_from_xml(build_asset_context(), config=cfg, s3=_mock_s3(S1000D_XML))

    assert "DataModule" in out["rdf_string"]
    assert out["root_uri"].startswith("http://edgy-solutions.com/ontology/mil#dmc-")
    assert out["s3_key"] == "s1000d/manual.xml"


def test_router_dispatches_40051_prefix():
    cfg = XmlIngestConfig(s3_bucket="bucket", s3_key="40051/wp.xml")
    xml = b"<wp><wpno>WP1</wpno></wp>"
    out = extract_rdf_from_xml(build_asset_context(), config=cfg, s3=_mock_s3(xml))
    assert "WorkPackage" in out["rdf_string"]
    assert out["root_uri"].endswith("wpn-WP1")


def test_router_unsupported_prefix_raises():
    cfg = XmlIngestConfig(s3_bucket="bucket", s3_key="unknown/x.xml")
    with pytest.raises(ValueError):
        extract_rdf_from_xml(build_asset_context(), config=cfg, s3=_mock_s3(b"<x/>"))
