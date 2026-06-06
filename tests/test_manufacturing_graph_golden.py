"""Characterization (golden-snapshot) test for ManufacturingPlugin.to_graph_queries.

This pins the EXACT Cypher + SPARQL emitted by the current, hardcoded graph
writer before the base/overlay refactor. It is a safety net, not a spec: any
change to the emitted graph shape will fail this test and show up as a diff, so
"do the whole migration and revert if it's a disaster" becomes "the diff tells
us instantly what moved."

The fixture deliberately exercises every persistence pattern found in the
current writer:
  - plain step attributes (step_id, flags, justification, duration)
  - relationship-only fields (tooling, hazard_class, required_cert, figures)
  - dual-written fields (standards, internal_part_numbers, slang)
  - Jena-only fields (consumables, standard_ref)
  - the conditional-absent branch (step 2: empty lists / None)
  - StrategicAssessment on the Part node
  - quote sanitization in the SPARQL literal path

Regenerate the golden after an INTENTIONAL change:
    UPDATE_GOLDEN=1 uv run python -m pytest tests/test_manufacturing_graph_golden.py
"""
import json
import os
from pathlib import Path
from types import SimpleNamespace

from doc_tools.plugins.manufacturing import (
    ManufacturingPlugin,
    ManufacturingStep,
    StrategicAssessment,
    MatAugmentation,
)
from doc_tools.plugins.models import BaseSection, DocumentNode

GOLDEN = Path(__file__).parent / "golden" / "manufacturing_to_graph_queries.json"
DOC_ID = "part_42"
IMAGE_PREFIX = "https://cdn.example/img/"


def _build_nodes():
    """One fully-populated step + one minimal step (conditionals absent)."""
    full = ManufacturingStep(
        procedure_id="1000",
        step_id="1.1",
        instruction_text='Apply sealant "MIL-S-81733" to the seam.',  # quote -> SPARQL sanitization
        action_verb="Apply sealant",
        tooling=["Torque Wrench", "Brush"],
        consumables=["Sealant MIL-S-81733"],
        hazard_class="1.1D",
        required_cert="QC Inspector",
        standard_ref="ISO-9001",
        is_value_added=True,
        is_safety_critical=True,
        process_category="Transformation",
        justification="Physically transforms the product.",
        estimated_duration_minutes=30,
        military_and_industry_standards=["MIL-PRF-81733", "J-STD-001"],
        internal_part_numbers=["99-812"],
        material_and_hardware_slang=["RTV Silicone"],
        figure_references=["3", "12A"],
    )
    minimal = ManufacturingStep(
        procedure_id="1000",
        step_id="2.1",
        instruction_text="Inspect the weld.",
        action_verb="Inspect",
        tooling=[],
        consumables=[],
        hazard_class=None,
        required_cert=None,
        standard_ref=None,
        is_value_added=False,
        is_safety_critical=False,
        process_category="Inspection",
        justification="Inspection only; no transformation.",
        estimated_duration_minutes=None,  # exercises the -1 default
        military_and_industry_standards=[],
        internal_part_numbers=[],
        material_and_hardware_slang=[],
        figure_references=[],
    )
    aug = MatAugmentation(
        steps=[full, minimal],
        assessment=StrategicAssessment(proprietary_score=0.8, outsourceable=False),
    )
    section = BaseSection(
        title="Seal & Inspect Assembly",
        level=0,
        page_start=1,
        content="",
        node_id=DOC_ID,
    )
    return [DocumentNode(base_extraction=section, domain_augmentation=aug)]


def _normalize(cypher_queries, sparql_queries):
    """Collapse whitespace so the snapshot is robust to reformatting but still
    captures the full structure (labels, relationships, SET attrs, params)."""
    def norm(s: str) -> str:
        return " ".join(s.split())

    return {
        "cypher": [
            {"query": norm(c["query"]), "params": c["params"]} for c in cypher_queries
        ],
        "sparql": [norm(s) for s in sparql_queries],
    }


def _actual():
    nodes = _build_nodes()
    config = SimpleNamespace(graph_child_label="Part")
    plugin = ManufacturingPlugin(domain_type="manufacturing")
    cypher, sparql = plugin.to_graph_queries(
        nodes, config, doc_id=DOC_ID, image_prefix=IMAGE_PREFIX
    )
    return _normalize(cypher, sparql)


def test_to_graph_queries_matches_golden():
    actual = _actual()

    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n")
        return  # regeneration run; nothing to assert

    assert GOLDEN.exists(), (
        f"Golden file missing: {GOLDEN}. Generate it with "
        f"UPDATE_GOLDEN=1 uv run python -m pytest {Path(__file__).name}"
    )
    expected = json.loads(GOLDEN.read_text())
    assert actual == expected
