import logging
import os
from typing import Optional

from dagster import ConfigurableResource

# We will need some stubs for the resources that the assets depend on.
# For doc-tools, we can use these simple wrappers around the clients.

from pydantic import Field

class Neo4jResource(ConfigurableResource):
    uri: str
    username: str
    password: str

    def get_client(self):
        # In a real system, this would return a driver or a wrapper
        from .neo4j_client import Neo4jClient
        return Neo4jClient(uri=self.uri, user=self.username, password=self.password)

    def get_driver(self):
        """Return a raw ``neo4j.Driver`` for callers that want to use the
        native ``with driver.session() as session:`` pattern directly.

        ``aitool_linker.sync_aitool_predicate_to_neo4j`` calls this. Without
        the method the asset raises ``AttributeError: 'Neo4jResource' object
        has no attribute 'get_driver'`` on every sync, every URN, which then
        gets caught by Dagster's broad except and reported as a generic
        step failure with no operator-visible cause.
        """
        from neo4j import GraphDatabase
        return GraphDatabase.driver(self.uri, auth=(self.username, self.password))

class WeaviateResource(ConfigurableResource):
    http_host: str = Field(description="The HTTP REST endpoint for Weaviate (e.g., weaviate:8080)")
    grpc_host: str = Field(description="The high-speed gRPC endpoint for Weaviate (e.g., weaviate-grpc:50051)")

    def get_client(self):
        from .weaviate_client import get_weaviate_client
        return get_weaviate_client(http_host=self.http_host, grpc_host=self.grpc_host)

class LLMExtractorResource(ConfigurableResource):
    langfuse_public_key: str = Field(description="Public key for Langfuse tracing")
    langfuse_secret_key: str = Field(description="Secret key for Langfuse tracing")
    langfuse_host: str = Field(description="Langfuse API host (e.g., https://cloud.langfuse.com)")

    def get_client(self):
        # This provides a centralized way to access Langfuse config if needed
        return {
            "public_key": self.langfuse_public_key,
            "secret_key": self.langfuse_secret_key,
            "host": self.langfuse_host
        }

class IngestStatusResource(ConfigurableResource):
    """ADR-0041 stage-status seam for the ingress-user path.

    Lane 1 (`invincible-agent/src/iagent/gateway.py`'s `POST /ingest`) owns a
    `ingest_status_projection` row per ingest, keyed on the `ingest_id` its
    own sidecar manifest already carries. This resource lets doc-tools
    announce the stage *it* observes (received the file -> extracting ->
    awaiting_disposition / failed) against that SAME vocabulary.

    LOUD NO-OP, ON PURPOSE. There is today no write path from doc-tools to
    that row: Lane 1 exposes only `GET /ingest/{id}/status` (read-only),
    `PROJECTOR_POSTGRES_DSN` is not plumbed into doc-tools, and
    `invincible-agent/src/iagent/ingest_status.py`'s own module docstring
    says it "owns the WRITE path" to that table. Picking a transport (an
    HTTP callback, a direct Postgres write, a queue) is a cross-repo
    decision for whoever owns both sides of that seam — it is NOT something
    to improvise here by reaching into Lane 1's database or duplicating its
    SQL. So `update()` validates every call against the REAL vocabulary and
    Lane 1's own rule, then only logs. Replacing the log call with a real
    transport is the entire scope of closing this seam later.
    """

    def update(self, ingest_id: str, stage: str, *,
               extracted_count: Optional[int] = None,
               extracted_total: Optional[int] = None,
               detail: Optional[str] = None) -> None:
        """Validate and (for now) log one stage transition for `ingest_id`.

        Import the vocabulary, never mirror it: `INGEST_STAGES` is owned by
        `iagent_mesh.ingest` (SDK v0.9.5+, pinned in pyproject.toml).
        `invincible-agent/src/iagent/ingest_status.py` mirrors this same
        tuple only because the fleet's OLD v0.9.3 pin lacked the module —
        doc-tools is on v0.9.5 and imports the real thing. Local import so
        this resource (and this whole module) stays importable without the
        SDK installed for every caller that never calls `update()`.
        """
        from iagent_mesh.ingest import INGEST_STAGES

        if stage not in INGEST_STAGES:
            raise ValueError(
                f"stage={stage!r} is not one of INGEST_STAGES={INGEST_STAGES!r}"
            )
        # Lane 1's own rule, at ingest_status.update_status: a terminal
        # negative stage must say why.
        if stage in ("rejected", "failed") and not (detail and detail.strip()):
            raise ValueError(
                f"stage={stage!r} requires a non-blank `detail` (Lane 1's "
                f"rule at ingest_status.update_status) — got detail={detail!r}"
            )

        logging.getLogger(__name__).info(
            "ADR-0041 ingest status (NO-OP transport — no write path to "
            "Lane 1's ingest_status_projection exists yet; see class "
            "docstring): ingest_id=%s stage=%s extracted_count=%s "
            "extracted_total=%s detail=%s",
            ingest_id, stage, extracted_count, extracted_total, detail,
        )


class JenaResource(ConfigurableResource):
    url: str 
    dataset: str
    username: str 
    password: str 

    def get_client(self):
        from .jena_client import JenaClient
        return JenaClient(url=self.url, dataset=self.dataset, username=self.username, password=self.password)

