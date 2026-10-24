"""Per-domain graph overlay names (training-workbench contract section 4.3).

The generic structure (``Document``/``Chunk`` labels, ``HAS_CHILD``) is written
for every kind. A domain listed here ALSO gets an extra parent label, an extra
child label and an extra parent->child edge; a domain with no entry gets
nothing extra. The names live here, as data, so neither this repo nor the
workbench renames anything by hand.

Names are interpolated into Cypher (labels and edge types cannot be
parameters), so ``overlay_for`` refuses anything that is not a plain identifier.
"""
import re
from typing import Dict, NamedTuple, Optional

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class GraphOverlay(NamedTuple):
    parent_label: str
    child_label: str
    edge: str


GRAPH_OVERLAYS: Dict[str, GraphOverlay] = {
    "training": GraphOverlay(parent_label="Course", child_label="Slide", edge="HAS_SLIDE"),
}


def overlay_for(domain_type: str) -> Optional[GraphOverlay]:
    overlay = GRAPH_OVERLAYS.get(domain_type)
    if overlay is None:
        return None
    for name in overlay:
        if not _IDENT.match(name):
            raise ValueError(f"graph overlay name {name!r} is not a plain identifier")
    return overlay
