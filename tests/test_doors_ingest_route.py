"""Tests for the DOORS export ingest route (doc_tools/assets/doors_ingestion).

S3 is stubbed; the parser, dispatcher and identity pass are real.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from dagster import build_asset_context

from doc_tools.assets.doors_ingestion import DoorsIngestConfig, ingest_doors_export
from doc_tools.parsers.doors_export import DoorsParseError

FIXTURE = (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "doors"
           / "SRS-MRAD-001_baseline-2.1.csv")
KEY = "doors/SRS-MRAD-001_baseline-2.1.csv"


def _mock_s3(content: bytes):
    s3 = MagicMock()
    body = MagicMock()
    body.read.return_value = content
    s3.get_client.return_value.get_object.return_value = {"Body": body}
    return s3


def _run(content: bytes):
    cfg = DoorsIngestConfig(s3_bucket="processing-artifacts", s3_key=KEY)
    return ingest_doors_export(build_asset_context(), config=cfg, s3=_mock_s3(content))


# A valid export whose preamble carries no identity label at all. Module/Project/
# Baseline are not identity fields, so all four are refused while the parse and
# the pass both succeed.
NO_IDENTITY = (
    "Module: /MRAD Program/Requirements/SRS-MRAD-001\n"
    "Project: MRAD Program\n"
    "Baseline: 2.1\n"
    "Object Identifier,Object Level,Object Heading,Object Text,Absolute Number\n"
    "SRS-1,1,Scope,,1\n"
).encode("utf-8")

IDENTITY_FIELDS = ("document_number", "revision", "cage_code", "contract_number")


def test_declared_pass_runs_over_real_fixture_and_returns_a_value():
    out = _run(FIXTURE.read_bytes())
    assert out["doc_id"] == "SRS-MRAD-001_baseline-2.1"
    assert out["source_object_key"] == KEY
    assert out["object_count"] > 0
    assert len(out["passes"]) == 1
    p = out["passes"][0]
    assert p["name"] == "identity.identity_from_doors_text"
    assert p["status"] == "ok"
    # Assert real extracted values, not merely that a value object exists: the
    # serialized identity is a non-empty dict even when every field is refused.
    v = p["value"]
    assert v["refused"] == []
    assert v["document_number"] == "SRS-MRAD-001"
    assert v["revision"] == "C"
    assert v["cage_code"] == "1AB23"
    assert v["contract_number"] == "W58RGZ-24-C-0031"
    for name in IDENTITY_FIELDS:
        assert v[f"{name}_source"], f"{name} has a value but no source"


def test_a_preamble_with_no_identity_refuses_per_field_without_failing():
    """The degrade-never-fail rule, at the level it actually operates.

    A missing field is a per-field refusal recorded inside the value
    (``identity.py``: "Absent fields are refusals, not failures"), NOT a
    ``PassResult.status`` of "refused" -- that status is reserved for a pass that
    raised. Asserting the status here would be asserting the wrong contract.
    """
    out = _run(NO_IDENTITY)
    assert out["object_count"] == 1
    p = out["passes"][0]
    assert p["status"] == "ok"
    assert p["error"] == ""
    v = p["value"]
    assert sorted(v["refused"]) == sorted(IDENTITY_FIELDS)
    for name in IDENTITY_FIELDS:
        assert v[name] is None
        assert v[f"{name}_source"] is None


def test_the_returned_dict_survives_a_json_round_trip():
    """The result crosses an IO manager and is attached as Dagster metadata, so
    a dataclass left in ``passes[].value`` would break a real run while every
    in-process test still passed."""
    out = _run(FIXTURE.read_bytes())
    assert json.loads(json.dumps(out)) == out


def test_malformed_export_is_not_swallowed():
    with pytest.raises(DoorsParseError):
        _run(b"this is not a doors export\nno header row here\n")


def test_route_touches_no_store():
    keys = set(ingest_doors_export.required_resource_keys)
    assert "s3" in keys
    assert not keys & {"neo4j", "weaviate", "llm", "jena"}
