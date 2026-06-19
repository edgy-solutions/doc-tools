import sys
import os

# Target: /doc-tools/doc_tools/baml_client
# __file__: /doc-tools/doc_tools/doc_tools/__init__.py
baml_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "baml_client")
if baml_dir not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ---------------------------------------------------------------------------
# OPENAI_* -> LLM_* env-var aliasing.
#
# doc-tools' BAML client reads env.LLM_BASE_URL / env.LLM_API_KEY /
# env.LLM_MODEL / env.LLM_NUM_CTX literally (no fallback expressions
# possible in BAML). Operators who already configure their cluster with
# OPENAI_* names — typical when iagent (which uses smolagents/BAML's
# OPENAI_* path natively) shares the same iagent-config ConfigMap with
# doc-tools — would otherwise need to duplicate every variable. We
# alias them here so OPENAI_* alone is enough for both clients.
#
# Rules:
#   - LLM_* wins when both are set (preserves explicit overrides).
#   - Only populated when LLM_* is missing AND OPENAI_* is present.
#   - LLM_EMBED_MODEL has no OPENAI_* equivalent (the OpenAI chat model
#     and the embedding model are typically different) — embed.py uses
#     its own DEFAULT_EMBED_MODEL fallback there.
#
# Runs at module import — BEFORE BAML reads env on first call. Safe to
# re-import (idempotent: skipped when LLM_* is already set).
# ---------------------------------------------------------------------------
for _src, _dst in [
    ("OPENAI_BASE_URL", "LLM_BASE_URL"),
    ("OPENAI_API_KEY", "LLM_API_KEY"),
    ("OPENAI_MODEL", "LLM_MODEL"),
]:
    _v = os.environ.get(_src)
    if _v and not os.environ.get(_dst):
        os.environ[_dst] = _v

from .definitions import defs

__all__ = ["defs"]
