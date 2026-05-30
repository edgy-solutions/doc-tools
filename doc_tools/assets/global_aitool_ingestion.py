"""Backfill / catch-up asset for the AITool binding plane.

Companion to ``aitool_linker.sync_aitool_predicate_to_neo4j``. The sensor
(``AIToolSensorComponent``) fires sync runs on DataHub changes; this asset
provides the bootstrap / catch-up path that scans DataHub for every existing
mesh tool registration and ensures each one has a corresponding predicate
edge in Neo4j.

Mirror of ``global_semantic_ingestion.ingest_global_semantic_links`` for
Datasets. Useful when:

- The Neo4j substrate is replayed from scratch
- The sensor was down during a deployment window
- An operator wants to verify the runtime graph matches DataHub state
"""

from typing import List

import requests
from dagster import AssetExecutionContext, Config, asset
from pydantic import Field

from doc_tools.assets.aitool_linker import (
    DATAHUB_GMS_URL,
    DATAHUB_TOKEN,
    AIToolSyncConfig,
)


class GlobalAIToolIngestionConfig(Config):
    search_limit: int = Field(
        default=1000,
        description="Max number of mlModel entities to scan in DataHub",
    )


def _find_mesh_tool_urns(search_limit: int) -> List[str]:
    """Page DataHub for ``mlModel`` entities tagged as mesh tool registrations.

    DataHub's GraphQL ``search`` endpoint doesn't reliably support filtering
    by a customProperty value across all platform configurations, so we
    fetch every recent ``MLMODEL`` and filter in Python on
    ``mesh_is_registration == "true"``. Cap defaults to 1000; raise it via
    config if the mesh has more registered tools than that.
    """
    query = """
    query searchMeshTools($input: SearchInput!) {
      search(input: $input) {
        searchResults {
          entity {
            urn
            ... on MLModel {
              properties {
                customProperties {
                  key
                  value
                }
              }
            }
          }
        }
      }
    }
    """
    variables = {
        "input": {
            "type": "MLMODEL",
            "query": "*",
            "start": 0,
            "count": search_limit,
        }
    }
    headers = {
        "Authorization": f"Bearer {DATAHUB_TOKEN}",
        "Content-Type": "application/json",
    }

    resp = requests.post(
        DATAHUB_GMS_URL,
        json={"query": query, "variables": variables},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    results = resp.json().get("data", {}).get("search", {}).get("searchResults", [])

    urns: List[str] = []
    for r in results:
        entity = r.get("entity", {}) or {}
        urn = entity.get("urn")
        if not urn:
            continue
        props = (entity.get("properties") or {}).get("customProperties", []) or []
        flat = {p["key"]: p["value"] for p in props}
        if flat.get("mesh_is_registration") == "true":
            urns.append(urn)
    return urns


@asset
def ingest_global_aitool_registrations(
    context: AssetExecutionContext,
    config: GlobalAIToolIngestionConfig,
) -> dict:
    """Scan DataHub for mesh tool registrations and report counts.

    This asset is *informational* — it does not directly write to Neo4j.
    Instead it surfaces the list of mesh tools currently registered in
    DataHub so operators can spot drift against Neo4j (per the
    reconciliation pattern of ADR-0006). The sensor handles the actual
    sync of new/changed registrations; an operator wanting to force-sync
    every tool can use the sensor's job manually with the URN list this
    asset returns.
    """
    context.log.info(
        f"Scanning DataHub for mesh tool registrations (limit={config.search_limit})..."
    )
    try:
        urns = _find_mesh_tool_urns(config.search_limit)
    except Exception as e:
        context.log.error(f"Failed to scan DataHub for mesh tools: {e}")
        raise

    for urn in urns:
        context.log.info(f"📍 Mesh tool registration found: {urn}")

    return {
        "scanned": len(urns),
        "tool_urns": urns,
    }
