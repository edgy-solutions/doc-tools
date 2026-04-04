import oracledb
from typing import Dict, Any, Optional
from pydantic import Field
from dagster import Definitions, asset, AssetExecutionContext
from dagster.components import Component, ComponentLoadContext
from dagster.components.resolved.base import Resolvable
from dagster.components.resolved.model import Model

class OracleExtractorComponent(Component, Resolvable, Model):
    """A declarative Dagster Component that extracts metadata from Oracle."""
    
    name: str = Field(default="extract_oracle_metadata", description="The name of the asset.")
    domain: str = Field(default="DATA_ENGINEERING", description="Domain tag for the extracted metadata.")
    
    # Connection parameters
    host: str = Field(description="Oracle host")
    port: int = Field(default=1521, description="Oracle port")
    service_name: str = Field(description="Oracle Service Name or SID")
    username: str = Field(description="Oracle username")
    password: str = Field(description="Oracle password")

    def build_defs(self, context: ComponentLoadContext) -> Definitions:
        asset_name = self.name
        domain_tag = self.domain
        
        # Build the Oracle DSN string
        dsn_str = f"{self.host}:{self.port}/{self.service_name}"
        
        # Capture credentials in the closure
        db_user = self.username
        db_pass = self.password

        @asset(name=asset_name)
        def oracle_metadata_asset(context: AssetExecutionContext) -> dict:
            """
            Extracts table comments from Oracle's ALL_TAB_COMMENTS.
            Returns a mapping with the required domain tag: 
            {"owner.table_name": {"description": "DBA Description", "domain": "DOMAIN_TAG"}}
            """
            query = """
            SELECT 
                owner AS SchemaName, 
                table_name AS TableName, 
                comments AS Description
            FROM all_tab_comments
            WHERE comments IS NOT NULL
            """
            
            metadata_map = {}
            try:
                connection = oracledb.connect(user=db_user, password=db_pass, dsn=dsn_str)
                with connection.cursor() as cursor:
                    cursor.execute(query)
                    for row in cursor:
                        table_key = f"{row[0]}.{row[1]}".lower()
                        # 🟢 INJECT THE DOMAIN TAG HERE
                        metadata_map[table_key] = {
                            "description": row[2],
                            "domain": domain_tag
                        }
                        
                context.log.info(f"Extracted {len(metadata_map)} table descriptions tagged with domain '{domain_tag}'.")
                return metadata_map
            except Exception as e:
                context.log.error(f"Failed to extract Oracle metadata: {e}")
                return {}
            finally:
                if 'connection' in locals():
                    connection.close()

        return Definitions(assets=[oracle_metadata_asset])