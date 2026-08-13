"""doc-tools' one platform-facing call mints as svc:doc-tools, and never breaks if it can't.

WHY THIS FILE EXISTS. `assets/semantic_linker.py` holds the ONLY call from this repo to a
platform service — engine-o `POST /classify_legacy_table`. That was established by enumerating
every configured endpoint in doc-tools (DATAHUB_GMS_URL, JENA_URL, WEAVIATE_*, S3_ENDPOINT_URL,
LLM_BASE_URL, OPENAI_BASE_URL, VISION_LLM_BASE_URL, SQLSERVER_HOST, ORACLE_HOST,
RABBITMQ_GIT_REPO_URL, DDS_GIT_REPO_URL) and finding exactly one platform service among them —
not by grepping call sites and hoping enough were run.

It was the LAST KNOWN BLOCKER for the platform's REQUIRE_TRANSPORT_AUTH flip: unminted, with
`raise_for_status()` on the next line, so under REQUIRE the asset fails rather than degrading.

TWO PROPERTIES ARE PINNED, and the second is what makes shipping this safe:

1. The call carries a credential minted as **svc:doc-tools** — its own identity, not a borrowed
   one. Reusing engine-a's or the supervisor's would be the `mint_service_token()` defect
   committed deliberately instead of by accident.
2. A mint failure **logs and proceeds**, never raises. Engine-o accepts unauthenticated callers
   today (transport auth defaults to OBSERVE), so attaching a credential where none was sent is
   behaviourally inert — and an asset that works today must not start failing because Keycloak
   blipped or a chart value has not landed. When REQUIRE flips, the same failure becomes a 401
   at engine-o, which is the right moment for it to become loud.

THE SEAM IS IN `utils/mesh_identity.py` SO THESE PINS CAN ACTUALLY RUN. Defined inside the asset
module they could only execute where dagster + dagster_aws + datahub all install, and would have
SKIPPED everywhere else — pins that pass by vacuum in exactly the environments that matter least.
Extracting it is testability as a contract, not tidiness.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_ASSET = _ROOT / "doc_tools" / "assets" / "semantic_linker.py"
_SEAM = _ROOT / "doc_tools" / "utils" / "mesh_identity.py"


def _asset_src() -> str:
    return _ASSET.read_text(encoding="utf-8")


def _seam_src() -> str:
    return _SEAM.read_text(encoding="utf-8")


def _code_only(src: str) -> str:
    """Strip docstrings and comments, leaving executable code.

    WHY THIS EXISTS, and it is the same lesson as the platform guard's allowlist: a check that
    cannot tell a LIVE REFERENCE from a DESCRIPTION of one fails on its own documentation. Both
    the seam and this file name `mint_service_token` while explaining why nothing may use it —
    a naive substring ban would forbid explaining the defect it exists to prevent, and a guard
    that punishes documentation gets relaxed until it means nothing.
    """
    import ast
    tree = ast.parse(src)
    for node in ast.walk(tree):
        # Blank out docstring expressions in place of deleting them (keeps line numbers sane).
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body[0].value.value = ""
    stripped = ast.unparse(tree)  # comments are dropped by the parser
    return stripped


# ---------------------------------------------------------------------------
# Source pins — hold even where the dagster stack cannot be imported
# ---------------------------------------------------------------------------
def test_the_engine_o_call_carries_headers():
    """The regression that matters: an edit dropping `headers=` restores the flip blocker."""
    m = re.search(r"requests\.post\(\s*f?\"\{ONTOLOGY_SVC_URL\}/classify_legacy_table\".*?\n\s*\)",
                  _asset_src(), re.S)
    assert m, "the classify_legacy_table call site moved or changed shape"
    assert "headers=" in m.group(0), (
        "the engine-o call lost its credential — this is the last known REQUIRE flip blocker"
    )


def test_it_mints_as_its_OWN_identity():
    assert "iagent-doc-tools" in _seam_src(), "the call must mint as svc:doc-tools"
    src = _code_only(_seam_src())  # prose may NAME the defect; code may not commit it
    for borrowed in ("iagent-engine-a", "iagent-supervisor", "iagent-review-starter",
                     "mint_service_token"):
        assert borrowed not in src, (
            f"doc-tools reaches for {borrowed!r} — borrowing another service's identity is the "
            f"general-name-over-specific-behaviour defect, committed deliberately"
        )


def test_it_consumes_the_SHARED_mint_not_a_local_one():
    """ONE IMPLEMENTATION. A second client-credentials body here would drift from the platform's
    exactly the way the SDK's and the platform's already did once."""
    assert "from iagent_mesh.service_identity import mint_token" in _seam_src()
    src = _code_only(_seam_src())
    for stray in ("grant_type", "access_token", "httpx.post"):
        assert stray not in src, (
            f"inline mint body survives ({stray!r}) — that is a second implementation"
        )


def test_the_legacy_DNS_default_is_GONE():
    """The offender the platform's phantom-scope guard predicted but could not see: `doc-tools`
    was declared in its SCANNED_DIRS and never walked, because it is a SIBLING REPO."""
    m = re.search(r"^ONTOLOGY_SVC_URL\s*=\s*os\.getenv\([^)]*\)", _asset_src(), re.M)
    assert m, "the ONTOLOGY_SVC_URL assignment moved — this pin is measuring nothing"

    # THE LIVE DEFAULT ONLY, not the whole file. The comment above that assignment NAMES the
    # forbidden pattern while explaining it, and a file-wide check would fail on its own
    # documentation — the same reason the platform's guard carries a narrow allowlist keyed on
    # (path, line-substring) rather than banning the string outright. A guard that cannot tell a
    # live default from a description of one gets relaxed until it means nothing.
    assert ".default.svc.cluster.local" not in m.group(0), (
        "legacy DNS returned in the LIVE DEFAULT — it does not resolve in the current cluster, "
        "so an unset ONTOLOGY_SERVICE_URL points every classify call at a non-existent host"
    )
    assert "iagent-engine-o" in m.group(0)


# ---------------------------------------------------------------------------
# Behavioural — the seam imports with nothing but os + the SDK, so these RUN
# ---------------------------------------------------------------------------
def _load_seam():
    """Load `mesh_identity` BY PATH, bypassing the package `__init__`.

    `doc_tools/__init__.py` eagerly does `from .definitions import defs`, which imports
    dagster_aws — so *any* `doc_tools.*` import drags the entire orchestration stack in, and
    these pins would skip wherever it is not installed. That is the pass-by-vacuum this file's
    header refuses.

    Loading by path is legitimate here precisely BECAUSE the seam is a true leaf: it imports
    `logging`, `os`, `typing`, and (lazily, inside the function) the mesh SDK. Nothing from its
    own package. If that ever stops being true this will fail loudly rather than quietly skip,
    which is the right direction to fail.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("_doc_tools_mesh_identity", _SEAM)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mi = _load_seam()  # noqa: E402 — after the source pins above


def test_a_mint_failure_LOGS_AND_PROCEEDS(monkeypatch, caplog):
    """THE PIN THAT MAKES THIS SAFE TO SHIP. "No secret configured" is the state of every
    deployment until the chart value lands, and it must not break a working asset."""
    monkeypatch.delenv(mi.CLIENT_SECRET_ENV, raising=False)

    with caplog.at_level(logging.WARNING, logger="doc_tools.utils.mesh_identity"):
        headers = mi.ontology_auth_headers()

    assert "Authorization" not in headers, "no credential may be fabricated"
    assert headers.get("X-Auth-Status", "").startswith("mint-failed:"), (
        "a mint FAILURE must be distinguishable from a caller that never minted"
    )
    assert any("UNAUTHENTICATED" in m for m in caplog.messages)


def test_it_fails_LOCALLY_before_opening_a_socket(monkeypatch):
    """`os.environ[...]` is evaluated BEFORE mint_token is entered, so an unconfigured
    deployment never reaches Keycloak — and this suite never makes a real network call."""
    monkeypatch.delenv(mi.CLIENT_SECRET_ENV, raising=False)

    import iagent_mesh.service_identity as si

    def _boom(*a, **k):
        raise AssertionError("mint_token was entered despite no secret being configured")

    monkeypatch.setattr(si, "mint_token", _boom)
    assert "Authorization" not in mi.ontology_auth_headers()


def test_a_successful_mint_produces_a_bearer(monkeypatch):
    monkeypatch.setenv(mi.CLIENT_SECRET_ENV, "s3cret")
    import iagent_mesh.service_identity as si
    seen = {}

    def _mint(*, client_id, client_secret, **kw):
        seen["client_id"] = client_id
        seen["client_secret"] = client_secret
        return "tok-doc-tools"

    monkeypatch.setattr(si, "mint_token", _mint)
    headers = mi.ontology_auth_headers()

    assert headers["Authorization"] == "Bearer tok-doc-tools"
    assert seen["client_id"] == "iagent-doc-tools", "the identity must be named, not inferred"
    assert seen["client_secret"] == "s3cret"


def test_the_client_id_is_overridable_per_deployment(monkeypatch):
    """Work and sandbox may name the client differently; the default must not be the only path."""
    monkeypatch.setenv(mi.CLIENT_ID_ENV, "work-doc-tools")
    assert mi.client_id() == "work-doc-tools"
