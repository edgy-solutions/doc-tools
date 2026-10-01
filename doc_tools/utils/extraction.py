import json
import os
import shutil
from typing import List, Any, Dict
from unstructured.partition.auto import partition
from unstructured.staging.base import elements_to_json

# Configure Tesseract OCR path
def configure_tesseract():
    """
    Auto-discover and configure tesseract executable path for both Windows and Linux.
    Checks: PATH, environment variables, and common installation locations.
    """
    try:
        # Unstructured uses unstructured_pytesseract, not standard pytesseract
        import unstructured_pytesseract as pytesseract
        
        # First check if tesseract is already in PATH
        if shutil.which('tesseract'):
            return  # Already accessible, no need to configure
        
        # Check TESSERACT_CMD environment variable
        tesseract_env = os.getenv('TESSERACT_CMD')
        if tesseract_env and os.path.isfile(tesseract_env):
            pytesseract.pytesseract.tesseract_cmd = tesseract_env
            print(f"Configured tesseract from TESSERACT_CMD: {tesseract_env}")
            return
        
        # Platform-specific common installation paths
        common_paths = []
        if os.name == 'nt':  # Windows
            common_paths = [
                r'C:\Program Files\Tesseract-OCR\tesseract.exe',
                r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
                os.path.expanduser(r'~\AppData\Local\Tesseract-OCR\tesseract.exe'),
            ]
        else:  # Linux/Mac
            common_paths = [
                '/usr/bin/tesseract',
                '/usr/local/bin/tesseract',
                '/opt/homebrew/bin/tesseract',  # Mac with Homebrew
            ]
        
        # Try each common path
        for path in common_paths:
            if os.path.isfile(path):
                pytesseract.pytesseract.tesseract_cmd = path
                print(f"Found and configured tesseract at: {path}")
                return
        
        # If we get here, tesseract wasn't found
        print("Warning: Tesseract not found. OCR may not work properly.")
        print("Install tesseract or set TESSERACT_CMD environment variable.")
        
    except ImportError as e:
        # unstructured_pytesseract not installed
        print(f"Warning: Could not import unstructured_pytesseract: {e}")
        pass

# Configure tesseract when module is imported
configure_tesseract()

def extract_text_and_metadata(file_path: str, extract_images: bool = False, image_output_dir: str = None, pdf_image_dpi: int = None) -> List[Dict[str, Any]]:
    """
    Extract text, metadata, and optionally images from a file using unstructured.io.
    Returns a list of dictionaries representing the elements.
    """
    try:
        strategy = "auto" # Let unstructured decide based on available libs
        
        kwargs = {
            "strategy": strategy,
            "infer_table_structure": True,
            "include_slide_notes": True,  # Extract speaker notes if applicable
        }
        if extract_images and image_output_dir:
            # Capture Images (Diagrams, Clip Art, Photos) and Tables
            kwargs[ "strategy"] = "hi_res"
            kwargs["extract_image_block_types"] = ["Image", "Table"]
            kwargs["extract_image_block_to_payload"] = False # Save to disk
            kwargs["extract_image_block_output_dir"] = image_output_dir
            if pdf_image_dpi:
                # Render DPI for hi_res page rasterization -> the DPI the cropped
                # Table/Image blocks (used by the sustainment vision pass) are
                # captured at. Surfaced as config (DOC_PARSER_PDF_IMAGE_DPI) for
                # reproducibility; >=150 recommended, higher if table text is small.
                kwargs["pdf_image_dpi"] = int(pdf_image_dpi)

        elements = partition(filename=file_path, **kwargs)
        
        # Convert to list of dicts
        element_dicts = []
        for el in elements:
            d = el.to_dict()
            # Add image path if available in metadata
            if "image_path" in d.get("metadata", {}):
                # The metadata might contain the absolute path, we might want to normalize it or just keep it
                pass
            element_dicts.append(d)
            
        return element_dicts
    except Exception as e:
        print(f"Error extracting from {file_path}: {e}")
        raise


def rasterize_pdf_pages(file_path: str, out_dir: str, dpi: int = 300) -> List[Dict[str, Any]]:
    """Render each PDF page to a full-page JPEG in ``out_dir``.

    This is the CONTEXT half of the evidence card — which table on the page, where
    it sits, what surrounds it (headers, effectivity dates, footnotes engineers
    actually check). The table crops (from unstructured's hi_res path) are the
    DETAIL half. unstructured renders a full-page bitmap internally but only writes
    the cropped Image/Table blocks to disk, so the page raster must be produced
    here.

    The render DPI is deliberately INDEPENDENT of the crop DPI: the viewer
    normalizes each bbox against the element's ``page_dims`` and positions the
    highlight as a FRACTION of the rendered page, so the overlay lands correctly at
    any render size (the sealed bbox-scale rule).

    THE DEFAULT HAS MOVED TWICE IN ONE DAY (2026-10-01) AND BOTH STEPS WERE
    MEASURED. It was 150, on the rationale that the page is context rather than a
    row-level read. The SUSTAINMENT second witness made that false by transcribing
    this raster to corroborate header dates: at 150 it collapsed a wrapped
    two-column date grid and substituted digits (06->08, 07->02), and at 200 it
    read both dates correctly. It is now 300, for a different consumer again --
    `witness_regions` cuts the header-block and dates-block CROPS the header
    witness reads out of THIS raster, and a crop cannot be sharper than the image
    it is cut from.

    That makes the page raster serve two readers with different needs, which is
    worth stating plainly because the measurement is NOT uniformly in favour of
    300. Asked to transcribe a WHOLE page, the model did worse at 300 than at 200
    (3 of 6 scored tokens against 5 of 6) and took longer (289s against 223s,
    against a hard ~300s server-side ceiling). Asked about a CROP, more pixels can
    only help. The resolution of that tension is that the whole-page transcription
    no longer answers header questions at all -- it serves
    `text_layer_health.uncorroborated_parts`, where containment of a part number
    is the test -- so what 300 costs is latency on the page call, and what it buys
    is the detail of every crop. If page transcriptions start hitting the ceiling,
    the fix is to downscale the page in the transcription path, NOT to lower this.

    Lowering it will silently degrade both witnesses. The raster is written at
    INGEST, so a change here is inert until documents are re-ingested.

    Returns a list of ``{page (1-based), path, basename, width, height, dpi}`` — one
    per page. Returns ``[]`` for non-PDF inputs (PPTX etc. have no page raster).
    """
    if not file_path.lower().endswith(".pdf"):
        return []
    import pypdfium2 as pdfium
    scale = float(dpi) / 72.0  # PDF user space is 72 units/inch
    pages_out: List[Dict[str, Any]] = []
    pdf = pdfium.PdfDocument(file_path)
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            try:
                pil = page.render(scale=scale).to_pil().convert("RGB")
            finally:
                page.close()
            n = i + 1
            basename = f"page-{n}.jpg"
            local_path = os.path.join(out_dir, basename)
            pil.save(local_path, format="JPEG", quality=85)
            pages_out.append({
                "page": n,
                "path": local_path,
                "basename": basename,
                "width": pil.width,
                "height": pil.height,
                "dpi": int(dpi),
            })
    finally:
        pdf.close()
    return pages_out
