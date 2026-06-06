"""Tests for the prompt-sourcing contract in ``AugmentationPlugin``.

Covers the ``PROMPT_SOURCE`` env switch that makes production CM-canonical
(file-backed, git-committed) while keeping an opt-in live Langfuse path for
SME/dev hot-tuning. See ``doc_tools/plugins/base.py::_get_dynamic_prompt`` and
the "Prompt Source & GitOps" section of the README.
"""
from typing import Any, List
from unittest.mock import MagicMock

import pytest

from doc_tools.plugins.base import AugmentationPlugin


class _DummyPlugin(AugmentationPlugin):
    """Minimal concrete plugin so we can exercise the base prompt logic."""

    def augment(self, section: Any, config: Any = None):  # pragma: no cover - not used
        return None

    def to_graph_queries(self, nodes, config, doc_id: str = "", image_prefix: str = ""):  # pragma: no cover
        return ([], [])


@pytest.fixture
def plugin():
    return _DummyPlugin(domain_type="sustainment")


@pytest.fixture
def prompt_file(tmp_path):
    """A canonical, git-style prompt file on disk."""
    f = tmp_path / "demo_instructions.md"
    f.write_text("CANONICAL prompt: format is {{ fmt }}.")
    return f


def _mock_langfuse(text="LANGFUSE prompt"):
    """Build a Langfuse stand-in whose get_prompt returns a compilable prompt."""
    prompt_obj = MagicMock()
    prompt_obj.prompt = text
    prompt_obj.compile.side_effect = lambda **kw: text + " " + "|".join(
        f"{k}={v}" for k, v in kw.items()
    )
    client = MagicMock()
    client.get_prompt.return_value = prompt_obj
    return client


# --- Default / file path (the production, CM-canonical contract) -------------

def test_default_source_is_file_and_never_builds_langfuse(plugin, prompt_file, monkeypatch):
    monkeypatch.delenv("PROMPT_SOURCE", raising=False)
    out = plugin._get_dynamic_prompt("demo_instructions", str(prompt_file))
    assert out.startswith("CANONICAL prompt")
    # Critical: the production default must not construct a Langfuse client.
    assert plugin._langfuse is None


def test_explicit_file_source_reads_canonical_file(plugin, prompt_file, monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "file")
    out = plugin._get_dynamic_prompt("demo_instructions", str(prompt_file))
    assert out.startswith("CANONICAL prompt")


def test_file_mode_substitutes_compile_kwargs(plugin, prompt_file, monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "file")
    out = plugin._get_dynamic_prompt("demo_instructions", str(prompt_file), fmt="REGEX-42")
    assert out == "CANONICAL prompt: format is REGEX-42."


def test_unknown_source_defaults_to_file(plugin, prompt_file, monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "banana")
    out = plugin._get_dynamic_prompt("demo_instructions", str(prompt_file))
    assert out.startswith("CANONICAL prompt")
    assert plugin._langfuse is None


# --- Opt-in Langfuse path (SME / dev hot-tuning) -----------------------------

def test_langfuse_mode_serves_langfuse(plugin, prompt_file, monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "langfuse")
    monkeypatch.delenv("LANGFUSE_PROMPT_LABEL", raising=False)
    plugin._langfuse = _mock_langfuse("LIVE from GUI")

    out = plugin._get_dynamic_prompt("demo_instructions", str(prompt_file))

    assert out == "LIVE from GUI"
    plugin._langfuse.get_prompt.assert_called_once_with(
        "demo_instructions", label="production", cache_ttl_seconds=0
    )


def test_langfuse_mode_compiles_kwargs(plugin, prompt_file, monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "langfuse")
    plugin._langfuse = _mock_langfuse("LIVE")
    out = plugin._get_dynamic_prompt("demo_instructions", str(prompt_file), fmt="X")
    assert out == "LIVE fmt=X"


def test_langfuse_label_is_honored(plugin, prompt_file, monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "langfuse")
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "staging")
    plugin._langfuse = _mock_langfuse()

    plugin._get_dynamic_prompt("demo_instructions", str(prompt_file))

    _, kwargs = plugin._langfuse.get_prompt.call_args
    assert kwargs["label"] == "staging"


def test_langfuse_outage_falls_back_to_canonical_file(plugin, prompt_file, monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "langfuse")
    client = MagicMock()
    client.get_prompt.side_effect = RuntimeError("simulated Langfuse outage")
    plugin._langfuse = client

    out = plugin._get_dynamic_prompt("demo_instructions", str(prompt_file))

    # Degrades gracefully to the committed file rather than failing the run.
    assert out.startswith("CANONICAL prompt")


def test_file_mode_raises_when_canonical_file_missing(plugin, monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "file")
    with pytest.raises(Exception):
        plugin._get_dynamic_prompt("missing", "does/not/exist.md")
