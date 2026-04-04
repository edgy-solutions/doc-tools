from typing import Dict, Any, Optional
from pydantic import Field
from dagster import Definitions, asset, AssetExecutionContext, Config
from dagster.components import Component, ComponentLoadContext
from dagster.components.resolved.base import Resolvable
from dagster.components.resolved.model import Model
import urllib.parse
from sqlalchemy import create_engine, text

class SqlServerExtractorComponent(Component, Resolvable, Model):
    """A declarative Dagster Component that extracts metadata from SQL Server."""
    
    name: str = Field(default="extract_sqlserver_metadata", description="The name of the asset.")
    domain: str = Field(default="DATA_ENGINEERING", description="Domain tag for the extracted metadata.")
    
    # Connection parameters
    host: str = Field(description="SQL Server host")
    port: int = Field(default=1433, description="SQL Server port")
    database: str = Field(description="SQL Server database name")
    username: str = Field(description="SQL Server username")
    password: str = Field(description="SQL Server password")
    driver: str = Field(default="ODBC Driver 18 for SQL Server", description="ODBC Driver name")
    trust_server_certificate: bool = Field(default=True, description="Trust Server Certificate")

    def build_defs(self, context: ComponentLoadContext) -> Definitions:
        asset_name = self.name
        domain_tag = self.domain
        
        # Build connection string
        # mssql+pyodbc://<username>:<password>@<host>:<port>/<database>?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes
        encoded_password = urllib.parse.quote_plus(self.password)
        encoded_driver = urllib.parse.quote_plus(self.driver)
        trust_cert = "yes" if self.trust_server_certificate else "no"
        
        conn_str = f"mssql+pyodbc://{self.username}:{encoded_password}@{self.host}:{self.port}/{self.database}?driver={encoded_driver}&TrustServerCertificate={trust_cert}"

        @asset(name=asset_name)
        def sqlserver_metadata_asset(context: AssetExecutionContext) -> dict:
            """
            Extracts table-level 'MS_Description' extended properties from SQL Server.
            Returns a mapping with the required domain tag: 
            {"schema.table_name": {"description": "DBA Description", "domain": "DOMAIN_TAG"}}
            """
            query = """
            SELECT 
                s.name AS SchemaName,
                t.name AS TableName,
                CAST(ep.value AS NVARCHAR(MAX)) AS Description
            FROM sys.extended_properties ep
            INNER JOIN sys.tables t ON ep.major_id = t.object_id
            INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
            WHERE ep.minor_id = 0 AND ep.name = 'MS_Description'
            """
            
            metadata_map = {}
            try:
                engine = create_engine(conn_str)
                with engine.connect() as conn:
                    result = conn.execute(text(query))
                    for row in result:
                        table_key = f"{row.SchemaName}.{row.TableName}".lower()
                        metadata_map[table_key] = {
                            "description": row.Description,
                            "domain": domain_tag 
                        }
                        
                context.log.info(f"Extracted {len(metadata_map)} table descriptions tagged with domain '{domain_tag}'.")
                return metadata_map
            except Exception as e:
                context.log.error(f"Failed to extract SQL Server metadata: {e}")
                return {}

        return Definitions(assets=[sqlserver_metadata_asset])