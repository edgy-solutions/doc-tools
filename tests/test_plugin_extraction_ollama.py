"""Live Ollama-backed extraction tests for the remaining domain plugins.

Mirrors test_manufacturing_extraction_ollama.py: each test exercises the real
LLM extraction path (compliance/training via augment, maintenance/sustainment
via process_fulltext) and asserts domain-appropriate structured output. Where a
plugin has a fallback path, we assert the output is NOT the fallback, proving
real extraction ran.

SKIPPED unless OLLAMA_BASE_URL is set, so CI never depends on a model server:

    OLLAMA_BASE_URL=http://192.168.1.119:11434/v1 \
    OLLAMA_MODEL=gpt-oss-128k:120b OLLAMA_NUM_CTX=8192 \
    uv run python -m pytest tests/test_plugin_extraction_ollama.py -q -s
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("OLLAMA_BASE_URL"),
    reason="requires a live Ollama server (set OLLAMA_BASE_URL / OLLAMA_MODEL)",
)


def test_compliance_augment_extracts_rules(monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "file")
    from doc_tools.plugins.compliance import CompliancePlugin, ComplianceAugmentation
    from doc_tools.plugins.models import BaseSection

    content = (
        "Per DAFMAN 91-201, the maximum net explosive weight permitted in storage "
        "bay 3 is 500 pounds. Hazard class 1.1 munitions must be segregated from "
        "incompatible materials at all times."
    )
    sec = BaseSection(title="Storage Limits", level=1, page_start=1, content=content, node_id="s1")
    aug = CompliancePlugin(domain_type="compliance").augment(sec).domain_augmentation

    assert isinstance(aug, ComplianceAugmentation)
    assert aug.rules, "no compliance rules extracted"
    # not the error-fallback path
    assert all(not r.manual_reference.startswith("ERROR-FALLBACK") for r in aug.rules)
    print("\ncompliance rules:", [(r.manual_reference, r.rule_type) for r in aug.rules])


def test_maintenance_process_fulltext_extracts_steps(monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "file")
    from doc_tools.plugins.maintenance import MaintenancePlugin, MroAugmentation

    text = (
        "Procedure 0010, Step 1: Torque the retaining bolt to 35 Nm using a calibrated "
        "torque wrench. This step is safety critical. "
        "Step 2: Visually inspect the hydraulic seal for cracks."
    )
    nodes = MaintenancePlugin(domain_type="maintenance").process_fulltext(
        full_text=text, doc_id="d1", elements=[{"type": "NarrativeText", "text": text}]
    )
    assert nodes, "extraction returned no nodes"
    aug = nodes[0].domain_augmentation
    assert isinstance(aug, MroAugmentation)
    assert aug.steps, "no maintenance steps extracted"
    blob = " ".join((s.instruction_text + " " + s.action_verb).lower() for s in aug.steps)
    assert any(w in blob for w in ("torque", "bolt", "inspect", "seal"))
    print("\nmaintenance steps:", [(s.step_id, s.action_verb) for s in aug.steps])


def test_training_augment_extracts_concepts(monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "file")
    from doc_tools.plugins.training import TrainingPlugin, SlideAugmentation
    from doc_tools.plugins.models import BaseSection

    content = (
        "This lesson covers hydraulic actuator maintenance and torque control. "
        "By the end, students will be able to calibrate the actuator to spec."
    )
    sec = BaseSection(title="Hydraulics 101", level=1, page_start=1, content=content, node_id="slide1")
    aug = TrainingPlugin(domain_type="training").augment(sec).domain_augmentation

    assert isinstance(aug, SlideAugmentation)
    assert aug.concepts or aug.objectives, "no concepts or objectives extracted"
    print("\ntraining concepts:", [c.name for c in aug.concepts], "objectives:", aug.objectives)


def test_sustainment_process_fulltext_extracts_notice(monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "file")
    from doc_tools.plugins.sustainment import SustainmentPlugin, SustainmentAugmentation

    text = (
        "Product Discontinuation Notice PDN-500 issued 2026-04-28 by Acme Corp. "
        "Part MPN-A is being discontinued; the recommended replacement is MPN-B. "
        "The last time buy date is 2026-12-31."
    )
    nodes = SustainmentPlugin(domain_type="sustainment").process_fulltext(
        full_text=text, doc_id="d1", elements=[{"type": "NarrativeText", "text": text}]
    )
    assert nodes, "extraction returned no nodes"
    aug = nodes[0].domain_augmentation
    assert isinstance(aug, SustainmentAugmentation)
    # not the exception fallback mock (proves real extraction)
    assert aug.notice.doc_id != "MOCK-PDN-123", "fell back to mock; real extraction failed"
    print("\nsustainment notice:", aug.notice.doc_id, aug.notice.doc_type,
          [p.affected_mpn for p in aug.notice.impacted_parts])
