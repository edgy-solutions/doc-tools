"""Live: a Section-subtree replace leaves Course, Slide, Concept, TEACHES and ALIGNS_TO alone.

Needs a real Neo4j (NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD) and is outside the
default run: ``pytest -m neo4j_live tests/test_section_replace_survival.py``. The
logic lives in ``scripts/training_section_replace_survival.py`` so it can also run
in a pod with no pytest. It writes only tagged ``zz-survival-`` data and deletes it.
"""
import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.neo4j_live

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "training_section_replace_survival.py"


@pytest.mark.skipif(not os.getenv("NEO4J_URI"),
                    reason="NEO4J_URI is unset: this test needs a live Neo4j (neo4j_live)")
def test_section_replace_survival():
    from doc_tools.utils.neo4j_client import Neo4jClient

    spec = importlib.util.spec_from_file_location("training_section_replace_survival", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    client = Neo4jClient()
    try:
        report = mod.run(client)
    finally:
        client.close()
    assert report["problems"] == [], report
    assert report["left_after_cleanup"] == 0
