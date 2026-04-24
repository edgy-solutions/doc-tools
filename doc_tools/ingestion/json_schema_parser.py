import json
from typing import Dict, List, Any

# DataHub type mappings
JSON_TO_DATAHUB_TYPE_MAP = {
    "integer": "NumberTypeClass",
    "number": "NumberTypeClass",
    "string": "StringTypeClass",
    "boolean": "BooleanTypeClass",
    "array": "ArrayTypeClass",
    "object": "RecordTypeClass",
}

class JSONSchemaParser:
    def __init__(self):
        pass

    def _traverse_properties(self, properties: Dict[str, Any], prefix: str = "") -> List[Dict[str, Any]]:
        fields = []
        for prop_name, prop_details in properties.items():
            full_name = f"{prefix}{prop_name}"
            json_type = prop_details.get("type", "string")
            datahub_type = JSON_TO_DATAHUB_TYPE_MAP.get(json_type, "StringTypeClass")
            
            description = prop_details.get("description", "")
            if "enum" in prop_details:
                enum_vals = ", ".join(str(v) for v in prop_details["enum"])
                if description:
                    description += f" (Enum: {enum_vals})"
                else:
                    description = f"Enum: {enum_vals}"
                    
            fields.append({
                "name": full_name,
                "json_type": json_type,
                "datahub_type": datahub_type,
                "description": description
            })
            
            # Handle nested objects
            if json_type == "object" and "properties" in prop_details:
                fields.extend(self._traverse_properties(prop_details["properties"], prefix=f"{full_name}."))
                
            # Handle arrays of objects
            if json_type == "array" and "items" in prop_details:
                items = prop_details["items"]
                if items.get("type") == "object" and "properties" in items:
                    fields.extend(self._traverse_properties(items["properties"], prefix=f"{full_name}[]."))
                    
        return fields

    def parse(self, file_path: str) -> List[Dict[str, Any]]:
        with open(file_path, 'r', encoding='utf-8') as f:
            schema = json.load(f)
            
        struct_name = schema.get("title", "UnknownSchema")
        properties = schema.get("properties", {})
        
        fields = self._traverse_properties(properties)
        
        for field in fields:
            field["struct_name"] = struct_name
            
        return [{
            "struct_name": struct_name,
            "fields": fields
        }]
