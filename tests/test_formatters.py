"""Unit tests for doc_tools/utils/formatters.convert_element_to_markdown.

Converts unstructured elements to Markdown, turning HTML tables into Markdown
grids (with a hybrid spatial + raw-text fallback). Previously ~20% covered.
"""
from types import SimpleNamespace

from doc_tools.utils.formatters import convert_element_to_markdown


def test_narrative_text_dict_returns_text():
    assert convert_element_to_markdown({"type": "NarrativeText", "text": "Remove panel."}) == "Remove panel."


def test_object_element_returns_text():
    el = SimpleNamespace(type="Title", text="Section 1")
    assert convert_element_to_markdown(el) == "Section 1"


def test_table_html_converts_to_markdown_grid_with_hybrid_output():
    html = (
        "<table><thead><tr><th>Part</th><th>Qty</th></tr></thead>"
        "<tbody><tr><td>Bolt</td><td>4</td></tr></tbody></table>"
    )
    el = {"type": "Table", "text": "Part Qty Bolt 4", "metadata": {"text_as_html": html}}
    md = convert_element_to_markdown(el)
    # hybrid: spatial grid + supplemental raw text
    assert "TABLE STRUCTURE (SPATIAL)" in md
    assert "TABLE CONTENT (SUPPLEMENTAL RAW TEXT)" in md
    assert "Part" in md and "Qty" in md and "Bolt" in md
    assert "Part Qty Bolt 4" in md  # supplemental raw text preserved


def test_table_object_metadata_supported():
    html = "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"
    el = SimpleNamespace(type="Table", text="A 1",
                         metadata=SimpleNamespace(text_as_html=html))
    md = convert_element_to_markdown(el)
    assert "A" in md and "1" in md


def test_table_without_html_marks_structure_unavailable():
    el = {"type": "Table", "text": "raw cells only", "metadata": {}}
    md = convert_element_to_markdown(el)
    assert "Structure unavailable" in md
    assert "raw cells only" in md


def test_table_with_missing_cells_fills_without_future_warning():
    # A table with an empty numeric cell -> pandas NaN. fillna("") on a numeric
    # column raised a FutureWarning; the astype(object) fix must avoid it.
    import warnings
    html = (
        "<table><thead><tr><th>Qty</th><th>Note</th></tr></thead>"
        "<tbody><tr><td>4</td><td></td></tr><tr><td></td><td>see spec</td></tr></tbody></table>"
    )
    el = {"type": "Table", "text": "raw", "metadata": {"text_as_html": html}}
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)  # fail if the dtype warning returns
        md = convert_element_to_markdown(el)
    assert "Qty" in md and "see spec" in md
