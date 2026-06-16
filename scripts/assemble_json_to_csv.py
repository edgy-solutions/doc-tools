#!/usr/bin/env python3
"""Download the JSON artifacts the document pipeline writes to MinIO/S3 and
flatten every one under a prefix into a single CSV.

The document pipeline (manufacturing and the other domains) writes, per file:
    {base_dir}/generated/{file_stem}/text.json      # list of unstructured elements
    {base_dir}/generated/{file_stem}/manifest.json  # one manifest dict

This script lists every ``*.json`` under ``--prefix``, parses each, and flattens
it into rows:
    * a JSON **list** (e.g. text.json) -> one row per element
    * a JSON **dict** (e.g. manifest.json) -> one row
Nested objects are flattened with dotted keys (``metadata.page_number``); nested
lists are JSON-encoded into the cell. Columns are the union across all rows, so
mixing schemas is fine (missing cells are blank). Each row carries
``_source_file`` and ``_index`` so you can trace it back.

Connection uses the same env vars as the pipeline:
    S3_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, MINIO_SECURE
Override the endpoint with --endpoint. MinIO is usually in-cluster, so run this
from a pod, or first: ``kubectl port-forward svc/minio 9000:9000`` and use
``--endpoint http://localhost:9000``.

Examples:
    # all elements for one document
    uv run python scripts/assemble_json_to_csv.py \\
        --prefix manufacturing/inbound/22/generated/ --name text.json --out steps.csv

    # every json under a whole domain prefix
    uv run python scripts/assemble_json_to_csv.py \\
        --bucket processing-artifacts --prefix manufacturing/ --out all.csv
"""
import argparse
import csv
import json
import os
import sys


def endpoint_url(raw: str | None, secure: bool) -> str | None:
    if not raw:
        return None
    if raw.startswith(("http://", "https://")):
        return raw
    return ("https://" if secure else "http://") + raw


def make_s3_client(endpoint: str | None, verify: bool):
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        sys.exit("boto3 is required. Run via `uv run python scripts/assemble_json_to_csv.py ...`")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        verify=verify,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def iter_json_keys(s3, bucket: str, prefix: str, name: str | None):
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.lower().endswith(".json"):
                continue
            if name and os.path.basename(key) != name:
                continue
            yield key


def flatten(obj, prefix: str = "") -> dict:
    """Flatten a dict into {dotted_key: scalar}; nested lists -> JSON string."""
    out = {}
    for k, v in obj.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        elif isinstance(v, list):
            out[key] = json.dumps(v, ensure_ascii=False)
        else:
            out[key] = v
    return out


def records_from_doc(doc, source_key: str):
    """A list -> one record per item; a dict/scalar -> one record."""
    items = doc if isinstance(doc, list) else [doc]
    for i, item in enumerate(items):
        row = {"_source_file": source_key, "_index": i}
        if isinstance(item, dict):
            row.update(flatten(item))
        else:
            row["value"] = json.dumps(item, ensure_ascii=False) if isinstance(item, list) else item
        yield row


def main(argv=None):
    ap = argparse.ArgumentParser(description="Assemble pipeline JSON artifacts from S3/MinIO into one CSV.")
    ap.add_argument("--bucket", default=os.getenv("PIPELINE_BUCKET", "processing-artifacts"))
    ap.add_argument("--prefix", required=True, help="S3 key prefix (the 'dir') to scan recursively")
    ap.add_argument("--name", default=None, help="Only files with this exact basename, e.g. text.json")
    ap.add_argument("--out", default="output.csv")
    ap.add_argument("--endpoint", default=os.getenv("S3_ENDPOINT_URL"))
    ap.add_argument("--secure", action="store_true",
                    default=os.getenv("MINIO_SECURE", "false").lower() == "true",
                    help="Use https for the endpoint")
    ap.add_argument("--verify", action="store_true", help="Verify TLS certs (default off, matching the pipeline)")
    args = ap.parse_args(argv)

    s3 = make_s3_client(endpoint_url(args.endpoint, args.secure), args.verify)

    rows, fieldnames, seen, n_files = [], ["_source_file", "_index"], {"_source_file", "_index"}, 0
    for key in iter_json_keys(s3, args.bucket, args.prefix, args.name):
        try:
            doc = json.loads(s3.get_object(Bucket=args.bucket, Key=key)["Body"].read())
        except Exception as e:  # noqa: BLE001 - keep going on a bad/partial object
            print(f"  skip {key}: {e}", file=sys.stderr)
            continue
        n_files += 1
        for row in records_from_doc(doc, key):
            for k in row:
                if k not in seen:
                    seen.add(k)
                    fieldnames.append(k)
            rows.append(row)

    if not rows:
        where = f"s3://{args.bucket}/{args.prefix}" + (f" (name={args.name})" if args.name else "")
        sys.exit(f"No JSON rows found under {where}")

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} rows from {n_files} JSON file(s) -> {args.out} ({len(fieldnames)} columns)")


if __name__ == "__main__":
    main()
