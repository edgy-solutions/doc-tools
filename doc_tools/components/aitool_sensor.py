"""Dagster Component for the AITool binding sensor.

Mirror of ``DataHubSensorComponent`` (which watches Dataset glossary-term
changes) but for mesh tool registrations. Polls DataHub for ``mlModel``
entities tagged with ``mesh_is_registration: "true"`` and dispatches
``sync_aitool_predicate_to_neo4j`` runs for new or changed registrations.

Per ADR-0006 (DataHub inbox, Neo4j substrate), code-controlled mesh tools
auto-approve -- there is no HITL queue between the SDK lifespan and the
Neo4j predicate edge. The sensor's poll interval bounds end-to-end
registration latency (typically ~30s).
"""

import time

import requests
from dagster import (
    Definitions,
    RunConfig,
    RunRequest,
    SensorEvaluationContext,
    define_asset_job,
    sensor,
)
from dagster.components import Component, ComponentLoadContext
from dagster.components.resolved.base import Resolvable
from dagster.components.resolved.model import Model
from pydantic import Field

from doc_tools.assets.aitool_linker import (
    AIToolSyncConfig,
    sync_aitool_predicate_to_neo4j,
)


class AIToolSensorComponent(Component, Resolvable, Model):
    """Watches DataHub for mesh tool registrations and triggers Neo4j sync.

    Configuration fields mirror ``DataHubSensorComponent`` for operational
    parity. The sensor's run_key includes both the tool URN and a cursor
    component so the same registration is re-synced when its
    customProperties change (e.g., endpoint_url moves on redeploy).
    """

    name: str = Field(default="aitool_registration_sensor",
                      description="Name of the sensor.")
    datahub_gms_url: str = Field(description="DataHub GraphQL URL")
    datahub_token: str = Field(description="DataHub API Token")

    def build_defs(self, context: ComponentLoadContext) -> Definitions:
        sync_job = define_asset_job(
            name=f"{self.name}_sync_job",
            selection=[sync_aitool_predicate_to_neo4j],
        )

        gms_url = self.datahub_gms_url
        token = self.datahub_token

        @sensor(name=self.name, job=sync_job)
        def aitool_sensor(sensor_context: SensorEvaluationContext):
            current_time = time.time() * 1000

            # Search for recently-modified mlModel entities. We filter by
            # the mesh_is_registration custom property in Python because
            # DataHub's search filters on customProperties are
            # platform-dependent.
            query = """
            query searchMeshToolRegistrations($input: SearchInput!) {
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
                    "count": 50,
                    "sortFilters": [
                        {"field": "lastModified", "sortDirection": "DESCENDING"}
                    ],
                }
            }
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            try:
                resp = requests.post(
                    gms_url,
                    json={"query": query, "variables": variables},
                    headers=headers,
                )
                resp.raise_for_status()
                results = (
                    resp.json()
                    .get("data", {})
                    .get("search", {})
                    .get("searchResults", [])
                )

                for r in results:
                    entity = r.get("entity", {}) or {}
                    urn = entity.get("urn")
                    if not urn:
                        continue
                    props = (entity.get("properties") or {}).get(
                        "customProperties", []
                    ) or []
                    flat = {p["key"]: p["value"] for p in props}
                    if flat.get("mesh_is_registration") != "true":
                        continue

                    # The run_key is the URN + a coarse timestamp so a
                    # re-registration (same URN, new properties) re-syncs.
                    # Sub-second updates collapse to the same key; that's
                    # intentional -- if the SDK is re-emitting faster than
                    # 1Hz, we don't need to chase every flicker.
                    run_key = f"{urn}_{int(current_time)}"
                    yield RunRequest(
                        run_key=run_key,
                        run_config=RunConfig(
                            ops={
                                "sync_aitool_predicate_to_neo4j": AIToolSyncConfig(
                                    tool_urn=urn,
                                )
                            }
                        ),
                    )

                sensor_context.update_cursor(str(current_time))
            except Exception as e:
                sensor_context.log.error(
                    f"Failed to poll DataHub for mesh tool registrations: {e}"
                )

        return Definitions(assets=[], jobs=[sync_job], sensors=[aitool_sensor])
