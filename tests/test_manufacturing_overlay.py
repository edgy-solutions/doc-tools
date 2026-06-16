"""Direct unit tests for doc_tools/plugins/manufacturing_overlay.

The graph golden exercises the render path indirectly; these cover the
secret-loading and TypeBuilder-injection branches directly (the previously
uncovered lines).
"""
import json

from doc_tools.plugins import manufacturing_overlay as ov


def test_load_proprietary_overlay_parses_all_persistence_kinds(tmp_path, monkeypatch):
    spec = {"fields": [
        {"name": "lac", "kind": "scalar", "neo4j_attr": True, "rdf_literal": "hasLac", "description": "d"},
        {"name": "procs", "kind": "list",
         "related": {"label": "SP", "rel_type": "USES", "id_prefix": "sp_", "value_prop": "name"}},
        {"name": "sref", "kind": "scalar",
         "rdf_relation": {"predicate": "governedBy", "target_prefix": "iof:", "target_suffix": "_Standard"}},
    ]}
    p = tmp_path / "ov.json"
    p.write_text(json.dumps(spec))
    monkeypatch.setenv("MANUFACTURING_OVERLAY_SPEC", str(p))

    fields = ov.load_proprietary_overlay()
    assert [f.name for f in fields] == ["lac", "procs", "sref"]
    assert all(f.proprietary for f in fields)
    assert fields[0].neo4j_attr and fields[0].rdf_literal == "hasLac"
    assert fields[1].related.label == "SP" and fields[1].related.rel_type == "USES"
    assert fields[2].rdf_relation.predicate == "governedBy"


def test_load_proprietary_overlay_unset_returns_empty(monkeypatch):
    monkeypatch.delenv("MANUFACTURING_OVERLAY_SPEC", raising=False)
    assert ov.load_proprietary_overlay() == []


def test_active_overlay_composes_default_plus_proprietary(tmp_path, monkeypatch):
    monkeypatch.delenv("MANUFACTURING_OVERLAY_SPEC", raising=False)
    base = ov.active_overlay()
    assert ov.proprietary_field_names(base) == []
    assert any(f.name == "is_value_added" for f in base)  # default overlay loaded

    p = tmp_path / "ov.json"
    p.write_text(json.dumps({"fields": [{"name": "x", "kind": "scalar"}]}))
    monkeypatch.setenv("MANUFACTURING_OVERLAY_SPEC", str(p))
    composed = ov.active_overlay()
    assert len(composed) == len(base) + 1
    assert ov.proprietary_field_names(composed) == ["x"]


# --- Fake TypeBuilder to exercise injection without BAML/Ollama --- #
class _FT:
    def __init__(self, name): self.name = name; self.is_list = False; self.is_opt = False
    def list(self): self.is_list = True; return self
    def optional(self): self.is_opt = True; return self


class _Prop:
    def __init__(self): self.desc = None
    def description(self, d): self.desc = d; return self


class _Cls:
    def __init__(self, name="ManufacturingStep"): self.name = name; self.added = {}
    def add_property(self, name, ftype):
        pr = _Prop(); self.added[name] = (ftype, pr); return pr
    def type(self): return _FT(f"class:{self.name}")


class _TB:
    def __init__(self):
        self.ManufacturingStep = _Cls()
        self.MatAugmentation = _Cls("MatAugmentation")
        self.classes = {}
    def add_class(self, name): c = _Cls(name); self.classes[name] = c; return c
    def string(self): return _FT("string")
    def int(self): return _FT("int")
    def bool(self): return _FT("bool")


def test_inject_proprietary_properties_only_adds_proprietary_with_correct_types():
    fields = [
        ov.OverlayField(name="keep_static", kind="scalar"),               # not proprietary -> skipped
        ov.OverlayField(name="p_list", kind="list", proprietary=True, description="L"),
        ov.OverlayField(name="p_int", kind="int", optional=True, proprietary=True),
        ov.OverlayField(name="p_bool", kind="bool", proprietary=True),
        ov.OverlayField(name="p_scalar", kind="scalar", optional=False, proprietary=True),
    ]
    tb = _TB()
    injected = ov.inject_proprietary_properties(tb, fields)

    assert injected == ["p_list", "p_int", "p_bool", "p_scalar"]
    added = tb.ManufacturingStep.added
    assert "keep_static" not in added            # static fields stay in the BAML schema
    assert added["p_list"][0].is_list is True
    assert added["p_int"][0].name == "int" and added["p_int"][0].is_opt is True
    assert added["p_bool"][0].name == "bool"
    assert added["p_scalar"][0].name == "string" and added["p_scalar"][0].is_opt is False
    assert added["p_list"][1].desc == "L"        # description propagated to the property


# --------------------------------------------------------------------------- #
# Nested object lists (kind == "object_list")
# --------------------------------------------------------------------------- #
def test_object_list_parsed_from_dict():
    f = ov._field_from_dict({
        "name": "widget_items", "kind": "object_list", "description": "Components.",
        "properties": [
            {"name": "operation", "kind": "scalar", "description": "Op no."},
            {"name": "qty", "kind": "int", "description": "Quantity."},
        ],
        "object_node": {"label": "WidgetItem", "rel_type": "HAS_WIDGET", "id_props": ["operation", "qty"]},
    })
    assert f.kind == "object_list" and f.proprietary
    assert [(p.name, p.kind) for p in f.item_properties] == [("operation", "scalar"), ("qty", "int")]
    assert f.object_node.label == "WidgetItem"
    assert f.object_node.rel_type == "HAS_WIDGET"
    assert f.object_node.id_props == ("operation", "qty")


def test_inject_object_list_builds_nested_class_and_lists_it():
    f = ov.OverlayField(
        name="widget_items", kind="object_list", proprietary=True,
        item_properties=[ov.ObjectField("operation", "scalar", "Op"), ov.ObjectField("qty", "int", "Qty")],
    )
    tb = _TB()
    injected = ov.inject_proprietary_properties(tb, [f])

    assert injected == ["widget_items"]
    assert "WidgetItemsItem" in tb.classes
    assert set(tb.classes["WidgetItemsItem"].added) == {"operation", "qty"}
    assert tb.classes["WidgetItemsItem"].added["qty"][0].name == "int"  # sub-field kind honored
    ftype, _ = tb.ManufacturingStep.added["widget_items"]
    assert ftype.is_list and ftype.name == "class:WidgetItemsItem"


def test_coerce_extracted_normalizes_object_list_to_dicts():
    from types import SimpleNamespace

    class _Item:  # mimic a BAML pydantic item object
        def __init__(self, **kw): self.__dict__.update(kw)
        def model_dump(self): return dict(self.__dict__)

    fields = [
        ov.OverlayField(name="widget_items", kind="object_list", proprietary=True,
                        item_properties=[ov.ObjectField("operation"), ov.ObjectField("qty")]),
        ov.OverlayField(name="lot_code", kind="scalar", proprietary=True),
        ov.OverlayField(name="is_value_added", kind="bool"),  # not proprietary -> skipped
    ]
    src = SimpleNamespace(
        widget_items=[_Item(operation="0010", qty="4"), _Item(operation="0020", qty="1")],
        lot_code="LAC-7",
        is_value_added=True,
    )
    out = ov.coerce_extracted(fields, src)
    assert out["lot_code"] == "LAC-7"
    assert "is_value_added" not in out  # non-proprietary skipped
    assert out["widget_items"] == [{"operation": "0010", "qty": "4"}, {"operation": "0020", "qty": "1"}]


def test_render_object_blocks_builds_node_per_item():
    from types import SimpleNamespace
    f = ov.OverlayField(
        name="widget_items", kind="object_list", proprietary=True,
        item_properties=[ov.ObjectField("operation"), ov.ObjectField("qty")],
        object_node=ov.ObjectNode(label="WidgetItem", rel_type="HAS_WIDGET", id_props=("operation",)),
    )
    step = SimpleNamespace(widget_items=[{"operation": "0010", "qty": "4"}])
    blocks, params = ov.render_object_blocks([f], step)

    assert len(blocks) == 1
    b = blocks[0]
    assert "UNWIND $widget_items AS item" in b
    assert "MERGE (n:WidgetItem:{domain}" in b
    assert "n.operation = item.operation" in b and "n.qty = item.qty" in b
    assert "MERGE (s)-[:HAS_WIDGET]->(n)" in b
    assert params["widget_items"] == [{"operation": "0010", "qty": "4"}]


def test_render_object_blocks_skips_without_object_node():
    from types import SimpleNamespace
    f = ov.OverlayField(name="x", kind="object_list", proprietary=True, item_properties=[ov.ObjectField("a")])
    blocks, params = ov.render_object_blocks([f], SimpleNamespace(x=[{"a": "1"}]))
    assert blocks == [] and params == {}


# --------------------------------------------------------------------------- #
# Document-scope fields (per-document, injected onto MatAugmentation)
# --------------------------------------------------------------------------- #
def test_inject_routes_document_scope_to_mat_augmentation():
    fields = [
        ov.OverlayField(name="lot_code", kind="scalar", proprietary=True),                      # step
        ov.OverlayField(name="work_summary", kind="scalar", proprietary=True, scope="document"),
    ]
    tb = _TB()
    ov.inject_proprietary_properties(tb, fields)
    assert "lot_code" in tb.ManufacturingStep.added
    assert "work_summary" in tb.MatAugmentation.added
    assert "work_summary" not in tb.ManufacturingStep.added


def test_extract_document_fields_merges_across_chunks():
    from types import SimpleNamespace
    fields = [
        ov.OverlayField(name="work_summary", kind="scalar", proprietary=True, scope="document"),
        ov.OverlayField(name="notes", kind="list", proprietary=True, scope="document"),
        ov.OverlayField(name="lot_code", kind="scalar", proprietary=True),  # step-scope -> ignored
    ]
    responses = [
        SimpleNamespace(work_summary="Part A overview.", notes=["gap1"], lot_code="x"),
        SimpleNamespace(work_summary="Part B overview.", notes=["gap1", "gap2"], lot_code="y"),
        SimpleNamespace(work_summary="", notes=[], lot_code="z"),
    ]
    out = ov.extract_document_fields(responses, fields)
    assert "lot_code" not in out  # step-scope excluded
    assert out["work_summary"] == "Part A overview.\n\nPart B overview."  # distinct concat
    assert out["notes"] == ["gap1", "gap2"]  # unioned across chunks


def test_document_scope_field_never_renders_on_a_step():
    from types import SimpleNamespace
    # even mis-configured with neo4j_attr + a default, a document field must not
    # leak onto every step node.
    f = ov.OverlayField(name="work_summary", kind="scalar", proprietary=True, scope="document",
                        neo4j_attr=True, neo4j_default="X")
    clauses, params = ov.render_step_attrs([f], SimpleNamespace())
    assert clauses == [] and params == {}
