"""doc-tools telemetry glue (ADR-0038).

The thin seam between the extraction and the provenance-telemetry leaf. Kept free
of heavy imports (no baml / dagster) on purpose: the mapping and the projected-
values contract can be unit-tested here without standing up the whole plugin, and
that test is the "vocabulary owner validates truth" tier — the leaf validates the
mapping's SHAPE, this repo validates that every field the mapping names is a field
doc-tools actually produces.

When the leaf (or Langfuse) is absent, the re-exported primitives are no-ops, so
extraction keeps its zero-Langfuse-dependency property in file-mode.
"""
from __future__ import annotations

import os
from typing import Any, Dict

_MAPPING_PATH = os.path.join(os.path.dirname(__file__), "config", "telemetry-mapping.yaml")

try:
    from provenance_telemetry import traced, set_trace_standard, load_mapping

    try:
        MAPPING = load_mapping(_MAPPING_PATH)
    except Exception:  # a malformed/absent file -> the API stays live, emits nothing
        MAPPING = load_mapping({})
except Exception:  # provenance-telemetry not installed -> pure no-ops
    def traced(name=None, as_type=None):  # type: ignore[misc]
        def _deco(fn):
            return fn
        return _deco

    def set_trace_standard(*_a, **_k):  # type: ignore[misc]
        return None

    MAPPING = None


def build_trace_values(*, doc_id: str, header_d: Dict[str, Any], stats: Dict[str, Any],
                       needs_review: bool, domain: str, prompt_refs: str) -> Dict[str, Any]:
    """The flat provenance dict projected onto the extraction trace.

    SINGLE SOURCE OF TRUTH for which fields telemetry carries. The mapping is
    checked against these keys in tests: a mapping entry with no provider here is
    dead telemetry; a key here with no mapping entry is silently dropped. Keep the
    two in lockstep — the test enforces it.
    """
    return {
        "request_key": header_d.get("doc_id") or doc_id,
        "authz_id": "svc:doc-tools",
        "build_sha": os.getenv("LANGFUSE_RELEASE"),   # deployed git SHA (trace release)
        "environment": os.getenv("DEPLOY_ENV"),       # sandbox|work|prod (trace tag)
        "engine": "doc-tools",
        "domain": domain,
        "doc_type": header_d.get("doc_type") or "PCN",
        "doc_id": header_d.get("doc_id") or doc_id,
        "model": os.getenv("LLM_MODEL"),
        "prompt_version": prompt_refs,                # sha1 of the header + parts prompts (Phase 4)
        "vision_used": stats.get("vision_used"),
        "needs_review": 1.0 if needs_review else 0.0,
        "crops_failed": [stats.get("crops_failed", 0), stats.get("n_tables") or 1],
    }
