from dagster import DynamicPartitionsDefinition

pdf_files_partition = DynamicPartitionsDefinition(name="pdf_files")
ontology_partitions = DynamicPartitionsDefinition(name="ontology_files")
