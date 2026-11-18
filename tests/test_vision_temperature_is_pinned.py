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

    vision_calls = re.findall(r"b\.(ExtractParts|LabelGridColumns|ReadRegion)\((.*?)\)\n",
                              src, re.DOTALL)
    assert vision_calls, "expected to find the vision call sites"

    for name, args in vision_calls:
        assert "baml_options=" in args, \
            (f"b.{name} is called without baml_options, so it uses the declared Vision "
             f"client and SAMPLES - route it through _vision_call_opts()")


# --- The seed, 2026-11-17 -----------------------------------------------------
# Temperature pinned the parts pass. It did NOT pin the region witness, and that
# call is the one that decides a written `mfr` on a degraded text layer: the value
# is published only if `ReadRegion` corroborates it. TYC wrote
# `TE Connectivity | null | TE Connectivity` across three fires from identical raw
# text-layer input, so the deciding call was the last unpinned sampling path in the
# repo while `_header_call_opts` next door set temperature AND seed.


def test_the_vision_client_is_registered_with_a_seed(registered):
    """Asserted on the value that reaches the provider, like the temperature above."""
    options = registered.clients["VisionBounded"]["options"]
    assert "seed" in options, \
        ("no seed means the region witness samples freely, and a written `mfr` turns "
         "on which answer one call happened to draw")
    assert options["seed"] == 0


def test_the_seed_is_a_top_level_request_parameter(registered):
    """`seed` is a standard OpenAI-compatible REQUEST field, not an Ollama `options`
    knob. Nested under `options` it is dropped silently by this provider -- the same
    way `num_ctx` is inert on a `/v1` endpoint -- and the call would keep sampling
    while the registration looked pinned."""
    options = registered.clients["VisionBounded"]["options"]
    nested = options.get("options")
    assert not (isinstance(nested, dict) and "seed" in nested), \
        "a nested seed is dropped by the provider: set it at the top level"


def test_the_seed_is_not_env_overridable(registered):
    """Same reasoning as the temperature: it backs a reproducibility claim, so it
    reads the same in every environment."""
    assert sustainment_module.VISION_SEED == 0

    src = Path(sustainment_module.__file__).read_text(encoding="utf-8")
    match = re.search(r"^VISION_SEED\s*=\s*(.+)$", src, re.MULTILINE)
    assert match, "VISION_SEED must be a module-level constant"
    assert "getenv" not in match.group(1) and "environ" not in match.group(1), \
        "VISION_SEED must not be read from the environment"
