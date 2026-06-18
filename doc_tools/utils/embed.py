"""Shared embedding helper for doc-tools' Weaviate writes.

Same function shape and default model name as
invincible-agent/agent_fleet/utils/embed.py. Both repos call this; both
collections store vectors computed by this code; both query paths pass
explicit `vector=` to Weaviate. Weaviate is dumb storage of the vector —
it NEVER computes one via a text2vec module.

The contract is THIS file plus the iagent twin. A grep across both repos
for `LLM_EMBED_MODEL` and `embed_text` shows every call site.

See agent_fleet/utils/embed.py for the full rationale (why-not-text2vec,
endpoint discovery, model-name stability).

Usage::

    from doc_tools.utils.embed import embed_text

    vec = embed_text(chunk_text)
    collection.data.insert(properties={"text": chunk_text, ...}, vector=vec)
"""
from __future__ import annotations

import os
import httpx


# Must stay byte-identical to invincible-agent/agent_fleet/utils/embed.py's
# DEFAULT_EMBED_MODEL. Both repos' guard tests assert exactly one model-name
# string exists in their respective trees; the inter-repo agreement is
# enforced by code review on this constant.
DEFAULT_EMBED_MODEL = "nomic-embed-text"

# Expected embedding dimensionality. Must equal the constant of the same
# name in invincible-agent/agent_fleet/utils/embed.py — cross-repo
# agreement on dim is the contract; review on either constant catches drift.
# nomic-embed-text is nomic-bert-v1 → 768-dim.
#
# Weaviate v4 collections WITHOUT vectorizer_config lock the dim on first
# write and reject mismatched-dim writes loudly. This constant is the
# soft check (probe_embedding_dim()); Weaviate is the hard one.
#
# Migration to a different-dim model:
#   1. Wipe/rebuild Weaviate collections that store vectors.
#   2. Update EXPECTED_EMBED_DIM here AND in agent_fleet/utils/embed.py.
#   3. Update DEFAULT_EMBED_MODEL in both files.
#   4. Backfill writes to repopulate vectors.
EXPECTED_EMBED_DIM = 768


def _resolve_endpoint() -> tuple[str, str, str]:
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    if not base_url:
        raise RuntimeError(
            "embed_text requires LLM_BASE_URL (or OPENAI_BASE_URL) to be "
            "set. Point it at an OpenAI-compatible endpoint that exposes "
            "/embeddings — typically the in-cluster LiteLLM proxy "
            "(http://iagent-litellm:4000/v1)."
        )
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "any"
    model = os.getenv("LLM_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    return base_url, api_key, model


def embed_text(text: str, timeout: float = 30.0) -> list[float]:
    base_url, api_key, model = _resolve_endpoint()
    r = httpx.post(
        f"{base_url.rstrip('/')}/embeddings",
        json={"model": model, "input": text},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    r.raise_for_status()
    payload = r.json()
    data = payload.get("data") or []
    if not data or "embedding" not in data[0]:
        raise RuntimeError(
            f"Embedding endpoint {base_url} returned an empty/malformed "
            f"response for model={model!r}: {payload!r}"
        )
    return list(data[0]["embedding"])


def probe_embedding_dim(probe_text: str = "doc-tools embed probe") -> int:
    """Optional startup probe — assert the configured endpoint returns
    EXPECTED_EMBED_DIM vectors. Raises with a clear message on mismatch.
    Returns the observed dim on success.
    """
    vec = embed_text(probe_text)
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


def embed_texts(texts: list[str], timeout: float = 60.0) -> list[list[float]]:
    base_url, api_key, model = _resolve_endpoint()
    r = httpx.post(
        f"{base_url.rstrip('/')}/embeddings",
        json={"model": model, "input": texts},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    r.raise_for_status()
    payload = r.json()
    data = payload.get("data") or []
    if len(data) != len(texts):
        raise RuntimeError(
            f"Embedding endpoint {base_url} returned {len(data)} vectors "
            f"for {len(texts)} inputs (model={model!r})"
        )
    return [list(d["embedding"]) for d in data]
