"""ExtractOutline tolerates a reply whose sections carry ``"start_page": null``.

Recorded sandbox reply (fixtures/training/outline_reply_null_pages.txt): correct
titles and nesting, null pages on every section. With ``start_page int`` BAML
dropped every section and returned ``sections: []``. The outline pass reads
titles and nesting only; every page comes from the elements.
"""
import tempfile
from pathlib import Path

from doc_tools.baml_client.sync_client import b
from doc_tools.passes.structural import outline_from_llm
from doc_tools.utils.extraction import extract_text_and_metadata

FIXTURES = Path(__file__).parent / "fixtures" / "training"
REPLY = FIXTURES / "outline_reply_null_pages.txt"
DECK = FIXTURES / "hydraulics_fixture.pptx"

TITLES = [
    "Hydraulic Systems Fundamentals",
    "Module 1: fixture deck for the training-workbench contract",
    "Pascal's Law",
    "Hydraulic Pumps",
    "Reservoir Schematic",
]


def _preorder(sections):
    for s in sections:
        yield s
        yield from _preorder(s.subsections)


def _parse():
    return b.parse.ExtractOutline(REPLY.read_text(encoding="utf-8"))


def test_null_page_reply_parses_to_all_sections():
    flat = list(_preorder(_parse().sections))
    assert [s.title for s in flat] == TITLES
    assert all(s.start_page is None for s in flat)


def test_null_page_reply_yields_sections_with_element_pages():
    with tempfile.TemporaryDirectory() as td:
        elements = extract_text_and_metadata(str(DECK), extract_images=True, image_output_dir=td)
    pages = {e["metadata"]["page_number"] for e in elements}
    out = outline_from_llm(elements, [_parse()])
    flat = list(_preorder(out))
    assert flat
    for s in flat:
        assert s.start_page in pages and s.start_page >= 1
        assert s.end_page >= s.start_page
