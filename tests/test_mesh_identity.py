"""The svc:doc-tools credential seam (doc_tools/utils/mesh_identity).

This file exists because the module's own docstring claims testability is part of
its contract — "a credential seam nothing can exercise is a seam nothing can
seal" — while the engine-o half of it had no test at all. That gap is not
incidental to what went wrong: on 2026-10-06 the sandbox pod had been classifying
as caller:none for weeks because `KEYCLOAK_REALM_URL` was unset, and nothing
anywhere asserted what the helper does when it cannot mint.

The SDK is patched at `iagent_mesh.service_identity.mint_token`, which is where
both helpers import it from at call time, so these run with no Keycloak.
"""
from unittest.mock import patch

import pytest

from doc_tools.utils import mesh_identity as mi


@pytest.fixture(autouse=True)
def _creds(monkeypatch):
    monkeypatch.setenv(mi.CLIENT_SECRET_ENV, "s3cr3t")
    monkeypatch.delenv(mi.CLIENT_ID_ENV, raising=False)


def _mint_ok(**kw):
    return "tok"


def _mint_raises(exc):
    def _f(**kw):
        raise exc
    return _f


@pytest.mark.parametrize("helper", [mi.ontology_auth_headers, mi.stage_auth_headers])
def test_both_helpers_mint_the_same_identity(helper):
    """ONE REPO, ONE SERVICE IDENTITY — asserted on the arguments, not assumed."""
    with patch("iagent_mesh.service_identity.mint_token", side_effect=_mint_ok) as m:
        assert helper() == {"Authorization": "Bearer tok"}
    assert m.call_args.kwargs["client_id"] == mi.CLIENT_ID_DEFAULT
    assert m.call_args.kwargs["client_secret"] == "s3cr3t"


@pytest.mark.parametrize("helper", [mi.ontology_auth_headers, mi.stage_auth_headers])
def test_a_mint_failure_returns_none_and_never_raises(helper):
    """The refusal is the CALLER's to make; neither helper may raise.

    `ontology_auth_headers` used to return {"X-Auth-Status": ...} here, which the
    call site passed to requests.post — a header that engine-o accepts. The
    regression this pins is subtle in exactly the wrong way: returning a dict
    instead of None turns a refusal back into an anonymous POST without changing
    a single line at the call site.
    """
    with patch("iagent_mesh.service_identity.mint_token",
               side_effect=_mint_raises(KeyError(mi.REALM_URL_ENV))):
        assert helper() is None


def test_the_warning_names_the_variable_that_is_actually_missing(caplog):
    """A fixed remedy string is a guess wearing a diagnostic's authority.

    Both warnings used to end "configure DOC_TOOLS_CLIENT_SECRET" regardless of
    cause, which pointed an operator at the one variable the pod had set
    correctly while the KeyError printed two fields earlier said
    KEYCLOAK_REALM_URL.
    """
    with patch("iagent_mesh.service_identity.mint_token",
               side_effect=_mint_raises(KeyError(mi.REALM_URL_ENV))):
        with caplog.at_level("WARNING"):
            assert mi.ontology_auth_headers() is None

    msg = caplog.text
    assert mi.REALM_URL_ENV in msg
    assert f"{mi.CLIENT_SECRET_ENV} is unset" not in msg


def test_an_unknown_cause_admits_it_rather_than_naming_a_variable(caplog):
    """Keycloak unreachable is not a missing variable; say so."""
    with patch("iagent_mesh.service_identity.mint_token",
               side_effect=_mint_raises(RuntimeError("connection refused"))):
        with caplog.at_level("WARNING"):
            assert mi.stage_auth_headers() is None

    assert "connection refused" in caplog.text
    assert "is unset in this deployment" not in caplog.text


def test_client_id_is_overridable_but_defaults_to_this_service(monkeypatch):
    assert mi.client_id() == "iagent-doc-tools"
    monkeypatch.setenv(mi.CLIENT_ID_ENV, "other")
    assert mi.client_id() == "other"


# --------------------------------------------------------------------------- #
# publisher_auth_headers: the only helper that retries
# --------------------------------------------------------------------------- #
def test_the_publisher_recovers_from_a_transient_mint_failure():
    """Measured shape: 107 of 109 ticks minted, 2 did not.

    The publisher's PUT is the only thing that tells Lane 1's door what this
    image can ingest, so losing that ~2% means the door runs on whatever it was
    last told. The other two helpers do not retry on purpose, and that asymmetry
    is pinned in the test below.
    """
    calls = []
    slept = []

    def _flaky(**kw):
        calls.append(kw)
        if len(calls) < 3:
            raise RuntimeError("connection reset by peer")
        return "tok"

    with patch("iagent_mesh.service_identity.mint_token", side_effect=_flaky):
        headers = mi.publisher_auth_headers(attempts=3, backoff_s=0.0,
                                            sleep=slept.append)
    assert headers == {"Authorization": "Bearer tok"}
    assert len(calls) == 3
    assert len(slept) == 2, "one sleep between each pair of attempts, no more"


def test_exhausted_attempts_return_none_and_never_raise():
    with patch("iagent_mesh.service_identity.mint_token",
               side_effect=_mint_raises(RuntimeError("keycloak is down"))) as m:
        assert mi.publisher_auth_headers(attempts=3, backoff_s=0.0,
                                         sleep=lambda _s: None) is None
    assert m.call_count == 3


def test_a_missing_variable_is_not_retried():
    """`os.environ[...]` raising KeyError means the deployment is unconfigured.

    Three attempts at that is three identical failures and two pointless sleeps,
    and the sleeps are what make a sensor tick look hung.
    """
    slept = []
    with patch("iagent_mesh.service_identity.mint_token",
               side_effect=_mint_raises(KeyError(mi.REALM_URL_ENV))) as m:
        assert mi.publisher_auth_headers(attempts=3, backoff_s=0.0,
                                         sleep=slept.append) is None
    assert m.call_count == 1, "a KeyError is a configuration answer, not a blip"
    assert slept == []


def test_the_exhausted_warning_counts_attempts_made_not_configured(caplog):
    with caplog.at_level("WARNING"):
        with patch("iagent_mesh.service_identity.mint_token",
                   side_effect=_mint_raises(KeyError(mi.REALM_URL_ENV))):
            mi.publisher_auth_headers(attempts=3, backoff_s=0.0,
                                      sleep=lambda _s: None)
    # A log claiming three attempts after one would send a reader looking for two
    # failures that never happened.
    assert "after 1 attempt(s)" in caplog.text


def test_the_other_two_helpers_still_mint_exactly_once():
    """The asymmetry is deliberate, so it is asserted rather than left to drift.

    A stage POST is advisory telemetry about work that already happened and
    recurs on the next event; the engine-o classify raises Failure and dagster
    retries the run. Neither needs a retry here, and adding one to all three
    would make every unconfigured pod sleep through every call.
    """
    for helper in (mi.ontology_auth_headers, mi.stage_auth_headers):
        with patch("iagent_mesh.service_identity.mint_token",
                   side_effect=_mint_raises(RuntimeError("blip"))) as m:
            assert helper() is None
        assert m.call_count == 1, helper.__name__
