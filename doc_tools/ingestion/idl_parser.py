import os
import re
from typing import Dict, List, Any
from idl_parser import parser

# DataHub type mappings
IDL_TO_DATAHUB_TYPE_MAP = {
    "short": "NumberTypeClass",
    "long": "NumberTypeClass",
    "long long": "NumberTypeClass",
    "unsigned short": "NumberTypeClass",
    "unsigned long": "NumberTypeClass",
    "unsigned long long": "NumberTypeClass",
    "float": "NumberTypeClass",
    "double": "NumberTypeClass",
    "long double": "NumberTypeClass",
    "char": "StringTypeClass",
    "wchar": "StringTypeClass",
    "string": "StringTypeClass",
    "wstring": "StringTypeClass",
    "boolean": "BooleanTypeClass",
    "octet": "BytesTypeClass",
}

class IDLParser:
    def __init__(self):
        self.parser = parser.IDLParser()

    def _extract_comments(self, content: str) -> Dict[str, Dict[str, str]]:
        # Heuristic to extract comments since idl-parser AST drops them
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

    def _traverse_modules(self, node, prefix="") -> List[Dict[str, Any]]:
        structs = []
        
        if hasattr(node, "is_struct") and node.is_struct:
            struct_name = f"{prefix}{node.name}"
            fields = []
            for m in node.members:
                is_seq = getattr(m.type, "is_sequence", False)
                idl_type = getattr(m.type, "name", "string").replace(" ", "")
                
                if is_seq:
                    datahub_type = "ArrayTypeClass"
                else:
                    datahub_type = IDL_TO_DATAHUB_TYPE_MAP.get(idl_type, "StringTypeClass")
                
                fields.append({
                    "name": m.name,
                    "idl_type": idl_type,
                    "datahub_type": datahub_type,
                    "struct_name": node.name
                })
                
            structs.append({
                "struct_name": struct_name,
                "fields": fields
            })
            
        if hasattr(node, "modules"):
            for m in node.modules:
                node_name = getattr(node, "name", "")
                new_prefix = f"{m.name}::" if node_name == "__global__" else f"{prefix}{m.name}::"
                structs.extend(self._traverse_modules(m, new_prefix))
                
        if hasattr(node, "structs"):
            for s in node.structs:
                structs.extend(self._traverse_modules(s, prefix))
                
        return structs

    def parse(self, file_path: str) -> List[Dict[str, Any]]:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        comments_map = self._extract_comments(content)
        
        global_module = self.parser.load(content)
        structs = self._traverse_modules(global_module, "")
        
        # Inject comments
        for s in structs:
            short_struct_name = s["struct_name"].split("::")[-1]
            for f in s["fields"]:
                f["description"] = comments_map.get(short_struct_name, {}).get(f["name"], "")
                
        return structs