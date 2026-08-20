"""Minimal in-process engine executor for the doc-type engine spike.

DESIGN SPIKE — not production wiring. See docs/engine-design-spike.md.

The executor is deliberately boring: topological order over the config's
`needs` edges, run each block, record its BlockResult under its id. All
composition intelligence lives in the blocks; all selection lives in the
config. Dagster stays at the coarse stage boundary (parse asset ->
knowledge-graph asset); a block that genuinely earns isolation (a vision pass
wanting its own GPU box) gets promoted by giving it `isolation: true` in
config and having the PRODUCTION executor split the run there — this spike
records the flag and runs in-process regardless.
"""
from __future__ import annotations

from typing import Dict, List

from .blocks import BLOCKS
from .context import BlockResult, ExtractionContext, ENGINE_SPIKE_VERSION


class ConfigError(Exception):
    """A doc-type config referencing unknown blocks/ids fails LOUDLY at load,
    not silently at runtime — the config-lie family's front door."""


def _topo_order(blocks: Dict[str, dict]) -> List[str]:
    order: List[str] = []
    perm, temp = set(), set()

    def visit(bid: str):
        if bid in perm:
            return
        if bid in temp:
            raise ConfigError(f"cycle through block '{bid}'")
        temp.add(bid)
        for dep in blocks[bid].get("needs", []):
            if dep not in blocks:
                raise ConfigError(f"block '{bid}' needs unknown block '{dep}'")
            visit(dep)
        temp.discard(bid)
        perm.add(bid)
        order.append(bid)

    for bid in blocks:
        visit(bid)
    return order


def validate_config(config: dict) -> None:
    blocks = config.get("blocks") or {}
    if not blocks:
        raise ConfigError("doc-type config has no blocks")
    for bid, spec in blocks.items():
        kind = spec.get("uses")
        if kind not in BLOCKS:
            raise ConfigError(
                f"block '{bid}' uses unknown kind '{kind}'. Known kinds: "
                f"{sorted(BLOCKS)}. If the doc type needs new behavior, add a "
                f"TESTED block to the library — do not encode logic in config.")
    _topo_order(blocks)  # raises on cycles / unknown needs


def run(config: dict, ctx: ExtractionContext) -> ExtractionContext:
    """Execute a doc-type config over a context. Returns the same context with
    ctx.results populated (block id -> BlockResult)."""
    validate_config(config)
    blocks: Dict[str, dict] = config["blocks"]
    for bid in _topo_order(blocks):
        spec = blocks[bid]
        fn = BLOCKS[spec["uses"]]
        inputs = {dep: ctx.results[dep] for dep in spec.get("needs", [])}
        try:
            res = fn(ctx, spec.get("with", {}), inputs)
        except Exception as e:
            # A block crash is recorded and halts: downstream blocks would run
            # on absent inputs otherwise. Halting > silent partial (HALT rule).
            raise RuntimeError(f"block '{bid}' ({spec['uses']}) failed: {e}") from e
        res.meta.setdefault("engine_version", ENGINE_SPIKE_VERSION)
        res.meta.setdefault("doc_type", config.get("doc_type"))
        if spec.get("isolation"):
            res.meta["isolation_requested"] = True  # promoted to its own Dagster asset in prod
        ctx.results[bid] = res
    return ctx
