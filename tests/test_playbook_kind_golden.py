"""The ``playbook`` kind: row, pass, chunker, plugin tier, Weaviate properties.

Contract: ``docs/contracts/playbook-kind.md``. Several assertions read the SOURCE,
which is this repo's idiom for a wiring claim: a branch that falls through to the
wrong plugin and a property added to only one of two arms are invisible to a
behavioural test that stubs the thing being wired.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures", "playbook")
MD = os.path.join(FIXTURE_DIR, "restart_runbook.md")
GOLDEN = os.path.join(FIXTURE_DIR, "golden.json")


def _golden() -> dict:
    with io.open(GOLDEN, encoding="utf-8") as fh:
        return json.load(fh)


def _text() -> str:
    with io.open(MD, "rb") as fh:
        return fh.read().decode("utf-8")


def _source(relative: str) -> str:
    with io.open(os.path.join(ROOT, relative), encoding="utf-8") as fh:
        return fh.read()


def _doc_id() -> str:
    return _golden()["fixture"]["doc_id"]


def _dispatch(text: str, doc_id: str):
    from doc_tools.passes.dispatch import PassContext, run_passes_for_kind

    return run_passes_for_kind("playbook", PassContext(text=text, doc_id=doc_id))


def _outline():
    (result,) = _dispatch(_text(), _doc_id())
    assert result.status == "ok", (result.status, result.error)
    return result.value


# ---------------------------------------------------------------------------
# 1. the row
# ---------------------------------------------------------------------------

def test_the_row_matches_the_golden_and_the_spec():
    from doc_tools.utils.content_kind import KIND_MAPPING

    row = KIND_MAPPING["playbook"]
    expected = _golden()["row"]
    assert row.kind == expected["kind"] == "playbook"
    assert row.kind_source_value == "playbook"
    assert row.domain_type == expected["domain_type"] == "playbook"
    assert list(row.passes) == expected["passes"] == ["playbook.playbook_outline"]
    assert list(row.outputs) == expected["outputs"] == ["mesh:PlaybookArtifact"]
    assert row.ingress_prefix is None
    assert list(row.file_suffixes) == [".md"]
    assert row.extractor_config == "" and row.baml_function == ""
    assert row.target_ontology_class == (
        "http://edgy-solutions.com/ontology/mesh#PlaybookArtifact")
    assert row.branch == "document"


def test_the_output_is_a_phantom_and_the_pass_is_built():
    from doc_tools.utils.content_kind import PHANTOM_OUTPUTS, UNBUILT_PASSES

    assert "mesh:PlaybookArtifact" in PHANTOM_OUTPUTS
    assert "playbook.playbook_outline" not in UNBUILT_PASSES


def test_the_pass_resolves_to_exactly_one_callable():
    from doc_tools.passes.dispatch import resolve_python_pass

    hits = resolve_python_pass("playbook.playbook_outline")
    assert hits is not None and len(hits) == 1
    assert callable(hits[0][1])


def test_the_pass_signature_stays_inside_the_dispatcher_vocabulary():
    import inspect

    from doc_tools.passes.dispatch import PassContext
    from doc_tools.passes.playbook import playbook_outline

    vocabulary = set(PassContext().bindings())
    assert set(inspect.signature(playbook_outline).parameters) <= vocabulary


def test_the_door_does_not_advertise_it_and_there_is_no_drop_seam():
    """Arm 1 claims the kind; the door must still not offer it.

    The pass IS built, so `processable_kinds()` contains `playbook` -- which is
    precisely why the hold in `doc_tools.api.kinds.HELD_OUT` has to be written
    down. There is no drop seam here at all: `ingress_prefix=None`, no sensor,
    no prefix, and the kind arrives by git clone. Advertising it to Lane 1
    offers a leaf no user can drop, and that is the state this test caught --
    with the whole suite green -- before the hold was added.
    """
    from doc_tools.api.kinds import HELD_OUT, ingestable_kinds
    from doc_tools.utils.content_kind import (KIND_MAPPING, ingress_user_key_pattern,
                                               ingress_user_prefixes,
                                               processable_kinds)

    assert "playbook" in processable_kinds()
    assert "playbook" not in ingestable_kinds()
    # The hold is the reason for the asymmetry, so it is asserted, not assumed.
    assert "playbook" in HELD_OUT
    assert "playbook" not in ingress_user_prefixes()
    with pytest.raises(ValueError):
        ingress_user_key_pattern(KIND_MAPPING["playbook"])


def test_the_registry_projection_is_regenerated():
    path = os.path.join(ROOT, "registry", "content_kinds", "playbook.yaml")
    assert os.path.exists(path), "run scripts/generate_kind_registrations.py"
    with io.open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert "kind: playbook" in text
    assert "playbook.playbook_outline" in text
    with io.open(os.path.join(ROOT, "registry", "content_kind_domains.json"),
                 encoding="utf-8") as fh:
        assert json.load(fh)["domains"]["playbook"] == "playbook"


# ---------------------------------------------------------------------------
# 2. the golden
# ---------------------------------------------------------------------------

def test_the_fixture_bytes_are_the_pinned_ones():
    with io.open(MD, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    assert digest == _golden()["fixture"]["md_sha256"], (
        "restart_runbook.md changed. That moves every chunk_id: re-pin "
        "deliberately and packet the consumer, do not just refresh the sha")


def test_the_pass_status_is_ok_through_the_dispatcher():
    results = _dispatch(_text(), _doc_id())
    assert [{"name": r.name, "status": r.status} for r in results] == \
        _golden()["pass_results"] == [
            {"name": "playbook.playbook_outline", "status": "ok"}]


def test_the_golden_has_no_nondeterministic_block():
    assert "nondeterministic" not in _golden()


def test_the_heading_tree_matches_the_golden():
    assert _outline().as_dict() == _golden()["outline"]


def test_the_heading_tree_nests_as_the_markdown_does():
    outline = _outline()
    by_heading = {s.heading: s for s in outline.sections}
    assert by_heading["Restart the ingest service"].parent == _doc_id()
    assert by_heading["Before you start"].parent == by_heading["Restart the ingest service"].id
    assert by_heading["Check the queue depth"].parent == by_heading["Before you start"].id
    # A level that skips a depth (h1 then h4) nests under the deepest open
    # heading; no ancestor is invented.
    assert by_heading["Rotate"].parent == by_heading["Rotate the service token"].id
    # A fenced shell comment is not a heading.
    assert "this comment is not a heading" not in by_heading


def test_every_chunk_id_matches_the_golden():
    from doc_tools.utils.md_chunks import chunk_markdown

    g = _golden()["fixture"]
    chunks = chunk_markdown(_text(), g["doc_id"], g["source"], g["path"])
    actual = [{k: c[k] for k in ("chunk_id", "section_id", "heading",
                                  "heading_path", "synthetic", "source", "path")}
              for c in chunks]
    assert actual == _golden()["chunks"]


def test_one_chunk_per_leaf_and_the_outline_names_it():
    outline = _outline()
    leaves = [s for s in outline.sections if s.chunk_id]
    assert [s.chunk_id for s in leaves] == [c["chunk_id"] for c in _golden()["chunks"]]
    # Parents carry no chunk.
    assert [s.heading for s in outline.sections if not s.chunk_id] == [
        "Restart the ingest service", "Before you start", "Restart",
        "Rotate the service token"]


def test_a_chunk_carries_the_citation_triple_and_no_page():
    from doc_tools.utils.md_chunks import chunk_markdown

    g = _golden()["fixture"]
    for chunk in chunk_markdown(_text(), g["doc_id"], g["source"], g["path"]):
        assert chunk["source"] == g["source"]
        assert chunk["path"] == g["path"]
        assert chunk["heading"] and chunk["heading"] in _text()
        assert chunk["doc_id"] == g["doc_id"] and chunk["text"]
        assert "page" not in chunk


def test_chunk_markdown_refuses_half_a_citation():
    from doc_tools.utils.md_chunks import MarkdownChunkError, chunk_markdown

    with pytest.raises(MarkdownChunkError):
        chunk_markdown("# A\nbody", "D", "", "a.md")
    with pytest.raises(MarkdownChunkError):
        chunk_markdown("# A\nbody", "D", "https://x", "")


def test_reordering_sections_does_not_re_mint_ids():
    """The whole point of deriving chunk_id from the heading path."""
    from doc_tools.utils.md_chunks import split_markdown

    a = "# One\nfirst body\n\n# Two\nsecond body\n"
    b = "# Two\nsecond body\n\n# One\nfirst body\n"
    ids_a = {c["chunk_id"] for c in split_markdown(a, "D")}
    ids_b = {c["chunk_id"] for c in split_markdown(b, "D")}
    assert ids_a == ids_b and len(ids_a) == 2


def test_the_chunk_id_follows_the_documented_encoding():
    from doc_tools.utils.md_chunks import split_markdown

    (chunk,) = split_markdown("# Top\n## Leaf Name\nbody\n", "D")
    digest = hashlib.sha1(chunk["text"].encode("utf-8")).hexdigest()[:12]
    assert chunk["chunk_id"] == f"D_top__leaf-name_{digest}"


def test_a_headingless_file_gets_one_marked_synthetic_chunk():
    from doc_tools.utils.md_chunks import split_markdown

    (chunk,) = split_markdown("just prose, no heading\n", "D")
    assert chunk["synthetic"] is True
    assert chunk["heading"] == ""
    outline = _dispatch("just prose, no heading\n", "D")[0].value
    assert outline.synthetic is True
    assert [s.method for s in outline.sections] == ["synthetic"]


def test_an_empty_file_is_refused_not_filled_in():
    (result,) = _dispatch("  \n\n", "D")
    assert result.status == "refused"
    assert result.value is None


def test_a_heading_that_is_not_in_the_source_raises():
    """The verbatim invariant, tested AS an invariant."""
    from doc_tools.utils.md_chunks import MarkdownChunkError, MdHeading, _verify

    ghost = MdHeading(level=1, heading="Ghost", heading_source="# Ghost", line=0)
    with pytest.raises(MarkdownChunkError):
        _verify(ghost, "# Something else\n")


def test_doc_id_convention():
    from doc_tools.utils.md_chunks import playbook_doc_id

    assert playbook_doc_id("repo", "a/b/run.md") == "repo.a/b/run"


def test_the_outline_is_stable_across_runs():
    assert _outline().as_dict() == _outline().as_dict()


def test_the_golden_is_not_stale():
    sys.path.insert(0, FIXTURE_DIR)
    try:
        spec = importlib.util.spec_from_file_location(
            "make_playbook_golden_probe", os.path.join(FIXTURE_DIR, "make_golden.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules["make_playbook_golden_probe"] = module
        spec.loader.exec_module(module)
        built = module.build()
    finally:
        sys.path.remove(FIXTURE_DIR)
    assert built == _golden()


# ---------------------------------------------------------------------------
# 3. the plugin tier
# ---------------------------------------------------------------------------

class _Config:
    graph_node_label = "Playbook"
    graph_child_label = "Chunk"


def _plugin():
    from doc_tools.plugins.playbook import PlaybookPlugin

    plugin = PlaybookPlugin("playbook")
    assert plugin.process_fulltext(_text(), _doc_id(), {}, elements=None) == []
    assert plugin._outline is not None
    return plugin


def test_the_plugin_runs_the_row_through_the_dispatcher():
    plugin = _plugin()
    assert [r.name for r in plugin._pass_results] == ["playbook.playbook_outline"]
    assert plugin.domain_label == "PLAYBOOK"


def test_the_tiers_are_playbook_section_chunk_with_domain_labels():
    queries, sparql = _plugin().to_graph_queries([], _Config(), doc_id=_doc_id())
    joined = "\n".join(q["query"] for q in queries)
    assert sparql == []
    assert "MATCH (d:Playbook:PLAYBOOK {id: $doc_id})" in joined
    assert "MERGE (s:Section:PLAYBOOK {id: $id})" in joined
    assert "MATCH (c:Chunk:PLAYBOOK {id: $chunk_id})" in joined
    assert "MERGE (d)-[:HAS_SECTION]->(s)" in joined
    assert "MERGE (p)-[:HAS_SUBSECTION]->(s)" in joined


def test_the_chunk_is_matched_never_merged():
    queries, _ = _plugin().to_graph_queries([], _Config(), doc_id=_doc_id())
    for q in queries:
        assert "MERGE (c:" not in q["query"]
    assert sum("MATCH (c:Chunk:PLAYBOOK" in q["query"] for q in queries) == 6


def test_another_documents_outline_writes_nothing():
    assert _plugin().to_graph_queries([], _Config(), doc_id="someone.else") == ([], [])


def test_a_refused_pass_leaves_no_outline_and_writes_nothing():
    from doc_tools.plugins.playbook import PlaybookPlugin

    plugin = PlaybookPlugin("playbook")
    plugin.process_fulltext("   ", "D")
    assert plugin._outline is None
    assert plugin.to_graph_queries([], _Config(), doc_id="D") == ([], [])


def test_the_plugin_has_no_mock_fallback():
    source = _source("doc_tools/plugins/playbook.py")
    assert "except ImportError" not in source
    assert "TrainingPlugin" not in source.split('"""', 2)[2]


# ---------------------------------------------------------------------------
# 4. the selector branch and the Weaviate properties
# ---------------------------------------------------------------------------

def test_the_playbook_domain_gets_its_own_plugin_branch():
    """Not the ``else``: that is TrainingPlugin."""
    source = _source("doc_tools/assets/semantic_assets.py")
    branch = 'elif domain_type == "playbook":'
    assert branch in source
    assert source.index(branch) < source.index(
        "    else:\n        plugin = TrainingPlugin(domain_type)")
    assert "plugin = PlaybookPlugin(domain_type)" in source


def test_source_and_path_are_declared_in_the_create_arm():
    source = _source("doc_tools/assets/semantic_assets.py")
    create = source.split("def _ensure_weaviate_collection", 1)[1].split(
        "wanted = {", 1)[0]
    for prop in ("source", "path"):
        assert (f'wvc.config.Property(name="{prop}", '
                f'data_type=wvc.config.DataType.TEXT)') in create, prop


def test_source_and_path_are_declared_in_the_already_exists_arm():
    """The defect this repo has paid for: a property added only to ``create`` is
    inert on every deployed cluster, because ``DocumentChunk`` already exists."""
    source = _source("doc_tools/assets/semantic_assets.py")
    wanted = source.split("wanted = {", 1)[1].split("}", 1)[0]
    assert '"source": wvc.config.DataType.TEXT' in wanted
    assert '"path": wvc.config.DataType.TEXT' in wanted


def test_an_existing_collection_is_actually_given_source_and_path():
    """Behavioural half: drive the already-exists arm with a fake client."""
    from doc_tools.assets import semantic_assets as sa

    added = []

    class _Prop:
        def __init__(self, name):
            self.name = name

    class _Cfg:
        def get(self):
            class _C:
                properties = [_Prop(n) for n in (
                    "text", "doc_id", "chunk_id", "domain", "page", "heading",
                    "section_id", "chunk_kind")]
            return _C()

        def add_property(self, prop):
            added.append(prop.name)

    class _Collection:
        config = _Cfg()

    class _Collections:
        def exists(self, name):
            return True

        def get(self, name):
            return _Collection()

    class _Client:
        collections = _Collections()

    sa._ensure_weaviate_collection(_Client(), "DocumentChunk")
    assert sorted(added) == ["path", "source"]


def test_the_playbook_domain_names_its_own_graph_labels():
    source = _source("doc_tools/assets/semantic_assets.py")
    assert 'if domain_type == "playbook":\n        node_label = "Playbook"' in source
