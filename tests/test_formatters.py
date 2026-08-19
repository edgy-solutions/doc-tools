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


# ---------------------------------------------------------------------------
# Image placeholders — the figure-in-prompt gap
# ---------------------------------------------------------------------------
# An unstructured `Image` element carries its content in metadata.image_path,
# never in .text. Before the Image branch existed every figure converted to ""
# and the LLM's markdown had NO TRACE a figure was there — so `figure_references`
# could only populate when the prose said "see Figure 3", and a page whose
# figures carry no inline callout yielded an empty list on a document full of
# diagrams. These tests pin the placeholder AND the join key.

def test_image_element_emits_placeholder_with_crop_basename():
    """The basename IS the join key into `embedded_images` (see the branch's
    comment). Asserting on the BASENAME rather than merely 'some placeholder'
    is the point: a marker that doesn't carry the key resolves to nothing."""
    el = {
        "type": "Image",
        "text": "",
        "metadata": {"image_path": "/tmp/xyz123/figure-1-1.jpg"},
    }
    md = convert_element_to_markdown(el)
    assert md == "[FIGURE: figure-1-1.jpg]"


def test_image_placeholder_joins_to_the_embedded_images_key():
    """THE CONTRACT, stated as a test. `embedded_images_map` in
    components/document_parser.py is keyed by `os.listdir(temp_extract_dir)`
    filenames; `metadata.image_path` points into that same directory. So the
    emitted name must equal the map key EXACTLY -- not a normalized, slugified
    or extension-stripped variant, or the downstream lookup misses silently."""
    embedded_images = {
        "figure-1-1.jpg": "s3://processing-artifacts/mfg/generated/doc_pdf/images/figure-1-1.jpg",
    }
    el = {"type": "Image", "text": "",
          "metadata": {"image_path": "/tmp/extract/figure-1-1.jpg"}}
    md = convert_element_to_markdown(el)
    name = md[len("[FIGURE: "):-1]
    assert name in embedded_images, f"{name!r} does not join to embedded_images"


def test_image_object_metadata_supported():
    el = SimpleNamespace(type="Image", text="",
                         metadata=SimpleNamespace(image_path="/tmp/e/table-2-3.png"))
    assert convert_element_to_markdown(el) == "[FIGURE: table-2-3.png]"


def test_image_without_path_still_marks_position_but_invents_no_key():
    """Position is useful even when the crop can't be joined. A FABRICATED name
    would be worse than none -- it would resolve to nothing while reading as if
    it had, which is the silent-wrong shape this whole chain keeps producing."""
    md = convert_element_to_markdown({"type": "Image", "text": "", "metadata": {}})
    assert md == "[FIGURE]"


def test_image_caption_text_is_preserved_after_the_marker():
    el = {"type": "Image", "text": "Exploded view of the seal assembly",
          "metadata": {"image_path": "/tmp/e/figure-4-2.jpg"}}
    md = convert_element_to_markdown(el)
    assert md.startswith("[FIGURE: figure-4-2.jpg]")
    assert "Exploded view of the seal assembly" in md


def test_figure_type_alias_also_handled():
    el = {"type": "Figure", "text": "", "metadata": {"image_path": "/tmp/e/f-9.png"}}
    assert convert_element_to_markdown(el) == "[FIGURE: f-9.png]"


def test_non_image_elements_are_unchanged_by_the_image_branch():
    """Guard against the branch widening: NarrativeText/Title/Table must not
    acquire a marker."""
    assert convert_element_to_markdown({"type": "NarrativeText", "text": "Torque to 40 Nm."}) == "Torque to 40 Nm."
    assert "[FIGURE" not in convert_element_to_markdown(
        {"type": "Table", "text": "a b", "metadata": {}}
    )
