"""Seal for the missing-prompt-file hard-fail fix.

THE BUG (real run, 2026-09-24): launched from the wrong cwd, the relative path
`prompts/sustainment_parts_instructions.md` did not resolve. `_load_prompt_from_file`
already ended its `except` with a bare `raise` — the loader was never the defect.
The defect was downstream: `doc_tools/plugins/sustainment.py` wraps its extraction
calls in broad `except Exception` handlers meant to degrade a genuine PER-DOCUMENT
failure (a vision timeout, a bad response). Those handlers also absorbed a missing
prompt file, which is not a per-document failure at all — it is a configuration
defect that affects every document identically. Three notices silently returned 0
parts; the only tell was wall time (0.7s vs 33.5s for a real vision pass).

The fix: a distinct `PromptUnavailableError`, raised by the loader on a genuinely
missing file (naming the given path, its resolved absolute path, and the cwd), a
first-use validator that checks a plugin's declared prompt files up front, and an
`except PromptUnavailableError: raise` ahead of each broad handler so the config
error escapes while a real per-document failure still degrades.

Matches the style of tests/test_prompt_source.py (same base module, same fixtures).
"""
from typing import Any

import pytest

from doc_tools.plugins.base import AugmentationPlugin, PromptUnavailableError
from doc_tools.plugins.sustainment import SustainmentPlugin


class _DummyPlugin(AugmentationPlugin):
    """Minimal concrete plugin so the base class's prompt logic can be exercised
    without pulling in a domain's BAML/LLM machinery."""

    def augment(self, section: Any, config: Any = None):  # pragma: no cover - not used
        return None

    def to_graph_queries(self, nodes, config, doc_id: str = "", image_prefix: str = ""):  # pragma: no cover
        return ([], [])


@pytest.fixture
def plugin():
    return _DummyPlugin(domain_type="sustainment")


@pytest.fixture
def sustainment_plugin():
    return SustainmentPlugin(domain_type="sustainment")


# --------------------------------------------------------------------------- #
# _load_prompt_from_file on a nonexistent path.
# --------------------------------------------------------------------------- #

def test_load_prompt_from_file_raises_prompt_unavailable_with_cwd_and_abspath(plugin):
    missing_path = "does/not/exist/sustainment_header_instructions.md"

    with pytest.raises(PromptUnavailableError) as excinfo:
        plugin._load_prompt_from_file(missing_path, prompt_name="demo")

    msg = str(excinfo.value)
    assert missing_path in msg
    import os
    assert os.getcwd() in msg
    assert os.path.abspath(missing_path) in msg


# --------------------------------------------------------------------------- #
# THE SEAL: running from the wrong directory must go RED — a missing prompt must
# propagate OUT of the plugin's extraction path rather than degrade to a 0-parts
# result. Written so it fails against the pre-fix code: the old bare
# `except Exception` at the header-pass call site swallowed ANY exception
# (including a plain FileNotFoundError, since PromptUnavailableError did not
# exist yet) and returned normally with needs_review=True and zero parts —
# pytest.raises below would see nothing raised at all.
# --------------------------------------------------------------------------- #

def test_running_from_the_wrong_directory_raises_instead_of_degrading(
    sustainment_plugin, monkeypatch, tmp_path
):
    monkeypatch.delenv("PROMPT_SOURCE", raising=False)
    # Simulate the /tmp launch: cwd has no `prompts/` directory at all, so the
    # header pass's relative `fallback_file` cannot resolve.
    monkeypatch.chdir(tmp_path)

    with pytest.raises(PromptUnavailableError):
        sustainment_plugin._extract_fulltext("some full text", "doc-1", elements=[])


# --------------------------------------------------------------------------- #
# First-use validation names EVERY missing prompt file, not just the first.
# --------------------------------------------------------------------------- #

def test_ensure_prompts_available_reports_every_missing_file_at_once(monkeypatch, tmp_path):
    class _TwoPromptPlugin(AugmentationPlugin):
        REQUIRED_PROMPT_FILES = ["prompts/one_instructions.md", "prompts/two_instructions.md"]

        def augment(self, section, config=None):  # pragma: no cover
            return None

        def to_graph_queries(self, nodes, config, doc_id="", image_prefix=""):  # pragma: no cover
            return ([], [])

    monkeypatch.chdir(tmp_path)   # neither file exists here
    p = _TwoPromptPlugin(domain_type="demo")

    with pytest.raises(PromptUnavailableError) as excinfo:
        p._ensure_prompts_available()

    msg = str(excinfo.value)
    assert "one_instructions.md" in msg
    assert "two_instructions.md" in msg


def test_sustainment_plugin_declares_its_two_prompt_files():
    """Only SustainmentPlugin is wired to this validation; its declared set is
    exactly the two files it uses."""
    assert SustainmentPlugin.REQUIRED_PROMPT_FILES == [
        "prompts/sustainment_header_instructions.md",
        "prompts/sustainment_parts_instructions.md",
    ]


def test_ensure_prompts_available_is_a_noop_when_none_are_declared():
    """A plugin that declares no required prompt files (the base-class default) is
    unaffected — no other plugin's behavior is wired to this validation."""
    class _NoPromptPlugin(AugmentationPlugin):
        def augment(self, section, config=None):  # pragma: no cover
            return None

        def to_graph_queries(self, nodes, config, doc_id="", image_prefix=""):  # pragma: no cover
            return ([], [])

    _NoPromptPlugin(domain_type="demo")._ensure_prompts_available()  # must not raise


# --------------------------------------------------------------------------- #
# A genuine PER-DOCUMENT failure must still be swallowed and still degrade — the
# broad `except Exception` handlers keep working for the case they were written
# for. Without this test the PromptUnavailableError carve-out is a regression
# risk: a real vision timeout must not suddenly blow up the whole run.
# --------------------------------------------------------------------------- #

def test_a_genuine_per_document_failure_still_degrades(sustainment_plugin, monkeypatch):
    def _boom(full_text):
        raise RuntimeError("simulated per-document extraction failure")

    monkeypatch.setattr(sustainment_plugin, "_extract_header", _boom)

    nodes = sustainment_plugin._extract_fulltext("some full text", "doc-1", elements=[])

    aug = nodes[0].domain_augmentation
    assert aug.needs_review is True
    assert any("header pass failed" in r for r in aug.review_reasons)
    assert aug.notice.impacted_parts == []


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
