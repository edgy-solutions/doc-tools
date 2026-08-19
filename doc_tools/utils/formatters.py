import os
import pandas as pd
from io import StringIO
import logging
from typing import Any, Dict, Union

logger = logging.getLogger(__name__)

def convert_element_to_markdown(element: Union[Dict[str, Any], Any]) -> str:
    """
    Takes an unstructured element (dict or object) and returns Markdown text.
    Converts HTML tables to Markdown grids.
    """
    # Handle both dict and object representations from unstructured
    el_type = element.get("type") if isinstance(element, dict) else getattr(element, "type", "")
    el_text = element.get("text", "") if isinstance(element, dict) else getattr(element, "text", "")
    
    if el_type in ("Image", "Figure"):
        # FIGURE PLACEHOLDER — the LLM cannot see bitmaps, and an unstructured
        # `Image` element carries its content in `metadata.image_path`, NOT in
        # `.text` (which is empty or a stray OCR fragment). Before this branch
        # existed every figure converted to "" and the assembled markdown had no
        # trace that a figure was ever there — so `figure_references` could only
        # be populated when the PROSE happened to say "see Figure 3", and a page
        # whose figures carry no inline callout produced an empty list even
        # though the document was full of diagrams.
        #
        # THE BASENAME IS THE JOIN KEY. `embedded_images_map` in
        # components/document_parser.py is keyed by the filenames of
        # `os.listdir(temp_extract_dir)`, and `metadata.image_path` points at a
        # file in THAT SAME directory — so `basename(image_path)` is exactly the
        # key whose value is the `s3://` URL. Emitting it here is what lets a
        # model-extracted `figure_references` entry be resolved to an actual
        # image downstream (s3:// -> FederatedImage -> bff /federated_image).
        # The document's own numbering ("Figure 3") is a DIFFERENT namespace and
        # joins to nothing; this one joins.
        #
        # Emitted IN READING ORDER, so the placeholder lands between the steps it
        # sits between on the page — that positional fact is what lets a figure be
        # attached to the right step rather than to the document as a whole.
        metadata = element.get("metadata", {}) if isinstance(element, dict) else getattr(element, "metadata", None)
        image_path = None
        if isinstance(metadata, dict):
            image_path = metadata.get("image_path")
        elif metadata:
            image_path = getattr(metadata, "image_path", None)

        # No image_path (some producers omit it) still emits a marker: the
        # POSITION of a figure is useful to the model even when the crop cannot
        # be joined. Deliberately no fabricated name — a placeholder with an
        # invented key would resolve to nothing and read as if it had.
        name = os.path.basename(image_path) if image_path else ""
        marker = f"[FIGURE: {name}]" if name else "[FIGURE]"
        caption = el_text.strip() if isinstance(el_text, str) else ""
        return marker + '\n' + caption if caption else marker

    if el_type == "Table":
        metadata = element.get("metadata", {}) if isinstance(element, dict) else getattr(element, "metadata", None)
        
        # Safely extract text_as_html
        html_str = None
        if isinstance(metadata, dict):
            html_str = metadata.get("text_as_html")
        elif metadata:
            html_str = getattr(metadata, "text_as_html", None)
            
        md_table = ""
        if html_str:
            try:
                # Wrap HTML in StringIO to avoid pandas deprecation warnings
                dfs = pd.read_html(StringIO(html_str))
                if dfs:
                    # Cast to object before fillna: an all-NaN / numeric column
                    # raises a pandas FutureWarning when filled with "" in place.
                    df = dfs[0].astype(object).fillna("")  # NaNs -> empty strings
                    md_table = df.to_markdown(index=False)
            except Exception as e:
                # Non-fatal: degenerate/empty table HTML (e.g. "No tables found
                # matching pattern") just falls back to the raw HTML. Debug-level
                # so it doesn't spam the logs once per table on every document.
                logger.debug(f"HTML to Markdown conversion failed, using raw HTML: {e}")
                md_table = html_str # Fallback to raw HTML
        
        # HYBRID APPROACH: Return both the spatial Markdown grid AND the supplemental raw text.
        # This helps the LLM if the OCR missed cells in the HTML structure but captured them in raw text.
        hybrid_output = f"### TABLE STRUCTURE (SPATIAL) ###\n{md_table if md_table else 'Structure unavailable'}\n\n"
        hybrid_output += f"### TABLE CONTENT (SUPPLEMENTAL RAW TEXT) ###\n{el_text}"
        return hybrid_output
                
    # Fallback 2: Return standard text for non-tables or failed extractions
    return el_text
