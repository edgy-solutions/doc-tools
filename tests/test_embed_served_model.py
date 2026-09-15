"""The served model is what describes the vectors — capture it, and say so once.

THE DEFECT THIS CLOSES, measured rather than supposed. `EXPECTED_EMBED_DIM`
catches a dimension change loudly and is BLIND to a model change at the same
dimension: a swap between two 768-dim models writes cleanly, reads cleanly, and
returns neighbours computed in a different space. Plausible results, not an error.

And `LLM_EMBED_MODEL` is env-overridable at runtime (embed.py:54), so
`DEFAULT_EMBED_MODEL` records what the code BELIEVES rather than what the process
did. The identity of what actually served the request was arriving in every
`/v1/embeddings` response — `{"object": "list", "model": ..., "usage": ...}`,
measured in-cluster 2026-09-15 — and was discarded one line from where it was
needed.

This is deliberately independent of the MeshCollectionMeta marker work, which is
blocked on a contract decision. It needs no SDK, no reader and no marker: one
warning at write time makes a same-dim swap visible to the operator who caused it.
"""
import logging
from unittest.mock import MagicMock, patch

import pytest

from doc_tools.utils import embed


@pytest.fixture(autouse=True)
def _endpoint(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://embed.test/v1")
    monkeypatch.delenv("LLM_EMBED_MODEL", raising=False)
    embed._REPORTED_MODEL_SWAPS.clear()


def _response(model, n=1):
    r = MagicMock()
    r.json.return_value = {
        "object": "list",
        "model": model,
        "usage": {"prompt_tokens": 3},
        "data": [{"embedding": [0.0] * 768} for _ in range(n)],
    }
    return r


# ---------------------------------------------------------------------------
# served_model — the response, not the request
# ---------------------------------------------------------------------------

def test_the_served_model_comes_from_the_RESPONSE():
    """The request is what we asked for; the response is what we got, and only
    the second describes the vectors."""
    assert embed.served_model({"model": "actually-served"}, "asked-for") == "actually-served"


def test_a_provider_omitting_the_field_falls_back_to_the_REQUEST():
    """A missing identity must not read as a mismatch. Not every OpenAI-compatible
    implementation populates `model`, and a silent absence reported as a swap would
    cry wolf on every call until the check was muted."""
    assert embed.served_model({}, "asked-for") == "asked-for"
    assert embed.served_model({"model": None}, "asked-for") == "asked-for"
    assert embed.served_model({"model": ""}, "asked-for") == "asked-for"


# ---------------------------------------------------------------------------
# The warning — loud, once, and never fatal
# ---------------------------------------------------------------------------

def test_a_model_swap_WARNS_at_write_time(caplog):
    """THE WHOLE POINT. Nothing else in this pipeline notices a same-dim swap."""
    with patch.object(embed.httpx, "post", return_value=_response("some-other-model")):
        with caplog.at_level(logging.WARNING, logger="doc_tools.utils.embed"):
            vec = embed.embed_document("x")

    assert len(vec) == 768, "the vector is still returned — this warns, it does not block"
    joined = " ".join(caplog.messages)
    assert "nomic-embed-text" in joined and "some-other-model" in joined, (
        "the warning must name BOTH sides — an operator cannot act on 'a mismatch'"
    )


def test_a_swap_does_NOT_raise(caplog):
    """WARN, NOT RAISE, and the reason is not timidity. A proxy legitimately
    rewrites names — LiteLLM may serve `nomic-embed-text` as
    `ollama/nomic-embed-text` — so refusing here turns routine aliasing into a
    failed ingest. A check that breaks working deployments is a check that gets
    deleted, and then the real swap goes unreported too."""
    with patch.object(embed.httpx, "post", return_value=_response("ollama/nomic-embed-text")):
        assert len(embed.embed_document("x")) == 768


def test_the_warning_fires_ONCE_not_per_call(caplog):
    """An ontology ingest embeds ~21,000 classes. A per-call warning is 21,000
    identical lines, which is how a real signal becomes log noise people filter
    out — the same end state as not warning at all."""
    with patch.object(embed.httpx, "post", return_value=_response("some-other-model")):
        with caplog.at_level(logging.WARNING, logger="doc_tools.utils.embed"):
            for _ in range(50):
                embed.embed_document("x")

    swaps = [m for m in caplog.messages if "EMBEDDING MODEL MISMATCH" in m]
    assert len(swaps) == 1, f"expected one warning across 50 calls, got {len(swaps)}"


def test_a_SECOND_distinct_swap_is_reported_separately(caplog):
    """Non-vacuity for the dedup: suppression is keyed on the PAIR, so a genuinely
    different swap is not swallowed by the first one's report."""
    with caplog.at_level(logging.WARNING, logger="doc_tools.utils.embed"):
        with patch.object(embed.httpx, "post", return_value=_response("model-a")):
            embed.embed_document("x")
        with patch.object(embed.httpx, "post", return_value=_response("model-b")):
            embed.embed_document("x")

    swaps = [m for m in caplog.messages if "EMBEDDING MODEL MISMATCH" in m]
    assert len(swaps) == 2


def test_the_matching_case_is_SILENT(caplog):
    """The control. Without it, a warning that fired unconditionally would pass
    every test above while making the signal meaningless."""
    with patch.object(embed.httpx, "post", return_value=_response("nomic-embed-text")):
        with caplog.at_level(logging.WARNING, logger="doc_tools.utils.embed"):
            embed.embed_document("x")

    assert not [m for m in caplog.messages if "EMBEDDING MODEL MISMATCH" in m]


def test_an_env_override_is_what_gets_compared(monkeypatch, caplog):
    """`LLM_EMBED_MODEL` is the runtime truth, not `DEFAULT_EMBED_MODEL`. If the
    comparison used the constant, an operator who deliberately set the override
    would be warned on every run — and the one case that matters, the endpoint
    serving something OTHER than what was asked for, would be invisible."""
    monkeypatch.setenv("LLM_EMBED_MODEL", "deliberate-choice")
    with patch.object(embed.httpx, "post", return_value=_response("deliberate-choice")):
        with caplog.at_level(logging.WARNING, logger="doc_tools.utils.embed"):
            embed.embed_document("x")

    assert not [m for m in caplog.messages if "EMBEDDING MODEL MISMATCH" in m], (
        "warned about an override the operator set deliberately and the endpoint honoured"
    )


def test_batch_embedding_reports_the_swap_too(caplog):
    """embed_documents is the path the ontology ingest actually uses in bulk;
    a check present on the single path only would miss the 21k-class run."""
    with patch.object(embed.httpx, "post", return_value=_response("some-other-model", n=3)):
        with caplog.at_level(logging.WARNING, logger="doc_tools.utils.embed"):
            vecs = embed.embed_documents(["a", "b", "c"])

    assert len(vecs) == 3
    assert [m for m in caplog.messages if "EMBEDDING MODEL MISMATCH" in m]
