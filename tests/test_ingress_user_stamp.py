"""ADR-0041 ingress-user sensor: the user-drop provenance stamp.

Covers the five deliverables end to end at the unit level:
  1. doc_tools/utils/ingest_provenance.py's build_ingest_provenance()
  2. DocumentParserComponent's path_prefix_strip / obtained_via stamp fields
  3. (wiring only — partitions.py / definitions.py; no runtime behavior to
     unit-test beyond what (2) already covers)
  4. The ProvenanceNotPersistableError enforcement point in
     doc_tools/assets/semantic_assets.py's build_knowledge_graph
  5. SustainmentPlugin.to_graph_queries() persisting the block onto
     SustainmentNotice (Neo4j properties + PROV-term RDF in the
     ..._INSTANCES graph)

Some tests need the real iagent_mesh.provenance module (SDK v0.9.5+), which
the SHARED repo .venv does not have (it's pinned to an older SDK — see
tests/test_mesh_sdk_pin.py). Those tests call `pytest.importorskip` first so
they skip (not fail) under the shared venv and only run for real against the
pinned wheel. The path-derivation, no-provenance-no-op, and enforcement-point
tests need no SDK at all and run in both environments.

PART 2 (below) covers spec-ingress-user-live-routes.md's F1-F6: gating the
sensor on Lane 1's live `POST /ingest` key shape, reading Lane 1's own
sidecar instead of deriving a semantic label from a file FORMAT or a HASH,
carrying `ingest_id` as the join key, and the stage-status seam
(`IngestStatusResource`). Any test that exercises the sidecar-enabled
parser path transitively imports `iagent_mesh.ingest` (via
`IngestStatusResource.update`'s "extracting"/"awaiting_disposition" calls),
so those are ALSO gated with `pytest.importorskip("iagent_mesh.ingest")`,
matching this file's existing SDK-gating style.
"""
import json
import os
import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from dagster import build_asset_context
from dag_tools.components.s3_sensor.file_component import S3FileConfig

from doc_tools.components.document_parser import DocumentParserComponent
from doc_tools.config import IngestionConfig

BUCKET = "test-bucket"


# --------------------------------------------------------------------------- #
# Fakes for driving DocumentParserComponent's asset end to end (same shape as
# tests/test_document_parser_versioning.py's fakes — kept local/self-contained
# rather than imported cross-file).
# --------------------------------------------------------------------------- #
class _FakeS3Client:
    def __init__(self):
        self.objects = {}

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

    def put_object(self, Bucket, Key, Body, ContentType=None):
        data = Body if isinstance(Body, bytes) else Body.encode("utf-8")
        self.objects[(Bucket, Key)] = data

    def get_object(self, Bucket, Key):
        data = self.objects[(Bucket, Key)]
        return {"Body": SimpleNamespace(read=lambda: data)}


class _FakeS3Resource:
    def __init__(self, client):
        self._client = client

    def get_client(self):
        return self._client


def _fake_extract_text_and_metadata(file_path, extract_images=True, image_output_dir=None, pdf_image_dpi=200):
    return [{"type": "Text", "text": "hello world", "metadata": {"page_number": 1}}]


def _fake_rasterize_pdf_pages(file_path, pages_dir, dpi=150):
    return []


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
    monkeypatch.setattr(
        "doc_tools.utils.crop_geometry.repair_table_crops",
        lambda *a, **k: 0,
    )


def _run_parser(component_kwargs, key, fake_client=None):
    fake_client = fake_client or _FakeS3Client()
    defs = DocumentParserComponent(**component_kwargs).build_defs(None)
    asset_def = next(iter(defs.assets))
    ctx = build_asset_context(partition_key=key)
    cfg = S3FileConfig(file_url=f"s3://{BUCKET}/{key}")
    resource = _FakeS3Resource(fake_client)
    return asset_def(ctx, config=cfg, s3=resource)


# --------------------------------------------------------------------------- #
# 1. build_ingest_provenance: as_of=None -> AS_OF_UNKNOWN ("unknown")
# --------------------------------------------------------------------------- #
def test_build_ingest_provenance_as_of_none_becomes_unknown():
    pytest.importorskip("iagent_mesh.provenance")
    from doc_tools.utils.ingest_provenance import build_ingest_provenance

    block = build_ingest_provenance(
        obtained_via="user-drop",
        authoritative_source="user-upload",
        ingest_run="run-1",
        standing="unverified",
        as_of=None,
    )
    assert block["as_of"] == "unknown"
    assert block["obtained_via"] == "user-drop"
    # ingested_at is generated internally (not a caller-supplied field) and
    # must be present and non-empty — the SDK requires it.
    assert block["ingested_at"]


# --------------------------------------------------------------------------- #
# 2. obtained_via="user-drop" round-trips; an unknown rung raises
# --------------------------------------------------------------------------- #
def test_build_ingest_provenance_user_drop_round_trips_and_unknown_rung_raises():
    pytest.importorskip("iagent_mesh.provenance")
    from doc_tools.utils.ingest_provenance import build_ingest_provenance

    block = build_ingest_provenance(
        obtained_via="user-drop",
        authoritative_source="user-upload",
        ingest_run="run-2",
        standing="unverified",
        ingest_id="deadbeef",
        as_of="2026-09-30",
    )
    assert block["obtained_via"] == "user-drop"
    assert block["ingest_id"] == "deadbeef"
    assert block["as_of"] == "2026-09-30"

    with pytest.raises(Exception):
        build_ingest_provenance(
            obtained_via="user_drop",  # underscore, not the real hyphenated rung
            authoritative_source="user-upload",
            ingest_run="run-3",
            standing="unverified",
        )


# --------------------------------------------------------------------------- #
# 3. path_prefix_strip strips for domain/content_kind derivation ONLY —
#    source_key keeps the full, un-stripped S3 key.
# --------------------------------------------------------------------------- #
def test_path_prefix_strip_derives_domain_and_content_kind_but_keeps_full_source_key():
    pytest.importorskip("iagent_mesh.provenance")
    key = "ingress-user/sustainment/pcn/TYC/x.pdf"
    manifest = _run_parser(
        dict(
            name="process_user_document_artifact",
            partition_name="user_pdf_files",
            obtained_via="user-drop",
            path_prefix_strip="ingress-user/",
        ),
        key,
    )
    assert manifest["metadata"]["domain_type"] == "sustainment"
    assert manifest["metadata"]["content_kind"] == "pcn"
    # The REAL S3 key, ingress-user/ prefix and all — never rewritten.
    assert manifest["source_key"] == key
    # And the stamp itself is present (obtained_via was configured).
    assert manifest["provenance"]["obtained_via"] == "user-drop"


# --------------------------------------------------------------------------- #
# 4. obtained_via=None -> manifest carries no "provenance" key at all
#    (every existing/vetted DocumentParserComponent instance's no-op proof).
# --------------------------------------------------------------------------- #
def test_obtained_via_none_is_a_no_op_no_provenance_key():
    key = "sustainment/inbound/testnotice/Test_Notice.pdf"
    manifest = _run_parser(
        dict(name="process_document_artifact", partition_name="pdf_files"),
        key,
    )
    assert "provenance" not in manifest


# --------------------------------------------------------------------------- #
# 5. A flat drop (no subdirectory under the transport prefix) must NOT turn
#    the transport location itself into a semantic domain label.
# --------------------------------------------------------------------------- #
def test_flat_drop_does_not_become_domain_ingress_user():
    key = "ingress-user/foo.pdf"
    manifest = _run_parser(
        dict(
            name="process_user_document_artifact",
            partition_name="user_pdf_files",
            path_prefix_strip="ingress-user/",
            # obtained_via left None here: this test is about domain
            # derivation, not the stamp itself (covered by tests 1-3).
        ),
        key,
    )
    assert manifest["metadata"]["domain_type"] != "ingress-user"
    assert manifest["metadata"]["domain_type"] == "unknown"


# --------------------------------------------------------------------------- #
# 6. Enforcement point: a manifest carrying "provenance" halts unless the
#    resolved domain is in DOMAINS_THAT_PERSIST_PROVENANCE.
#
# build_knowledge_graph's orchestration past this point is heavy (S3/Neo4j/
# Weaviate/LLM/Jena I/O) and is intentionally left to integration tests
# (see tests/test_semantic_assets.py's module docstring). The enforcement
# check runs at the very top of the function, before any of that I/O, so
# both cases here are exercised via DIRECT INVOCATION of the asset function
# with mocked resources: the halting case never reaches the resources at
# all, and the pass-through case proves it got PAST the check by making the
# very next resource call (s3.get_client()) raise a distinct sentinel
# exception — if ProvenanceNotPersistableError had fired instead, the
# sentinel would never be reached.
# --------------------------------------------------------------------------- #
def _manifest_with_provenance(domain_type):
    return {
        "doc_id": "doc-1",
        "text_location": "x/text.json",
        "metadata": {"domain_type": domain_type},
        "provenance": {
            "obtained_via": "user-drop",
            "authoritative_source": "user-upload",
            "as_of": "unknown",
            "ingested_at": "2026-09-30T00:00:00+00:00",
            "ingest_run": "run-1",
            "standing": "unverified",
        },
    }


def _bkg_config():
    # build_knowledge_graph's `config` parameter is a Dagster Config object
    # (doc_tools.config.IngestionConfig), not a plain namespace — direct
    # invocation runs it through Dagster's config system, which requires a
    # real Config instance (or dict) here.
    return IngestionConfig(
        graph_node_label="WorkInstruction",
        graph_child_label="Page",
        vector_collection_name="DocumentChunk",
        bucket=BUCKET,
    )


def test_enforcement_halts_for_a_domain_not_in_the_persists_set():
    from doc_tools.assets.semantic_assets import (
        build_knowledge_graph, ProvenanceNotPersistableError, DOMAINS_THAT_PERSIST_PROVENANCE,
    )
    assert "MANUFACTURING" not in DOMAINS_THAT_PERSIST_PROVENANCE

    with pytest.raises(ProvenanceNotPersistableError):
        build_knowledge_graph(
            build_asset_context(),
            _bkg_config(),
            _manifest_with_provenance("manufacturing"),
            s3=MagicMock(), neo4j=MagicMock(), weaviate=MagicMock(),
            llm=MagicMock(), jena=MagicMock(),
        )


def test_enforcement_passes_through_for_sustainment():
    from doc_tools.assets.semantic_assets import (
        build_knowledge_graph, DOMAINS_THAT_PERSIST_PROVENANCE,
    )
    assert "SUSTAINMENT" in DOMAINS_THAT_PERSIST_PROVENANCE

    s3 = MagicMock()
    s3.get_client.side_effect = RuntimeError("SENTINEL_PAST_ENFORCEMENT")
    with pytest.raises(RuntimeError, match="SENTINEL_PAST_ENFORCEMENT"):
        build_knowledge_graph(
            build_asset_context(),
            _bkg_config(),
            _manifest_with_provenance("sustainment"),
            s3=s3, neo4j=MagicMock(), weaviate=MagicMock(),
            llm=MagicMock(), jena=MagicMock(),
        )


# --------------------------------------------------------------------------- #
# 7. SustainmentPlugin.to_graph_queries persists the block onto
#    SustainmentNotice: Neo4j properties, and PROV-term RDF triples landing
#    in the domain's INSTANCE graph — never the default graph (invisible to
#    the mesh) and never the vocabulary graph (DROP-first on every prime).
# --------------------------------------------------------------------------- #
def test_sustainment_rdf_persists_provenance_into_instances_graph_only():
    pytest.importorskip("iagent_mesh.provenance")
    from iagent_mesh.provenance import PROV_GENERATED_AT
    from doc_tools.plugins.sustainment import (
        SustainmentPlugin, SustainmentAugmentation, SustainmentNotice,
    )
    from doc_tools.plugins.models import BaseSection, DocumentNode

    sec = BaseSection(title="Notice", level=0, page_start=0, content="", node_id="doc-3")
    notice = SustainmentNotice(
        doc_id="PDN-900", doc_type="PDN", pub_date="2026-05-01", mfr="Acme",
        categories=[], summary="x", impacted_parts=[],
    )
    node = DocumentNode(base_extraction=sec, domain_augmentation=SustainmentAugmentation(notice=notice))
    config = SimpleNamespace(graph_node_label="Document", graph_child_label="Section")
    provenance = {
        "obtained_via": "user-drop",
        "authoritative_source": "user-upload",
        "as_of": "unknown",
        "ingested_at": "2026-09-30T12:00:00+00:00",
        "ingest_run": "run-7",
        "standing": "unverified",
    }

    cypher, sparql = SustainmentPlugin(domain_type="sustainment").to_graph_queries(
        [node], config, provenance=provenance,
    )
    sp = " ".join(sparql)

    # Lands in the INSTANCE graph for this domain...
    assert "GRAPH <http://internal/SUSTAINMENT_INSTANCES>" in sp
    assert f"<{PROV_GENERATED_AT}>" in sp
    assert "2026-09-30T12:00:00+00:00" in sp
    # ...and NOT the vocabulary graph (same prefix, no _INSTANCES suffix —
    # a bare substring check on "SUSTAINMENT>" would also match inside
    # "SUSTAINMENT_INSTANCES>", so this asserts the closing bracket directly
    # follows the bare domain name, which only the vocabulary graph IRI does).
    assert "SUSTAINMENT>" not in sp

    # Neo4j side also carries the stamp, keyed on the SAME SustainmentNotice
    # node the rest of this method already MERGEs (never a new node type).
    blob = "\n".join(q["query"] for q in cypher)
    assert "SustainmentNotice" in blob
    assert "provenance_obtained_via" in blob
    prov_query = [q for q in cypher if "provenance_obtained_via" in q["query"]][0]
    assert prov_query["params"]["notice_id"] == "PDN-900"
    assert prov_query["params"]["obtained_via"] == "user-drop"


def test_sustainment_rdf_omits_provenance_entirely_when_absent():
    """No `provenance` kwarg (every pre-ADR-0041 call site) must emit exactly
    what the method emitted before this parameter existed — no SDK import,
    no PROV triples, no provenance_* Neo4j properties."""
    from doc_tools.plugins.sustainment import (
        SustainmentPlugin, SustainmentAugmentation, SustainmentNotice,
    )
    from doc_tools.plugins.models import BaseSection, DocumentNode

    sec = BaseSection(title="Notice", level=0, page_start=0, content="", node_id="doc-4")
    notice = SustainmentNotice(
        doc_id="PDN-901", doc_type="PDN", pub_date="2026-05-01", mfr="Acme",
        categories=[], summary="x", impacted_parts=[],
    )
    node = DocumentNode(base_extraction=sec, domain_augmentation=SustainmentAugmentation(notice=notice))
    config = SimpleNamespace(graph_node_label="Document", graph_child_label="Section")

    cypher, sparql = SustainmentPlugin(domain_type="sustainment").to_graph_queries([node], config)
    blob = "\n".join(q["query"] for q in cypher)
    sp = " ".join(sparql)
    assert "provenance_obtained_via" not in blob
    assert "generatedAtTime" not in sp
    assert "wasDerivedFrom" not in sp


# =========================================================================== #
# PART 2 — Lane 1's LIVE routes (spec-ingress-user-live-routes.md, F1-F6).
#
# Lane 1's `POST /ingest` (invincible-agent/src/iagent/gateway.py:8277)
# writes, into bucket `processing-artifacts`:
#   ingress-user/{kind}/{sha256}/{filename}      <- the document
#   ingress-user/{kind}/{sha256}/manifest.json   <- the sidecar
# where `kind` is a FILE FORMAT ("pdf"/"cad"; ingest_status.KINDS), not a
# semantic domain, and `sha256` is 64 lowercase hex. The four defects this
# closes (D1-D4) and the live key shapes below are measured against the
# sandbox, not re-derived here.
# =========================================================================== #

_LIVE_DOC_KEY_1 = "ingress-user/pdf/736499f2eebb7dece392ad285e1a5b03e49e50a88a069cb0cc820b91dc4149d9/roll11-capture.pdf"
_LIVE_SIDECAR_KEY_1 = "ingress-user/pdf/736499f2eebb7dece392ad285e1a5b03e49e50a88a069cb0cc820b91dc4149d9/manifest.json"
_LIVE_DOC_KEY_2 = "ingress-user/pdf/fa231498f527921fc547cb97009a7d98fb45927bdaf7237028ea1cb60305e9bb/PCN23-002.pdf"
_LIVE_SIDECAR_KEY_2 = "ingress-user/pdf/fa231498f527921fc547cb97009a7d98fb45927bdaf7237028ea1cb60305e9bb/manifest.json"


# --------------------------------------------------------------------------- #
# F1 — the sensor's s3_filter regex is the GATE (D1/D2): matches the two
# live document keys, rejects the two live sidecar keys, and rejects a CAD
# drop. filter_patterns' "manifest.json" entry is the independent BELT.
# --------------------------------------------------------------------------- #
def test_f1_sensor_gate_matches_pdf_rejects_sidecar_and_cad():
    from doc_tools.definitions import ingress_user_sensor

    pattern = ingress_user_sensor.s3_filter
    assert pattern, "ingress_user_sensor must declare an s3_filter (D1/D2 gate)"

    assert re.match(pattern, _LIVE_DOC_KEY_1)
    assert re.match(pattern, _LIVE_DOC_KEY_2)
    assert re.match(pattern, _LIVE_SIDECAR_KEY_1) is None
    assert re.match(pattern, _LIVE_SIDECAR_KEY_2) is None

    # D2 — a CAD drop must never reach the PDF parser.
    assert re.match(pattern, "ingress-user/cad/" + "a" * 64 + "/part.step") is None

    # The belt: stated by a SECOND, independent mechanism.
    assert "manifest.json" in ingress_user_sensor.filter_patterns


# --------------------------------------------------------------------------- #
# Shared sidecar fixture for the F2-F6 tests below.
# --------------------------------------------------------------------------- #
def _live_sidecar(ingest_id="sha256:fa231498f527921fc547cb97009a7d98fb45927bdaf7237028ea1cb60305e9bb",
                   domain_type=None, content_kind=None, provenance="default"):
    if provenance == "default":
        provenance = {
            "authoritative_source": "unconfirmed-at-intake",
            "obtained_via": "user-drop",
            "as_of": "unknown",
            "ingested_at": "2026-10-02T00:00:00+00:00",
            "ingest_run": f"user-drop:{ingest_id}",
            "standing": "supervised",
            "ingest_id": ingest_id,
        }
    sidecar = {
        "ingest_id": ingest_id,
        "object_ref": _LIVE_DOC_KEY_2,
        "content_kind": content_kind,
        "domain_type": domain_type,
    }
    if provenance is not None:
        sidecar["provenance"] = provenance
    return sidecar


def _user_parser_kwargs():
    return dict(
        name="process_user_document_artifact",
        partition_name="user_pdf_files",
        obtained_via="user-drop",
        path_prefix_strip="ingress-user/",
        sidecar_manifest_name="manifest.json",
    )


# --------------------------------------------------------------------------- #
# F2 — the sidecar's own provenance block WINS over minting a fresh one
# (D4): the emitted manifest's "provenance" is exactly the sidecar's block,
# and "ingest_id" (the join key to Lane 1's ingest_status_projection row)
# is present at the manifest's TOP LEVEL (F4), sibling of "provenance".
# --------------------------------------------------------------------------- #
def test_f2_sidecar_provenance_wins_and_ingest_id_is_carried():
    pytest.importorskip("iagent_mesh.ingest")
    sidecar = _live_sidecar()
    fake_client = _FakeS3Client()
    fake_client.objects[(BUCKET, _LIVE_SIDECAR_KEY_2)] = json.dumps(sidecar).encode("utf-8")

    manifest = _run_parser(_user_parser_kwargs(), _LIVE_DOC_KEY_2, fake_client=fake_client)

    assert manifest["provenance"] == sidecar["provenance"]
    assert manifest["ingest_id"] == sidecar["ingest_id"]
    # D3 — the live sidecar's domain_type/content_kind are null; they must
    # stay null, never fall back to the path's "pdf" / 64-hex sha.
    assert manifest["metadata"]["domain_type"] is None
    assert manifest["metadata"]["content_kind"] is None


# --------------------------------------------------------------------------- #
# F2 — a missing or unparseable sidecar is a HARD FAILURE: no path-
# derivation fallback, and the exception names the sidecar key.
# --------------------------------------------------------------------------- #
def test_f2_missing_sidecar_raises_and_names_the_key():
    with pytest.raises(RuntimeError, match=re.escape(_LIVE_SIDECAR_KEY_2)):
        _run_parser(_user_parser_kwargs(), _LIVE_DOC_KEY_2)  # no sidecar seeded


# --------------------------------------------------------------------------- #
# F3 — the D3 guard: a resolved domain_type that is still a FILE FORMAT, or
# a resolved content_kind that is still a sha256 HASH, must raise rather
# than silently becoming a semantic label.
# --------------------------------------------------------------------------- #
def test_f3_guard_rejects_format_as_domain_type():
    sidecar = _live_sidecar(domain_type="pdf")
    fake_client = _FakeS3Client()
    fake_client.objects[(BUCKET, _LIVE_SIDECAR_KEY_2)] = json.dumps(sidecar).encode("utf-8")

    with pytest.raises(ValueError, match="domain_type"):
        _run_parser(_user_parser_kwargs(), _LIVE_DOC_KEY_2, fake_client=fake_client)


def test_f3_guard_rejects_sha256_hash_as_content_kind():
    sidecar = _live_sidecar(content_kind="c" * 64)
    fake_client = _FakeS3Client()
    fake_client.objects[(BUCKET, _LIVE_SIDECAR_KEY_2)] = json.dumps(sidecar).encode("utf-8")

    with pytest.raises(ValueError, match="content_kind"):
        _run_parser(_user_parser_kwargs(), _LIVE_DOC_KEY_2, fake_client=fake_client)


# --------------------------------------------------------------------------- #
# F5 — IngestStatusResource.update validates against the REAL imported
# vocabulary (never a mirrored copy) and Lane 1's own "failed"/"rejected"
# need-a-detail rule.
# --------------------------------------------------------------------------- #
def test_f5_ingest_status_resource_rejects_unknown_stage():
    pytest.importorskip("iagent_mesh.ingest")
    from doc_tools.utils.dagster_resources import IngestStatusResource

    resource = IngestStatusResource()
    # "extracted" does not exist in INGEST_STAGES (do NOT add it — see the
    # spec's "Do NOT do" list; extracted_count/extracted_total are columns,
    # not a stage).
    with pytest.raises(ValueError):
        resource.update("sha256:deadbeef", "extracted")


def test_f5_ingest_status_resource_rejects_blank_detail_on_failed():
    pytest.importorskip("iagent_mesh.ingest")
    from doc_tools.utils.dagster_resources import IngestStatusResource

    resource = IngestStatusResource()
    with pytest.raises(ValueError):
        resource.update("sha256:deadbeef", "failed", detail="")
    with pytest.raises(ValueError):
        resource.update("sha256:deadbeef", "failed", detail="   ")
    # A non-blank detail is accepted (no raise).
    resource.update("sha256:deadbeef", "failed", detail="boom")


# --------------------------------------------------------------------------- #
# F6 — nothing new to build: assert the join. notice_identity's Level-2 key
# and the manifest's ingest_id (F4) both land on the SAME emitted
# manifest/base_dir pair, so Lane 1 can join notice_identity -> ingest_id
# without a second dedupe implementation.
# --------------------------------------------------------------------------- #
def test_f6_notice_identity_and_ingest_id_join_on_the_same_manifest():
    pytest.importorskip("iagent_mesh.ingest")
    from doc_tools.utils.notice_identity import build_identity

    sidecar = _live_sidecar()
    fake_client = _FakeS3Client()
    fake_client.objects[(BUCKET, _LIVE_SIDECAR_KEY_2)] = json.dumps(sidecar).encode("utf-8")

    manifest = _run_parser(_user_parser_kwargs(), _LIVE_DOC_KEY_2, fake_client=fake_client)

    # doc_id here stands in for the header's doc_id a later sustainment
    # pass extracts (notice_identity has no knowledge of ingest_id and must
    # not gain one). The join this asserts: both values are read off the
    # ONE manifest this run produced, at the SAME base_dir.
    identity = build_identity(mfr="Diodes", doc_id=manifest["doc_id"], revision="A")
    assert identity["complete"] is True
    assert identity["doc_id"] == manifest["doc_id"]
    assert manifest["ingest_id"] == sidecar["ingest_id"]
    assert manifest["source_key"] == _LIVE_DOC_KEY_2
    assert manifest["source_key"].startswith(os.path.dirname(_LIVE_SIDECAR_KEY_2))
