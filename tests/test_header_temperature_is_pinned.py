"""The header pass must decode GREEDILY, because identity/routing fields depend on it.

`ExtractHeader` (client `LLM`, gpt-oss) reads the SAME 1713 input tokens every fire and
answered differently: on `EOL-36_BYV34-400,-BYV34-500` it produced `mfr` = "TT Electronics"
against a SEMELAB document — a value that is not in the PDF at all — and `doc_type` flipped
PCN/PDN/PCN across repeated fires on byte-identical input. The client set no temperature, so
the server default applied and the call SAMPLED.

These tests are cheap and they are the only thing standing between that finding and a
silent regression: the temperature lives in a dict passed to a third-party client
registry, so nothing else in the suite would notice its removal. The header call is
stubbed in every other test (see `tests/test_sustainment_plugin.py`), which is exactly
why the guard is placed on the REGISTRATION and on the CALL SITE rather than on behaviour.
"""

import re
from pathlib import Path

import pytest

from doc_tools.plugins import sustainment as sustainment_module


class _CapturingRegistry:
    """Stands in for `baml_py.ClientRegistry` to capture what gets registered."""

    def __init__(self):
        self.clients = {}
        self.primary = None

    def add_llm_client(self, name, provider, options):
        self.clients[name] = {"provider": provider, "options": options}

    def set_primary(self, name):
        self.primary = name


@pytest.fixture
def registered(monkeypatch):
    """The options dict `_header_call_opts` actually hands to the client registry."""
    import baml_py

    captured = {}

    def _factory():
        reg = _CapturingRegistry()
        captured["reg"] = reg
        return reg

    monkeypatch.setattr(baml_py, "ClientRegistry", _factory)
    sustainment_module._header_call_opts()
    return captured["reg"]


def test_the_header_client_is_registered_with_temperature_zero(registered):
    """Greedy decoding, asserted on the value that reaches the provider."""
    assert registered.primary == "HeaderBounded", \
        "the bounded client must be primary, or none of its options apply"

    options = registered.clients["HeaderBounded"]["options"]
    assert "temperature" in options, \
        ("no temperature means the SERVER default applies and the header pass samples - "
         "the exact defect that fabricated 'TT Electronics' against a SEMELAB notice")
    assert options["temperature"] == 0, \
        "the header pass must decode greedily so doc_id/mfr/doc_type are reproducible"


def test_header_temperature_is_not_env_overridable(registered):
    """An env knob is a way to unpin the gate in the one place it matters.

    LLM_NUM_CTX beside it IS forwarded when set (mirroring `client<llm> LLM` in
    `baml_src/main.baml`, so pinning the client does not silently drop its declared
    config). The temperature is not: it backs an identity claim, so it is a constant
    in the module and reads the same in every environment.
    """
    assert sustainment_module.HEADER_TEMPERATURE == 0

    src = Path(sustainment_module.__file__).read_text(encoding="utf-8")
    match = re.search(r"^HEADER_TEMPERATURE\s*=\s*(.+)$", src, re.MULTILINE)
    assert match, "HEADER_TEMPERATURE must be a module-level constant"
    assert "getenv" not in match.group(1) and "environ" not in match.group(1), \
        "HEADER_TEMPERATURE must not be read from the environment"


def test_the_header_call_site_passes_the_bounded_client():
    """One source of truth only holds if nothing bypasses it.

    `temperature` is set on the ClientRegistry, not in `baml_src/main.baml`, so a header
    call made WITHOUT `baml_options` silently falls back to the declared `LLM` client -
    which has no temperature and samples. That regression would be invisible: the call
    still succeeds, still returns a header, and every other test stubs it. So the call
    site is asserted at the source level.
    """
    src = Path(sustainment_module.__file__).read_text(encoding="utf-8")

    header_calls = re.findall(r"b\.(ExtractHeader)\((.*?)\)\n", src, re.DOTALL)
    assert header_calls, "expected to find the header call site"

    for name, args in header_calls:
        assert "baml_options=" in args, \
            (f"b.{name} is called without baml_options, so it uses the declared LLM "
             f"client and SAMPLES - route it through _header_call_opts()")
