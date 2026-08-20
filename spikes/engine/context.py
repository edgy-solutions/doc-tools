"""Extraction context + block result types for the doc-type engine spike.

DESIGN SPIKE — not production wiring. See docs/engine-design-spike.md.

The contract in one paragraph: a *block* is a small, tested, pure function
over an ExtractionContext. A *doc-type config* SELECTS and PARAMETERIZES
blocks; it never contains logic. The engine executor topologically orders the
blocks by their declared `needs` and runs them in-process. Every block returns
a BlockResult whose `anomalies` list is the miss-path (a miss is a
needs_review row, never a silent null — same contract as
doc_tools/utils/mfg_extractors.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

Anomaly = Dict[str, Any]

# Bump when the context/result contract changes — stamped into engine output
# the same way EXTRACTOR_VERSION is stamped into corpus reports.
ENGINE_SPIKE_VERSION = "0.1.0"


@dataclass
class BlockResult:
    """What every block returns.

    data       — the block's payload (shape is block-specific and documented
                 on the block; downstream blocks receive it via `needs`).
    anomalies  — the miss-path. Routed to the review lane by the review sink;
                 never dropped.
    meta       — provenance for the report/telemetry layer: block version,
                 config hash of the params it ran with, counts.
    """
    data: Any
    anomalies: List[Anomaly] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionContext:
    """Everything a block may read. Blocks WRITE only their own BlockResult.

    elements   — the parsed unstructured element dicts (text.json), the same
                 input both extraction arms read today.
    full_text  — the page-tagged reconstruction (what plugins receive now).
    metadata   — the manifest metadata (domain_type, content_kind, formats...).
    services   — the impure edges, INJECTED: {"llm": callable, "s3": client,
                 ...}. Blocks never construct clients; that keeps every block
                 unit-testable and lets the spike run with a fake LLM. A block
                 that needs a service it wasn't given fails loudly.
    results    — upstream BlockResults keyed by block id (the executor fills
                 this; blocks receive their declared `needs` as a dict too).
    """
    doc_id: str
    elements: List[dict]
    full_text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    services: Dict[str, Any] = field(default_factory=dict)
    results: Dict[str, BlockResult] = field(default_factory=dict)

    def element_text(self, idx: int) -> str:
        el = self.elements[idx]
        return el.get("text", "") or ""

    def page_of(self, idx: int) -> Optional[int]:
        return (self.elements[idx].get("metadata") or {}).get("page_number")
