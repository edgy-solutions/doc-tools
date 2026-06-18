"""Live LLM-backed extraction test for the proprietary overlay feature.

End-to-end proof that a proprietary overlay field (defined only in a secret
spec, never committed) is:
  1. injected onto the @@dynamic ManufacturingStep via TypeBuilder,
  2. extracted by the LLM from text that mentions it,
  3. carried through the mirror model in process_fulltext, and
  4. persisted by to_graph_queries (Neo4j attr + RDF literal).

This test requires a live OpenAI-compatible LLM endpoint (Ollama, LiteLLM,
vLLM, OpenRouter, or real OpenAI). SKIPPED unless LLM_BASE_URL is set, so
the normal unit suite is unaffected. Run it with, e.g.:

    LLM_BASE_URL=http://192.168.1.119:11434/v1 \
    LLM_MODEL=gpt-oss-128k:120b \
    LLM_NUM_CTX=8192 \
    uv run python -m pytest tests/test_manufacturing_extraction_ollama.py -q -s
"""
import json
import os
from types import SimpleNamespace

import pytest

LLM_BASE_URL = os.getenv("LLM_BASE_URL")
pytestmark = pytest.mark.skipif(
    not LLM_BASE_URL,
    reason="requires a live LLM endpoint (set LLM_BASE_URL / LLM_MODEL)",
)

# A stand-in "proprietary" spec. Plain test fields — the point is to prove the
# secret-loaded overlay path works, not to ship real proprietary semantics.
PROPRIETARY_SPEC = {
    "fields": [
        {
            "name": "lot_acceptance_code",
            "kind": "scalar",
            "neo4j_attr": True,
            "rdf_literal": "hasLotAcceptanceCode",
            "description": "The Lot Acceptance Code (LAC) governing this step, e.g. 'LAC-7731'. Null if not mentioned.",
        },
        {
            "name": "torque_spec_nm",
            "kind": "int",
            "neo4j_attr": True,
            "rdf_literal": "torqueSpecNm",
            "description": "The torque specification in newton-metres (Nm) called out in this step, as an integer. Null if not mentioned.",
        },
    ]
}

WORK_INSTRUCTION_TEXT = (
    "Procedure 1000, Step 1.1: Apply sealant MIL-S-81733 to the forward seam "
    "using a calibrated torque wrench. Torque the retaining fastener to 35 Nm. "
    "The Lot Acceptance Code (LAC) governing this operation is LAC-7731. "
    "This step physically transforms the assembly and is value-added."
)


def test_proprietary_overlay_field_extracted_and_persisted(tmp_path, monkeypatch):
    from doc_tools.plugins.manufacturing import ManufacturingPlugin, MatAugmentation

    spec_path = tmp_path / "proprietary_overlay.json"
    spec_path.write_text(json.dumps(PROPRIETARY_SPEC))
    monkeypatch.setenv("MANUFACTURING_OVERLAY_SPEC", str(spec_path))
    monkeypatch.setenv("PROMPT_SOURCE", "file")  # canonical committed prompt

    elements = [{"type": "NarrativeText", "text": WORK_INSTRUCTION_TEXT}]
    plugin = ManufacturingPlugin(domain_type="manufacturing")

    nodes = plugin.process_fulltext(
        full_text=WORK_INSTRUCTION_TEXT, doc_id="part_test", elements=elements
    )
    assert nodes, "extraction returned no nodes"
    aug = nodes[0].domain_augmentation
    assert isinstance(aug, MatAugmentation)
    assert aug.steps, "no manufacturing steps were extracted"

    # 1-3: the proprietary fields rode the @@dynamic schema through to the steps.
    lacs = [getattr(s, "lot_acceptance_code", None) for s in aug.steps]
    torques = [getattr(s, "torque_spec_nm", None) for s in aug.steps]
    print(f"\nExtracted lot_acceptance_code={lacs} torque_spec_nm={torques}")
    assert any(v and "7731" in str(v) for v in lacs), f"lot_acceptance_code not extracted: {lacs}"
    assert any(str(v) == "35" for v in torques if v is not None), f"torque_spec_nm not extracted: {torques}"

    # 4: and they reach the graph writer (Neo4j attribute + RDF literal).
    config = SimpleNamespace(graph_child_label="Part")
    cypher, sparql = plugin.to_graph_queries(nodes, config, doc_id="part_test", image_prefix="img/")
    cypher_blob = json.dumps(cypher)
    sparql_blob = " ".join(sparql)
    assert "lot_acceptance_code" in cypher_blob, "proprietary field not SET on the step node"
    assert "hasLotAcceptanceCode" in sparql_blob, "proprietary RDF literal not emitted"


# A generic object_list overlay (nested objects inside a list). Plain test
# field names — proves the nested-class path works end-to-end via the LLM.
OBJECT_LIST_SPEC = {
    "fields": [
        {
            "name": "component_items",
            "kind": "object_list",
            "description": "List of components/parts the step installs or consumes. One entry per distinct part.",
            "properties": [
                {"name": "part_number", "kind": "scalar",
                 "description": "The part number, e.g. '99-812'. If missing write 'Not specified'."},
                {"name": "quantity", "kind": "scalar",
                 "description": "Quantity required. If not stated write 'Not specified'."},
            ],
            "object_node": {"label": "ComponentItem", "rel_type": "HAS_COMPONENT", "id_props": ["part_number"]},
        }
    ]
}

COMPONENT_TEXT = (
    "Procedure 1000, Step 1.1: Install the bracket assembly. Required components: "
    "part number 99-812, quantity 2; and part number AN960-10 washer, quantity 4. "
    "Secure using a calibrated torque wrench."
)


def test_object_list_overlay_extracted_as_objects_and_persisted(tmp_path, monkeypatch):
    from doc_tools.plugins.manufacturing import ManufacturingPlugin, MatAugmentation

    spec_path = tmp_path / "object_overlay.json"
    spec_path.write_text(json.dumps(OBJECT_LIST_SPEC))
    monkeypatch.setenv("MANUFACTURING_OVERLAY_SPEC", str(spec_path))
    monkeypatch.setenv("PROMPT_SOURCE", "file")

    elements = [{"type": "NarrativeText", "text": COMPONENT_TEXT}]
    plugin = ManufacturingPlugin(domain_type="manufacturing")
    nodes = plugin.process_fulltext(full_text=COMPONENT_TEXT, doc_id="part_obj", elements=elements)
    assert nodes, "extraction returned no nodes"
    aug = nodes[0].domain_augmentation
    assert isinstance(aug, MatAugmentation) and aug.steps

    # the nested object list comes back as a list of dicts with the sub-fields
    items = [it for s in aug.steps for it in (getattr(s, "component_items", None) or [])]
    print(f"\ncomponent_items={items}")
    assert items, "no component_items extracted"
    assert all(isinstance(it, dict) for it in items), "items are not plain dicts"
    assert all("part_number" in it for it in items), "sub-field part_number missing"
    assert any("99-812" in str(it.get("part_number", "")) for it in items)

    # and they persist as typed nodes off the step
    config = SimpleNamespace(graph_child_label="Part")
    cypher, _ = plugin.to_graph_queries(nodes, config, doc_id="part_obj", image_prefix="img/")
    cypher_blob = json.dumps(cypher)
    assert "ComponentItem" in cypher_blob and "HAS_COMPONENT" in cypher_blob
    assert "UNWIND $component_items AS item" in cypher_blob


# A document-scope overlay (one summary + notes per document, on MatAugmentation).
DOC_SCOPE_SPEC = {
    "fields": [
        {
            "name": "work_instruction_summary",
            "kind": "scalar",
            "scope": "document",
            "description": "A concise 1-2 sentence summary of the overall purpose of this work instruction and the major process types involved (e.g. sealing, torqueing, inspection). Based only on the source.",
        },
        {
            "name": "extraction_notes",
            "kind": "list",
            "scope": "document",
            "description": "Notes on gaps/ambiguities: missing part numbers, missing quantities, unclear references, or fields where information was not specified. One note per item. Empty list if none.",
        },
    ]
}


def test_document_scope_fields_populate_augmentation_and_extraction_json(tmp_path, monkeypatch):
    from doc_tools.plugins.manufacturing import ManufacturingPlugin, MatAugmentation
    from doc_tools.assets.semantic_assets import _extraction_payload

    spec_path = tmp_path / "doc_overlay.json"
    spec_path.write_text(json.dumps(DOC_SCOPE_SPEC))
    monkeypatch.setenv("MANUFACTURING_OVERLAY_SPEC", str(spec_path))
    monkeypatch.setenv("PROMPT_SOURCE", "file")

    plugin = ManufacturingPlugin(domain_type="manufacturing")
    nodes = plugin.process_fulltext(
        full_text=WORK_INSTRUCTION_TEXT, doc_id="part_doc",
        elements=[{"type": "NarrativeText", "text": WORK_INSTRUCTION_TEXT}],
    )
    assert nodes
    aug = nodes[0].domain_augmentation
    assert isinstance(aug, MatAugmentation)

    summary = getattr(aug, "work_instruction_summary", None)
    print(f"\nwork_instruction_summary={summary!r}")
    print(f"extraction_notes={getattr(aug, 'extraction_notes', None)!r}")
    assert summary and isinstance(summary, str) and len(summary) > 10, "no document summary extracted"

    # the document field rides through into extraction.json (at the augmentation level)
    payload = _extraction_payload(nodes, "part_doc", "manufacturing")
    assert "work_instruction_summary" in payload["augmentations"][0]
