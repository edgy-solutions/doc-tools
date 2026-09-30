"""Reprocess-safe artifact layout for the ingest writer (doc_tools/components/document_parser.py).

Before this change a reprocess overwrote `{base_dir}/generated/{base_name}/manifest.json`
(and text.json, and every image) in place — there was no way to tell two runs apart, and
no way to keep the old run's artifacts around after a new one landed. Now every generated
artifact lands under a `{version}` path segment (`DOC_TOOLS_VERSION`, used VERBATIM — see
the comment in document_parser.py and doc_tools/plugins/sustainment.py's `pipeline_version`
stamp, which this MUST spell identically), and only a small pointer file
(`current.json`) is ever overwritten, written LAST so a crashed run can never leave it
naming an incomplete version.

Extraction (`extract_text_and_metadata`, `rasterize_pdf_pages`) and the best-effort crop
geometry repair are faked/stubbed out — this suite is about WHERE bytes land, not the
extraction logic itself, which has its own tests elsewhere.
"""
import json
import os
from types import SimpleNamespace

import pytest
from dagster import build_asset_context
from dag_tools.components.s3_sensor.file_component import S3FileConfig

from doc_tools.components.document_parser import DocumentParserComponent

BUCKET = "test-bucket"
KEY = "sustainment/inbound/testnotice/Test_Notice.pdf"
BASE_DIR = "sustainment/inbound/testnotice"
BASE_NAME = "Test_Notice_pdf"
GENERATED_DIR = f"{BASE_DIR}/generated/{BASE_NAME}"


class _FakeS3Client:
    """In-memory S3 stand-in. Tracks every put/upload IN ORDER so tests can assert on
    write ordering (the current.json-after-manifest.json guarantee), and keeps bytes
    around under (Bucket, Key) so a second run can be checked against the first run's
    untouched objects."""

    def __init__(self):
        self.objects = {}       # (Bucket, Key) -> bytes
        self.write_order = []   # [(Bucket, Key), ...] in call order

    def download_file(self, Bucket, Key, Filename):
        data = self.objects.get((Bucket, Key))
        if data is None:
            raise FileNotFoundError(Key)
        with open(Filename, "wb") as fh:
            fh.write(data)

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None):
        with open(Filename, "rb") as fh:
            data = fh.read()
        self.objects[(Bucket, Key)] = data
        self.write_order.append((Bucket, Key))

    def put_object(self, Bucket, Key, Body, ContentType=None):
        data = Body if isinstance(Body, bytes) else Body.encode("utf-8")
        self.objects[(Bucket, Key)] = data
        self.write_order.append((Bucket, Key))

    def get_object(self, Bucket, Key):
        data = self.objects[(Bucket, Key)]
        return {"Body": SimpleNamespace(read=lambda: data)}


class _FakeS3Resource:
    def __init__(self, client):
        self._client = client

    def get_client(self):
        return self._client


def _fake_extract_text_and_metadata(file_path, extract_images=True, image_output_dir=None, pdf_image_dpi=200):
    """Writes one fake crop image into image_output_dir (so the images/ upload loop has
    something to upload) and returns one text element."""
    if image_output_dir:
        with open(os.path.join(image_output_dir, "crop1.png"), "wb") as fh:
            fh.write(b"fake-crop-bytes")
    return [{"type": "Text", "text": "hello world", "metadata": {"page_number": 1}}]


def _fake_rasterize_pdf_pages(file_path, pages_dir, dpi=150):
    p = os.path.join(pages_dir, "page_1.jpg")
    with open(p, "wb") as fh:
        fh.write(b"fake-page-bytes")
    return [{"page": 1, "path": p, "basename": "page_1.jpg", "width": 100, "height": 100, "dpi": dpi}]


@pytest.fixture(autouse=True)
def _stub_extraction(monkeypatch):
    monkeypatch.setattr(
        "doc_tools.components.document_parser.extract_text_and_metadata",
        _fake_extract_text_and_metadata,
    )
    monkeypatch.setattr(
        "doc_tools.components.document_parser.rasterize_pdf_pages",
        _fake_rasterize_pdf_pages,
    )
    # Best-effort crop geometry repair does a real PDF open on the fake (non-PDF) bytes
    # this test writes to disk; it's already wrapped in a broad except in the caller, but
    # stub it out so the test isn't exercising (or timing) that unrelated code path.
    monkeypatch.setattr(
        "doc_tools.utils.crop_geometry.repair_table_crops",
        lambda *a, **k: 0,
    )


def _asset():
    defs = DocumentParserComponent(
        name="process_document_artifact", partition_name="pdf_files"
    ).build_defs(None)
    return next(iter(defs.assets))


def _run(fake_client, version=None, monkeypatch=None):
    if version is not None:
        monkeypatch.setenv("DOC_TOOLS_VERSION", version)
    ctx = build_asset_context(partition_key=KEY)
    cfg = S3FileConfig(file_url=f"s3://{BUCKET}/{KEY}")
    resource = _FakeS3Resource(fake_client)
    asset_def = _asset()
    return asset_def(ctx, config=cfg, s3=resource)


def test_artifacts_land_under_version_segment_verbatim(monkeypatch):
    """The version segment must be the env var's value BYTE-IDENTICAL, `@` and all — no
    slugifying, no normalising."""
    client = _FakeS3Client()
    version = "doc-tools@abc123def"
    manifest = _run(client, version=version, monkeypatch=monkeypatch)

    assert manifest["text_location"] == f"{GENERATED_DIR}/{version}/text.json"

    written_keys = [k for (_b, k) in client.write_order]
    assert f"{GENERATED_DIR}/{version}/manifest.json" in written_keys
    assert f"{GENERATED_DIR}/{version}/text.json" in written_keys
    assert f"{GENERATED_DIR}/{version}/images/crop1.png" in written_keys
    assert f"{GENERATED_DIR}/{version}/images/page_1.jpg" in written_keys
    # current.json itself is NOT versioned — it's the one mutable pointer.
    assert f"{GENERATED_DIR}/current.json" in written_keys
    # And nothing landed at the bare, unversioned legacy path.
    assert f"{GENERATED_DIR}/manifest.json" not in written_keys
    assert f"{GENERATED_DIR}/text.json" not in written_keys


def test_default_version_matches_sustainment_pipeline_version_sentinel(monkeypatch):
    """Undeclared DOC_TOOLS_VERSION must fall back to the SAME sentinel string
    doc_tools/plugins/sustainment.py stamps into review.json — verbatim, because two
    spellings of "unstamped" is the exact seam this repo keeps getting bitten by."""
    monkeypatch.delenv("DOC_TOOLS_VERSION", raising=False)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "doc_tools", "plugins", "sustainment.py"), encoding="utf-8") as fh:
        sustainment_src = fh.read()
    assert 'os.getenv("DOC_TOOLS_VERSION", "doc-tools@unstamped")' in sustainment_src

    client = _FakeS3Client()
    manifest = _run(client)
    assert manifest["text_location"] == f"{GENERATED_DIR}/doc-tools@unstamped/text.json"


def test_current_json_written_after_manifest_and_names_that_version(monkeypatch):
    client = _FakeS3Client()
    version = "doc-tools@currenttest"
    _run(client, version=version, monkeypatch=monkeypatch)

    manifest_key = f"{GENERATED_DIR}/{version}/manifest.json"
    current_key = f"{GENERATED_DIR}/current.json"

    manifest_idx = client.write_order.index((BUCKET, manifest_key))
    current_idx = client.write_order.index((BUCKET, current_key))
    assert manifest_idx < current_idx, (
        "current.json must be written strictly after the versioned manifest.json put "
        "succeeds — otherwise a crash mid-run can leave the pointer naming a version "
        "whose manifest was never written"
    )

    pointer = json.loads(client.objects[(BUCKET, current_key)])
    assert pointer["pipeline_version"] == version
    assert pointer["manifest_key"] == manifest_key
    # updated_at must be a real, parseable ISO-8601 timestamp.
    from datetime import datetime
    datetime.fromisoformat(pointer["updated_at"])


def test_second_run_different_version_leaves_first_version_objects_intact(monkeypatch):
    """The whole point: a reprocess at a NEW pipeline version must not touch the prior
    run's objects. Same fake S3 store reused across both runs, exactly like a real
    bucket would be."""
    client = _FakeS3Client()
    v1 = "doc-tools@v1"
    v2 = "doc-tools@v2"

    _run(client, version=v1, monkeypatch=monkeypatch)
    v1_keys = {
        (BUCKET, f"{GENERATED_DIR}/{v1}/manifest.json"),
        (BUCKET, f"{GENERATED_DIR}/{v1}/text.json"),
        (BUCKET, f"{GENERATED_DIR}/{v1}/images/crop1.png"),
    }
    v1_snapshot = {k: client.objects[k] for k in v1_keys}
    assert all(v is not None for v in v1_snapshot.values())

    _run(client, version=v2, monkeypatch=monkeypatch)

    # v1's objects are untouched, byte-for-byte.
    for k, original_bytes in v1_snapshot.items():
        assert k in client.objects, f"{k} disappeared after the v2 reprocess"
        assert client.objects[k] == original_bytes, f"{k} was overwritten by the v2 reprocess"

    # v2 landed at its own, separate keys.
    assert (BUCKET, f"{GENERATED_DIR}/{v2}/manifest.json") in client.objects

    # The pointer now names v2 — it IS the one mutable file.
    pointer = json.loads(client.objects[(BUCKET, f"{GENERATED_DIR}/current.json")])
    assert pointer["pipeline_version"] == v2
