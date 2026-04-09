import os
import requests
import time
from pydantic import Field
from dagster import Definitions, sensor, SensorEvaluationContext, RunRequest, RunConfig, define_asset_job
from dagster.components import Component, ComponentLoadContext
from dagster.components.resolved.base import Resolvable
from dagster.components.resolved.model import Model
from doc_tools.assets.semantic_linker import ApprovedTagConfig, sync_approved_tags_to_neo4j

class DataHubSensorComponent(Component, Resolvable, Model):
    name: str = Field(default="datahub_approval_sensor", description="Name of the sensor.")
    datahub_gms_url: str = Field(description="DataHub GraphQL URL")
    datahub_token: str = Field(description="DataHub API Token")
    
    def build_defs(self, context: ComponentLoadContext) -> Definitions:
        sync_job = define_asset_job(name=f"{self.name}_sync_job", selection=[sync_approved_tags_to_neo4j])
        
        gms_url = self.datahub_gms_url
        token = self.datahub_token
        
        @sensor(name=self.name, job=sync_job)
        def datahub_sensor(sensor_context: SensorEvaluationContext):
            current_time = time.time() * 1000
            
            query = """
            query searchRecentlyTagged($input: SearchInput!) {
              search(input: $input) {
                searchResults {
                  entity {
                    urn
                    ... on Dataset {
                      glossaryTerms {
                        terms {
                          term { urn }
                        }
                      }
                    }
                  }
                }
              }
            }
            """
            variables = {
                "input": {"type": "DATASET", "query": "*", "start": 0, "count": 50, "sortFilters": [{"field": "lastModified", "sortDirection": "DESCENDING"}]}
            }
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            
            try:
                resp = requests.post(gms_url, json={"query": query, "variables": variables}, headers=headers)
                resp.raise_for_status()
                results = resp.json().get("data", {}).get("search", {}).get("searchResults", [])
                
                for result in results:
                    entity = result.get("entity", {})
                    dataset_urn = entity.get("urn")
                    terms_aspect = entity.get("glossaryTerms")
                    
                    if terms_aspect and terms_aspect.get("terms"):
                        for term_node in terms_aspect["terms"]:
                            term_urn = term_node.get("term", {}).get("urn")
                            if term_urn:
                                run_key = f"{dataset_urn}_{term_urn}_{int(current_time)}"
                                yield RunRequest(
                                    run_key=run_key,
                                    run_config=RunConfig(ops={"sync_approved_tags_to_neo4j": ApprovedTagConfig(dataset_urn=dataset_urn, term_urn=term_urn)})
                                )
                sensor_context.update_cursor(str(current_time))
            except Exception as e:
                sensor_context.log.error(f"Failed to poll DataHub: {e}")

        return Definitions(assets=[], jobs=[sync_job], sensors=[datahub_sensor])
