"""Truth check: doc-tools' telemetry mapping names only fields doc-tools produces.

The provenance-telemetry leaf validates the mapping's SHAPE (that its slots and
score encodings are a closed, known set). It CANNOT know whether ``crops_failed``
or ``doc_id`` are real doc-tools fields — that truth lives here, with the
vocabulary owner (ADR-0038's two-tier validation).

The single source of truth for the projected fields is
``doc_tools.telemetry.build_trace_values``; this test pins the mapping to it, so a
renamed key or a dangling mapping entry trips CI instead of silently emitting
nothing to Langfuse.
"""
import importlib.util
import os

import pytest

# The leaf is a git dependency; skip cleanly in a checkout that hasn't installed it.
pytest.importorskip("provenance_telemetry")

from provenance_telemetry import load_mapping  # noqa: E402

# Load the thin telemetry seam by FILE PATH, bypassing doc_tools/__init__ (which
# eagerly imports dagster). telemetry.py is deliberately heavy-import-free so this
# contract is testable without standing up the plugin — the test honors that.
_TELEMETRY_PY = os.path.join(os.path.dirname(__file__), "..", "doc_tools", "telemetry.py")
_spec = importlib.util.spec_from_file_location("dt_telemetry_undertest", _TELEMETRY_PY)
_telemetry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_telemetry)
build_trace_values = _telemetry.build_trace_values
_MAPPING_PATH = _telemetry._MAPPING_PATH


def _sample_values():
    """A representative extraction result — degraded on purpose (needs_review=True,
    2/5 crops failed) so the honest-degradation scores are exercised."""
    return build_trace_values(
        doc_id="NOTICE-1",
        header_d={"doc_id": "NOTICE-1", "doc_type": "PCN"},
        stats={"crops_failed": 2, "n_tables": 5, "vision_used": True},
        needs_review=True,
        domain="sustainment",
        prompt_refs="header_prompt:sha1:abc123def456",
    )


def test_mapping_file_is_valid_and_nonempty():
    # load_mapping raises on a malformed file (unknown slot / bad encoding); the
    # module-level fallback would hide that, so load the file DIRECTLY here.
    m = load_mapping(_MAPPING_PATH)
    assert m.slots, "mapping declares no slots"
    assert "trace_id" in m.slots, "a trace with no id cannot be joined by the sensor"


def test_every_mapped_trace_field_has_a_provider_and_vice_versa():
    m = load_mapping(_MAPPING_PATH)
    provided = set(_sample_values())
    # slots reference the source FIELD (dict value); tags/metadata/scores reference
    # the field NAME directly. content_bearing is span-level (redacted when present),
    # not part of the doc-level trace projection, so it is excluded here.
    mapped = set(m.slots.values()) | set(m.tags) | set(m.metadata) | set(m.scores)

    dangling = mapped - provided       # mapping names a field nobody provides -> dead telemetry
    dropped = provided - mapped        # code computes a field nobody maps -> silently discarded
    assert not dangling, f"mapping references fields with no provider: {sorted(dangling)}"
    assert not dropped, f"build_trace_values emits unmapped fields (silently dropped): {sorted(dropped)}"


def test_scores_carry_the_honest_degradation_signals():
    # These two ARE the reason telemetry exists for doc-tools: a partial extraction
    # must be visible as a score, not buried. Guard against their removal.
    m = load_mapping(_MAPPING_PATH)
    assert {"needs_review", "crops_failed"} <= set(m.scores)


def test_content_bearing_is_declared_for_redaction():
    # The hash-don't-drop contract only bites if fields are declared content-bearing.
    m = load_mapping(_MAPPING_PATH)
    assert m.content_bearing, "no content-bearing fields declared -> nothing gets redacted"
