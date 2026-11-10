"""Serve each re-ingested deck's outline through the workbench's document reader (in the pod, read-only).

    cd /app && PYTHONPATH=/app /opt/venv/bin/python /tmp/tr_run/tr_outline_check.py <rb_dir> <out.json>

For every tr_readback.py output in <rb_dir>, read the manifest, find the
extraction.json beside it the way the gateway does, and run #225's reader on it.
A deck passes when the reader serves a list and its ids are the deck's Section
ids in the graph. A None is what the review card would get: no sections.

`_page`, `_flatten_outline` and `sections_from_extraction` are copied verbatim
(the last without its docstring) from invincible-agent
`src/iagent/review_coverage.py` at master 46df4825; the key
rule is `_beside_manifest_key` in `src/iagent/gateway.py` at the same commit.
The module itself imports iagent_mesh, which this image does not carry.
"""
import json
import os
import posixpath
import sys
from typing import Any, Optional
from urllib.parse import urlparse

BUCKET = "processing-artifacts"


# --- verbatim from invincible-agent review_coverage.py @ 46df4825 ---
def _page(v: Any) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else None


def _flatten_outline(rows: Any, parent_id: str, out: list) -> bool:
    """Depth-first, outline order; False on the first invalid row (the caller drops the list)."""
    if not isinstance(rows, list):
        return False
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            return False
        sid = f"{parent_id}_s{i}"                      # contract v3: `{parent.id}_s{i}`
        title = r.get("title")
        page = _page(r.get("start_page"))
        if not isinstance(title, str) or not title.strip() or page is None:
            return False
        item = {"section_id": sid, "title": title, "page": page}
        end = r.get("end_page")
        if end is not None:
            if _page(end) is None or end < page:
                return False
            item["page_end"] = end
        out.append(item)
        sub = r.get("subsections")
        if sub is not None and not _flatten_outline(sub, sid, out):
            return False
    return True


def sections_from_extraction(extraction: Any, ingest_id: str) -> Optional[list]:
    augs = extraction.get("augmentations") if isinstance(extraction, dict) else None
    if not isinstance(augs, list) or not ingest_id:
        return None
    found = [a for a in augs if isinstance(a, dict) and isinstance(a.get("sections"), list)
             and "outline_source" in a]
    if len(found) != 1:
        return None
    out: list = []
    if not _flatten_outline(found[0]["sections"], ingest_id, out) or not out:
        return None
    ids = [s["section_id"] for s in out]
    return out if len(set(ids)) == len(ids) else None
# --- end verbatim ---


def beside_manifest_key(manifest, extraction_ref, name):
    """gateway.py `_beside_manifest_key` @ 46df4825."""
    loc = str((manifest or {}).get("text_location") or "").strip()
    if loc.startswith("s3://"):
        u = urlparse(loc)
        if u.netloc != BUCKET:
            return None
        key = u.path.lstrip("/")
    else:
        key = loc or str(extraction_ref or "").strip()
    return posixpath.dirname(key) + "/" + name


def check(s3, rb):
    cid = rb["ingest_id"]
    root = f"training/generated/{cid.removeprefix('sha256:')}/"
    ref = rb["minio"].get("manifest_key")
    graph = sorted(d["id"] for d in rb["neo4j"]["descendants"] if "Section" in d["labels"])
    res = {"ingest_id": cid, "manifest_key": ref, "section_nodes": len(graph)}
    if not ref:
        return {**res, "served": None, "why": "readback has no manifest_key"}
    manifest = json.loads(s3.get_object(Bucket=BUCKET, Key=ref)["Body"].read())
    key = beside_manifest_key(manifest, ref, "extraction.json")
    res["extraction_key"] = key
    if not key or not key.startswith(root):
        return {**res, "served": None, "why": "extraction.json is not under the document's directory"}
    try:
        doc = json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    except Exception as exc:  # noqa: BLE001
        return {**res, "served": None, "why": f"extraction.json unreadable: {type(exc).__name__}"}
    augs = doc.get("augmentations") if isinstance(doc, dict) else None
    res["outline_augmentations"] = sum(
        1 for a in augs or [] if isinstance(a, dict) and isinstance(a.get("sections"), list)
        and "outline_source" in a)
    served = sections_from_extraction(doc, cid)
    if served is None:
        return {**res, "served": None, "why": "extraction.json carries no single valid outline"}
    ids = sorted(s["section_id"] for s in served)
    return {**res, "served": len(served), "ids_equal_graph": ids == graph,
            "only_served": sorted(set(ids) - set(graph)), "only_graph": sorted(set(graph) - set(ids))}


def main(rb_dir, out_path):
    import boto3
    s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT_URL"],
                      aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"])
    out = {}
    for name in sorted(os.listdir(rb_dir)):
        if name.endswith(".json"):
            with open(os.path.join(rb_dir, name), encoding="utf-8") as f:
                out[name[:-5]] = check(s3, json.load(f))
    with open(out_path, "wb") as f:
        f.write((json.dumps(out, indent=2) + "\n").encode("utf-8"))
    for slug, r in out.items():
        ok = r["served"] is not None and r.get("ids_equal_graph")
        print(f"{'PASS' if ok else 'FAIL'} {slug}: served={r['served']} graph={r['section_nodes']}"
              + ("" if ok else f" {r.get('why') or 'ids differ'}"), flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
