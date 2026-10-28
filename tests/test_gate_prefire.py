"""Guards for scripts/pcn_gate_prefire.py. No test invokes kubectl."""
import importlib.util
import pathlib

import pytest

pytestmark = pytest.mark.corpus_gate

_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "pcn_gate_prefire.py"
_spec = importlib.util.spec_from_file_location("pcn_gate_prefire", _PATH)
pf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pf)

HEX = "ab" * 32
DIGEST = f"sha256:{HEX}"
NEW = f"ghcr.io/x/y@{DIGEST}"
BRANCH = "corpus-gate/preroll-abababababab"
OVERRIDDEN = {"DOC_TOOLS_IMAGE", "PCN_GATE_IDENTITY_MODE",
              "PCN_GATE_PUBLISH_BRANCH", "PCN_GATE_EXPECT_IMAGE"}


def _job(containers=None):
    env = [
        {"name": "PYTHONUNBUFFERED", "value": "1"},
        {"name": "LLM_NUM_CTX", "value": "fake-ctx"},
        {"name": "PROMPT_SOURCE", "value": "fake-source"},
        {"name": "SOME_API_KEY", "value": "FAKE-PLACEHOLDER-NOT-A-SECRET"},
        {"name": "DOC_TOOLS_IMAGE", "value": "ghcr.io/x/y@sha256:" + "11" * 32},
        {"name": "PCN_GATE_EXPECT_IMAGE", "value": "old"},
        {"name": "PCN_GATE_PUBLISH_BRANCH", "value": "corpus-gate/nightly"},
    ]
    if containers is None:
        containers = [{"name": "corpus-gate", "image": "ghcr.io/x/y:old",
                       "env": env}]
    return {"spec": {"template": {"spec": {"containers": containers}}}}


def _env(job):
    return job["spec"]["template"]["spec"]["containers"][0]["env"]


def test_tag_only_is_refused_as_not_an_identity():
    with pytest.raises(pf.PrefireError, match="not an identity"):
        pf.require_digest("ghcr.io/x/y:latest")
    assert pf.main(["--image", "ghcr.io/x/y:latest"]) == 2


def test_both_reference_forms_yield_same_digest():
    assert pf.extract_digest(f"repo@{DIGEST}") == DIGEST
    assert pf.extract_digest(f"repo:tag@{DIGEST}") == DIGEST


def test_override_replaces_existing_entry():
    new, _ = pf.apply_overrides(_job(), NEW, BRANCH)
    for name in OVERRIDDEN:
        assert [e["name"] for e in _env(new)].count(name) == 1
    entry = [e for e in _env(new) if e["name"] == "DOC_TOOLS_IMAGE"][0]
    assert entry["value"] == NEW


def test_identity_mode_and_empty_expectation():
    new, _ = pf.apply_overrides(_job(), NEW, BRANCH)
    vals = {e["name"]: e["value"] for e in _env(new)}
    assert vals["PCN_GATE_IDENTITY_MODE"] == "pre_roll"
    assert vals["PCN_GATE_EXPECT_IMAGE"] == ""
    assert vals["PCN_GATE_PUBLISH_BRANCH"] == BRANCH
    assert new["spec"]["template"]["spec"]["containers"][0]["image"] == NEW


def test_unrelated_env_survives_by_name_and_value():
    old = _job()
    new, changes = pf.apply_overrides(old, NEW, BRANCH)
    got = {e["name"]: e["value"] for e in _env(new)}
    for e in _env(old):
        if e["name"] not in OVERRIDDEN:
            assert got[e["name"]] == e["value"]
    # the printed changes name no un-overridden env var
    assert not any("API_KEY" in f or "LLM_NUM_CTX" in f for f, _, _ in changes)
    # input was not mutated
    assert _env(old)[4]["value"].endswith("11" * 32)


@pytest.mark.parametrize("containers", [
    [],
    [{"name": "other", "image": "i"}],
    [{"name": "corpus-gate", "image": "i"}, {"name": "sidecar", "image": "j"}],
])
def test_container_list_must_be_exactly_corpus_gate(containers):
    with pytest.raises(pf.PrefireError):
        pf.apply_overrides(_job(containers), NEW, BRANCH)


def test_corroboration_has_three_states():
    assert pf.corroborate(DIGEST, f"docker-pullable://ghcr.io/x/y@{DIGEST}") == pf.MATCH
    other = "docker-pullable://ghcr.io/x/y@sha256:" + "cd" * 32
    assert pf.corroborate(DIGEST, other) == pf.MISMATCH
    assert pf.corroborate(DIGEST, "") == pf.UNPROVEN
    assert pf.corroborate(DIGEST, None) == pf.UNPROVEN
    assert len({pf.MATCH, pf.MISMATCH, pf.UNPROVEN}) == 3
