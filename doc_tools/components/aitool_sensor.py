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

import hashlib
import json
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
            # DataHub v1.6.0+ removed `sortFilters` from SearchInput; sending
            # it returns HTTP 200 with a GraphQL ValidationError and
            # `data: null`, which the .get('data', {}) default below CANNOT
            # catch (default only applies when the key is missing, not when
            # the value is null). The sensor then raises NoneType.get on
            # every tick, which gets caught by the broad except below and
            # silently reported as "empty result." See ADR-0019 Contract C
            # follow-up: this whole sensor is being retired in favor of the
            # mesh-registrar gateway; the fix here keeps Contract C green
            # in the meantime.
            variables = {
                "input": {
                    "type": "MLMODEL",
                    "query": "*",
                    "start": 0,
                    "count": 50,
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
                body = resp.json() or {}
                # Surface GraphQL-level errors (DataHub returns HTTP 200 with
                # `errors` and `data: null` on schema mismatches). Without
                # this, the .get chain below silently no-ops.
                gql_errors = body.get("errors") or []
                if gql_errors:
                    sensor_context.log.error(
                        "DataHub GraphQL errors on mesh tool search: %s",
                        gql_errors,
                    )
                # `or {}` (not the .get default) is intentional: `data` key
                # can be present with a `null` value, in which case the
                # default never fires.
                results = (
                    ((body.get("data") or {}).get("search") or {}).get(
                        "searchResults"
                    )
                    or []
                )

                for r in results:
                    if not isinstance(r, dict):
                        continue
                    entity = r.get("entity") or {}
                    if not isinstance(entity, dict):
                        continue
                    urn = entity.get("urn")
                    if not urn:
                        continue
                    props = (entity.get("properties") or {}).get(
                        "customProperties"
                    ) or []
                    flat = {
                        p.get("key"): p.get("value")
                        for p in props
                        if isinstance(p, dict)
                    }
                    if flat.get("mesh_is_registration") != "true":
                        continue

                    # The run_key is the URN + a content hash of the
                    # registration's customProperties. Dagster dedups on
                    # run_key; same URN + same properties => same key =>
                    # the next sensor tick skips this URN. Same URN +
                    # different properties => new hash => new key => a
                    # fresh sync fires.
                    #
                    # The prior implementation used `int(current_time)`
                    # in place of the hash, which made the key change on
                    # every tick (current_time is captured at the start
                    # of each tick). With a 30s tick interval and N
                    # registered tools, this enqueued N runs per tick
                    # forever — 12 tools at 30s = 24 runs/min, queue
                    # depth climbs without bound and the user-code gRPC
                    # server times out under the load. (Caught in 2026-
                    # 06-09 incident: 397 queued runs after ~15 min,
                    # daemon spiraled.)
                    #
                    # Hashing the flattened customProperties (sorted) is
                    # both deterministic and tolerant of key-order
                    # variation from DataHub's response.
                    props_hash = hashlib.sha256(
                        json.dumps(
                            sorted(flat.items()), sort_keys=True
                        ).encode()
                    ).hexdigest()[:12]
                    run_key = f"{urn}_{props_hash}"
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
