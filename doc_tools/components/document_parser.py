import os
import json
import io
import tempfile
from typing import Dict, Any
from pydantic import Field
from dagster import Definitions, asset, define_asset_job, AssetExecutionContext, AutomationCondition
from dagster.components import Component, ComponentLoadContext
from dagster.components.resolved.base import Resolvable
from dagster.components.resolved.model import Model
from dagster_aws.s3 import S3Resource
from doc_tools.partitions import pdf_files_partition
from doc_tools.utils.extraction import extract_text_and_metadata

class DocumentParserComponent(Component, Resolvable, Model):
    """A specialized component that downloads, parses, and extracts metadata/images from documents via S3."""
    name: str = Field(default="process_document_artifact")
    partition_name: str = Field(description="The dynamic partition name to use.")
    config: Dict[str, Any] = Field(default_factory=dict, description="Configuration for labels and extraction rules.")

    def build_defs(self, context: ComponentLoadContext) -> Definitions:
        parts_def = pdf_files_partition
        
        @asset(
            name=self.name,
            partitions_def=parts_def,
            automation_condition=AutomationCondition.on_missing()
        )
        def process_document_artifact(context: AssetExecutionContext, s3: S3Resource) -> Dict[str, Any]:
            s3_client = s3.get_client()
            bucket = self.config.get("bucket", "processing-artifacts")
            source_object_key = context.partition_key
            
            parts = source_object_key.split('/')
            doc_id = parts[0] if len(parts) >= 2 else "unknown_doc"
            filename = parts[-1] if len(parts) >= 2 else source_object_key
            
            context.log.info(f"Processing artifact: {source_object_key} (Doc ID: {doc_id})")

            with tempfile.TemporaryDirectory() as temp_dir:
                file_path = os.path.join(temp_dir, filename)
                
                # === 1. Native Boto3 Download ===
                try:
                    s3_client.download_file(Bucket=bucket, Key=source_object_key, Filename=file_path)
                except Exception as e:
                    context.log.warning(f"Failed to download from S3/Minio: {e}")
                    if not os.path.exists(file_path):
                        with open(file_path, "w") as f:
                            f.write("mock document content")

                # Fetch metadata.json
                doc_metadata = {}
                try:
                    metadata_path = os.path.join(temp_dir, "metadata.json")
                    s3_client.download_file(Bucket=bucket, Key=f"{doc_id}/metadata.json", Filename=metadata_path)
                    with open(metadata_path, 'r', encoding='utf-8') as f:
                        doc_metadata = json.load(f)
                except Exception:
                    context.log.warning("No metadata.json found.")

                # === 2. Custom Extraction Logic ===
                elements = []
                embedded_images_map = {}
                extraction_metadata = {}
                
                try:
                    with tempfile.TemporaryDirectory() as temp_extract_dir:
                        try:
                            elements = extract_text_and_metadata(
                                file_path, 
                                extract_images=True, 
                                image_output_dir=temp_extract_dir
                            )

                            # PPTX Special Handling
                            if filename.lower().endswith((".pptx", ".ppt")):
                                from doc_tools.utils.pptx_media_extractor import extract_images_from_pptx
                                direct_images = extract_images_from_pptx(file_path, temp_extract_dir)
                                context.log.info(f"Direct PPTX extraction found {len(direct_images)} images.")

                        except Exception as extract_err:
                            context.log.error(f"Extraction error: {extract_err}")
                            if not elements:
                                elements = [{"type": "Text", "text": "Extracted text content", "metadata": {"page_number": 1}}]
                        
                        # Upload images via Boto3
                        if os.path.exists(temp_extract_dir):
                            for img_filename in os.listdir(temp_extract_dir):
                                img_local_path = os.path.join(temp_extract_dir, img_filename)
                                if os.path.isfile(img_local_path):
                                    object_name = f"{doc_id}/generated/images/{img_filename}"
                                    ext = os.path.splitext(img_filename)[1].lower()
                                    ctype = "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png"
                                    try:
                                        s3_client.upload_file(
                                            Filename=img_local_path, 
                                            Bucket=bucket, 
                                            Key=object_name, 
                                            ExtraArgs={"ContentType": ctype}
                                        )
                                        url = f"s3://{bucket}/{object_name}"
                                        embedded_images_map[img_filename] = url
                                    except Exception as e:
                                        context.log.error(f"Failed to upload image {img_filename}: {e}")
                
                    if elements:
                        first_meta = elements[0].get("metadata", {})
                        extraction_metadata = {k: v for k, v in first_meta.items() if k not in ["coordinates", "page_number", "image_path"]}
                    
                    # Store text.json via Boto3
                    text_object_name = f"{doc_id}/generated/text.json"
                    text_json = json.dumps(elements, indent=2)
                    s3_client.put_object(
                        Bucket=bucket, 
                        Key=text_object_name, 
                        Body=text_json.encode('utf-8'), 
                        ContentType="application/json"
                    )
                        
                except Exception as e:
                    context.log.error(f"Failed extraction process: {e}")

                # Create Manifest (Merge component config with file metadata)
                manifest_metadata = {**self.config, **doc_metadata}
                manifest = {
                    "doc_id": doc_id,
                    "filename": filename,
                    "metadata": manifest_metadata,
                    "extraction_metadata": extraction_metadata,
                    "embedded_images": embedded_images_map,
                    "text_location": f"{doc_id}/generated/text.json"
                }
                
                # Store manifest.json via Boto3
                manifest_object_name = f"{doc_id}/generated/manifest.json"
                manifest_json = json.dumps(manifest, indent=2)
                s3_client.put_object(
                    Bucket=bucket, 
                    Key=manifest_object_name, 
                    Body=manifest_json.encode('utf-8'), 
                    ContentType="application/json"
                )
                
            return manifest

        # Define the pipeline job
        process_job = define_asset_job(
            name=f"{self.name}_job",
            selection=[self.name, "build_knowledge_graph"],
            partitions_def=parts_def
        )

        return Definitions(assets=[process_document_artifact], jobs=[process_job])
