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


def _no_such_key(key: str) -> Exception:
    """A boto3-shaped 404. The asset matches on `response["Error"]["Code"]`
    rather than on `s3_client.exceptions.NoSuchKey`, so the mock only has to
    carry the code — see `_is_missing_key` for why the class form was dropped."""
    e = Exception(f"NoSuchKey: {key}")
    e.response = {"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}}
    return e


def _mock_s3(content: bytes, manifest: bytes | None = None):
    """S3 double that answers PER KEY, not one body for every call.

    The 40051 branch fetches a SECOND object — the sibling
    `graphics_manifest.json` — before parsing. A single canned body handed the
    manifest fetch the WP XML back, so the test exercised "manifest is corrupt"
    while claiming to cover the ordinary legacy path where the manifest is
    simply absent. Absent is the default here; pass `manifest=` to model a
    bundle that has one.
    """
    s3 = MagicMock()

    def get_object(Bucket, Key):
        if Key.endswith("graphics_manifest.json"):
            if manifest is None:
                raise _no_such_key(Key)
            body = MagicMock()
            body.read.return_value = manifest
            return {"Body": body}
        body = MagicMock()
        body.read.return_value = content
        return {"Body": body}

    s3.get_client.return_value.get_object.side_effect = get_object
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


# ---------------------------------------------------------------------------
# The sibling graphics_manifest.json — optional, and never fatal
# ---------------------------------------------------------------------------
# The manifest is what turns a `<graphic boardno>` into a real S3 URL. It is
# OPTIONAL: without one the parser emits rendering_origin="unresolved" and no
# mil:hasURL (the confabulation-kill — a predicted `<boardno>.png` was a URL the
# pipeline had no evidence for). Because the fallback is defined, no failure to
# READ the manifest may take the ingest down with it.

MANIFEST_XML = b'<wp><wpno>WP1</wpno><graphic boardno="FIG-1"/></wp>'


def test_manifest_is_read_from_the_sibling_key_not_under_generated():
    """Path pin. `extract_iads_bundle` writes the manifest NEXT TO the WP XML;
    reading it from `generated/` instead would miss every time and degrade
    silently to unresolved, which looks identical to "no manifest exists"."""
    cfg = XmlIngestConfig(s3_bucket="bucket", s3_key="40051/army/helmet/M0004.xml")
    s3 = _mock_s3(MANIFEST_XML, manifest=b'{"figures": {}}')
    extract_rdf_from_xml(build_asset_context(), config=cfg, s3=s3)

    keys = [c.kwargs["Key"] for c in s3.get_client.return_value.get_object.call_args_list]
    assert "40051/army/helmet/graphics_manifest.json" in keys


def test_manifest_resolves_a_boardno_to_the_uploaded_filename():
    cfg = XmlIngestConfig(s3_bucket="bucket", s3_key="40051/wp.xml")
    manifest = (
        b'{"figures": {"FIG-1": {"uploaded_filename": "FIG-1.svg",'
        b' "rendering_origin": "rendered"}}}'
    )
    out = extract_rdf_from_xml(
        build_asset_context(), config=cfg, s3=_mock_s3(MANIFEST_XML, manifest=manifest)
    )
    assert "FIG-1.svg" in out["rdf_string"]      # the manifest's name, not a predicted .png
    assert "rendered" in out["rdf_string"]


def test_a_corrupt_manifest_is_non_fatal_and_degrades_to_unresolved():
    """THE REGRESSION THIS PINS. The read used to be guarded by
    `except s3_client.exceptions.NoSuchKey` alone, so a manifest that existed but
    would not parse raised straight out of the asset and failed the whole WP
    ingest — over an OPTIONAL file with a defined fallback."""
    cfg = XmlIngestConfig(s3_bucket="bucket", s3_key="40051/wp.xml")
    out = extract_rdf_from_xml(
        build_asset_context(), config=cfg,
        s3=_mock_s3(MANIFEST_XML, manifest=b"<html>403 Forbidden</html>"),
    )
    assert "WorkPackage" in out["rdf_string"]    # the ingest still completed
    assert "unresolved" in out["rdf_string"]     # and said so, rather than inventing a URL


def test_an_unreadable_manifest_is_also_non_fatal():
    """AccessDenied, a transient 503 — anything that is not a plain miss. Same
    ruling: an optional read may not decide whether the ingest survives."""
    cfg = XmlIngestConfig(s3_bucket="bucket", s3_key="40051/wp.xml")
    s3 = _mock_s3(MANIFEST_XML)
    real = s3.get_client.return_value.get_object.side_effect

    def boom(Bucket, Key):
        if Key.endswith("graphics_manifest.json"):
            e = Exception("AccessDenied")
            e.response = {"Error": {"Code": "AccessDenied"}}
            raise e
        return real(Bucket=Bucket, Key=Key)

    s3.get_client.return_value.get_object.side_effect = boom
    out = extract_rdf_from_xml(build_asset_context(), config=cfg, s3=s3)
    assert "WorkPackage" in out["rdf_string"]
