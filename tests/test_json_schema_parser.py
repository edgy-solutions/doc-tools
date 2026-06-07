"""Unit tests for the RabbitMQ JSON-Schema parser (doc_tools/ingestion/json_schema_parser).

Pure logic: flattens nested JSON Schema into dot/bracket-notation field lists for
DataHub. Previously ~21% covered (import only).
"""
import json

from doc_tools.ingestion.json_schema_parser import JSONSchemaParser


def test_flat_type_mapping_and_enum():
    fields = JSONSchemaParser()._traverse_properties({
        "count": {"type": "integer", "description": "How many"},
        "name": {"type": "string"},
        "active": {"type": "boolean"},
        "mode": {"type": "string", "enum": ["A", "B"]},
        "weird": {"type": "nonsense"},
    })
    by = {f["name"]: f for f in fields}
    assert by["count"]["datahub_type"] == "NumberTypeClass"
    assert by["count"]["description"] == "How many"
    assert by["name"]["datahub_type"] == "StringTypeClass"
    assert by["active"]["datahub_type"] == "BooleanTypeClass"
    assert "Enum: A, B" in by["mode"]["description"]
    # unknown json types fall back to StringTypeClass
    assert by["weird"]["datahub_type"] == "StringTypeClass"


def test_nested_object_dot_notation():
    fields = JSONSchemaParser()._traverse_properties(
        {"telemetry": {"type": "object", "properties": {"rpm": {"type": "number"}}}}
    )
    names = {f["name"] for f in fields}
    assert "telemetry" in names and "telemetry.rpm" in names


def test_array_of_objects_bracket_notation():
    fields = JSONSchemaParser()._traverse_properties(
        {"rotors": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}}}}}
    )
    assert "rotors[].id" in {f["name"] for f in fields}


def test_parse_uses_title_and_wraps(tmp_path):
    f = tmp_path / "rotor.json"
    f.write_text(json.dumps({"title": "RotorStatus", "properties": {"rpm": {"type": "number"}}}))
    out = JSONSchemaParser().parse(str(f))
    assert len(out) == 1
    assert out[0]["struct_name"] == "RotorStatus"
    assert any(fld["name"] == "rpm" for fld in out[0]["fields"])
    assert out[0]["fields"][0]["struct_name"] == "RotorStatus"


def test_parse_falls_back_to_filename(tmp_path):
    f = tmp_path / "myschema.json"
    f.write_text(json.dumps({"properties": {"x": {"type": "string"}}}))
    assert JSONSchemaParser().parse(str(f))[0]["struct_name"] == "myschema"
