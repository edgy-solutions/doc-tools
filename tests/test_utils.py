"""Tests for the utility wrappers (doc_tools/utils): Weaviate/Jena clients and
the unstructured extraction helper. External libraries are mocked so these run
with no live services.
"""
from unittest.mock import MagicMock, patch

import pytest

from doc_tools.utils import weaviate_client as wc
from doc_tools.utils.jena_client import JenaClient
import doc_tools.utils.extraction as ext


# --------------------------------------------------------------------------- #
# Weaviate client: host/port parsing for split HTTP/gRPC routing
# --------------------------------------------------------------------------- #
@patch("doc_tools.utils.weaviate_client.weaviate.connect_to_custom")
def test_weaviate_parses_explicit_host_port(mock_conn):
    wc.get_weaviate_client(http_host="myhost:8080", grpc_host="grpcd:50051")
    kw = mock_conn.call_args.kwargs
    assert (kw["http_host"], kw["http_port"]) == ("myhost", 8080)
    assert (kw["grpc_host"], kw["grpc_port"]) == ("grpcd", 50051)
    assert kw["http_secure"] is False and kw["grpc_secure"] is False


@patch("doc_tools.utils.weaviate_client.weaviate.connect_to_custom")
def test_weaviate_strips_scheme_and_falls_back_to_defaults(mock_conn):
    wc.get_weaviate_client(http_host="http://h", grpc_host="grpc://g:notaport")
    kw = mock_conn.call_args.kwargs
    assert (kw["http_host"], kw["http_port"]) == ("h", 8080)        # no port -> default
    assert (kw["grpc_host"], kw["grpc_port"]) == ("g", 50051)       # bad port -> default


@patch("doc_tools.utils.weaviate_client.weaviate.connect_to_custom")
def test_weaviate_reads_env(mock_conn, monkeypatch):
    monkeypatch.setenv("WEAVIATE_HTTP_HOST", "envhost:1234")
    monkeypatch.setenv("WEAVIATE_GRPC_HOST", "envgrpc:5678")
    wc.get_weaviate_client()
    kw = mock_conn.call_args.kwargs
    assert (kw["http_host"], kw["http_port"]) == ("envhost", 1234)
    assert (kw["grpc_host"], kw["grpc_port"]) == ("envgrpc", 5678)


# --------------------------------------------------------------------------- #
# Jena client: URL construction + auth + endpoint routing
# --------------------------------------------------------------------------- #
def test_jena_init_strips_trailing_slash_and_resolves():
    c = JenaClient(url="http://jena:3030/", dataset="ds", username="u", password="p")
    assert c.base_url == "http://jena:3030"
    assert c.dataset == "ds" and c.username == "u"


def test_jena_init_reads_env(monkeypatch):
    monkeypatch.setenv("JENA_URL", "http://fuseki:3030")
    monkeypatch.setenv("JENA_DS", "kg")
    c = JenaClient()
    assert c.base_url == "http://fuseki:3030" and c.dataset == "kg"


@patch("doc_tools.utils.jena_client.httpx.Client")
def test_jena_execute_update_posts_sparql_update(mock_client_cls):
    # execute_update now POSTs via httpx with application/sparql-update
    # (SPARQLWrapper hit the /update endpoint with a method Fuseki 405'd).
    client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = client
    client.post.return_value = MagicMock(raise_for_status=lambda: None)

    JenaClient(url="http://jena:3030", dataset="ds", username="u", password="p").execute_update(
        "INSERT DATA { <a> <b> <c> }"
    )

    assert client.post.call_args.args[0] == "http://jena:3030/ds/update"
    kw = client.post.call_args.kwargs
    assert kw["headers"]["Content-Type"] == "application/sparql-update"
    assert kw["content"] == b"INSERT DATA { <a> <b> <c> }"
    assert mock_client_cls.call_args.kwargs["auth"] == ("u", "p")


@patch("doc_tools.utils.jena_client.SPARQLWrapper")
def test_jena_execute_query_targets_query_endpoint(mock_wrapper):
    inst = MagicMock()
    mock_wrapper.return_value = inst
    JenaClient(url="http://jena:3030", dataset="ds").execute_query("SELECT * {}")
    assert mock_wrapper.call_args[0][0] == "http://jena:3030/ds/query"
    inst.queryAndConvert.assert_called_once()


# --------------------------------------------------------------------------- #
# Extraction: tesseract discovery + unstructured partition wrapper
# --------------------------------------------------------------------------- #
@patch("doc_tools.utils.extraction.shutil.which", return_value="/usr/bin/tesseract")
def test_configure_tesseract_already_in_path_is_noop(_which):
    ext.configure_tesseract()  # returns early, no exception


@patch("doc_tools.utils.extraction.shutil.which", return_value=None)
@patch("doc_tools.utils.extraction.os.path.isfile", return_value=False)
def test_configure_tesseract_not_found_warns(_isfile, _which, monkeypatch):
    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    ext.configure_tesseract()  # falls through all paths, warns, no exception


@patch("doc_tools.utils.extraction.partition")
def test_extract_text_returns_element_dicts(mock_partition):
    el = MagicMock()
    el.to_dict.return_value = {"type": "NarrativeText", "text": "hi", "metadata": {}}
    mock_partition.return_value = [el]
    out = ext.extract_text_and_metadata("/tmp/x.pdf")
    assert out == [{"type": "NarrativeText", "text": "hi", "metadata": {}}]
    assert mock_partition.call_args.kwargs["strategy"] == "auto"


@patch("doc_tools.utils.extraction.partition")
def test_extract_images_switches_to_hi_res(mock_partition):
    mock_partition.return_value = []
    ext.extract_text_and_metadata("/tmp/x.pdf", extract_images=True, image_output_dir="/out")
    kw = mock_partition.call_args.kwargs
    assert kw["strategy"] == "hi_res"
    assert kw["extract_image_block_output_dir"] == "/out"
    assert "Image" in kw["extract_image_block_types"]


@patch("doc_tools.utils.extraction.partition", side_effect=RuntimeError("boom"))
def test_extract_text_reraises_on_failure(_partition):
    with pytest.raises(RuntimeError):
        ext.extract_text_and_metadata("/tmp/x.pdf")


# --------------------------------------------------------------------------- #
# SPARQL IRI local-part sanitization (Fuseki 400 fix)
# --------------------------------------------------------------------------- #
def test_safe_iri_local_replaces_unsafe_chars():
    from doc_tools.utils.jena_client import safe_iri_local
    # slash from a doc id like "inbound/22" is the real-world offender
    assert safe_iri_local("step_inbound/22_1.1") == "step_inbound_22_1.1"
    assert safe_iri_local("a b#c") == "a_b_c"
    assert safe_iri_local(".lead.trail.") == "lead.trail"  # no leading/trailing dot
    assert safe_iri_local("") == "_"
    assert safe_iri_local("12A") == "12A"  # already-safe passes through
