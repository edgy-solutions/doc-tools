"""The vision pass must decode GREEDILY, because the corpus gate depends on it.

Measured 2026-09-27 on pin sha256:0136991e: `ADI_PDN_23_0120` emitted 'AD7873ACPZ' in
one corpus run and '7873ACPZ' in two others from byte-identical input (same prompt, 1299
in-tokens in all three, no tier-1 activity on that notice at all). The client set no
temperature, so the server default applied and the call sampled. A 898/898 that can pass
or fail on unchanged code is not a measurement, and a gate that lands heads certifies
whatever was drawn.

These tests are cheap and they are the only thing standing between that finding and a
silent regression: the temperature lives in a dict passed to a third-party client
registry, so nothing else in the suite would notice its removal. Every vision call in
this repo is stubbed (see `tests/test_grid_forwarding_seal.py`), which is exactly why the
guard is placed on the REGISTRATION and on the CALL SITES rather than on behaviour.
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
    """The options dict `_vision_call_opts` actually hands to the client registry."""
    import baml_py

    captured = {}

    def _factory():
        reg = _CapturingRegistry()
        captured["reg"] = reg
        return reg

    monkeypatch.setattr(baml_py, "ClientRegistry", _factory)
    sustainment_module._vision_call_opts()
    return captured["reg"]


def test_the_vision_client_is_registered_with_temperature_zero(registered):
    """Greedy decoding, asserted on the value that reaches the provider."""
    assert registered.primary == "VisionBounded", \
        "the bounded client must be primary, or none of its options apply"

    options = registered.clients["VisionBounded"]["options"]
    assert "temperature" in options, \
        ("no temperature means the SERVER default applies and the parts pass samples - "
         "the exact defect that made ADI_PDN_23_0120 a coin flip across three runs")
    assert options["temperature"] == 0, \
        "the parts pass must decode greedily so a corpus score is reproducible"


def test_temperature_is_not_env_overridable(registered):
    """An env knob is a way to unpin the gate in the one place it matters.

    The output cap beside it IS env-tunable on purpose (it is a function of deployment
    throughput). The temperature is not: it backs an identity claim, so it is a constant
    in the module and reads the same in every environment.
    """
    assert sustainment_module.VISION_TEMPERATURE == 0

    src = Path(sustainment_module.__file__).read_text(encoding="utf-8")
    match = re.search(r"^VISION_TEMPERATURE\s*=\s*(.+)$", src, re.MULTILINE)
    assert match, "VISION_TEMPERATURE must be a module-level constant"
    assert "getenv" not in match.group(1) and "environ" not in match.group(1), \
        "VISION_TEMPERATURE must not be read from the environment"


def test_every_vision_call_site_passes_the_bounded_client():
    """One source of truth only holds if nothing bypasses it.

    `temperature` is set on the ClientRegistry, not in `baml_src/main.baml`, so a vision
    call made WITHOUT `baml_options` silently falls back to the declared `Vision` client -
    which has no temperature and samples. That regression would be invisible: the call
    still succeeds, still returns parts, and every test stubs it. So the call sites are
    asserted at the source level.
    """
    src = Path(sustainment_module.__file__).read_text(encoding="utf-8")

    vision_calls = re.findall(r"b\.(ExtractParts|LabelGridColumns)\((.*?)\)\n",
                              src, re.DOTALL)
    assert vision_calls, "expected to find the vision call sites"

    for name, args in vision_calls:
        assert "baml_options=" in args, \
            (f"b.{name} is called without baml_options, so it uses the declared Vision "
             f"client and SAMPLES - route it through _vision_call_opts()")
