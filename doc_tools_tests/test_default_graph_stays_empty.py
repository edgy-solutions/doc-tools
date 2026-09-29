"""Seal: the Jena default graph is empty after an ingest.

``JenaOntologyWriter.upsert()`` (iagent-mesh SDK @8e4a881, this branch) takes
``graph`` as a required keyword argument and wraps BOTH the delete and the
insert half of its update in ``GRAPH <graph>`` — there is no code path that
skips it. That closes the write side. This file proves the *outcome* against
a real Fuseki: after driving the real ingest shape for all four
SPARQL-emitting plugins through the writer, nothing lands in Jena's true
default graph, where the mesh resolver (engine-o, which scopes every read to
the per-domain named graphs) cannot see it.

THE TRAP THIS FILE IS WRITTEN AROUND. No CI job has ever had a live Fuseki,
and every test in ``test_plugin_sparql_integration.py`` past line 307 skips
the whole live tier unless ``JENA_INTEGRATION_URL`` is set. A test added
there — or here, without a guard — would be grey in CI and read as a pass:
exactly the "check that exists, is honest, and gates nothing" failure this
lane (PR #21, the helm guard) already fixed once for a different fixture.
``REQUIRE_JENA`` closes the same hole for this one: unset, a workstation
without Docker/Fuseki legitimately skips; set (as CI now does), a missing
Fuseki is a FAILURE, not a skip.

Run locally against a real Fuseki:

  docker run --rm -p 3030:3030 -e ADMIN_PASSWORD=test -e FUSEKI_DATASET_1=ds \\
      stain/jena-fuseki:5.1.0

  JENA_INTEGRATION_URL=http://localhost:3030 \\
  JENA_INTEGRATION_DS=ds \\
  JENA_INTEGRATION_USER=admin \\
  JENA_INTEGRATION_PASSWORD=test \\
  pytest doc_tools_tests/test_default_graph_stays_empty.py -v
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest

from doc_tools_tests.test_plugin_sparql_integration import (
    _FakeConfig,
    _build_compliance_node,
    _build_maintenance_node,
    _build_manufacturing_node,
    _build_sustainment_node,
)

# Set by the `tests` job in .github/workflows/build-container.yml once the
# Fuseki service container is wired up. Anywhere it is set, a missing Fuseki
# is a BUG IN THE ENVIRONMENT, not a reason to pass — mirrors REQUIRE_HELM
# in tests/test_chart_image_pin_guard.py.
REQUIRE_JENA = os.environ.get("REQUIRE_JENA") == "1"

# The true default graph, as ARQ names it explicitly. Deliberately NOT a bare
# `WHERE { ?s ?p ?o }`: under a TDB2 dataset configured with
# `unionDefaultGraph`, a bare pattern with no GRAPH clause returns the union
# of every named graph, not the default graph alone — so it would report
# nonzero for entirely correctly-scoped data and the seal would be both
# meaningless (it wouldn't isolate the default graph) and falsely red. Named
# explicitly, this always means the one graph nothing should ever land in.
_SEAL_QUERY = (
    "SELECT (COUNT(*) AS ?c) WHERE { GRAPH <urn:x-arq:DefaultGraph> { ?s ?p ?o } }"
)


def _require_or_skip_jena():
    if os.environ.get("JENA_INTEGRATION_URL"):
        return
    if REQUIRE_JENA:
        pytest.fail(
            "REQUIRE_JENA=1 but JENA_INTEGRATION_URL is unset. The "
            "default-graph seal (and the four live-Fuseki tests in "
            "test_plugin_sparql_integration.py) would SKIP and this job "
            "would stay GREEN over an unproven guard. Restore the Fuseki "
            "service container in the `tests` job of "
            ".github/workflows/build-container.yml, or unset REQUIRE_JENA "
            "and accept that the default-graph seal is unproven in CI."
        )
    pytest.skip(
        "set JENA_INTEGRATION_URL (+ DS, USER, PASSWORD) to run the "
        "live-Jena default-graph seal; a local run may legitimately lack "
        "Docker/Fuseki"
    )


def _count(client, sparql: str) -> int:
    result = client.execute_query(sparql)
    return int(result["results"]["bindings"][0]["c"]["value"])


def test_default_graph_has_zero_triples_after_an_ingest():
    """Drive all four plugins' real SPARQL through the real writer, then
    prove the default graph is empty — with a positive control (something
    was actually written) and a negative control (the seal query can in
    fact see a nonzero default graph, so a 0 later is meaningful) bracketing
    the assertion that matters.
    """
    _require_or_skip_jena()
    from doc_tools.utils.jena_client import JenaClient
    from iagent_mesh.interfaces import Initiator
    from iagent_mesh.writers.jena import JenaOntologyWriter

    url = os.environ["JENA_INTEGRATION_URL"]
    dataset = os.environ.get("JENA_INTEGRATION_DS", "ds")
    username = os.environ.get("JENA_INTEGRATION_USER", "admin")
    password = os.environ.get("JENA_INTEGRATION_PASSWORD", "")

    # Reads still go through JenaClient (execute_query, unaffected by this
    # migration). Writes go through JenaOntologyWriter — see the module
    # docstring; NOTE it posts unauthenticated (no username/password param
    # exists on its constructor), unlike JenaClient.execute_update before it.
    client = JenaClient(url=url, dataset=dataset, username=username, password=password)
    writer = JenaOntologyWriter(base_url=url, dataset=dataset)
    initiator = Initiator(
        subject="test_default_graph_stays_empty", kind="delegate", on_behalf_of="doc-tools-tests"
    )

    # Unique per run so repeat runs (and parallel CI runs) don't collide.
    doc_id = f"SEAL-DEFAULT-GRAPH-{uuid.uuid4()}"
    builders = [
        _build_maintenance_node,
        _build_manufacturing_node,
        _build_compliance_node,
        _build_sustainment_node,
    ]

    written_graphs: set[str] = set()
    try:
        # ------------------------------------------------------------
        # 1. Drive the real ingest shape for every SPARQL-emitting plugin.
        # ------------------------------------------------------------
        for builder in builders:
            plugin, node = builder()
            _, sparql_batches = plugin.to_graph_queries(
                [node], _FakeConfig(), doc_id=doc_id, image_prefix=""
            )
            assert sparql_batches, f"{plugin.domain_label} plugin produced no SPARQL"
            for i, batch in enumerate(sparql_batches):
                written_graphs.add(batch["graph"])
                result = writer.upsert(
                    initiator, graph=batch["graph"], iri=batch["iri"], triples=batch["triples"]
                )
                assert result.applied, (
                    f"{plugin.domain_label} upsert #{i} against live Fuseki did not "
                    f"apply: outcome={result.outcome!r} detail={result.detail!r}"
                )

        # ------------------------------------------------------------
        # 2. Positive control — asserted BEFORE the seal. Without this,
        #    "the default graph is empty" is trivially satisfied by having
        #    written nothing at all, and the seal would pass on a total
        #    failure to write.
        # ------------------------------------------------------------
        #    Counted PER GRAPH THIS TEST WROTE, not across `GRAPH ?g`: a
        #    dataset left dirty by an earlier run would satisfy a global
        #    count without this run having written anything at all.
        for graph_uri in sorted(written_graphs):
            n = _count(
                client,
                "SELECT (COUNT(*) AS ?c) WHERE { GRAPH <%s> { ?s ?p ?o } }"
                % graph_uri,
            )
            assert n > 0, (
                f"positive control failed: <{graph_uri}> holds zero triples "
                "after driving its plugin — that ingest wrote nothing, so a "
                "later '0' from the seal query would prove nothing about it"
            )

        # ------------------------------------------------------------
        # 3. The seal.
        # ------------------------------------------------------------
        assert _count(client, _SEAL_QUERY) == 0, (
            "the Jena default graph is NOT empty after driving all four "
            "plugins' real to_graph_queries() output through "
            "JenaOntologyWriter.upsert() — something landed unscoped, where "
            "the mesh resolver cannot see it"
        )

        # ------------------------------------------------------------
        # 4. Negative control, in the same test. A COUNT that cannot see
        #    the default graph returns 0 forever and would make the seal
        #    vacuous — prove the query genuinely can observe a nonzero
        #    default graph by writing straight to it, bypassing the
        #    scoping writer entirely (direct httpx, not JenaClient).
        # ------------------------------------------------------------
        update_url = f"{url.rstrip('/')}/{dataset}/update"
        auth = (username, password) if (username and password) else None
        probe_insert = 'INSERT DATA { <urn:probe:7f> <urn:probe:p> "x" }'
        probe_delete = 'DELETE DATA { <urn:probe:7f> <urn:probe:p> "x" }'
        try:
            resp = httpx.post(
                update_url,
                content=probe_insert.encode("utf-8"),
                headers={"Content-Type": "application/sparql-update"},
                auth=auth,
                verify=False,
            )
            resp.raise_for_status()

            assert _count(client, _SEAL_QUERY) == 1, (
                "negative control failed: after inserting one triple with "
                "no GRAPH clause (bypassing JenaClient), the seal query "
                "still reports 0 — it cannot see the true default graph at "
                "all, which would make the '0' assertion above vacuous"
            )
        finally:
            del_resp = httpx.post(
                update_url,
                content=probe_delete.encode("utf-8"),
                headers={"Content-Type": "application/sparql-update"},
                auth=auth,
                verify=False,
            )
            del_resp.raise_for_status()

        assert _count(client, _SEAL_QUERY) == 0, (
            "probe cleanup failed: the default graph still reports a "
            "triple after DELETE DATA of the negative-control probe"
        )
    finally:
        # ------------------------------------------------------------
        # 5. Clean up only the _INSTANCES graphs THIS test created, so
        #    repeat runs don't accumulate. JenaClient.execute_update no
        #    longer exists (deleted with the old write path) — drop via
        #    direct httpx, exactly like the negative control's probe
        #    insert/delete above.
        # ------------------------------------------------------------
        update_url = f"{url.rstrip('/')}/{dataset}/update"
        auth = (username, password) if (username and password) else None
        for graph_uri in written_graphs:
            try:
                resp = httpx.post(
                    update_url,
                    content=f"DROP GRAPH <{graph_uri}>".encode("utf-8"),
                    headers={"Content-Type": "application/sparql-update"},
                    auth=auth,
                    verify=False,
                )
                resp.raise_for_status()
            except Exception:
                pass
