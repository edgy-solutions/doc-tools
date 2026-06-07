"""Tests for DDSToDataHubEmitter (doc_tools/ingestion/datahub_emitter).

Builds DataHub MCPs for DDS/RabbitMQ schemas and Kafka lineage. The DataHub
REST emitter is mocked; the MCP/aspect construction is real (so this also
guards against datahub schema-class signature drift).
"""
from unittest.mock import MagicMock

from datahub.metadata.schema_classes import (
    NumberTypeClass, StringTypeClass, BooleanTypeClass,
)

from doc_tools.ingestion.datahub_emitter import DDSToDataHubEmitter


def test_type_class_mapping():
    e = DDSToDataHubEmitter(MagicMock())
    assert isinstance(e._get_datahub_type_class("NumberTypeClass").type, NumberTypeClass)
    assert isinstance(e._get_datahub_type_class("BooleanTypeClass").type, BooleanTypeClass)
    # unknown -> StringTypeClass fallback
    assert isinstance(e._get_datahub_type_class("???").type, StringTypeClass)


def test_emit_dds_schema_emits_three_aspects():
    emitter = MagicMock()
    fields = [{"name": "rpm", "datahub_type": "NumberTypeClass", "idl_type": "long", "description": "Rotor RPM"}]
    DDSToDataHubEmitter(emitter).emit_dds_schema("openddil.sensor.rotor", fields)
    # schemaMetadata + datasetProperties + browsePathsV2
    assert emitter.emit.call_count == 3


def test_emit_kafka_lineage_emits_one_upstream():
    emitter = MagicMock()
    DDSToDataHubEmitter(emitter).emit_kafka_lineage("dds.topic", "kafka.topic")
    assert emitter.emit.call_count == 1


def test_emit_rabbitmq_schema_and_lineage():
    emitter = MagicMock()
    e = DDSToDataHubEmitter(emitter)
    fields = [{"name": "rpm", "datahub_type": "NumberTypeClass", "json_type": "number", "description": ""}]
    e.emit_rabbitmq_schema("rabbit.rotor", fields)
    assert emitter.emit.call_count == 3
    emitter.reset_mock()
    e.emit_rabbitmq_lineage("kafka.topic", "rabbit.topic")
    assert emitter.emit.call_count == 1
