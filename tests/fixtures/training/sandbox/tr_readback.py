"""Read back what a training ingest wrote (MinIO, Neo4j, Weaviate). READ-ONLY.

    /opt/venv/bin/python /tmp/cand_tr/tr_readback.py <s3_key_of_deck> <out.json>

Prints counts only. Never prints env values.
"""
import hashlib
import json
import os
import posixpath
import sys

BUCKET = "processing-artifacts"
SMALL = 5 * 1024 * 1024
HOPS = "HAS_CHILD|HAS_SLIDE|HAS_SECTION"


def say(*a):
    print(*a, flush=True)


def minio_part(deck_key, hexd):
    import boto3
    s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT_URL"],
                      aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"])

    def listing(prefix):
        out, tok = [], None
        while True:
            kw = {"Bucket": BUCKET, "Prefix": prefix}
            if tok:
                kw["ContinuationToken"] = tok
            r = s3.list_objects_v2(**kw)
            out += [(o["Key"], o["Size"]) for o in r.get("Contents", [])]
            if not r.get("IsTruncated"):
                return out
            tok = r.get("NextContinuationToken")

    def body(key):
        return s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()

    root = f"training/generated/{hexd}/"
    keys = []
    for k, size in listing(root):
        e = {"key": k, "size": size, "sha256": None}
        if size <= SMALL:
            e["sha256"] = hashlib.sha256(body(k)).hexdigest()
        keys.append(e)
    m = {"bucket": BUCKET, "root": root, "keys": keys,
         "current_json_key": root + "current.json", "current_json": None,
         "manifest_key": None, "manifest": None}
    try:
        m["current_json"] = json.loads(body(root + "current.json"))
    except Exception as e:
        m["current_json_error"] = f"{type(e).__name__}"
    cj = m["current_json"]
    if isinstance(cj, dict) and cj.get("manifest_key"):
        m["manifest_key"] = cj["manifest_key"]
        try:
            m["manifest"] = json.loads(body(cj["manifest_key"]))
        except Exception as e:
            m["manifest_error"] = f"{type(e).__name__}"
    old = posixpath.dirname(deck_key) + "/generated/"
    m["old_layout_prefix"] = old
    m["old_layout_keys"] = [{"key": k, "size": s} for k, s in listing(old)]
    return m


def neo4j_part(ingest_id, stem):
    from neo4j import GraphDatabase
    drv = GraphDatabase.driver(os.environ["NEO4J_URI"],
                               auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]))
    out = {"course": None, "descendants": [], "relationships": [], "concepts": [],
           "stem_id_node_count": None}

    def work(tx):
        r = tx.run("MATCH (c {id: $id}) RETURN labels(c) AS l, properties(c) AS p", id=ingest_id).data()
        if r:
            out["course"] = {"labels": r[0]["l"], "props": r[0]["p"], "duplicates": len(r) - 1}
        out["descendants"] = tx.run(
            f"MATCH (c {{id: $id}})-[:{HOPS}*1..6]->(n) "
            "RETURN DISTINCT n.id AS id, labels(n) AS labels, properties(n) AS props", id=ingest_id).data()
        ids = [ingest_id] + [d["id"] for d in out["descendants"] if d["id"] is not None]
        out["relationships"] = tx.run(
            "MATCH (a)-[r]->(b) WHERE a.id IN $ids AND (b.id IN $ids OR b:Concept) "
            "RETURN type(r) AS type, a.id AS start_id, b.id AS end_id, b.name AS end_name, "
            "labels(b) AS end_labels, properties(r) AS props", ids=ids).data()
        out["concepts"] = tx.run(
            "MATCH (a)-[r]->(b:Concept) WHERE a.id IN $ids "
            "RETURN DISTINCT b.name AS name, labels(b) AS labels, properties(b) AS props", ids=ids).data()
        out["stem_id_node_count"] = tx.run(
            "MATCH (n) WHERE n.id STARTS WITH $stem RETURN count(n) AS c", stem=stem).single()["c"]

    with drv.session(default_access_mode="READ") as s:
        s.execute_read(work)
    drv.close()
    return out


def weaviate_part(ingest_id):
    from doc_tools.utils.weaviate_client import get_weaviate_client
    from weaviate.classes.query import Filter
    client = get_weaviate_client()
    objs = []
    try:
        col = client.collections.get("DocumentChunk")
        offset = 0
        while True:
            r = col.query.fetch_objects(
                filters=Filter.by_property("doc_id").equal(ingest_id),
                include_vector=True, limit=200, offset=offset)
            for o in r.objects:
                v = o.vector
                if isinstance(v, dict):
                    v = v.get("default") if "default" in v else next(iter(v.values()), None)
                objs.append({"uuid": str(o.uuid), "properties": o.properties,
                             "vector_length": len(v) if v else None})
            if len(r.objects) < 200:
                break
            offset += 200
    finally:
        client.close()
    return {"collection": "DocumentChunk", "objects": objs}


def main(deck_key, out_path):
    import boto3
    s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT_URL"],
                      aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"])
    data = s3.get_object(Bucket=BUCKET, Key=deck_key)["Body"].read()
    hexd = hashlib.sha256(data).hexdigest()
    ingest_id = "sha256:" + hexd
    stem = posixpath.splitext(posixpath.basename(deck_key))[0]
    res = {"deck_key": deck_key, "deck_size": len(data), "ingest_id": ingest_id,
           "filename_stem": stem}
    res["minio"] = minio_part(deck_key, hexd)
    res["neo4j"] = neo4j_part(ingest_id, stem)
    res["weaviate"] = weaviate_part(ingest_id)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, default=str, indent=2, ensure_ascii=False)
    say("ingest_id", ingest_id[:15] + "...")
    say("minio keys:", len(res["minio"]["keys"]), "current.json:", res["minio"]["current_json"] is not None,
        "old-layout keys:", len(res["minio"]["old_layout_keys"]))
    n = res["neo4j"]
    say("neo4j course:", n["course"] is not None, "descendants:", len(n["descendants"]),
        "rels:", len(n["relationships"]), "concepts:", len(n["concepts"]),
        "stem-id nodes:", n["stem_id_node_count"])
    say("weaviate objects:", len(res["weaviate"]["objects"]))
    say("wrote", out_path)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        say("usage: tr_readback.py <s3_key_of_deck> <out.json>")
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])
