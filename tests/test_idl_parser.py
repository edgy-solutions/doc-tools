import os
import tempfile
import pytest
from doc_tools.ingestion.idl_parser import IDLParser

@pytest.fixture
def idl_parser():
    return IDLParser()

def test_idl_parser_extracts_structs_and_comments(idl_parser):
    idl_content = """
    module Vehicle {
        module Telemetry {
            struct RotorData {
                long rotor_id; // The ID of the rotor
                sequence<double> rpm_history; /* The RPM history */
                string model_name; // The model name
            };
        };
    };
    """
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.idl', delete=False) as f:
        f.write(idl_content)
        temp_path = f.name
        
    try:
        structs = idl_parser.parse(temp_path)
        
        assert len(structs) == 1
        
        struct = structs[0]
        assert struct["struct_name"] == "Vehicle::Telemetry::RotorData"
        assert len(struct["fields"]) == 3
        
        # Field 1: rotor_id
        assert struct["fields"][0]["name"] == "rotor_id"
        assert struct["fields"][0]["idl_type"] == "long"
        assert struct["fields"][0]["datahub_type"] == "NumberTypeClass"
        assert struct["fields"][0]["description"] == "The ID of the rotor"
        
        # Field 2: rpm_history
        assert struct["fields"][1]["name"] == "rpm_history"
        assert struct["fields"][1]["idl_type"] == "sequence<double>"
        assert struct["fields"][1]["datahub_type"] == "ArrayTypeClass"
        assert struct["fields"][1]["description"] == "The RPM history"
        
        # Field 3: model_name
        assert struct["fields"][2]["name"] == "model_name"
        assert struct["fields"][2]["idl_type"] == "string"
        assert struct["fields"][2]["datahub_type"] == "StringTypeClass"
        assert struct["fields"][2]["description"] == "The model name"
        
    finally:
        os.unlink(temp_path)
