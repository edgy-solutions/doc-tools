"""Shared embedding helper for doc-tools' Weaviate writes.

Same function shape, same default model name, same dim, and same task
prefixes as invincible-agent/agent_fleet/utils/embed.py. Both repos call
this; both collections store vectors computed by this code; both query
paths pass explicit `vector=` to Weaviate. Weaviate is dumb storage of
the vector — it NEVER computes one via a text2vec module.

The contract is THIS file plus the iagent twin. A grep across both repos
for ``DEFAULT_EMBED_MODEL`` / ``EXPECTED_EMBED_DIM`` / ``DOCUMENT_PREFIX``
/ ``QUERY_PREFIX`` shows every call site.

See agent_fleet/utils/embed.py for the full rationale (why-not-text2vec,
endpoint discovery, model-name stability, task-prefix discipline).

Usage::

    from doc_tools.utils.embed import embed_document  # corpus writes
    from doc_tools.utils.embed import embed_query     # query reads

    vec = embed_document(chunk_text)
    collection.data.insert(properties={"text": chunk_text, ...}, vector=vec)
"""
from __future__ import annotations

import os
import httpx


# Must stay byte-identical to invincible-agent/agent_fleet/utils/embed.py's
# constants. Both repos' guard tests assert exactly one model-name string
# exists in their respective trees; the inter-repo agreement is enforced by
# code review on these constants.
DEFAULT_EMBED_MODEL = "nomic-embed-text"
EXPECTED_EMBED_DIM = 768
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


def _resolve_endpoint() -> tuple[str, str, str]:
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    if not base_url:
        raise RuntimeError(
            "embed requires LLM_BASE_URL (or OPENAI_BASE_URL) to be set. "
            "Point it at an OpenAI-compatible endpoint that exposes "
            "/embeddings — typically the in-cluster LiteLLM proxy "
            "(http://iagent-litellm:4000/v1)."
        )
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "any"
    model = os.getenv("LLM_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    return base_url, api_key, model


def _post_embedding(input_payload, timeout: float) -> list:
    base_url, api_key, model = _resolve_endpoint()
    r = httpx.post(
        f"{base_url.rstrip('/')}/embeddings",
        json={"model": model, "input": input_payload},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    r.raise_for_status()
    payload = r.json()
    data = payload.get("data") or []
    if not data:
        raise RuntimeError(
            f"Embedding endpoint {base_url} returned an empty response for "
            f"model={model!r}: {payload!r}"
        )
    return data


def embed_document(text: str, timeout: float = 30.0) -> list[float]:
    data = _post_embedding(f"{DOCUMENT_PREFIX}{text}", timeout=timeout)
    if "embedding" not in data[0]:
        raise RuntimeError(f"Embedding response missing 'embedding' key: {data[0]!r}")
    return list(data[0]["embedding"])


def embed_documents(texts: list[str], timeout: float = 60.0) -> list[list[float]]:
    prefixed = [f"{DOCUMENT_PREFIX}{t}" for t in texts]
    data = _post_embedding(prefixed, timeout=timeout)
    if len(data) != len(texts):
        raise RuntimeError(
            f"Embedding endpoint returned {len(data)} vectors for "
            f"{len(texts)} inputs"
        )
    return [list(d["embedding"]) for d in data]


def embed_query(text: str, timeout: float = 30.0) -> list[float]:
    data = _post_embedding(f"{QUERY_PREFIX}{text}", timeout=timeout)
    if "embedding" not in data[0]:
        raise RuntimeError(f"Embedding response missing 'embedding' key: {data[0]!r}")
    return list(data[0]["embedding"])


def probe_embedding_dim(probe_text: str = "doc-tools embed probe") -> int:
    vec = embed_query(probe_text)
    dim = len(vec)
    if dim != EXPECTED_EMBED_DIM:
        _, _, model = _resolve_endpoint()
        raise RuntimeError(
            f"Embedding-model dimension mismatch: model={model!r} returned "
            f"{dim}-dim vectors but the codebase expects EXPECTED_EMBED_DIM="
            f"{EXPECTED_EMBED_DIM} (the dim for DEFAULT_EMBED_MODEL="
            f"{DEFAULT_EMBED_MODEL!r}). EITHER your LLM_EMBED_MODEL is set "
            f"to a different-dim model than the default, OR you intend "
            f"to migrate the codebase to a new embedder — in which case "
            f"update EXPECTED_EMBED_DIM in BOTH doc_tools/utils/embed.py "
            f"AND agent_fleet/utils/embed.py, AND wipe/rebuild every "
            f"Weaviate collection that stores vectors."
        )
    return dim
