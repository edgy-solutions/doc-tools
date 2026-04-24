import time
from typing import List, Dict, Any
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    SchemaMetadataClass,
    SchemaFieldClass,
    SchemaFieldDataTypeClass,
    NumberTypeClass,
    StringTypeClass,
    BooleanTypeClass,
    BytesTypeClass,
    ArrayTypeClass,
    RecordTypeClass,
    UpstreamLineageClass,
    UpstreamClass,
    DatasetLineageTypeClass,
    AuditStampClass
)

class DDSToDataHubEmitter:
    def __init__(self, emitter: DatahubRestEmitter):
        self.emitter = emitter

    def _get_datahub_type_class(self, type_str: str):
        if type_str == "NumberTypeClass":
            return SchemaFieldDataTypeClass(type=NumberTypeClass())
        elif type_str == "BooleanTypeClass":
            return SchemaFieldDataTypeClass(type=BooleanTypeClass())
        elif type_str == "BytesTypeClass":
            return SchemaFieldDataTypeClass(type=BytesTypeClass())
        elif type_str == "ArrayTypeClass":
            return SchemaFieldDataTypeClass(type=ArrayTypeClass())
        elif type_str == "RecordTypeClass":
            return SchemaFieldDataTypeClass(type=RecordTypeClass())
        else:
            return SchemaFieldDataTypeClass(type=StringTypeClass())

    def emit_dds_schema(self, topic_name: str, parsed_fields: List[Dict[str, Any]]):
        dataset_urn = f"urn:li:dataset:(urn:li:dataPlatform:dds,{topic_name},PROD)"
        
        schema_fields = []
        for field in parsed_fields:
            schema_fields.append(
                SchemaFieldClass(
                    fieldPath=field["name"],
                    type=self._get_datahub_type_class(field["datahub_type"]),
                    nativeDataType=field["idl_type"],
                    description=field["description"] if field["description"] else None
                )
            )
            
        schema_metadata = SchemaMetadataClass(
            schemaName=topic_name,
            platform="urn:li:dataPlatform:dds",
            version=0,
            hash="",
            platformSchema={"string": ""}, # required dummy
            fields=schema_fields
        )
        
        mcp = MetadataChangeProposalWrapper(
            entityType="dataset",
            changeType="UPSERT",
            entityUrn=dataset_urn,
            aspectName="schemaMetadata",
            aspect=schema_metadata
        )
        
        self.emitter.emit(mcp)
        
    def emit_kafka_lineage(self, dds_topic_name: str, kafka_topic_name: str):
        upstream_urn = f"urn:li:dataset:(urn:li:dataPlatform:dds,{dds_topic_name},PROD)"
        downstream_urn = f"urn:li:dataset:(urn:li:dataPlatform:kafka,{kafka_topic_name},PROD)"
        
        audit_stamp = AuditStampClass(
            time=int(time.time() * 1000),
            actor="urn:li:corpuser:datahub"
        )
        
        upstream = UpstreamClass(
            dataset=upstream_urn,
            type=DatasetLineageTypeClass.TRANSFORMED,
            auditStamp=audit_stamp
        )
        
        lineage = UpstreamLineageClass(
            upstreams=[upstream]
        )
        
        mcp = MetadataChangeProposalWrapper(
            entityType="dataset",
            changeType="UPSERT",
            entityUrn=downstream_urn,
            aspectName="upstreamLineage",
            aspect=lineage
        )
        
        self.emitter.emit(mcp)

    def emit_rabbitmq_schema(self, topic_name: str, parsed_fields: List[Dict[str, Any]]):
        dataset_urn = f"urn:li:dataset:(urn:li:dataPlatform:rabbitmq,{topic_name},PROD)"
        
        schema_fields = []
        for field in parsed_fields:
            schema_fields.append(
                SchemaFieldClass(
                    fieldPath=field["name"],
                    type=self._get_datahub_type_class(field["datahub_type"]),
                    nativeDataType=field["json_type"],
                    description=field["description"] if field["description"] else None
                )
            )
            
        schema_metadata = SchemaMetadataClass(
            schemaName=topic_name,
            platform="urn:li:dataPlatform:rabbitmq",
            version=0,
            hash="",
            platformSchema={"string": ""}, # required dummy
            fields=schema_fields
        )
        
        mcp = MetadataChangeProposalWrapper(
            entityType="dataset",
            changeType="UPSERT",
            entityUrn=dataset_urn,
            aspectName="schemaMetadata",
            aspect=schema_metadata
        )
        
        self.emitter.emit(mcp)

    def emit_rabbitmq_lineage(self, kafka_topic_name: str, rabbitmq_topic_name: str):
        upstream_urn = f"urn:li:dataset:(urn:li:dataPlatform:kafka,{kafka_topic_name},PROD)"
        downstream_urn = f"urn:li:dataset:(urn:li:dataPlatform:rabbitmq,{rabbitmq_topic_name},PROD)"
        
        audit_stamp = AuditStampClass(
            time=int(time.time() * 1000),
            actor="urn:li:corpuser:datahub"
        )
        
        upstream = UpstreamClass(
            dataset=upstream_urn,
            type=DatasetLineageTypeClass.TRANSFORMED,
            auditStamp=audit_stamp
        )
        
        lineage = UpstreamLineageClass(
            upstreams=[upstream]
        )
        
        mcp = MetadataChangeProposalWrapper(
            entityType="dataset",
            changeType="UPSERT",
            entityUrn=downstream_urn,
            aspectName="upstreamLineage",
            aspect=lineage
        )
        
        self.emitter.emit(mcp)
