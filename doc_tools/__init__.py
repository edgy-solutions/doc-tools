import sys
import os

# Target: /doc-tools/doc_tools/baml_client
# __file__: /doc-tools/doc_tools/doc_tools/__init__.py
baml_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "baml_client")
if baml_dir not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from .definitions import defs

__all__ = ["defs"]
