"""The iagent-mesh pin guard: the two symbols doc-tools actually consumes, and the
import posture the pin exists to protect.

WHY THIS FILE EXISTS. `iagent-mesh` is pinned to a TAG in pyproject.toml, and the
long comment above that pin is a *census* of the consumed surface — one symbol at
v0.9.1, two at v0.9.5. A census is a claim about the installed package, and the
only thing that can hold it true across a bump is a test that imports the package
and looks. Reading the SDK's source on GitHub cannot: what ships in our image is
the resolved wheel, not the tree we read.

The specific failure this guards is NOT hypothetical. At v0.9.0,
`iagent_mesh/__init__.py` reached `transport_auth.py`, which did an UNGUARDED
`from fastapi import HTTPException, Request` — so `import iagent_mesh` raised
unless a web framework happened to be installed. doc-tools imports no web
framework, and the symbol it needs sits behind that same `__init__`. v0.9.1 moved
the guard inside `transport_auth`, and v0.9.3 moved fastapi/uvicorn out of the
SDK's hard dependencies into a `[server]` extra. Both of those are *absences*,
and an absence is only observable by exercising it.

These tests DO NOT skip when `iagent_mesh` is missing. It is a declared hard
dependency; its absence means the install is broken, which is a failure and not a
reason to pass quietly. A guard that skips itself into silence is how a claim
outlives the thing it described.
"""

import importlib.metadata as md

import pytest


def test_import_does_not_need_a_web_framework():
    """`import iagent_mesh` must work on its own. This is the v0.9.0 regression."""
    import iagent_mesh  # noqa: F401 — importing IS the assertion


def test_fastapi_and_uvicorn_are_not_hard_requirements():
    """They must stay extras-only, so our install never silently depends on a web
    framework. Any `fastapi`/`uvicorn` requirement WITHOUT an `extra == ...`
    marker is a hard one and fails here."""
    hard = [
        req for req in (md.requires("iagent-mesh") or [])
        if ("fastapi" in req or "uvicorn" in req) and "extra ==" not in req
    ]
    assert hard == [], (
        "iagent-mesh now requires a web framework unconditionally: %r. doc-tools "
        "imports neither; if this is intended, the pin census in pyproject.toml "
        "has to say so." % hard
    )


def test_mint_token_is_importable():
    """Consumed symbol #1, by `doc_tools/utils/mesh_identity.py`. Its own import
    site is inside a try/except that LOGS AND PROCEEDS, so a move there would not
    raise in production — it would downgrade auth quietly. Hence an explicit
    assertion here."""
    from iagent_mesh.service_identity import mint_token
    assert callable(mint_token)


def test_provenance_block_is_importable_with_the_user_drop_rung():
    """Consumed symbol #2, needed by the ingress-user sensor stamp. v0.9.5 is the
    FLOOR for that work: on v0.9.1 `iagent_mesh.provenance` does not exist."""
    from iagent_mesh.provenance import OBTAINED_VIA, USER_DROP, ProvenanceBlock

    assert ProvenanceBlock.model_fields["obtained_via"] is not None
    assert USER_DROP == "user-drop"
    assert USER_DROP in OBTAINED_VIA, (
        "the user-drop rung is what the ingress-user stamp writes; without it in "
        "OBTAINED_VIA the block cannot be constructed"
    )


def test_a_user_drop_block_constructs_and_round_trips():
    """The stamp the ingress-user sensor will write, built against the real model
    rather than a local copy of its field list."""
    from iagent_mesh.provenance import USER_DROP, ProvenanceBlock

    block = ProvenanceBlock(
        authoritative_source="user-upload",
        obtained_via=USER_DROP,
        as_of="2026-09-30",
        ingested_at="2026-09-30T00:00:00Z",
        ingest_run="run-1",
        standing="unverified",
    )
    assert block.obtained_via == USER_DROP
    assert block.as_dict()["obtained_via"] == "user-drop"
    # derived_from/ingest_id are optional and must stay out of the wire shape when unset
    assert "derived_from" not in block.as_dict()


def test_an_unknown_rung_is_refused():
    """Pins the rejection, so a typo in the stamp fails loudly at construction
    instead of landing an unscoreable path in the graph."""
    from iagent_mesh.provenance import ProvenanceBlock

    with pytest.raises(Exception):
        ProvenanceBlock(
            authoritative_source="user-upload",
            obtained_via="user_drop",  # underscore, not the hyphen the rung uses
            as_of="2026-09-30",
            ingested_at="2026-09-30T00:00:00Z",
            ingest_run="run-1",
            standing="unverified",
        )
