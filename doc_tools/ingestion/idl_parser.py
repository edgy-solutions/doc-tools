import io
import os
import re
import sys
import uuid
import inspect
import shutil
import subprocess
import tempfile
import importlib.util
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Sequence, get_args, get_origin

from pcpp import Preprocessor
from dagster import get_dagster_logger
from cyclonedds.idl import IdlStruct

logger = get_dagster_logger()

PYTHON_TYPE_TO_DATAHUB_MAP = {
    "int8": "NumberTypeClass", "int16": "NumberTypeClass",
    "int32": "NumberTypeClass", "int64": "NumberTypeClass",
    "uint8": "NumberTypeClass", "uint16": "NumberTypeClass",
    "uint32": "NumberTypeClass", "uint64": "NumberTypeClass",
    "float32": "NumberTypeClass", "float64": "NumberTypeClass",
    "float": "NumberTypeClass", "int": "NumberTypeClass",
    "str": "StringTypeClass", "char": "StringTypeClass", "wchar": "StringTypeClass",
    "bool": "BooleanTypeClass",
    "bytes": "BytesTypeClass", "byte": "BytesTypeClass", "octet": "BytesTypeClass",
}


def _map_datahub_type(idl_type: str) -> str:
    if idl_type in PYTHON_TYPE_TO_DATAHUB_MAP:
        return PYTHON_TYPE_TO_DATAHUB_MAP[idl_type]
    lower = idl_type.lower()
    if lower.startswith(("int", "uint", "float", "double", "long", "short")):
        return "NumberTypeClass"
    if lower.startswith("bool"):
        return "BooleanTypeClass"
    if lower in ("byte", "octet", "bytes"):
        return "BytesTypeClass"
    return "StringTypeClass"


class IDLParser:
    def _extract_comments(self, content: str) -> Dict[str, Dict[str, str]]:
        comments: Dict[str, Dict[str, str]] = {}
        current_struct: Optional[str] = None
        pending: List[str] = []
        r_struct = re.compile(r'\bstruct\s+(\w+)')
        r_field_trail = re.compile(r'(\w+)\s*;\s*(?://\s*(.*)|/\*\s*(.*?)\s*\*/)')
        r_field_only = re.compile(r'^\s*[\w:<>\[\]\s,]+?\b(\w+)\s*;')
        r_lead_line = re.compile(r'^\s*//\s*(.*)$')
        r_lead_block = re.compile(r'^\s*/\*+\s*(.*?)\s*\*+/\s*$')

        for raw in content.split('\n'):
            line = raw.strip()
            if not line:
                pending = []
                continue
            m = r_struct.search(line)
            if m and not line.startswith('//'):
                current_struct = m.group(1)
                comments.setdefault(current_struct, {})
                pending = []
                continue
            if current_struct is None:
                continue
            lead = r_lead_line.match(line) or r_lead_block.match(line)
            if lead:
                pending.append(lead.group(1).strip())
                continue
            trail = r_field_trail.search(line)
            if trail:
                field = trail.group(1)
                text = (trail.group(2) or trail.group(3) or "").strip()
                if text:
                    comments[current_struct][field] = text
                elif pending:
                    comments[current_struct][field] = " ".join(pending).strip()
                pending = []
                continue
            fo = r_field_only.match(line)
            if fo and pending:
                comments[current_struct][fo.group(1)] = " ".join(pending).strip()
                pending = []
                continue
            pending = []
        return comments

    def _parse_python_files(self, directory: str) -> List[Dict[str, Any]]:
        structs: List[Dict[str, Any]] = []
        sys.path.insert(0, directory)
        injected: List[str] = []
        try:
            for root, _, files in os.walk(directory):
                for file in files:
                    if not file.endswith('.py') or file == '__init__.py':
                        continue
                    filepath = os.path.join(root, file)
                    module_name = f"_idl_{uuid.uuid4().hex}"
                    spec = importlib.util.spec_from_file_location(module_name, filepath)
                    if spec is None or spec.loader is None:
                        continue
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    injected.append(module_name)
                    try:
                        spec.loader.exec_module(module)
                    except Exception as e:
                        logger.error(f"Failed to import generated module {filepath}: {e}")
                        continue

                    rel = os.path.relpath(filepath, directory)
                    parts = os.path.dirname(rel).split(os.sep)
                    prefix = "::".join(p for p in parts if p)
                    if prefix:
                        prefix += "::"

                    for _, obj in inspect.getmembers(module, inspect.isclass):
                        if obj.__module__ != module.__name__:
                            continue
                        if not issubclass(obj, IdlStruct) or obj is IdlStruct:
                            continue
                        typename = getattr(obj, '__idl_typename__', obj.__name__)
                        if "::" in typename or "." in typename:
                            struct_name = typename.replace(".", "::")
                        else:
                            struct_name = f"{prefix}{typename}"

                        fields = []
                        for fname, ftype in getattr(obj, "__annotations__", {}).items():
                            origin = get_origin(ftype)
                            args = get_args(ftype)
                            idl_type = "str"
                            datahub_type: Optional[str] = None

                            if hasattr(ftype, "__metadata__"):  # Annotated
                                inner = args[0] if args else None
                                if inner is not None and hasattr(inner, "__name__"):
                                    idl_type = inner.__name__
                            elif origin in (list, Sequence) or ftype is list:
                                idl_type = "sequence"
                                datahub_type = "ArrayTypeClass"
                            elif hasattr(ftype, "__name__"):
                                idl_type = ftype.__name__

                            if datahub_type is None:
                                datahub_type = _map_datahub_type(idl_type)

                            fields.append({
                                "name": fname,
                                "idl_type": idl_type,
                                "datahub_type": datahub_type,
                                "struct_name": obj.__name__,
                            })
                        structs.append({"struct_name": struct_name, "fields": fields})
        finally:
            sys.path.pop(0)
            for name in injected:
                sys.modules.pop(name, None)
        return structs

    def _xml_member_doc(self, member_elem) -> str:
        for ann in member_elem.findall("annotation"):
            doc = ann.find("documentation")
            if doc is not None and doc.text:
                return doc.text.strip()
        if (doc_attr := member_elem.get("documentation")):
            return doc_attr.strip()
        doc = member_elem.find("documentation")
        if doc is not None and doc.text:
            return doc.text.strip()
        return ""

    def _parse_rti_xml(self, xml_path: str) -> List[Dict[str, Any]]:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        typedefs: Dict[str, str] = {}
        enums: set = set()

        def collect(elem, prefix=""):
            for child in elem:
                name = child.get("name", "")
                fq = f"{prefix}{name}" if prefix else name
                if child.tag in ("types", "dds"):
                    collect(child, prefix)
                elif child.tag == "module":
                    collect(child, f"{fq}::")
                elif child.tag == "typedef":
                    target = child.get("type") or child.get("nonBasicTypeName") or "string"
                    typedefs[fq] = target
                    typedefs.setdefault(name, target)
                elif child.tag == "enum":
                    enums.add(fq)
                    enums.add(name)

        collect(root)

        def resolve(idl_type: str, seen=None) -> str:
            seen = seen or set()
            if idl_type in seen:
                return idl_type
            seen.add(idl_type)
            if idl_type in typedefs:
                return resolve(typedefs[idl_type], seen)
            return idl_type

        structs: List[Dict[str, Any]] = []

        def process(elem, prefix=""):
            for child in elem:
                if child.tag in ("types", "dds"):
                    process(child, prefix)
                elif child.tag == "module":
                    mod = child.get("name", "")
                    process(child, f"{prefix}{mod}::" if prefix else f"{mod}::")
                elif child.tag in ("struct", "valuetype"):
                    struct_name = f"{prefix}{child.get('name', '')}"
                    fields = []
                    for member in child.findall("member"):
                        fname = member.get("name", "")
                        raw_type = member.get("type") or "string"
                        if raw_type == "nonBasic":
                            raw_type = member.get("nonBasicTypeName", "string")
                        resolved = resolve(raw_type)

                        is_array = bool(
                            member.get("sequenceMaxLength")
                            or member.get("arrayDimensions")
                        )
                        if is_array:
                            datahub_type = "ArrayTypeClass"
                        elif resolved in enums or raw_type in enums:
                            datahub_type = "EnumTypeClass"
                        else:
                            datahub_type = _map_datahub_type(resolved)

                        fields.append({
                            "name": fname,
                            "idl_type": raw_type,
                            "resolved_type": resolved,
                            "datahub_type": datahub_type,
                            "struct_name": struct_name,
                            "description": self._xml_member_doc(member),
                        })
                    structs.append({"struct_name": struct_name, "fields": fields})

        process(root)
        return structs

    def parse(
        self,
        file_path: str,
        include_dirs: Optional[List[str]] = None,
        use_pcpp: bool = False,
    ) -> List[Dict[str, Any]]:
        base_path = os.path.splitext(file_path)[0]
        xml_path = base_path + ".xml"
        if os.path.exists(xml_path):
            idl_mtime = os.path.getmtime(file_path)
            xml_mtime = os.path.getmtime(xml_path)
            if idl_mtime > xml_mtime:
                logger.warning(
                    f"XML {xml_path} is older than IDL {file_path} "
                    f"(IDL mtime={idl_mtime}, XML mtime={xml_mtime}) — proceeding with XML; "
                    f"regenerate if schemas have diverged."
                )
            else:
                logger.info(f"Using pre-flattened XML {xml_path} for {file_path}")
            
            if include_dirs or use_pcpp:
                logger.info("XML shortcut used: include_dirs and use_pcpp arguments are ignored.")
            
            return self._parse_rti_xml(xml_path)

        include_dirs = include_dirs or []
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        if use_pcpp:
            p = Preprocessor()
            for d in include_dirs:
                p.add_path(d)
            p.parse(content)
            buf = io.StringIO()
            p.write(buf)
            flattened_content = buf.getvalue()
        else:
            flattened_content = content

        comments_map = self._extract_comments(content)

        with tempfile.TemporaryDirectory() as tmpdir:
            if use_pcpp:
                target_idl_path = os.path.join(tmpdir, "temp.idl")
                with open(target_idl_path, 'w', encoding='utf-8') as f:
                    f.write(flattened_content)
            else:
                target_idl_path = file_path

            idlc_bin = shutil.which("idlc")
            if not idlc_bin:
                raise RuntimeError("idlc not found on PATH")

            cmd = [idlc_bin, "-l", "py"]
            for d in include_dirs:
                cmd.extend(["-I", os.path.abspath(d)])
            cmd.append(os.path.abspath(target_idl_path))

            res = subprocess.run(cmd, cwd=tmpdir, capture_output=True, text=True)

            python_files_generated = any(
                f.endswith('.py')
                for _, _, fs in os.walk(tmpdir)
                for f in fs
            )
            if not python_files_generated:
                logger.error(f"idlc produced no python output for {file_path}")
                logger.error(f"cmd: {' '.join(cmd)}")
                logger.error(f"stdout: {res.stdout}")
                logger.error(f"stderr: {res.stderr}")
                logger.error("First 500 chars of flattened content:")
                logger.error(flattened_content[:500])
                raise RuntimeError(
                    f"idlc produced no output for {file_path} "
                    f"(rc={res.returncode}): {res.stderr}"
                )

            structs = self._parse_python_files(tmpdir)

        for s in structs:
            short = s["struct_name"].split("::")[-1]
            for f in s["fields"]:
                f["description"] = comments_map.get(short, {}).get(f["name"], "")
        return structs
