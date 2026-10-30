"""`normalise_concepts_job`: the fleet-wide `concepts.normalise` run, on demand.

No partitions: it reads the whole domain. The config defaults to a DRY RUN, so launching it
from the launchpad changes nothing until `dry_run` is set to false.
"""
from typing import Optional

from dagster import Config, job, op


class NormaliseConceptsConfig(Config):
    domain: str = "TRAINING"
    collection: str = "DocumentChunk"
    course_id: Optional[str] = None
    dry_run: bool = True


@op(required_resource_keys={"neo4j", "weaviate"})
def normalise_concepts_op(context, config: NormaliseConceptsConfig) -> dict:
    from doc_tools.passes import concepts

    neo4j_client = context.resources.neo4j.get_client()
    weaviate_client = context.resources.weaviate.get_client()
    try:
        summary = concepts.normalise(
            neo4j_client, weaviate_client, config.collection, config.domain,
            course_id=config.course_id, dry_run=config.dry_run)
    finally:
        for c in (neo4j_client, weaviate_client):
            try:
                c.close()
            except Exception:
                pass
    context.log.info(f"concepts.normalise: {summary}")
    return summary


@job(name="normalise_concepts_job")
def normalise_concepts_job():
    normalise_concepts_op()
