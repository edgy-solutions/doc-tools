from typing import List, Any, Dict

def detect_layout(slide_elements: List[Dict[str, Any]]) -> str:
    """
    Detects the layout archetype of a slide/page based on heuristics.
    
    Args:
        slide_elements: List of dictionaries representing elements on the slide.
                        Expected keys: 'type' (str), 'text' (str), 'metadata' (dict).
                        Metadata may contain 'coordinates' or 'image_path' etc.
                        
    Returns:
        One of: 'hero', 'documentary', 'split', 'content_caption', 'grid', 'table', 'blank'
    """
    
    # Step A: Inventory
    tables = 0
    embedded_artifacts = 0 # images, videos, figures
    text_content = ""
    
    max_embedded_width_ratio = 0.0
    
    for el in slide_elements:
        el_type = el.get("type", "").lower()
        text = el.get("text", "") or ""
        metadata = el.get("metadata", {})
        
        # Accumulate text
        if el_type in ["title", "narrativeText", "listitem", "text"]:
             text_content += text + " "
             
        # Count Tables
        if el_type == "table":
            tables += 1
            
        # Count Embedded (Image, Figure, Picture)
        if el_type in ["image", "figure", "picture"]:
            embedded_artifacts += 1
            
            coords = metadata.get("coordinates")
            if coords:
                try:
                    xs = [p[0] for p in coords.points] if hasattr(coords, 'points') else [p[0] for p in coords]
                    width = max(xs) - min(xs)
                    
                    slide_width_est = 1280 
                    ratio = width / slide_width_est
                    if ratio > max_embedded_width_ratio:
                        max_embedded_width_ratio = ratio
                except:
                    pass

    text_length = len(text_content.strip())
    
    # Step B: Apply Heuristics
    
    # 1. Table
    if tables > 0:
        return "table"
        
    # 2. Hero (No embedded, short text)
    if embedded_artifacts == 0 and text_length < 200:
        return "hero"
        
    # 3. Documentary (No embedded, long text)
    if embedded_artifacts == 0 and text_length >= 200:
        return "documentary"
        
    # 4. Grid (3+ embedded)
    if embedded_artifacts >= 3:
        return "grid"
        
    # 5. Single Embedded Logic
    if embedded_artifacts == 1:
        if max_embedded_width_ratio > 0.6: 
            return "content_caption"
        else:
            return "split"
            
    # 6. Default Fallback
    if embedded_artifacts == 2:
        return "split" 
        
    return "documentary"
