import json
import xml.etree.ElementTree as ET
from pydantic import Field
from dagster import Definitions, asset, AssetExecutionContext
from dagster.components import Component, ComponentLoadContext
from dagster.components.resolved.base import Resolvable
from dagster.components.resolved.model import Model
from dagster_aws.s3 import S3Resource
from dag_tools.components.s3_sensor.file_component import S3FileConfig
from doc_tools.partitions import design_files_partition

class DesignParserComponent(Component, Resolvable, Model):
    """A declarative Dagster Component that extracts design metadata from EDMX/JSON files."""
    
    name: str = Field(default="parse_design_metadata", description="The name of the asset.")

    def build_defs(self, context: ComponentLoadContext) -> Definitions:
        asset_name = self.name
        
        @asset(
            name=asset_name,
            partitions_def=design_files_partition
        )
        def design_metadata_asset(context: AssetExecutionContext, config: S3FileConfig, s3: S3Resource) -> dict:
            """
            Downloads a database design file from S3, parses its metadata, 
            and strictly tags all outputs with the inferred domain.
            """
            file_url = config.file_url
            if file_url.startswith("s3://"):
                url_parts = file_url[5:].split("/", 1)
                s3_bucket = url_parts[0]
                s3_key = url_parts[1]
            else:
                # Fallback if not an s3:// URL
                s3_bucket = "processing-artifacts"
                s3_key = context.partition_key
                
            # Infer domain from s3_key (e.g. domain/design_files/file.edmx)
            parts = s3_key.split('/')
            if len(parts) >= 2:
                domain = parts[0].upper()
            else:
                domain = "DATA_ENGINEERING"
                
            context.log.info(f"Processing {s3_key} for domain: {domain}")
            
            try:
                file_obj = s3.get_client().get_object(Bucket=s3_bucket, Key=s3_key)
                file_content = file_obj['Body'].read().decode('utf-8')
                
                extracted_metadata = {}
                
                # 1. Handle JSON Toolchain Exports
                if s3_key.endswith('.json'):
                    raw_data = json.loads(file_content)
                    for table in raw_data.get('tables', []):
                        extracted_metadata[table['name']] = {
                            "description": table.get('description', 'No description'),
                            "relationships": table.get('relations', []),
                            "domain": domain # 🟢 STRICT DOMAIN INJECTION
                        }
                        
                # 2. Handle .NET Entity Framework EDMX Exports
                elif s3_key.endswith('.edmx'):
                    # EDMX files use strict XML namespaces. 
                    # We use local-name() bypassing or explicit namespaces to reliably find nodes.
                    root = ET.fromstring(file_content)
                    
                    # Map of common EDMX namespaces to search through the Conceptual Model
                    namespaces = {
                        'edmx': 'http://schemas.microsoft.com/ado/2009/11/edmx',
                        'edm': 'http://schemas.microsoft.com/ado/2009/11/edm'
                    }
                    
                    # Find all EntityTypes in the Conceptual Model
                    for entity in root.findall('.//edm:EntityType', namespaces):
                        name = entity.get('Name')
                        
                        # Extract relationships (Navigation Properties)
                        relationships = [
                            nav.get('Name') for nav in entity.findall('.//edm:NavigationProperty', namespaces)
                        ]
                        
                        # Look for an explicit Documentation/Summary node if it exists
                        doc_node = entity.find('.//edm:Documentation/edm:Summary', namespaces)
                        description = doc_node.text if doc_node is not None else f"Entity Model: {name}"

                        extracted_metadata[name] = {
                            "description": description,
                            "relationships": relationships,
                            "domain": domain # 🟢 STRICT DOMAIN INJECTION
                        }
                else:
                    context.log.warning(f"Unsupported file type for {s3_key}")
                    return {}

                context.log.info(f"Extracted {len(extracted_metadata)} entities tagged with domain '{domain}'.")
                return extracted_metadata
                
            except Exception as e:
                context.log.error(f"Failed to process design file {s3_key}: {e}")
                raise e

        return Definitions(assets=[design_metadata_asset])
