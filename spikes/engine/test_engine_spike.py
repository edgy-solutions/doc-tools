"""Pressure test for the engine spike: does the config shape hold?

Run from the repo root:
    python -m pytest spikes/engine/test_engine_spike.py -q
or standalone:
    python spikes/engine/test_engine_spike.py

What this proves (and only this — it is a spike, not a parity harness):
  1. The manufacturing wiring executes end-to-end over a hard-ish fixture with
     a FAKE LLM: deterministic blocks fill the pattern/geometry fields, the
     LLM block is called once per operation with a judgment-only spec, and
     reconcile joins the arms per unit.
  2. The pollution and disagreement classes fall out BY CONSTRUCTION:
     an LLM row for an operation the structural pass didn't find becomes an
     llm_only_unit anomaly; a double-armed field is scored
     agree/script_only/llm_only exactly like the corpus report.
  3. Maintenance runs as a ~90-line DELTA config: same engine, TM/NSN
     standards families, a torque block, an MRO judgment schema — no new code.
  4. Config lies fail loudly at load (unknown block kind / unknown dependency).

The real migration oracle stays scripts/mfg_corpus_report.py generalized to
engine-vs-plugin over the corpus; this file only proves the shape composes.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spikes.engine.context import ExtractionContext  # noqa: E402
from spikes.engine.executor import ConfigError, run, validate_config  # noqa: E402
from spikes.engine.loader import load_doctype  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixture: a small work instruction with the known failure shapes —
# a stranded figure marker, spaced standards, a PN, a hazard, a duration.
# --------------------------------------------------------------------------- #
def _elements():
    return [
        {"type": "Title", "text": "Operation 0010 — Apply Conformal Coating",
         "element_id": "e0", "metadata": {"page_number": 1}},
        {"type": "NarrativeText", "element_id": "e1", "metadata": {"page_number": 1},
         "text": "Clean the assembly PN 99-812 with isopropyl alcohol per J STD 001. "
                 "Cure for 2 hours."},
        {"type": "Image", "element_id": "e2",
         "metadata": {"page_number": 1, "image_path": "/tmp/figs/figure-1-2.jpg"},
         "text": ""},
        {"type": "NarrativeText", "element_id": "e3", "metadata": {"page_number": 1},
         "text": "Apply sealant per MIL PRF 81733, observing ESD precautions (Class 1.1)."},
        {"type": "Title", "text": "Operation 0020 — Final Inspection",
         "element_id": "e4", "metadata": {"page_number": 2}},
        {"type": "NarrativeText", "element_id": "e5", "metadata": {"page_number": 2},
         "text": "Inspect torque to 15 ft-lbs per TM 9-1005-317-23. Record results."},
    ]


def _ctx(fake_llm):
    els = _elements()
    return ExtractionContext(
        doc_id="wi_test_doc", elements=els,
        full_text="\n".join(e.get("text", "") for e in els),
        metadata={"domain_type": "manufacturing"},
        services={"llm": fake_llm},
    )


def _fake_llm_mfg(spec, chunk):
    """Judgment-only rows; also emits a partial standards list (migration mode)
    and one POLLUTION unit — an operation id that is not in the document."""
    assert "instruction_text" not in spec["fields"], "verbatim echo snuck back in"
    rows = [{
        "unit_id": chunk["unit_id"],
        "action_verb": "Apply" if chunk["unit_id"] == "0010" else "Inspect",
        "is_value_added": chunk["unit_id"] == "0010",
        "is_safety_critical": True,
        "process_category": "Transformation" if chunk["unit_id"] == "0010" else "Inspection",
        "justification": "spike fixture row",
        # double-armed field: the LLM finds J-STD-001 but misses MIL-PRF-81733
        # (the measured miss shape) and invents nothing here.
        "military_and_industry_standards": (["J-STD-001"] if chunk["unit_id"] == "0010" else []),
    }]
    if chunk["unit_id"] == "0010":
        rows.append({"unit_id": "4500", "action_verb": "Assemble",
                     "is_value_added": True, "is_safety_critical": False,
                     "process_category": "Transformation",
                     "justification": "page-furniture pollution",
                     "military_and_industry_standards": []})
    return rows


def _fake_llm_mro(spec, chunk):
    assert spec["function"] == "ExtractMaintenanceJudgment"
    assert "torque_spec" not in spec["fields"], "regex field leaked into the LLM schema"
    return [{"unit_id": chunk["unit_id"], "action_verb": "Inspect",
             "is_safety_critical": True, "inspection_type": "Dimensional",
             "maintenance_level": "Depot", "justification": "spike fixture row",
             "military_and_industry_standards": []}]


# --------------------------------------------------------------------------- #
# 1 + 2: manufacturing wiring end-to-end
# --------------------------------------------------------------------------- #
def test_manufacturing_config_runs_end_to_end():
    cfg = load_doctype("manufacturing")
    ctx = run(cfg, _ctx(_fake_llm_mfg))

    steps = ctx.results["steps"].data
    units = {u["unit_id"]: u for u in steps["units"]}
    assert set(units) == {"0010", "0020"}, "structural units own the spine"

    u1 = units["0010"]
    # deterministic arm filled the pattern/geometry fields
    assert "J-STD-001" in u1["military_and_industry_standards"]
    assert "MIL-PRF-81733" in u1["military_and_industry_standards"]
    assert u1["internal_part_numbers"] == ["PN-99-812"]
    assert u1["hazard_class"] is not None
    assert u1["estimated_duration_minutes"] == 120
    assert u1["figure_references"] == ["figure-1-2.jpg"], \
        "the stranded [FIGURE] bound geometrically, not via LLM callout text"
    # LLM arm filled judgment only
    assert u1["process_category"] == "Transformation"
    assert u1["is_value_added"] is True

    # the pollution class surfaced by construction
    polluted = [a for a in ctx.results["steps"].anomalies if a["kind"] == "llm_only_unit"]
    assert [a["unit"] for a in polluted] == ["4500"]

    # double-armed diff classes mirror the corpus report
    d = steps["diffs"]["military_and_industry_standards"]
    assert d["agree"] == 1          # J-STD-001
    assert d["script_only"] >= 1    # MIL-PRF-81733 (+ TM on op 0020 if matched)
    assert d["llm_only"] == 0

    # persistence emitted from descriptors, review lane collected the anomalies
    assert len(ctx.results["graph"].data["cypher"]) == 2
    assert any("GOVERNED_BY" in q["query"] for q in ctx.results["graph"].data["cypher"])
    review = ctx.results["review"].data
    assert review["needs_review"] is True
    assert any(it["kind"] == "llm_only_unit" for it in review["review_items"])


# --------------------------------------------------------------------------- #
# 3: maintenance as a delta config — no new code
# --------------------------------------------------------------------------- #
def test_maintenance_is_a_delta_config():
    cfg = load_doctype("maintenance")
    assert cfg["ontology"]["prefix"] == "mro"
    # inherited wiring survived the merge
    assert cfg["blocks"]["figures"]["uses"] == "geometry.figure_binder"
    # inherited enum keys were explicitly removed
    assert "process_category" not in cfg["blocks"]["judgment"]["with"]["scope"]["enums"]

    ctx = run(cfg, _ctx(_fake_llm_mro))
    units = {u["unit_id"]: u for u in ctx.results["steps"].data["units"]}
    u2 = units["0020"]
    assert u2["torque_spec"] == "15-FT-LBS", "torque came from the regex arm"
    assert "TM-9-1005-317-23" in u2["military_and_industry_standards"], \
        "the TM family (maintenance-only DATA) matched"
    assert u2["inspection_type"] == "Dimensional"
    assert u2["maintenance_level"] == "Depot"
    sparql = ctx.results["graph"].data["sparql"]
    assert all("mro:" in s for s in sparql)


# --------------------------------------------------------------------------- #
# 4: config lies fail loudly
# --------------------------------------------------------------------------- #
def test_unknown_block_kind_halts_at_load():
    bad = {"doc_type": "x", "blocks": {"a": {"uses": "regex.made_up", "with": {}}}}
    try:
        validate_config(bad)
        raise AssertionError("unknown block kind must raise ConfigError")
    except ConfigError:
        pass


def test_unknown_dependency_halts_at_load():
    bad = {"doc_type": "x", "blocks": {
        "a": {"uses": "gazetteer", "with": {"terms": []}, "needs": ["ghost"]}}}
    try:
        validate_config(bad)
        raise AssertionError("unknown dependency must raise ConfigError")
    except ConfigError:
        pass


if __name__ == "__main__":
    test_manufacturing_config_runs_end_to_end()
    test_maintenance_is_a_delta_config()
    test_unknown_block_kind_halts_at_load()
    test_unknown_dependency_halts_at_load()
    print("engine spike: all 4 checks passed")
