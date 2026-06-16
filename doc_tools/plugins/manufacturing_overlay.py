"""Overlay field descriptors for manufacturing work-instruction extraction.

The `ManufacturingStep` schema is split into two layers:

- **Base** (hardcoded in the plugin + BAML class): the irreducible identity and
  text of a work instruction — `procedure_id`, `step_id`, `instruction_text`,
  `action_verb`, `tooling`, `figure_references`. Without these the record (and
  the core graph MERGE) is meaningless. Base is stable and public.

- **Overlay** (described here, data-driven): everything layered on top —
  analytical flags, domain classifications, and integration "hooks". Each
  overlay field declares BOTH how it is extracted (a BAML description) AND how
  it is persisted to Neo4j / Jena, so adding or moving a field never requires
  touching `to_graph_queries`.

Two overlays are composed at runtime:
  - `DEFAULT_OVERLAY` — the non-proprietary hooks, committed here.
  - a **proprietary overlay** loaded from a secret JSON file pointed at by
    `MANUFACTURING_OVERLAY_SPEC` (e.g. a mounted K8s secret). Its field
    names/descriptions never enter this repo.

Persistence kinds a field can declare (it may combine several):
  - `neo4j_attr`     -> `SET s.<attr> = $<param>` on the step node
  - `related`        -> typed node + edge off the step (list -> UNWIND, scalar -> conditional)
  - `rdf_literal`    -> `mfg:<step> mfg:<pred> "value"` (scalar/list)
  - `rdf_relation`   -> `mfg:<step> mfg:<pred> <prefix><sanitized><suffix>` (scalar)

This module is pure/deterministic and has no I/O except the optional secret load.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, List, Optional


@dataclass(frozen=True)
class RelatedNode:
    """A typed node + edge created off the step node for each value."""
    label: str        # Neo4j label, e.g. "Standard"
    rel_type: str     # relationship type, e.g. "GOVERNED_BY"
    id_prefix: str    # node id prefix, e.g. "std_"
    value_prop: str   # property set on the related node, e.g. "name"


@dataclass(frozen=True)
class RdfRelation:
    """An RDF object-property triple to a derived IRI (vs. a literal)."""
    predicate: str               # e.g. "governedBy"
    target_prefix: str           # e.g. "iof:"
    target_suffix: str           # e.g. "_Standard"
    strip_chars: tuple = ("-", " ")  # characters removed to form a safe local name


@dataclass(frozen=True)
class ObjectField:
    """One property of an object inside an ``object_list`` overlay field."""
    name: str
    kind: str = "scalar"   # scalar | int | bool
    description: str = ""


@dataclass(frozen=True)
class ObjectNode:
    """Persistence for an ``object_list``: each item -> a typed node + edge."""
    label: str                            # Neo4j label for each item, e.g. "BomItem"
    rel_type: str                         # edge from the step to each item
    id_props: tuple = ()                  # sub-field names whose values form the item id
    rdf_predicate: Optional[str] = None   # reserved; RDF for object lists is future work


@dataclass(frozen=True)
class OverlayField:
    name: str
    kind: str                    # "scalar" | "list" | "bool" | "int" | "enum" | "object_list"
    description: str = ""        # BAML extraction instruction (the @description)
    optional: bool = True
    scope: str = "step"          # "step" (per ManufacturingStep) | "document" (per MatAugmentation)
    # --- persistence ---
    neo4j_attr: bool = False
    neo4j_attr_name: Optional[str] = None
    neo4j_default: Any = None    # value used when None (e.g. -1 for duration)
    related: Optional[RelatedNode] = None
    rdf_literal: Optional[str] = None      # predicate for a literal triple
    rdf_relation: Optional[RdfRelation] = None
    # --- nested object lists (kind == "object_list") ---
    item_properties: Optional[List["ObjectField"]] = None  # the per-item sub-schema
    object_node: Optional["ObjectNode"] = None             # how each item persists to the graph
    proprietary: bool = False

    @property
    def attr(self) -> str:
        return self.neo4j_attr_name or self.name


# ---------------------------------------------------------------------------
# Default (non-proprietary) overlay.
#
# Inconsistency fixes applied here (see the characterization golden diff):
#   * consumables, standard_ref: were Jena-only -> now also Neo4j.
#   * analytical flags + justification + duration: were Neo4j-only -> now also RDF.
#   * standards / internal_part_numbers / slang: were dual-written (step list
#     attribute AND relationship); the redundant list attribute is dropped,
#     keeping the richer typed relationship.
# ---------------------------------------------------------------------------
DEFAULT_OVERLAY: List[OverlayField] = [
    OverlayField(
        name="is_value_added", kind="bool", optional=False,
        description="True ONLY if the step physically transforms the product (machining, curing, sealant). False for inspection, movement, or waiting.",
        neo4j_attr=True, rdf_literal="isValueAdded",
    ),
    OverlayField(
        name="is_safety_critical", kind="bool", optional=False,
        description="True if the step involves static grounding, explosive hazard mitigation, environmental safety, or regulatory sign-offs.",
        neo4j_attr=True, rdf_literal="isSafetyCritical",
    ),
    OverlayField(
        name="process_category", kind="enum", optional=False,
        description="The functional category of the manufacturing process.",
        neo4j_attr=True, rdf_literal="hasProcessCategory",
    ),
    OverlayField(
        name="justification", kind="scalar", optional=False,
        description="A 1-sentence explanation of why the value-added and safety-critical flags were chosen.",
        neo4j_attr=True, rdf_literal="hasJustification",
    ),
    OverlayField(
        name="estimated_duration_minutes", kind="int", optional=True,
        description="Mentioned time constraints, cure times, or labor durations. Null if none.",
        neo4j_attr=True, neo4j_default=-1, rdf_literal="estimatedDurationMinutes",
    ),
    OverlayField(
        name="consumables", kind="list", optional=True,
        description="Consumable materials, e.g. ['Sealant MIL-S-81733']. Empty list if none.",
        neo4j_attr=True, rdf_literal="consumesMaterial",
    ),
    OverlayField(
        name="standard_ref", kind="scalar", optional=True,
        description="A single governing standard reference, e.g. 'ISO-9001'. Null if none.",
        neo4j_attr=True,
        rdf_relation=RdfRelation(predicate="governedBy", target_prefix="iof:", target_suffix="_Standard"),
    ),
    OverlayField(
        name="hazard_class", kind="enum", optional=True,
        description="Explosives/process safety hazard class. Null if none.",
        related=RelatedNode("Hazard", "HAS_HAZARD", "hazard_", "class"),
        rdf_literal="hasHazardClass",
    ),
    OverlayField(
        name="required_cert", kind="enum", optional=True,
        description="Quality/personnel certification requirement. Null if none.",
        related=RelatedNode("Certification", "REQUIRES_CERT", "cert_", "certification"),
        rdf_literal="requiresCertification",
    ),
    OverlayField(
        name="military_and_industry_standards", kind="list", optional=True,
        description="Formal standards (MIL-, MS, AN*, NAS*, AS*, J-STD-*, IPC-*, ASTM-, SAE-, ANSI-, ISO-, NADCAP*). Normalize to single hyphens. Empty array if none.",
        related=RelatedNode("Standard", "GOVERNED_BY", "std_", "name"),
    ),
    OverlayField(
        name="internal_part_numbers", kind="list", optional=True,
        description="Internal proprietary part/assembly/drawing numbers (strip the 'PN' prefix). Empty array if none.",
        related=RelatedNode("Part", "REQUIRES_PART", "part_", "part_number"),
    ),
    OverlayField(
        name="material_and_hardware_slang", kind="list", optional=True,
        description="Generic nouns for consumables/hardware lacking a part number (e.g. 'RTV Silicone', 'Loctite'). Empty array if none.",
        related=RelatedNode("SlangTerm", "USABLE_SLANG", "slang_", "term"),
    ),
]


# ---------------------------------------------------------------------------
# Proprietary overlay (loaded from a secret, never committed here).
# ---------------------------------------------------------------------------
def _field_from_dict(d: dict) -> OverlayField:
    related = d.get("related")
    rdf_rel = d.get("rdf_relation")
    props = d.get("properties")          # per-item sub-schema for object_list
    obj_node = d.get("object_node")      # how each item persists
    return OverlayField(
        name=d["name"],
        kind=d.get("kind", "scalar"),
        description=d.get("description", ""),
        optional=d.get("optional", True),
        scope=d.get("scope", "step"),
        neo4j_attr=d.get("neo4j_attr", False),
        neo4j_attr_name=d.get("neo4j_attr_name"),
        neo4j_default=d.get("neo4j_default"),
        related=RelatedNode(**related) if related else None,
        rdf_literal=d.get("rdf_literal"),
        rdf_relation=RdfRelation(**rdf_rel) if rdf_rel else None,
        item_properties=[
            ObjectField(name=p["name"], kind=p.get("kind", "scalar"), description=p.get("description", ""))
            for p in props
        ] if props else None,
        object_node=ObjectNode(
            label=obj_node["label"],
            rel_type=obj_node["rel_type"],
            id_props=tuple(obj_node.get("id_props", [])),
            rdf_predicate=obj_node.get("rdf_predicate"),
        ) if obj_node else None,
        proprietary=True,
    )


def load_proprietary_overlay() -> List[OverlayField]:
    """Load proprietary field descriptors from the secret JSON pointed at by
    MANUFACTURING_OVERLAY_SPEC. Returns [] when unset (the public default)."""
    path = os.getenv("MANUFACTURING_OVERLAY_SPEC")
    if not path or not os.path.exists(path):
        return []
    with open(path, "r") as f:
        spec = json.load(f)
    return [_field_from_dict(d) for d in spec.get("fields", [])]


def active_overlay() -> List[OverlayField]:
    """The full ordered overlay = default (public) + proprietary (secret)."""
    return [*DEFAULT_OVERLAY, *load_proprietary_overlay()]


# ---------------------------------------------------------------------------
# Rendering: turn an overlay field + a step's value into graph fragments.
# Deterministic; mirrors the shapes the original hardcoded writer produced.
# ---------------------------------------------------------------------------
def _present(value: Any) -> bool:
    return value is not None and value != "" and value != []


def render_step_attrs(fields: List[OverlayField], step: Any) -> tuple[list[str], dict]:
    """SET clauses + params for overlay fields persisted as step attributes."""
    clauses: list[str] = []
    params: dict = {}
    for f in fields:
        if f.scope == "document":
            continue
        if not f.neo4j_attr:
            continue
        raw = _enum_value(getattr(step, f.name, None))
        if raw is None:
            if f.neo4j_default is not None:
                raw = f.neo4j_default
            elif f.optional:
                continue  # don't emit SET s.x = null for an absent optional scalar
        clauses.append(f"s.{f.attr} = ${f.attr}")
        params[f.attr] = raw
    return clauses, params


def render_related_blocks(fields: List[OverlayField], step: Any) -> tuple[list[str], dict]:
    """Cypher blocks (+params) for overlay fields that create typed nodes/edges."""
    blocks: list[str] = []
    params: dict = {}
    for f in fields:
        if f.scope == "document":
            continue
        if not f.related:
            continue
        r = f.related
        value = _enum_value(getattr(step, f.name, None))
        if f.kind == "list":
            if not _present(value):
                continue
            param = f.name
            params[param] = list(value)
            blocks.append(
                f"WITH s UNWIND ${param} AS val "
                f'MERGE (n:{r.label}:{{domain}} {{id: "{r.id_prefix}" + val}}) '
                f"SET n.{r.value_prop} = val "
                f"MERGE (s)-[:{r.rel_type}]->(n)"
            )
        else:  # scalar/enum -> conditional single node
            if not _present(value):
                continue
            id_param = f"{f.name}_id"
            val_param = f.name
            params[id_param] = f"{r.id_prefix}{value}"
            params[val_param] = value
            blocks.append(
                f"WITH s "
                f"MERGE (n:{r.label}:{{domain}} {{id: ${id_param}}}) "
                f"SET n.{r.value_prop} = ${val_param} "
                f"MERGE (s)-[:{r.rel_type}]->(n)"
            )
    return blocks, params


def render_object_blocks(fields: List[OverlayField], step: Any) -> tuple[list[str], dict]:
    """Cypher blocks (+params) for object_list fields: each item becomes a typed
    node with one property per sub-field, plus an edge from the step. Items must
    already be plain dicts (see coerce_extracted)."""
    blocks: list[str] = []
    params: dict = {}
    for f in fields:
        if f.scope == "document":
            continue
        if f.kind != "object_list" or not f.object_node:
            continue
        value = getattr(step, f.name, None)
        if not _present(value):
            continue
        on = f.object_node
        sub_names = [p.name for p in (f.item_properties or [])]
        id_props = list(on.id_props) or sub_names[:1]
        param = f.name
        params[param] = [dict(it) for it in value]
        id_expr = ' + "_" + '.join(f'toString(coalesce(item.{p}, ""))' for p in id_props) or '""'
        block = (
            f"WITH s UNWIND ${param} AS item "
            f'MERGE (n:{on.label}:{{domain}} {{id: "{f.name}_" + {id_expr}}}) '
        )
        set_expr = ", ".join(f"n.{p} = item.{p}" for p in sub_names)
        if set_expr:
            block += f"SET {set_expr} "
        block += f"MERGE (s)-[:{on.rel_type}]->(n)"
        blocks.append(block)
    return blocks, params


def render_sparql_lines(fields: List[OverlayField], step: Any, step_uri: str) -> list[str]:
    """RDF triples for overlay fields (literals and derived-IRI relations)."""
    lines: list[str] = []
    for f in fields:
        if f.scope == "document":
            continue
        value = _enum_value(getattr(step, f.name, None))
        if f.rdf_literal:
            if f.kind == "list":
                for v in (value or []):
                    lines.append(f'{step_uri} mfg:{f.rdf_literal} "{_lit(v)}" .')
            elif _present(value) or isinstance(value, bool):
                lines.append(f'{step_uri} mfg:{f.rdf_literal} "{_lit(value)}" .')
        if f.rdf_relation and _present(value):
            rr = f.rdf_relation
            safe = str(value)
            for ch in rr.strip_chars:
                safe = safe.replace(ch, "_" if ch == " " else "")
            lines.append(f"{step_uri} mfg:{rr.predicate} {rr.target_prefix}{safe}{rr.target_suffix} .")
    return lines


def proprietary_field_names(fields: List[OverlayField]) -> List[str]:
    """Names of the secret-loaded (proprietary) overlay fields."""
    return [f.name for f in fields if f.proprietary]


def coerce_extracted(fields: List[OverlayField], source: Any) -> dict:
    """Pull proprietary overlay values off a BAML response object for the mirror
    model. object_list items are normalized to plain dicts (so they serialize
    into extraction.json and pass to Cypher cleanly); scalars are enum-unwrapped.
    """
    out: dict = {}
    for f in fields:
        if not f.proprietary:
            continue
        raw = getattr(source, f.name, None)
        if f.kind == "object_list":
            out[f.name] = [_to_dict(it) for it in (raw or [])]
        else:
            out[f.name] = _enum_value(raw)
    return out


def _to_dict(item: Any) -> dict:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if hasattr(item, "__dict__"):
        return dict(item.__dict__)
    return {"value": item}


def _item_class_name(field_name: str) -> str:
    """Unique BAML class name for an object_list field's item type."""
    return "".join(p.capitalize() for p in field_name.replace("-", "_").split("_")) + "Item"


def _baml_scalar_type(tb: Any, kind: str) -> Any:
    if kind == "int":
        return tb.int()
    if kind == "bool":
        return tb.bool()
    return tb.string()


def _baml_field_type(tb: Any, f: OverlayField) -> Any:
    """Map an overlay field kind to a BAML TypeBuilder FieldType."""
    if f.kind == "object_list":
        # Build a dynamic nested class from the per-item sub-schema, then list it.
        cls = tb.add_class(_item_class_name(f.name))
        for sub in (f.item_properties or []):
            prop = cls.add_property(sub.name, _baml_scalar_type(tb, sub.kind))
            if sub.description:
                prop.description(sub.description)
        return cls.type().list()
    if f.kind == "list":
        return tb.string().list()
    if f.kind == "int":
        t = tb.int()
        return t.optional() if f.optional else t
    if f.kind == "bool":
        return tb.bool()
    # scalar / enum -> string (enums are injected as free strings in the
    # proprietary path; their allowed values live in the secret, not here)
    t = tb.string()
    return t.optional() if f.optional else t


def inject_proprietary_properties(tb: Any, fields: List[OverlayField]) -> List[str]:
    """Add proprietary overlay fields via TypeBuilder so the LLM extracts them.
    Step-scope fields are injected onto the @@dynamic ManufacturingStep;
    document-scope fields onto MatAugmentation. Non-proprietary fields stay in
    the static BAML schema and are skipped. Returns the injected field names."""
    injected: List[str] = []
    for f in fields:
        if not f.proprietary:
            continue
        target = tb.MatAugmentation if f.scope == "document" else tb.ManufacturingStep
        prop = target.add_property(f.name, _baml_field_type(tb, f))
        if f.description:
            prop.description(f.description)
        injected.append(f.name)
    return injected


def extract_document_fields(responses: list, fields: List[OverlayField]) -> dict:
    """Collect + merge document-scope overlay values across the per-chunk BAML
    responses (each a MatAugmentation). Non-empty values are merged so a
    multi-chunk document keeps every chunk's contribution: lists are unioned,
    strings concatenated distinctly, scalars take the first non-empty.
    """
    out: dict = {}
    for resp in responses:
        for f in fields:
            if f.scope != "document" or not f.proprietary:
                continue
            v = _enum_value(getattr(resp, f.name, None))
            if f.kind == "object_list":
                v = [_to_dict(it) for it in (v or [])]
            if v in (None, "", []):
                continue
            if f.name not in out:
                out[f.name] = v
            elif isinstance(out[f.name], list) and isinstance(v, list):
                out[f.name] = out[f.name] + [x for x in v if x not in out[f.name]]
            elif isinstance(out[f.name], str) and isinstance(v, str) and v not in out[f.name]:
                out[f.name] = out[f.name] + "\n\n" + v
    return out


def _enum_value(v: Any) -> Any:
    """BAML may return enum wrappers; unwrap to the plain value."""
    return getattr(v, "value", v) if v is not None else None


def _lit(v: Any) -> str:
    """Sanitize a value for embedding in a SPARQL string literal.

    Delegates to ``escape_sparql_string`` so newlines / backslashes / tabs
    / unescaped quotes are properly escaped (the prior implementation
    only stripped raw double-quotes, which caused Fuseki 400s on any
    multi-line extracted text — see jena_client.escape_sparql_string).
    """
    from doc_tools.utils.jena_client import escape_sparql_string
    return escape_sparql_string(str(v))
