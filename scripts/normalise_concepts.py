"""Run the concept normalisation pass (`concepts.normalise`) over a whole domain.

The fleet-wide counterpart of the per-course call at the end of a TRAINING ingest: the
repair and the backfill. Run by hand in the doc-tools pod (NEO4J_* / WEAVIATE_* from the
environment, never printed). `--dry-run` computes the plan and the summary and writes
nothing; `--course <id>` narrows the writes to that Course's components.

    python scripts/normalise_concepts.py --domain TRAINING --dry-run
"""
import argparse
import json
import sys


def main(argv=None, neo4j_client=None, weaviate_client=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--domain", default="TRAINING")
    ap.add_argument("--collection", default="DocumentChunk", help="Weaviate collection")
    ap.add_argument("--course", default=None, help="only write this Course's components")
    ap.add_argument("--dry-run", action="store_true", help="plan and report, write nothing")
    args = ap.parse_args(argv)

    if neo4j_client is None:
        from doc_tools.utils.neo4j_client import Neo4jClient
        neo4j_client = Neo4jClient()
    if weaviate_client is None:
        from doc_tools.utils.weaviate_client import get_weaviate_client
        weaviate_client = get_weaviate_client()

    from doc_tools.passes import concepts
    try:
        summary = concepts.normalise(neo4j_client, weaviate_client, args.collection,
                                     args.domain, course_id=args.course, dry_run=args.dry_run)
    finally:
        for c in (neo4j_client, weaviate_client):
            try:
                c.close()
            except Exception:
                pass
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
