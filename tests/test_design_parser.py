"""Tests for DesignParserComponent (doc_tools/components/design_parser.py).

Parses database-design exports from S3 into domain-tagged metadata:
.edmx (.NET Entity Framework conceptual model) and .json (toolchain exports).
The S3 fetch is mocked; the XML/JSON parsing + domain inference is real.
"""
from unittest.mock import MagicMock

from dagster import build_asset_context
from dag_tools.components.s3_sensor.file_component import S3FileConfig

from doc_tools.components.design_parser import DesignParserComponent


def _asset():
    defs = DesignParserComponent(name="parse_design_metadata").build_defs(None)
    return next(iter(defs.assets))


def _mock_s3(content: bytes):
    s3 = MagicMock()
    body = MagicMock()
    body.read.return_value = content
    s3.get_client.return_value.get_object.return_value = {"Body": body}
    return s3


EDMX = b"""<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2009/11/edmx">
  <edmx:DataServices>
    <Schema xmlns="http://schemas.microsoft.com/ado/2009/11/edm">
      <EntityType Name="Aircraft">
        <Documentation><Summary>An aircraft entity.</Summary></Documentation>
        <Property Name="Id"/>
        <NavigationProperty Name="Engines"/>
        <NavigationProperty Name="Crew"/>
      </EntityType>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""

JSON_DESIGN = b'{"tables": [{"name": "orders", "description": "Order table", "relations": ["customers"]}]}'


def test_design_parser_edmx_dotnet_entity_framework():
    asset_def = _asset()
    ctx = build_asset_context(partition_key="avionics/design_files/model.edmx")
    cfg = S3FileConfig(file_url="s3://design-artifacts/avionics/design_files/model.edmx")

    result = asset_def(ctx, config=cfg, s3=_mock_s3(EDMX))

    assert "Aircraft" in result
    assert result["Aircraft"]["description"] == "An aircraft entity."
    assert result["Aircraft"]["relationships"] == ["Engines", "Crew"]
    assert result["Aircraft"]["domain"] == "AVIONICS"  # inferred from the S3 key prefix


def test_design_parser_json_toolchain_export():
    asset_def = _asset()
    ctx = build_asset_context(partition_key="sales/design_files/model.json")
    cfg = S3FileConfig(file_url="s3://design-artifacts/sales/design_files/model.json")

    result = asset_def(ctx, config=cfg, s3=_mock_s3(JSON_DESIGN))

    assert result["orders"]["description"] == "Order table"
    assert result["orders"]["relationships"] == ["customers"]
    assert result["orders"]["domain"] == "SALES"


def test_design_parser_unsupported_extension_returns_empty():
    asset_def = _asset()
    ctx = build_asset_context(partition_key="x/design_files/notes.txt")
    cfg = S3FileConfig(file_url="s3://design-artifacts/x/design_files/notes.txt")

    assert asset_def(ctx, config=cfg, s3=_mock_s3(b"plain text")) == {}
