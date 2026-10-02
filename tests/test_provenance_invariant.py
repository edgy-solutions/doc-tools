"""ADR-0041 provenance as an invariant of the write path (ruling 2026-10-02).

*"DOMAINS_THAT_PERSIST_PROVENANCE = {SUSTAINMENT}: provenance persists for
every domain; it's an invariant of the write path, not an opt-in. 7f deletes
the set and the check."*

Deleting a guard is the easy half and the dangerous half: the guard existed
because unvetted content reaching Neo4j with no mark on it is
indistinguishable from vetted content. So these tests are mostly about the
SUPPLY — that the write path now stamps — and only one of them is about the
absence.

HOW THE WRITE IS OBSERVED. ``build_knowledge_graph``'s orchestration past the
parent-node MERGE is heavy I/O (Weaviate/LLM/Jena) left to integration tests,
the same posture ``tests/test_semantic_assets.py`` takes. But the parent MERGE
is reached with nothing but mocked resources, and it is a RECORDED CALL on the
Neo4j mock — so the assertions here read the actual Cypher and the actual
parameters, not a flag. The run is allowed to fail after that point; what it
raises downstream is not this test's business, and swallowing it is what keeps
the test about the stamp instead of about the mocks.
"""
import contextlib

import pytest
from unittest.mock import MagicMock
from dagster import build_asset_context

from doc_tools.config import IngestionConfig
from doc_tools.utils.provenance_stamp import (
    PARAM_PREFIX,
    PROVENANCE_FIELDS,
    provenance_params,
    provenance_set_fragment,
)

BUCKET = "processing-artifacts"

_BLOCK = {
    "obtained_via": "user-drop",
    "authoritative_source": "user-upload",
    "as_of": "unknown",
    "ingested_at": "2026-10-02T00:00:00+00:00",
    "ingest_run": "run-1",
    "standing": "unverified",
    # derived_from deliberately ABSENT — the "" default is a load-bearing
    # behaviour (a Cypher null would drop the property), so one field is left
    # out of every fixture here on purpose.
    "ingest_id": "sha256:" + "a" * 64,
}


def _config():
    return IngestionConfig(
        graph_node_label="WorkInstruction",
        graph_child_label="Page",
        vector_collection_name="DocumentChunk",
        bucket=BUCKET,
    )


def _manifest(domain_type, *, provenance=_BLOCK, content_kind=None):
    metadata = {"domain_type": domain_type}
    if content_kind:
        metadata["content_kind"] = content_kind
    m = {"doc_id": "doc-1", "text_location": "x/text.json", "metadata": metadata}
    if provenance is not None:
        m["provenance"] = provenance
    return m


def parent_write(manifest, *, neo4j=None):
    """Drive the asset and return the FIRST recorded Cypher write (the parent
    MERGE), as ``(query, params)``.

    Returns ``None`` if no write was recorded — which is itself an assertable
    outcome (see the origin-unresolved test).
    """
    from doc_tools.assets.semantic_assets import build_knowledge_graph

    neo4j = neo4j or MagicMock()
    with contextlib.suppress(Exception):
        build_knowledge_graph(
            build_asset_context(), _config(), manifest,
            s3=MagicMock(), neo4j=neo4j, weaviate=MagicMock(),
            llm=MagicMock(), jena=MagicMock(),
        )
    calls = neo4j.get_client.return_value.execute_query.call_args_list
    if not calls:
        return None
    return calls[0].args[0], calls[0].args[1]


# --------------------------------------------------------------------------- #
# 1. The helper's two contracts
# --------------------------------------------------------------------------- #
def test_the_fragment_parameterises_every_value():
    """AGENTS.md §Safety Guardrails: bounded f-strings, parameterise the rest.

    The fragment interpolates only the alias and the property names (both
    module constants); every VALUE is a ``$``-parameter. Asserted by the
    absence of any quote character in the generated Cypher — a literal value
    could not be written without one.
    """
    fragment = provenance_set_fragment("n")
    assert "'" not in fragment and '"' not in fragment, fragment
    for field in PROVENANCE_FIELDS:
        assert f"n.provenance_{field} = ${PARAM_PREFIX}{field}" in fragment


def test_an_absent_field_binds_empty_string_not_none():
    """A Cypher null DROPS the property, which would collapse "this optional
    field was absent from the block" into "this document was never stamped" —
    and telling those apart is the whole purpose of the stamp. ``derived_from``
    is absent from ``_BLOCK``; it must still bind."""
    params = provenance_params(_BLOCK)
    assert params[f"{PARAM_PREFIX}derived_from"] == ""
    assert None not in params.values()
    assert len(params) == len(PROVENANCE_FIELDS)


# --------------------------------------------------------------------------- #
# 2. THE INVARIANT: a domain whose plugin persists nothing is still stamped
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("domain_type,label", [
    ("maintenance", "MAINTENANCE"),
    ("training", "TRAINING"),
    ("compliance", "COMPLIANCE"),
    ("sustainment", "SUSTAINMENT"),
])
def test_every_domain_gets_the_stamp_on_the_document_node(domain_type, label):
    """The ruling, at the only site that runs for every domain.

    Three of these four domains used to HALT here with
    ``ProvenanceNotPersistableError`` — their plugins' ``to_graph_queries()``
    do not write a provenance block and still do not. That is exactly why the
    stamp moved OUT of the plugins and onto the parent-document MERGE: one
    implementation, no per-domain opt-in, and no domain that can be added to
    the pipeline without inheriting it.
    """
    write = parent_write(_manifest(domain_type))
    assert write is not None, "no Cypher write was recorded at all"
    query, params = write
    assert f":{label} {{id: $id}}" in query, query
    for field in PROVENANCE_FIELDS:
        assert f"n.provenance_{field}" in query, field
    assert params[f"{PARAM_PREFIX}obtained_via"] == "user-drop"
    assert params[f"{PARAM_PREFIX}standing"] == "unverified"
    assert params["id"] == "doc-1"


def test_a_vetted_document_is_not_stamped_at_all():
    """The stamp is not a column every document grows an empty version of.

    No provenance block means no ``provenance_*`` properties — not eight empty
    strings. An empty-string stamp on a vetted document would make
    "arrived through the vetted path" and "arrived unvetted, fields unknown"
    the same shape in the graph, which is the distinction this whole mechanism
    exists to keep.
    """
    write = parent_write(_manifest("maintenance", provenance=None))
    assert write is not None
    query, params = write
    assert "provenance_" not in query, query
    assert not any(k.startswith(PARAM_PREFIX) for k in params), params


def test_a_failed_stamp_halts_while_a_failed_vetted_write_only_logs():
    """The error-policy split, which is the piece that replaces the guard.

    The parent MERGE was best-effort: it logged and continued. Left that way,
    a provenance-bearing document whose stamp errored would proceed through
    every later write and land in the graph wearing no mark — the exact harm
    the deleted check prevented, reached by a different route. So the write is
    load-bearing when, and only when, it carries a stamp.
    """
    from doc_tools.assets.semantic_assets import (
        build_knowledge_graph, ProvenanceStampFailedError,
    )

    def _run(manifest):
        neo4j = MagicMock()
        neo4j.get_client.return_value.execute_query.side_effect = RuntimeError(
            "neo4j is down"
        )
        return build_knowledge_graph(
            build_asset_context(), _config(), manifest,
            s3=MagicMock(), neo4j=neo4j, weaviate=MagicMock(),
            llm=MagicMock(), jena=MagicMock(),
        )

    with pytest.raises(ProvenanceStampFailedError, match="doc-1"):
        _run(_manifest("maintenance"))

    # The vetted document does NOT raise ProvenanceStampFailedError for the
    # same failing write. It carries on and fails (or not) somewhere else —
    # what matters is that it is not THIS refusal.
    with contextlib.suppress(Exception):
        _run(_manifest("maintenance", provenance=None))
    with pytest.raises(ProvenanceStampFailedError):
        _run(_manifest("maintenance"))


# --------------------------------------------------------------------------- #
# 3. The two spellings of the same eight properties cannot drift
# --------------------------------------------------------------------------- #
def test_sustainment_stamp_uses_the_same_property_names():
    """``SustainmentPlugin`` keeps its OWN stamp, on its own notice node, and
    that is deliberate: the parent-document node and the
    ``:SustainmentNotice`` node are different nodes, and the notice node is
    what the PCN consumers read. But two stamps mean two spellings of eight
    property names, so the set is pinned in one place and this test is what
    stops them drifting silently.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    src = (root / "doc_tools/plugins/sustainment.py").read_text(encoding="utf-8")
    found = re.findall(r"n\.provenance_([a-z_]+) = \$", src)
    assert tuple(found) == PROVENANCE_FIELDS, (
        f"sustainment.py stamps {found}, provenance_stamp.py declares "
        f"{list(PROVENANCE_FIELDS)}"
    )


def test_the_deleted_set_and_check_are_gone_from_the_source():
    """Pinned by absence, because the ruling is a deletion.

    A re-introduced frozenset would not fail any behavioural test here — the
    stamp would still be written for sustainment, and the halt would simply
    come back for everyone else. So the name itself is asserted absent.
    """
    from pathlib import Path

    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    gone = {"DOMAINS_THAT_PERSIST_PROVENANCE", "ProvenanceNotPersistableError"}
    for rel in ("doc_tools/assets/semantic_assets.py",
                "doc_tools/components/document_parser.py"):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        # Identifiers as CODE, via the AST — not a substring scan. Both names
        # are still written in prose in both files (the comments explain what
        # was deleted and why, which is the part a future reader needs), and a
        # substring check cannot tell an explanation from a resurrection.
        used = {
            n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
        } | {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        } | {
            n.name for n in ast.walk(tree)
            if isinstance(n, (ast.ClassDef, ast.FunctionDef))
        }
        assert not (used & gone), f"{rel} still uses {sorted(used & gone)}"
