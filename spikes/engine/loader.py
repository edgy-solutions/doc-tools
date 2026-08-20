"""Doc-type config loader for the engine spike: YAML (JSON fallback) + `extends`.

DESIGN SPIKE — not production wiring. See docs/engine-design-spike.md.

`extends: <name>` deep-merges a child config over its parent — the mechanism
that makes "maintenance is manufacturing with different data" a small delta
file (~100 lines, not a copy). NB the honest number: parameter LISTS replace
wholesale on merge by design (a standards-family list is one reviewable unit,
not a patch series), so adding TM/FM/NSN families and a torque field means
restating those two lists — that is what pushes it past the ~40 lines an
early estimate guessed. The falsifiable metric was never line count anyway:
it is ZERO NEW CODE, and that holds. Merging is DATA composition only:
`blocks` is a MAPPING (id -> spec) precisely so a child can override one
block's params without restating the wiring. Setting a block id to null removes it.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Optional

DOCTYPE_DIR = os.path.join(os.path.dirname(__file__), "doctypes")


def _deep_merge(base: dict, override: dict) -> dict:
    for k, v in (override or {}).items():
        if v is None and k in base:
            del base[k]           # explicit null removes an inherited key
        elif isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _read(path: str) -> dict:
    text = open(path, "r", encoding="utf-8").read()
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        return json.loads(text)


def load_doctype(name: str, doctype_dir: Optional[str] = None) -> dict:
    d = doctype_dir or DOCTYPE_DIR
    for ext in (".yaml", ".yml", ".json"):
        path = os.path.join(d, name + ext)
        if os.path.exists(path):
            cfg = _read(path)
            parent_name = cfg.pop("extends", None)
            if parent_name:
                parent = load_doctype(parent_name, d)
                cfg = _deep_merge(copy.deepcopy(parent), cfg)
            return cfg
    raise FileNotFoundError(f"no doc-type config named '{name}' in {d}")
