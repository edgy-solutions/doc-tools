import pytest
from unittest.mock import patch, MagicMock
from dagster import build_asset_context
from doc_tools.components.sqlserver_extractor import SqlServerExtractorComponent

def test_sqlserver_extractor_component_initialization():
    component = SqlServerExtractorComponent(
        name="test_sql_extractor",
        domain="TEST_DOMAIN",
        host="localhost",
        port=1433,
        database="testdb",
        username="user",
        password="password",
        driver="ODBC Driver 18 for SQL Server",
        trust_server_certificate=True
    )
    assert component.name == "test_sql_extractor"
    assert component.domain == "TEST_DOMAIN"
    
    defs = component.build_defs(None)
    assert len(defs.assets) == 1
    
    asset_def = next(iter(defs.assets))
    assert asset_def.op.name == "test_sql_extractor"

@patch("doc_tools.components.sqlserver_extractor.create_engine")
def test_sqlserver_extractor_asset_execution(mock_create_engine):
    # Setup mock
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_result = MagicMock()
    
    # Mock rows returned by the query
    row1 = MagicMock()
    row1.SchemaName = "dbo"
    row1.TableName = "users"
    row1.Description = "User table"
    
    mock_result.__iter__.return_value = [row1]
    mock_conn.execute.return_value = mock_result
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_create_engine.return_value = mock_engine
    
    component = SqlServerExtractorComponent(
        name="test_sql_extractor",
        domain="TEST_DOMAIN",
        host="localhost",
        database="testdb",
        username="user",
        password="password"
    )
    defs = component.build_defs(None)
    asset_def = next(iter(defs.assets))
    
    # Execute the asset
    result = asset_def(context=build_asset_context())
    
    assert "dbo.users" in result
    assert result["dbo.users"]["description"] == "User table"
    assert result["dbo.users"]["domain"] == "TEST_DOMAIN"
    
    # Verify the connection string
    mock_create_engine.assert_called_once()
    conn_str = mock_create_engine.call_args[0][0]
    assert "mssql+pyodbc://user:password@localhost:1433/testdb" in conn_str
