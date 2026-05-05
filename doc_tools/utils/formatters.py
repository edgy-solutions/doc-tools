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
    
    if el_type == "Table":
        metadata = element.get("metadata", {}) if isinstance(element, dict) else getattr(element, "metadata", None)
        
        # Safely extract text_as_html
        html_str = None
        if isinstance(metadata, dict):
            html_str = metadata.get("text_as_html")
        elif metadata:
            html_str = getattr(metadata, "text_as_html", None)
            
        if html_str:
            try:
                # Wrap HTML in StringIO to avoid pandas deprecation warnings
                dfs = pd.read_html(StringIO(html_str))
                if dfs:
                    df = dfs[0]
                    df.fillna("", inplace=True) # Replace NaNs with empty strings
                    return df.to_markdown(index=False)
            except Exception as e:
                logger.warning(f"HTML to Markdown conversion failed: {e}. Falling back to HTML.")
                return html_str # Fallback 1: Return the raw HTML
                
    # Fallback 2: Return standard text for non-tables or failed extractions
    return el_text
