"""DOORS spreadsheet-export ingest route.

Reads one flat-CSV DOORS export from S3, parses it, and runs the passes the
``doors-export`` content-kind row declares. It writes to NO store: the result is
a plain dict for downstream assets, and the pass outcomes are surfaced as
Dagster output metadata.

``DoorsParseError`` is deliberately not caught. The parser's refusals are
deliberate and none of them degrade quietly; swallowing one would make a
malformed export look like a successful ingest.
"""
import os
from urllib.parse import urlparse

from dagster import asset, Config, MetadataValue
from dagster_aws.s3 import S3Resource

from doc_tools.parsers.doors_export import parse_doors_export
from doc_tools.partitions import doors_files_partition
from doc_tools.passes.dispatch import PassContext, run_passes_for_kind


class DoorsIngestConfig(Config):
    """Same two shapes as ``XmlIngestConfig``: ``{s3_bucket, s3_key}`` for a
    manual launch, or ``{file_url: "s3://bucket/key"}`` as the
    S3SensorComponent passes it. Empty string means unset."""

    s3_bucket: str = ""
    s3_key: str = ""
    file_url: str = ""


def _jsonable_pass_value(value):
    """Flatten a pass value to plain data.

    A pass may return a dataclass -- ``identity_from_doors_text`` returns a
    ``DocumentIdentity``. This asset's return value crosses an IO manager and is
    also attached as Dagster metadata, so it must be plain data. ``as_dict()`` is
    the pass's own serializer; anything without one is assumed plain already.
    """
    as_dict = getattr(value, "as_dict", None)
    return as_dict() if callable(as_dict) else value


def resolve_doors_config(config: DoorsIngestConfig) -> tuple[str, str]:
    """Normalize the two-shape config to (bucket, key)."""
    if config.s3_bucket and config.s3_key:
        return config.s3_bucket, config.s3_key
    if config.file_url:
        parsed = urlparse(config.file_url)
        if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
            raise ValueError(
                f"file_url must be an s3:// URI with bucket+key; "
                f"got {config.file_url!r}"
            )
        return parsed.netloc, parsed.path.lstrip("/")
    raise ValueError(
        "DoorsIngestConfig requires either (s3_bucket+s3_key) or file_url. "
        "Got neither."
    )


@asset(partitions_def=doors_files_partition)
def ingest_doors_export(context, config: DoorsIngestConfig, s3: S3Resource) -> dict:
    """Parse a DOORS CSV export and run its declared passes. No store writes."""
    s3_client = s3.get_client()
    bucket, key = resolve_doors_config(config)
    context.log.info(f"Fetching DOORS export from s3://{bucket}/{key} into memory...")

    response = None
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        text = response["Body"].read().decode("utf-8")
    except Exception as e:
        context.log.error(f"Failed to fetch file from S3: {e}")
        raise
    finally:
        if response:
            try:
                response["Body"].close()
            except Exception:
                pass

    doc_id = os.path.splitext(os.path.basename(key))[0]

    # DoorsParseError propagates on purpose.
    export = parse_doors_export(text)

    results = run_passes_for_kind(
        "doors-export", PassContext(text=text, doc_id=doc_id)
    )
    passes = [
        {
            "name": r.name,
            "status": r.status,
            "value": _jsonable_pass_value(r.value),
            "error": r.error,
        }
        for r in results
    ]
    for r in results:
        context.log.info(f"pass {r.name}: status={r.status} error={r.error!r}")
        if r.status != "ok":
            context.log.warning(
                f"pass {r.name} did not complete ok: status={r.status} error={r.error!r}"
            )

    object_count = len(export.objects)
    tables = export.artifacts()
    context.add_output_metadata(
        {
            "doc_id": MetadataValue.text(doc_id),
            "source": MetadataValue.text(f"s3://{bucket}/{key}"),
            "object_count": MetadataValue.int(object_count),
            "tier1_table_count": MetadataValue.int(len(tables)),
            "passes": MetadataValue.json(passes),
        }
    )

    return {
        "doc_id": doc_id,
        "source_object_key": key,
        "object_count": object_count,
        "tables": tables,
        "passes": passes,
    }
