from dagster import DynamicPartitionsDefinition

pdf_files_partition = DynamicPartitionsDefinition(name="pdf_files")
# ADR-0041 ingress-user sensor — a SEPARATE partition set from pdf_files_partition,
# not stylistic. Both parser assets carry AutomationCondition.on_missing(); if a
# user-dropped document's partition were registered in the SAME set the vetted
# parser watches, the vetted parser would see it as "missing" and materialize it
# with NO provenance stamp — silently laundering a user drop into vetted-looking
# content. See doc_tools/components/document_parser.py and definitions.py
# (user_document_parser / ingress_user_sensor).
user_pdf_files_partition = DynamicPartitionsDefinition(name="user_pdf_files")
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
# DOORS flat-CSV exports; a separate set so the doors route never shares a
# partition key space with the XML or PDF routes.
doors_files_partition = DynamicPartitionsDefinition(name="doors_files")
