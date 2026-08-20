"""The block library for the doc-type engine spike.

DESIGN SPIKE — not production wiring. See docs/engine-design-spike.md.

Three categories, one signature:

    block(ctx: ExtractionContext, params: dict, inputs: dict[str, BlockResult])
        -> BlockResult

  * Deterministic extractors — regex / gazetteer / geometry / structural /
    parse. These DELEGATE to doc_tools.utils.mfg_extractors: the engine does
    not fork the tested extractors, it wires them. Per-domain differences
    (TM/FM/NSN families for maintenance, torque specs, ...) are params — DATA.
  * LLM extractors — one `llm.extract` block parameterized by function name,
    chunking policy and the judgment-only field list. The LLM callable itself
    is a SERVICE (ctx.services["llm"]) so the engine is testable offline and
    the BAML/TypeBuilder wiring stays at one seam.
  * Control + sinks — reconcile (merge arms, emit diff classes), tiered
    (first-non-empty fallback chain — sustainment's text-layer→vision shape),
    graph_map (descriptor-driven persistence), review_lane (anomaly sink).

THE RULE THAT KEEPS THE CONFIG HONEST: when a doc type needs behavior no block
provides, add a block HERE (tested code) — never a config hack. Config only
selects and parameterizes.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List

from .context import Anomaly, BlockResult, ExtractionContext

# The deterministic engine already built for manufacturing — reused, not forked.
# Loaded BY FILE PATH rather than `from doc_tools.utils import ...`, because the
# doc_tools package __init__ eager-imports Dagster (definitions), which the block
# library does not need — importing through the package would break the spike's
# offline-runnable claim. Same import discipline as scripts/mfg_corpus_report.py
# and scripts/mfg_deterministic_gate.py.
import importlib.util as _ilu
import os as _os

_MX_PATH = _os.path.abspath(
    _os.path.join(_os.path.dirname(__file__), "..", "..", "doc_tools", "utils", "mfg_extractors.py"))
_spec = _ilu.spec_from_file_location("mfg_extractors", _MX_PATH)
det = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(det)

BLOCKS: Dict[str, Callable] = {}


def register(kind: str):
    def deco(fn):
        BLOCKS[kind] = fn
        fn.block_kind = kind
        return fn
    return deco


def _per_element(ctx: ExtractionContext, fn) -> Dict[int, Any]:
    """Run a text->value extractor over every element; keep non-empty hits."""
    out: Dict[int, Any] = {}
    for i in range(len(ctx.elements)):
        v = fn(ctx.element_text(i))
        if v not in (None, "", []):
            out[i] = v
    return out


# --------------------------------------------------------------------------- #
# Deterministic: structural
# --------------------------------------------------------------------------- #
@register("structural.operations")
def structural_operations(ctx, params, inputs) -> BlockResult:
    """Operation/procedure numbers read from heading elements, WITH the element
    span each operation owns (heading index .. next heading). The span is what
    makes structural chunking and per-operation reconciliation possible.

    data: {"operations": [{"id", "title_index", "span": [start, end)}], "ids": [...]}
    """
    cfg = {"operations": {"title_types": params.get("title_types", ["Title"]),
                          "patterns": params.get("patterns", [])}}
    ttypes = set(cfg["operations"]["title_types"])
    heads: List[tuple] = []  # (element_index, op_id)
    for i, el in enumerate(ctx.elements):
        if el.get("type") not in ttypes:
            continue
        text = el.get("text", "") or ""
        for pat in cfg["operations"]["patterns"]:
            m = re.search(pat, text)
            if m:
                heads.append((i, m.group(1)))
                break
    ops = []
    for n, (idx, op_id) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(ctx.elements)
        ops.append({"id": op_id, "title_index": idx, "span": [idx, end]})
    anomalies: List[Anomaly] = []
    if not ops:
        anomalies.append({"kind": "no_operations",
                          "detail": "no heading matched an operation pattern; "
                                    "reconcile will fall back to one document-level span"})
    return BlockResult(data={"operations": ops, "ids": [o["id"] for o in ops]},
                       anomalies=anomalies,
                       meta={"extractor_version": det.EXTRACTOR_VERSION})


# --------------------------------------------------------------------------- #
# Deterministic: regex / gazetteer / parse — thin wrappers over mfg_extractors
# --------------------------------------------------------------------------- #
@register("regex.standards")
def regex_standards(ctx, params, inputs) -> BlockResult:
    """data: {"by_element": {idx: [canonical ids]}, "all": [...]}"""
    cfg = {"standards": {"families": params["families"],
                         "near_miss": params.get("near_miss")}}
    by_el: Dict[int, List[str]] = {}
    anomalies: List[Anomaly] = []
    seen: List[str] = []
    for i in range(len(ctx.elements)):
        found, anoms = det.extract_standards(ctx.element_text(i), cfg)
        if found:
            by_el[i] = found
            for f in found:
                if f not in seen:
                    seen.append(f)
        for a in anoms:
            a["element_index"] = i
        anomalies.extend(anoms)
    return BlockResult(data={"by_element": by_el, "all": seen}, anomalies=anomalies,
                       meta={"extractor_version": det.EXTRACTOR_VERSION})


@register("regex.patterns")
def regex_patterns(ctx, params, inputs) -> BlockResult:
    """Generic whole-token pattern lists (part numbers, torque specs, NSNs...).
    data: {"by_element": {idx: [values]}, "all": [...]}"""
    cfg = {"part_numbers": {"patterns": params["patterns"]}}
    by_el: Dict[int, List[str]] = {}
    seen: List[str] = []
    for i in range(len(ctx.elements)):
        vals, _ = det.extract_part_numbers(ctx.element_text(i), cfg)
        if vals:
            by_el[i] = vals
            for v in vals:
                if v not in seen:
                    seen.append(v)
    return BlockResult(data={"by_element": by_el, "all": seen},
                       meta={"extractor_version": det.EXTRACTOR_VERSION})


@register("gazetteer")
def gazetteer(ctx, params, inputs) -> BlockResult:
    """data: {"by_element": {idx: [terms]}, "all": [...]}"""
    cfg = {"slang": {"gazetteer": params["terms"]}}
    by_el = _per_element(ctx, lambda t: det.extract_slang(t, cfg))
    all_terms: List[str] = []
    for vals in by_el.values():
        for v in vals:
            if v not in all_terms:
                all_terms.append(v)
    return BlockResult(data={"by_element": by_el, "all": all_terms})


@register("regex.hazard")
def regex_hazard(ctx, params, inputs) -> BlockResult:
    """data: {"by_element": {idx: hazard}}"""
    cfg = {"hazard": {"pattern": params["pattern"], "lexicon": params.get("lexicon", [])}}
    return BlockResult(data={"by_element": _per_element(ctx, lambda t: det.extract_hazard(t, cfg))})


@register("parse.duration")
def parse_duration(ctx, params, inputs) -> BlockResult:
    """data: {"by_element": {idx: minutes}}"""
    cfg = {"durations": {"pattern": params["pattern"], "to_minutes": params["to_minutes"]}}
    return BlockResult(data={"by_element": _per_element(ctx, lambda t: det.extract_duration_minutes(t, cfg))})


@register("geometry.figure_binder")
def geometry_figure_binder(ctx, params, inputs) -> BlockResult:
    """The deterministic figure->step binder (the three-plugin fix), unchanged.
    data: {"bindings": [...], "by_element": {step_element_index: [figure names]}}"""
    cfg = {"figure_binder": {
        "same_page_only": params.get("same_page_only", True),
        "prefer": params.get("prefer", "preceding"),
        "marker_types": params.get("marker_types", ["Image", "Figure"]),
        "step_types": params.get("step_types", ["NarrativeText", "ListItem"]),
    }}
    bindings, anomalies = det.bind_figures_to_steps(ctx.elements, cfg)
    by_el: Dict[int, List[str]] = {}
    id_to_idx = {el.get("element_id"): i for i, el in enumerate(ctx.elements)}
    for b in bindings:
        idx = id_to_idx.get(b["step_element_id"])
        if idx is not None:
            by_el.setdefault(idx, []).append(b["figure"])
    return BlockResult(data={"bindings": bindings, "by_element": by_el},
                       anomalies=anomalies,
                       meta={"extractor_version": det.EXTRACTOR_VERSION})


# --------------------------------------------------------------------------- #
# LLM extraction — one block, thin judgment-only schemas, injected callable
# --------------------------------------------------------------------------- #
@register("llm.extract")
def llm_extract(ctx, params, inputs) -> BlockResult:
    """Call the LLM ONCE PER STRUCTURAL CHUNK with a judgment-only field list.

    params:
      function  — the BAML function name (resolved by the service in prod)
      fields    — the judgment fields the schema carries. THIS is the
                  anti-attention-disease lever: the schema the model sees is
                  exactly this list, not an 18-field spine.
      chunking  — "structural" (per operation span, needs an operations input),
                  "whole" (one call), or "per_element".
      scope     — optional extra params passed through to the service
                  (enum values, prompt name, ...).

    services["llm"](spec: dict, chunk: dict) -> list[dict]  # rows
      spec  = {"function", "fields", "scope"}
      chunk = {"unit_id", "text", "element_span"}

    data: {"rows": [ {unit_id, **judgment fields} ]}
    """
    llm = ctx.services.get("llm")
    if llm is None:
        raise RuntimeError("llm.extract: no 'llm' service injected")
    spec = {"function": params["function"], "fields": params["fields"],
            "scope": params.get("scope", {})}
    chunks: List[dict] = []
    if params.get("chunking", "structural") == "structural":
        ops_input = inputs.get("operations")
        ops = (ops_input.data["operations"] if ops_input else []) or []
        if not ops:  # fall back to one whole-document unit — never zero calls
            chunks = [{"unit_id": "__doc__", "text": ctx.full_text,
                       "element_span": [0, len(ctx.elements)]}]
        else:
            for op in ops:
                s, e = op["span"]
                text = "\n\n".join(ctx.element_text(i) for i in range(s, e))
                chunks.append({"unit_id": op["id"], "text": text, "element_span": [s, e]})
    elif params["chunking"] == "whole":
        chunks = [{"unit_id": "__doc__", "text": ctx.full_text,
                   "element_span": [0, len(ctx.elements)]}]
    else:  # per_element
        chunks = [{"unit_id": str(i), "text": ctx.element_text(i),
                   "element_span": [i, i + 1]} for i in range(len(ctx.elements))]
    rows: List[dict] = []
    anomalies: List[Anomaly] = []
    for ch in chunks:
        try:
            for r in llm(spec, ch) or []:
                r.setdefault("unit_id", ch["unit_id"])
                rows.append(r)
        except Exception as e:  # noqa: BLE001 — a failed chunk is a review row, not a crash
            anomalies.append({"kind": "llm_chunk_failed", "unit": ch["unit_id"],
                              "detail": str(e)})
    return BlockResult(data={"rows": rows}, anomalies=anomalies,
                       meta={"n_chunks": len(chunks), "function": spec["function"]})


# --------------------------------------------------------------------------- #
# Control: tiered fallback (sustainment's text-layer -> vision shape)
# --------------------------------------------------------------------------- #
@register("control.tiered")
def control_tiered(ctx, params, inputs) -> BlockResult:
    """First-non-empty over an ordered list of upstream blocks. The POLICY
    (what counts as empty, note the tier used) is code here; the config only
    names the order. data: the winning tier's data + {"tier_used": id}."""
    order: List[str] = params["order"]
    anomalies: List[Anomaly] = []
    for tier_id in order:
        res = inputs.get(tier_id)
        if res is None:
            continue
        payload = res.data
        rows = payload.get("rows") if isinstance(payload, dict) else payload
        if rows:
            return BlockResult(data={**(payload if isinstance(payload, dict) else {"rows": rows}),
                                     "tier_used": tier_id},
                               anomalies=anomalies, meta={"tier_used": tier_id})
        anomalies.append({"kind": "tier_empty", "tier": tier_id})
    anomalies.append({"kind": "all_tiers_empty", "detail": f"tiers tried: {order}"})
    return BlockResult(data={"rows": [], "tier_used": None}, anomalies=anomalies)


# --------------------------------------------------------------------------- #
# Reconcile: merge deterministic + LLM arms into unit records + diff classes
# --------------------------------------------------------------------------- #
def _aggregate_span(by_element: Dict[int, Any], span) -> List[Any]:
    out: List[Any] = []
    for i in range(span[0], span[1]):
        v = by_element.get(i)
        if v is None:
            continue
        for item in (v if isinstance(v, list) else [v]):
            if item not in out:
                out.append(item)
    return out


@register("reconcile.units")
def reconcile_units(ctx, params, inputs) -> BlockResult:
    """Join the deterministic arms and the LLM judgment rows into one record
    per structural unit (operation). Emits the SAME diff classes as the corpus
    report (agree / script_only / llm_only) for any field both arms produced,
    so the comparison harness generalizes to engine-vs-plugin unchanged.

    params:
      unit_source     — the operations block id (for spans)
      det_fields      — {field_name: block_id} deterministic arm per field
      llm_source      — the judgment block id (rows keyed by unit_id)
      llm_fields      — judgment-only fields copied from the LLM rows
      double_armed    — fields where the LLM ALSO emits a value today, kept
                        only to measure disagreement; deterministic wins.

    data: {"units": [...], "diffs": {field: {agree, script_only, llm_only}}}
    """
    ops = inputs[params["unit_source"]].data["operations"]
    if not ops:
        ops = [{"id": "__doc__", "title_index": 0, "span": [0, len(ctx.elements)]}]
    llm_rows = {r.get("unit_id"): r for r in inputs[params["llm_source"]].data["rows"]}
    anomalies: List[Anomaly] = []

    # LLM rows for units no structural pass found = the pollution class,
    # surfaced by construction (the 4500 case).
    known = {op["id"] for op in ops}
    for uid in llm_rows:
        if uid not in known:
            anomalies.append({"kind": "llm_only_unit", "unit": uid,
                              "detail": "LLM emitted a unit the structural pass did not find"})

    diffs: Dict[str, Dict[str, int]] = {}
    units: List[dict] = []
    for op in ops:
        rec: dict = {"unit_id": op["id"], "element_span": op["span"]}
        for fname, block_id in params.get("det_fields", {}).items():
            data = inputs[block_id].data
            by_el = data.get("by_element", {})
            vals = _aggregate_span(by_el, op["span"])
            rec[fname] = vals if fname not in params.get("scalar_fields", []) else (vals[0] if vals else None)
        row = llm_rows.get(op["id"], {})
        for fname in params.get("llm_fields", []):
            rec[fname] = row.get(fname)
        for fname in params.get("double_armed", []):
            det_vals = set(map(str, rec.get(fname) or []))
            llm_vals = set(map(str, row.get(fname) or []))
            d = diffs.setdefault(fname, {"agree": 0, "script_only": 0, "llm_only": 0})
            d["agree"] += len(det_vals & llm_vals)
            d["script_only"] += len(det_vals - llm_vals)
            d["llm_only"] += len(llm_vals - det_vals)
        units.append(rec)
    return BlockResult(data={"units": units, "diffs": diffs}, anomalies=anomalies)


# --------------------------------------------------------------------------- #
# Sinks
# --------------------------------------------------------------------------- #
@register("sink.graph_map")
def sink_graph_map(ctx, params, inputs) -> BlockResult:
    """Descriptor-driven persistence: manufacturing_overlay's idea promoted to
    engine level. Each field descriptor declares its Cypher/RDF shape; adding a
    field never edits this block. The spike emits simplified fragments to prove
    the mapping is DATA; production reuses the tested overlay renderers.

    params: {"unit_label", "ontology": {prefix, namespace, target_class},
             "fields": [{name, cypher: attr|related, rdf: literal|relation,
                         label?, rel_type?, predicate?}]}
    """
    src = inputs[params["source"]]
    ont = params["ontology"]
    cypher: List[dict] = []
    sparql: List[str] = []
    for u in src.data["units"]:
        uid = f"{params['unit_label'].lower()}_{ctx.doc_id}_{u['unit_id']}"
        sets, rels, triples = [], [], [f"{ont['prefix']}:{uid} a {ont['target_class']} ."]
        for f in params.get("fields", []):
            v = u.get(f["name"])
            if v in (None, "", []):
                continue
            if f.get("cypher") == "attr":
                sets.append(f"n.{f['name']} = ${f['name']}")
            elif f.get("cypher") == "related":
                rels.append(f"MERGE (x:{f['label']} {{id: $id_{f['name']}}}) "
                            f"MERGE (n)-[:{f['rel_type']}]->(x)")
            if f.get("rdf") == "literal":
                for item in (v if isinstance(v, list) else [v]):
                    triples.append(f'{ont["prefix"]}:{uid} {ont["prefix"]}:{f["predicate"]} "{item}" .')
        cypher.append({"query": f"MERGE (n:{params['unit_label']} {{id: $uid}})"
                                + (" SET " + ", ".join(sets) if sets else "")
                                + ("\n" + "\n".join(rels) if rels else ""),
                       "params": {"uid": uid, **{k: u.get(k) for k in u if k not in ("element_span",)}}})
        sparql.append(f"PREFIX {ont['prefix']}: <{ont['namespace']}>\nINSERT DATA {{ "
                      + " ".join(triples) + " }")
    return BlockResult(data={"cypher": cypher, "sparql": sparql},
                       meta={"n_units": len(src.data["units"])})


@register("sink.review_lane")
def sink_review_lane(ctx, params, inputs) -> BlockResult:
    """Collect EVERY upstream block's anomalies into the review payload.
    A miss is a needs_review row, never a silent null — engine-wide."""
    items: List[dict] = []
    for block_id, res in ctx.results.items():
        for a in res.anomalies:
            items.append({"block": block_id, **a})
    return BlockResult(data={"review_items": items,
                             "needs_review": bool(items)})
