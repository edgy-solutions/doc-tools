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
    def __init__(self): self.added = {}
    def add_property(self, name, ftype):
        pr = _Prop(); self.added[name] = (ftype, pr); return pr


class _TB:
    def __init__(self): self.ManufacturingStep = _Cls()
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
