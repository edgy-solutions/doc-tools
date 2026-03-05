import json
import os
import shutil
from typing import List, Any, Dict
import requests
import warnings
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# 1. Suppress the annoying "Unverified HTTPS request" warnings
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# 2. Monkeypatch requests.Session to always set verify=False
# This overrides the default behavior for ALL requests in this process
old_request = requests.Session.request

def unverified_request(self, method, url, *args, **kwargs):
    print(f"[SSL BYPASS] Downloading: {url}")
    kwargs['verify'] = False
    return old_request(self, method, url, *args, **kwargs)

requests.Session.request = unverified_request

# Now import unstructured
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

def extract_text_and_metadata(file_path: str, extract_images: bool = False, image_output_dir: str = None) -> List[Dict[str, Any]]:
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
