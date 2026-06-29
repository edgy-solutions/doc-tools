from dagster import DynamicPartitionsDefinition

pdf_files_partition = DynamicPartitionsDefinition(name="pdf_files")
ontology_partitions = DynamicPartitionsDefinition(name="ontology_files")
design_files_partition = DynamicPartitionsDefinition(name="design_files")
# Added 2026-06-29 for the IADS-bundle ingest path. iads_files holds
# each bundle's S3 key (slashes → __ per the sensor's partition-key
# scheme) so the `extract_iads_bundle` asset is partition-aware and
# the iads_sensor can register new bundles dynamically. xml_files
# holds each WP XML S3 key for the per-WP xml_graph_sync_job runs the
# xml_sensor triggers downstream of `extract_iads_bundle`.
iads_files_partition = DynamicPartitionsDefinition(name="iads_files")
xml_files_partition = DynamicPartitionsDefinition(name="xml_files")
