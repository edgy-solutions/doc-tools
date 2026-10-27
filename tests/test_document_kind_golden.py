"""The ``document`` kind: registry row, outline pass, plugin tier, page refs.

ARCHITECT ORDER 2026-10-25: *"a drop of a general document (manual, procedure,
spec) that is not a PCN/PDN/S1000D should ingest as kind `document` with
review_shape `document`, chunk to Weaviate with page refs, and land in the graph
as Document -> Section -> Chunk so ask-the-manual can cite page + heading."*

Four things are sealed here, and the order matters because each one is a way the
whole feature could be green and inert:

1. **The row.** Shape, domain, passes, outputs, and the two negative
   declarations (no ``ingress_prefix``, ``.pdf`` only) that are decisions rather
   than omissions.
2. **The outline, against a golden.** Not just "sections were found": the exact
   sections, spans, ids and per-page citations of a fixture whose bytes are
   pinned. Plus the three things that must NOT become headings -- an admonition
   label, page furniture, and body text.
3. **The plugin tier.** That ``to_graph_queries`` emits Document -> Section ->
   Chunk, that it MATCHes the chunk rather than MERGEing it, and that it writes
   NOTHING when handed another document's outline.
4. **The page ref actually reaching Weaviate.** The gap the order names was that
   ``_index_chunk`` was called with four properties and no page. A test that
   only checked the schema would pass while the call site still omitted it, so
   the call site is asserted too.

Several assertions read the SOURCE. That is deliberate and is this repo's idiom
for a wiring claim: a declaration that is never dispatched, a branch that falls
through to the wrong plugin, and a property declared but never passed are all
invisible to a behavioural test that stubs the thing being wired.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures", "document")
PDF = os.path.join(FIXTURE_DIR, "procedure_fixture.pdf")
GOLDEN = os.path.join(FIXTURE_DIR, "golden.json")

DOC_ID = "TP-204"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _golden() -> dict:
    with io.open(GOLDEN, encoding="utf-8") as fh:
        return json.load(fh)


def _fixture_pages() -> list:
    import pdfplumber

    with pdfplumber.open(PDF) as pdf:
        return [(page.extract_text() or "") for page in pdf.pages]


def _outline_from_fixture():
    """The outline as the REGISTRY runs it -- through the dispatcher."""
    from doc_tools.passes.dispatch import PassContext, run_passes_for_kind

    pages = _fixture_pages()
    ctx = PassContext(pages=tuple(pages), text="\n".join(pages), doc_id=DOC_ID)
    results = run_passes_for_kind("document", ctx)
    for result in results:
        if result.name.endswith("document_outline"):
            assert result.status == "ok", (result.name, result.status, result.error)
            return result.value
    pytest.fail("the document row no longer declares document_outline")


def _source(relative: str) -> str:
    with io.open(os.path.join(ROOT, relative), encoding="utf-8") as fh:
        return fh.read()


class _Config:
    graph_node_label = "Document"
    graph_child_label = "Chunk"


# ---------------------------------------------------------------------------
# 1. the registry row
# ---------------------------------------------------------------------------

def test_the_row_matches_the_golden():
    from doc_tools.utils.content_kind import KIND_MAPPING

    row = KIND_MAPPING["document"]
    expected = _golden()["row"]
    assert row.kind == expected["kind"]
    assert row.domain_type == expected["domain_type"]
    assert list(row.passes) == expected["passes"]
    assert list(row.outputs) == expected["outputs"]
    assert row.ingress_prefix == expected["ingress_prefix"]
    assert list(row.file_suffixes or ()) == expected["file_suffixes"]


def test_the_row_declares_a_domain_because_a_domainless_one_writes_nothing():
    """The one decision in the row, with the reason it was made still true.

    A ``domain_type=None`` row reaches the ORIGIN UNRESOLVED return, which
    writes no graph and no chunks -- so a domain-less ``document`` row would
    satisfy the registry half of the order and silently drop the half the order
    is for. This asserts both halves: that the row declares a domain, and that
    the gate whose behaviour forced that choice is still there.
    """
    from doc_tools.utils.content_kind import KIND_MAPPING

    assert KIND_MAPPING["document"].domain_type == "document"
    source = _source("doc_tools/assets/semantic_assets.py")
    assert "if kind_entry is not None and kind_entry.domain_type is None:" in source
    assert '"status": "origin_unresolved"' in source


def test_the_output_is_declared_a_phantom():
    from doc_tools.utils.content_kind import KIND_MAPPING, PHANTOM_OUTPUTS

    for output in KIND_MAPPING["document"].outputs:
        assert output in PHANTOM_OUTPUTS, (
            f"{output} is not listed as a phantom; either Lane 1 has declared "
            f"the owl:Class (remove it from PHANTOM_OUTPUTS) or the row names "
            f"a class nobody owes")


def test_it_declares_no_user_drop_seam():
    """No ``ingress_prefix``: a seam with no sensor behind it is a dead drop."""
    from doc_tools.utils.content_kind import (KIND_MAPPING,
                                               ingress_user_key_pattern,
                                               ingress_user_prefixes)

    assert "document" not in ingress_user_prefixes()
    with pytest.raises(ValueError):
        ingress_user_key_pattern(KIND_MAPPING["document"])


def test_the_door_advertises_it():
    """Both arms: processable (its passes run) and ingestable (no hold)."""
    from doc_tools.api.kinds import ingestable_kinds
    from doc_tools.utils.content_kind import processable_kinds

    assert "document" in processable_kinds()
    assert "document" in ingestable_kinds()


def test_the_registry_projection_is_regenerated():
    path = os.path.join(ROOT, "registry", "content_kinds", "document.yaml")
    assert os.path.exists(path), "run scripts/generate_kind_registrations.py"
    with io.open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert "kind: document" in text
    assert "document.document_outline" in text

    domains = os.path.join(ROOT, "registry", "content_kind_domains.json")
    with io.open(domains, encoding="utf-8") as fh:
        assert json.load(fh)["domains"]["document"] == "document"


# ---------------------------------------------------------------------------
# 2. the outline, against the golden
# ---------------------------------------------------------------------------

def test_the_fixture_bytes_are_the_pinned_ones():
    """A changed sha is a CONTRACT change: the generator is byte-deterministic."""
    import hashlib

    with io.open(PDF, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    assert digest == _golden()["fixture"]["pdf_sha256"], (
        "procedure_fixture.pdf does not match the golden. Re-running "
        "make_procedure.py yields identical bytes, so this means the fixture's "
        "CONTENT changed -- re-pin deliberately, do not just refresh the sha")


def test_the_identity_arm_reads_the_title_block():
    """The row declares TWO passes, and a golden that only pins the outline
    cannot tell a working identity arm from one refusing every field -- which
    is what this fixture measured before it carried a labelled title block."""
    from doc_tools.passes.dispatch import PassContext, run_passes_for_kind

    pages = _fixture_pages()
    ctx = PassContext(pages=tuple(pages), text="\n".join(pages), doc_id=DOC_ID)
    identity = None
    for result in run_passes_for_kind("document", ctx):
        if result.name.endswith("document_identity"):
            assert result.status == "ok", result.error
            identity = result.value
    assert identity is not None
    assert identity.as_dict() == _golden()["identity"]
    assert identity.value("document_number") == DOC_ID
    assert identity.value("revision") == "B"
    # A procedure has no contract number. Refused, not guessed, and recorded.
    assert identity.refused == ("contract_number",)


def test_the_outline_matches_the_golden():
    outline = _outline_from_fixture()
    assert outline.as_dict() == _golden()["outline"]


def test_every_page_cites_the_golden_section():
    outline = _outline_from_fixture()
    actual = [
        {"page": n,
         "section_id": outline.section_for_page(n).id,
         "heading": outline.section_for_page(n).heading}
        for n in range(1, outline.page_count + 1)
    ]
    assert actual == _golden()["page_citations"]


def test_every_page_has_a_section_to_cite():
    """The property ask-the-manual depends on: no page is unattributed."""
    outline = _outline_from_fixture()
    for n in range(1, outline.page_count + 1):
        assert outline.section_for_page(n) is not None, f"page {n} cites nothing"


def test_an_admonition_label_is_not_a_heading():
    """``WARNING`` / ``CAUTION:`` appear in the fixture and must not open a
    section -- a six-page procedure can print four of them, each capturing the
    pages beneath it."""
    outline = _outline_from_fixture()
    headings = {s.heading.upper().rstrip(":") for s in outline.sections}
    assert "WARNING" not in headings
    assert "CAUTION" not in headings
    # ... while a real heading that CONTAINS the word is still read.
    from doc_tools.passes.document import document_outline

    contains = document_outline(["WARNINGS AND CAUTIONS\nRead them."], doc_id="D")
    assert [s.heading for s in contains.sections] == ["WARNINGS AND CAUTIONS"]


def test_page_furniture_is_not_a_heading():
    outline = _outline_from_fixture()
    for section in outline.sections:
        assert "Page " not in section.heading
        assert not section.heading.strip().isdigit()
        assert section.heading.upper() != "REVISION B"


def test_the_appendix_heading_is_read():
    """An unnumbered all-caps heading is the ``caps`` arm's reason to exist."""
    outline = _outline_from_fixture()
    appendix = [s for s in outline.sections if s.heading == "APPENDIX A"]
    assert len(appendix) == 1, [s.heading for s in outline.sections]
    assert appendix[0].method == "caps"
    assert appendix[0].level == 1


def test_the_numbering_is_the_hierarchy():
    outline = _outline_from_fixture()
    by_number = {s.number: s for s in outline.sections if s.number}
    assert by_number["2"].level == 1
    assert by_number["2.1"].level == 2
    assert by_number["2.1"].parent == by_number["2"].id
    # The parent's span CONTAINS its subsections'.
    parent = by_number["2"]
    for child in (by_number["2.1"], by_number["2.2"]):
        assert parent.start_page <= child.start_page
        assert child.end_page <= parent.end_page


def test_a_document_with_no_headings_is_flagged_not_silently_sectioned():
    from doc_tools.passes.document import document_outline

    outline = document_outline(["just body text.", "and more."], doc_id="X")
    assert outline.synthetic is True
    assert len(outline.sections) == 1
    lone = outline.sections[0]
    assert lone.method == "synthetic"
    assert lone.heading == ""
    assert (lone.start_page, lone.end_page) == (1, 2)


def test_a_heading_that_is_not_on_its_page_raises():
    """The verbatim invariant, tested AS an invariant."""
    from doc_tools.passes.document import OutlineError, OutlineSection, _verify

    ghost = OutlineSection(id="D_s1", parent="D", heading="Ghost", level=1,
                           start_page=1, end_page=1, method="caps",
                           heading_source="Ghost", number="")
    with pytest.raises(OutlineError):
        _verify(ghost, "this page says something else entirely")


def test_the_outline_is_stable_across_runs():
    """Same bytes, same citation. The reason this path has no model in it."""
    first = _outline_from_fixture().as_dict()
    second = _outline_from_fixture().as_dict()
    assert first == second


# ---------------------------------------------------------------------------
# 3. the plugin tier
# ---------------------------------------------------------------------------

def _plugin_with_outline():
    from doc_tools.plugins.document import DocumentPlugin

    plugin = DocumentPlugin("document")
    pages = _fixture_pages()
    full_text = "\n".join(
        f"\n--- Page {n} ---\n{text}" for n, text in enumerate(pages, start=1))
    assert plugin.process_fulltext(full_text, DOC_ID, {}, elements=None) == []
    assert plugin._outline is not None, "the outline was not held for the page loop"
    return plugin


def _page_nodes(plugin):
    from doc_tools.plugins.models import BaseSection

    nodes = []
    for n in range(1, plugin._outline.page_count + 1):
        section = BaseSection(title=f"Page {n}", level=1, page_start=n,
                              content="body", node_id=f"{DOC_ID}_p{n}")
        nodes.append(plugin.augment(section, _Config()))
    return nodes


def test_process_fulltext_runs_the_declared_passes_and_returns_no_nodes():
    plugin = _plugin_with_outline()
    assert [r.name for r in plugin._pass_results] == [
        "identity.document_identity", "document.document_outline"]
    assert all(r.status == "ok" for r in plugin._pass_results)


def test_augment_attributes_each_page_to_its_section():
    plugin = _plugin_with_outline()
    citations = _golden()["page_citations"]
    for node, expected in zip(_page_nodes(plugin), citations):
        aug = node.domain_augmentation
        assert aug.section is not None
        assert aug.section.section_id == expected["section_id"]
        assert aug.section.heading == expected["heading"]
        assert aug.outline_synthetic is False


def test_to_graph_queries_builds_document_section_chunk():
    plugin = _plugin_with_outline()
    nodes = _page_nodes(plugin)
    cypher, sparql = plugin.to_graph_queries(nodes, _Config(), doc_id=DOC_ID)
    joined = "\n".join(q["query"] for q in cypher)

    assert "MERGE (s:Section:DOCUMENT {id: $id})" in joined
    assert "HAS_SECTION" in joined, "no Document -> Section edge"
    assert "HAS_SUBSECTION" in joined, "no Section -> Section edge"
    assert "HAS_CHUNK" in joined, "no Section -> Chunk edge"
    # Every section in the outline is written exactly once.
    merged = [q for q in cypher if "MERGE (s:Section" in q["query"]]
    assert len(merged) == len(plugin._outline.sections)
    # No SPARQL while the output class is a phantom.
    assert sparql == []


def test_the_chunk_is_matched_not_merged():
    """A MERGE would mint an empty chunk node if the asset's loop had not run,
    and coverage counted off an empty node is worse than a missing edge."""
    plugin = _plugin_with_outline()
    cypher, _ = plugin.to_graph_queries(_page_nodes(plugin), _Config(), doc_id=DOC_ID)
    chunk_queries = [q["query"] for q in cypher if "HAS_CHUNK" in q["query"]]
    assert chunk_queries
    for query in chunk_queries:
        assert "MATCH (c:Chunk" in query
        assert "MERGE (c:Chunk" not in query


def test_another_documents_outline_writes_nothing():
    plugin = _plugin_with_outline()
    nodes = _page_nodes(plugin)
    cypher, sparql = plugin.to_graph_queries(nodes, _Config(), doc_id="SOME-OTHER-DOC")
    assert cypher == []
    assert sparql == []


def test_the_plugin_has_no_mock_fallback_and_no_prompts():
    """Its siblings substitute invented content when BAML is absent; that has
    produced a whole green graph of placeholder text in this repo before."""
    from doc_tools.plugins.document import DocumentPlugin

    assert DocumentPlugin.REQUIRED_PROMPT_FILES == []
    source = _source("doc_tools/plugins/document.py")
    body = source.split('"""', 2)[-1]        # past the module docstring
    assert "baml" not in body.lower()
    assert "except ImportError" not in body
    assert "_get_dynamic_prompt" not in body


# ---------------------------------------------------------------------------
# 4. the page ref reaching Weaviate, and the asset wiring
# ---------------------------------------------------------------------------

def test_the_document_domain_gets_its_own_plugin_branch():
    """Not the ``else``. The ``else`` is TrainingPlugin, so an unbranched new
    domain extracts course concepts from a procedure and looks like it worked."""
    source = _source("doc_tools/assets/semantic_assets.py")
    branch = 'elif domain_type == "document":'
    assert branch in source
    assert source.index(branch) < source.index("    else:\n        plugin = TrainingPlugin(domain_type)")
    assert "from doc_tools.plugins.document import DocumentPlugin" in source


def test_the_document_domain_names_its_own_graph_labels():
    source = _source("doc_tools/assets/semantic_assets.py")
    assert 'if domain_type == "document":' in source
    assert 'node_label = "Document"' in source
    assert 'child_label = "Chunk"' in source


def test_the_collection_declares_the_citation_properties():
    source = _source("doc_tools/assets/semantic_assets.py")
    for prop in ("page", "heading", "section_id"):
        assert f'wvc.config.Property(name="{prop}"' in source, prop
    # page is an INT: stored as text, page 10 sorts before page 2.
    assert ('wvc.config.Property(name="page", data_type=wvc.config.DataType.INT)'
            in source)


def test_an_existing_collection_gains_the_properties():
    """Without this the schema change is correct in the tree and absent in the
    pod: ``DocumentChunk`` already exists on every deployed cluster, and the
    create block only runs when the collection does NOT exist."""
    source = _source("doc_tools/assets/semantic_assets.py")
    assert "collection.config.add_property(" in source
    assert "have = {prop.name for prop in collection.config.get().properties}" in source


def test_the_page_chunk_call_site_passes_the_page():
    """The gap the order names. A schema-only test would pass while the call
    site still sent four properties."""
    source = _source("doc_tools/assets/semantic_assets.py")
    assert '"page": _page_property(page_num), **citation,' in source


def test_page_property_coerces_and_refuses():
    from doc_tools.assets.semantic_assets import _page_property

    assert _page_property(3) == 3
    assert _page_property("3") == 3
    assert _page_property(" 3 ") == 3
    assert _page_property(None) is None
    assert _page_property("iii") is None
    assert _page_property(True) is None       # a bool is an int in Python


def test_chunk_citation_is_empty_for_a_plugin_that_attributes_nothing():
    from doc_tools.assets.semantic_assets import _chunk_citation

    class _Bare:
        domain_augmentation = None

    assert _chunk_citation(_Bare()) == {}
    assert _chunk_citation(object()) == {}


def test_chunk_citation_carries_heading_and_section_id():
    from doc_tools.assets.semantic_assets import _chunk_citation

    plugin = _plugin_with_outline()
    node = _page_nodes(plugin)[2]             # page 3
    citation = _chunk_citation(node)
    assert citation == {"heading": "Lockout and tagout",
                        "section_id": "TP-204_s3_s1"}


def test_the_citation_is_rebound_every_iteration():
    """``node`` is assigned inside a try, so a page whose augmentation raised
    would otherwise carry the PREVIOUS page's heading."""
    source = _source("doc_tools/assets/semantic_assets.py")
    loop = source.split("for page_num, texts in pages.items():", 1)[1]
    assert "        citation = {}\n" in loop.split("_index_chunk", 1)[0]


# ---------------------------------------------------------------------------
# 5. the fixture generators stay honest
# ---------------------------------------------------------------------------

def test_the_fixture_generator_is_byte_deterministic():
    spec = importlib.util.spec_from_file_location(
        "make_procedure_probe", os.path.join(FIXTURE_DIR, "make_procedure.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_procedure_probe"] = module
    spec.loader.exec_module(module)
    builder = getattr(module, "build_pdf", None) or getattr(module, "build", None)
    if builder is None:
        pytest.skip("make_procedure.py exposes no build function to call directly")
    assert builder() == builder()


def test_the_golden_is_not_stale():
    """``make_golden.py --check`` as a test, so a row edit that moves the
    outline fails here rather than in a fire."""
    sys.path.insert(0, FIXTURE_DIR)
    try:
        spec = importlib.util.spec_from_file_location(
            "make_golden_probe", os.path.join(FIXTURE_DIR, "make_golden.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules["make_golden_probe"] = module
        spec.loader.exec_module(module)
        built = module.build()
    finally:
        sys.path.remove(FIXTURE_DIR)
    assert built == _golden()
