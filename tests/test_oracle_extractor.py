import pytest
from unittest.mock import patch, MagicMock
from dagster import build_asset_context
from doc_tools.components.oracle_extractor import OracleExtractorComponent

def test_oracle_extractor_component_initialization():
    component = OracleExtractorComponent(
        name="test_oracle_extractor",
        domain="TEST_DOMAIN",
        host="localhost",
        port=1521,
        service_name="ORCL",
        username="user",
        password="password"
    )
    assert component.name == "test_oracle_extractor"
    assert component.domain == "TEST_DOMAIN"
    
    defs = component.build_defs(None)
    assert len(defs.assets) == 1
    
    asset_def = next(iter(defs.assets))
    assert asset_def.op.name == "test_oracle_extractor"

@patch("doc_tools.components.oracle_extractor.oracledb.connect")
def test_oracle_extractor_asset_execution(mock_connect):
    # Setup mock
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    
    # Mock rows returned by the query
    # Query returns: owner, table_name, comments
    mock_cursor.__iter__.return_value = [("HR", "EMPLOYEES", "Employee table")]
    
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_connect.return_value = mock_conn
    
    component = OracleExtractorComponent(
        name="test_oracle_extractor",
        domain="TEST_DOMAIN",
        host="localhost",
        service_name="ORCL",
        username="user",
        password="password"
    )
    defs = component.build_defs(None)
    asset_def = next(iter(defs.assets))
    
    # Execute the asset
    result = asset_def(context=build_asset_context())
    
    assert "hr.employees" in result
    assert result["hr.employees"]["description"] == "Employee table"
    assert result["hr.employees"]["domain"] == "TEST_DOMAIN"
    
    # Verify connection parameters
    mock_connect.assert_called_once_with(user="user", password="password", dsn="localhost:1521/ORCL")
