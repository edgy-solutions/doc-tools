import os
import subprocess
import tempfile
import io
import ast
from typing import Dict, List, Any
from pcpp import Preprocessor
from dagster import get_dagster_logger



logger = get_dagster_logger()

# DataHub type mappings based on cyclonedds python types
PYTHON_TYPE_TO_DATAHUB_MAP = {
    "int8": "NumberTypeClass",
    "int16": "NumberTypeClass",
    "int32": "NumberTypeClass",
    "int64": "NumberTypeClass",
    "uint8": "NumberTypeClass",
    "uint16": "NumberTypeClass",
    "uint32": "NumberTypeClass",
    "uint64": "NumberTypeClass",
    "float32": "NumberTypeClass",
    "float64": "NumberTypeClass",
    "float": "NumberTypeClass",
    "int": "NumberTypeClass",
    "str": "StringTypeClass",
    "char": "StringTypeClass",
    "wchar": "StringTypeClass",
    "bool": "BooleanTypeClass",
    "bytes": "BytesTypeClass",
}

class IDLParser:
    def __init__(self):
        pass

    def _extract_comments(self, content: str) -> Dict[str, Dict[str, str]]:
        # Heuristic to extract comments
        import re
        comments = {}
        current_struct = None
        
        lines = content.split('\n')
        for line in lines:
            line_clean = line.strip()
            struct_match = re.search(r'struct\s+(\w+)', line_clean)
            if struct_match and not line_clean.startswith('//'):
                current_struct = struct_match.group(1)
                comments[current_struct] = {}
                continue
                
            if current_struct:
                # look for field and comment
                field_match = re.search(r'(\w+)\s*;\s*(?://(.*)|/\*(.*)\*/)', line_clean)
                if field_match:
                    field_name = field_match.group(1)
                    c1 = field_match.group(2)
                    c2 = field_match.group(3)
                    comment = (c1 or c2 or "").strip()
                    if comment:
                        comments[current_struct][field_name] = comment
        return comments

    def _parse_python_files(self, directory: str) -> List[Dict[str, Any]]:
        import sys
        import importlib.util
        import inspect
        from typing import get_args, get_origin
        from cyclonedds.idl import IdlStruct

        structs = []
        # Add directory to sys.path for relative imports within the generated files
        sys.path.insert(0, directory)
        try:
            for root, _, files in os.walk(directory):
                for file in files:
                    if not file.endswith('.py') or file == '__init__.py':
                        continue
                    
                    filepath = os.path.join(root, file)
                    module_name = file[:-3]
                    
                    spec = importlib.util.spec_from_file_location(module_name, filepath)
                    if spec is None or spec.loader is None:
                        continue
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    
                    try:
                        spec.loader.exec_module(module)
                    except Exception as e:
                        logger.error(f"Failed to import {module_name}: {e}")
                        continue
                    
                    # Determine prefix from directory structure
                    rel_path = os.path.relpath(filepath, directory)
                    module_parts = os.path.dirname(rel_path).split(os.sep)
                    prefix = "::".join(p for p in module_parts if p)
                    if prefix:
                        prefix += "::"
                    
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        if issubclass(obj, IdlStruct) and obj is not IdlStruct:
                            typename = getattr(obj, '__idl_typename__', obj.__name__)
                            if "::" in typename or "." in typename:
                                struct_name = typename.replace(".", "::")
                            else:
                                struct_name = f"{prefix}{typename}"
                            fields = []
                            
                            for field_name, field_type in getattr(obj, "__annotations__", {}).items():
                                origin = get_origin(field_type)
                                args = get_args(field_type)
                                
                                idl_type = "str"
                                datahub_type = "StringTypeClass"
                                
                                if origin is getattr(sys.modules.get('typing'), 'Annotated', type(None)):
                                    if args and len(args) > 1:
                                        idl_type = str(args[1])
                                elif origin is list or field_type is list or origin is getattr(sys.modules.get('typing'), 'Sequence', type(None)):
                                    idl_type = "sequence"
                                    datahub_type = "ArrayTypeClass"
                                elif hasattr(field_type, "__name__"):
                                    idl_type = field_type.__name__
                                    
                                # Basic datahub mapping
                                if datahub_type != "ArrayTypeClass":
                                    if "int" in idl_type or "float" in idl_type or "double" in idl_type:
                                        datahub_type = "NumberTypeClass"
                                    elif "bool" in idl_type:
                                        datahub_type = "BooleanTypeClass"
                                    elif "byte" in idl_type or "octet" in idl_type:
                                        datahub_type = "BytesTypeClass"
                                
                                fields.append({
                                    "name": field_name,
                                    "idl_type": idl_type,
                                    "datahub_type": datahub_type,
                                    "struct_name": obj.__name__
                                })
                                
                            structs.append({
                                "struct_name": struct_name,
                                "fields": fields
                            })
        finally:
            sys.path.pop(0)
        return structs

    def parse(self, file_path: str, include_dirs: List[str] = None, use_pcpp: bool = False) -> List[Dict[str, Any]]:
        if include_dirs is None:
            include_dirs = []
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if use_pcpp:
            p = Preprocessor()
            for d in include_dirs:
                p.add_path(d)
                
            p.parse(content)
            output = io.StringIO()
            p.write(output)
            flattened_content = output.getvalue()
        else:
            flattened_content = content
            
        comments_map = self._extract_comments(content)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write flattened content to a temp file
            if use_pcpp:
                target_idl_path = os.path.join(tmpdir, "temp.idl")
                with open(target_idl_path, 'w', encoding='utf-8') as f:
                    f.write(flattened_content)
            else:
                target_idl_path = file_path
                
            # Run cyclonedds idlc
            env = os.environ.copy()

            try:
                cmd = ["idlc", "-l", "py", "-d", tmpdir]
                if not use_pcpp:
                    for d in include_dirs:
                        cmd.extend(["-I", d])
                cmd.append(target_idl_path)
                
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    env=env
                )
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed parsing IDL file with cyclonedds idlc: {file_path}")
                logger.error(f"idlc stderr: {e.stderr}")
                logger.error("Dumping the first 500 characters of flattened_content to verify includes worked:")
                logger.error(flattened_content[:500])
                raise Exception(f"Failed to parse {file_path}. idlc error: {e.stderr}") from e
                
            # Parse the generated python files
            structs = self._parse_python_files(tmpdir)
        
        # Inject comments
        for s in structs:
            short_struct_name = s["struct_name"].split("::")[-1]
            for f in s["fields"]:
                f["description"] = comments_map.get(short_struct_name, {}).get(f["name"], "")
                
        return structs
