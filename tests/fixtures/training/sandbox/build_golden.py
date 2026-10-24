"""Build a golden.json from a tr_readback.py result. Stdlib only; run locally.

    python build_golden.py <readback.json> <runs.jsonl|run.json> <deck_path> <metadata_path|-> <drop_folder> <out golden.json>

Every value is OBSERVED in the readback; nothing is derived from the contract.
The runs file may be a runs.jsonl (the last record whose key matches the
readback's deck_key is used, else the last record) or a single-record JSON.
"""
import hashlib
import json
import posixpath
import sys
from collections import defaultdict

BUCKET = "processing-artifacts"
VOLATILE_ELEMENT_KEYS = ["element_id", "metadata.parent_id", "metadata.file_directory",
                         "metadata.last_modified", "metadata.filename"]
COURSE_PROPS = ["id", "title", "filename", "current_key", "business_unit", "discipline",
                "audience", "level", "delivery_method", "duration_hours", "version"]
SECTION_PROPS = ["id", "title", "level", "start_page", "end_page", "concept_summary"]
EMBEDDER = {
    "env": {"base_url": ["LLM_BASE_URL", "OPENAI_BASE_URL"],
            "api_key": ["LLM_API_KEY", "OPENAI_API_KEY"],
            "model": ["LLM_EMBED_MODEL"]},
    "model_default": "nomic-embed-text", "dimension": 768,
    "document_prefix": "search_document: ", "query_prefix": "search_query: ",
    "normalized": False,
}


def strip(el):
    el = json.loads(json.dumps(el, default=str))
    for k in VOLATILE_ELEMENT_KEYS:
        head, _, tail = k.partition(".")
        if tail:
            if isinstance(el.get(head), dict):
                el[head].pop(tail, None)
        else:
            el.pop(head, None)
    return el


def load_run(path, deck_key):
    text = open(path, encoding="utf-8").read()
    try:
        one = json.loads(text)
        recs = one if isinstance(one, list) else [one]
    except ValueError:
        recs = [json.loads(l) for l in text.splitlines() if l.strip()]
    if not recs:
        raise SystemExit("no run records in " + path)
    match = [r for r in recs if r.get("key") == deck_key]
    return (match or recs)[-1]


def decode_elements(v):
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return []
    return v if isinstance(v, list) else []


def main(rb_path, runs_path, deck_path, meta_path, drop_folder, out_path):
    rb = json.load(open(rb_path, encoding="utf-8"))
    run = load_run(runs_path, rb.get("deck_key"))
    deck_bytes = open(deck_path, "rb").read()
    deck_name = posixpath.basename(deck_path.replace("\\", "/"))
    drop_folder = drop_folder.strip("/")
    ingest_id = rb["ingest_id"]
    if "sha256:" + hashlib.sha256(deck_bytes).hexdigest() != ingest_id:
        raise SystemExit("deck bytes do not hash to the readback ingest_id")
    meta_name = meta_sha = None
    keys_in_order = []
    if meta_path != "-":
        mb = open(meta_path, "rb").read()
        meta_name = posixpath.basename(meta_path.replace("\\", "/"))
        meta_sha = hashlib.sha256(mb).hexdigest()
        keys_in_order.append(f"{drop_folder}/{meta_name}")
    keys_in_order.append(f"{drop_folder}/{deck_name}")

    nj = rb["neo4j"]
    c = nj.get("course")
    if not c:
        raise SystemExit("readback has no Course node")
    labels = sorted(c["labels"], key=lambda x: (x != "Document", x))
    course_props = {k: c["props"].get(k) for k in COURSE_PROPS}

    desc = {}
    for d in nj["descendants"]:
        if d.get("id") is not None:
            desc[d["id"]] = d
    rels = nj["relationships"]
    section_ids = {i for i, d in desc.items() if "Section" in d["labels"]}
    slide_ids = {i for i, d in desc.items() if i not in section_ids
                 and ("Slide" in d["labels"] or "Chunk" in d["labels"])
                 and "Figure" not in d["labels"]}

    slides, label_sets = [], {}
    for sid in sorted(slide_ids, key=lambda i: (desc[i]["props"].get("number") or 0, i)):
        p = desc[sid]["props"]
        slides.append({"id": sid, "number": p.get("number"), "text": p.get("text"),
                       "asset_type": p.get("asset_type"), "layout_style": p.get("layout_style"),
                       "elements": [strip(e) for e in decode_elements(p.get("elements"))]})
        label_sets[sid] = sorted(desc[sid]["labels"])
    union = sorted({l for ls in label_sets.values() for l in ls},
                   key=lambda x: (x != "Chunk", x != "Slide", x))
    slides_block = {"labels": union, "nodes": slides}
    if len({tuple(v) for v in label_sets.values()}) > 1:
        slides_block["observed_label_sets"] = label_sets

    def edge_types(start_set, end_set):
        return sorted({r["type"] for r in rels
                       if r["start_id"] in start_set and r["end_id"] in end_set})

    course_slide_edges = edge_types({ingest_id}, slide_ids)

    parent = {}
    for r in rels:
        if r["type"] == "HAS_SECTION" and r["end_id"] in section_ids:
            parent[r["end_id"]] = r["start_id"]
    sec_slides = defaultdict(list)
    for r in rels:
        if (r["start_id"] in section_ids and r["end_id"] in slide_ids
                and r["type"] in ("HAS_CHILD", "HAS_SLIDE")
                and r["end_id"] not in sec_slides[r["start_id"]]):
            sec_slides[r["start_id"]].append(r["end_id"])
    covers = defaultdict(list)
    for r in rels:
        if r["type"] == "COVERS" and r["start_id"] in section_ids:
            p = r.get("props") or {}
            covers[r["start_id"]].append({"concept": r["end_name"], "score": p.get("score"),
                                          "frequency": p.get("frequency")})
    sections = []
    for sid in sorted(section_ids):
        p = desc[sid]["props"]
        n = {k: p.get(k) for k in SECTION_PROPS}
        n["id"] = sid
        n["parent"] = parent.get(sid)
        n["slides"] = sorted(sec_slides.get(sid, []))
        n["covers"] = sorted(covers.get(sid, []), key=lambda r: (-(r["score"] or 0), r["concept"] or ""))
        sections.append(n)
    sec_labels = sorted({l for i in section_ids for l in desc[i]["labels"]},
                        key=lambda x: (x != "Section", x))

    teaches_rels = [r for r in rels if r["type"] == "TEACHES" and r["start_id"] in slide_ids]
    teaches = [{"slide": r["start_id"], "concept": r["end_name"],
                "salience": (r.get("props") or {}).get("salience")} for r in teaches_rels]
    teaches.sort(key=lambda t: (t["slide"], t["concept"] or ""))
    if any("salience" in (r.get("props") or {}) for r in teaches_rels):
        loc = "edge"
    elif any("salience" in (cn.get("props") or {}) for cn in nj["concepts"]):
        loc = "concept_node"
    else:
        loc = "absent"
    concepts = sorted(nj["concepts"], key=lambda x: x.get("name") or "")
    con_labels = sorted({l for x in concepts for l in x["labels"]}, key=lambda x: (x != "Concept", x))

    edges = {
        "HAS_SECTION": sorted(({"from": r["start_id"], "to": r["end_id"]} for r in rels
                               if r["type"] == "HAS_SECTION" and r["end_id"] in section_ids),
                              key=lambda e: (e["from"], e["to"])),
        "section_slide": [{"from": s["id"], "to": t} for s in sections for t in s["slides"]],
        "COVERS": [{"from": s["id"], "to": r["concept"], "score": r["score"], "frequency": r["frequency"]}
                   for s in sections for r in s["covers"]],
        "TEACHES": [{"from": t["slide"], "to": t["concept"], "salience": t["salience"]} for t in teaches],
    }

    mn = rb["minio"]
    cj = mn.get("current_json")
    prefix = cj.get("prefix") if isinstance(cj, dict) else None
    if not prefix and mn.get("manifest_key"):
        prefix = mn["manifest_key"].rsplit("/", 1)[0] + "/"
    wv = sorted(({"uuid": o["uuid"], "properties": o["properties"], "vector_length": o["vector_length"]}
                 for o in rb["weaviate"]["objects"]),
                key=lambda o: (o["properties"].get("chunk_id") or ""))

    golden = {
        "contract": "docs/contracts/training-workbench.md",
        "contract_version": 2,
        "fixture": {"deck": deck_name, "deck_sha256": hashlib.sha256(deck_bytes).hexdigest(),
                    "metadata": meta_name, "metadata_sha256": meta_sha},
        "volatile_element_keys": VOLATILE_ELEMENT_KEYS,
        "drop": {"bucket": BUCKET, "keys_in_order": keys_in_order},
        "ingest_id": ingest_id,
        "neo4j": {
            "course": {"labels": labels, "props": course_props},
            "slides": slides_block,
            "course_slide_edges": course_slide_edges,
            "nondeterministic": {
                "note": "OBSERVED from a sandbox run. doc-tools asserts shape only; wb uses it as fake-store data.",
                "sections": {"labels": sec_labels,
                             "section_slide_edges": edge_types(section_ids, slide_ids),
                             "nodes": sections},
                "concepts": {"labels": con_labels,
                             "nodes": [{"name": x["name"],
                                        **{k: v for k, v in (x["props"] or {}).items() if k != "name"}}
                                       for x in concepts]},
                "teaches": teaches,
                "salience_location": loc,
                "edges": edges,
            },
            "never_written": {
                "labels": ["Project", "TargetNode", "User", "CanonicalConcept"],
                "relations": ["OWNS", "ALIGNS_TO", "SUGGESTED_SOURCE", "DERIVED_FROM"],
            },
        },
        "minio": {
            "bucket": mn.get("bucket", BUCKET),
            "current_json_key": mn.get("current_json_key"),
            "current_json": cj,
            "prefix": prefix,
            "keys_required": sorted(k["key"] for k in mn["keys"]),
        },
        "weaviate": {"server": "1.27.0", "collection": "DocumentChunk", "distance": "cosine",
                     "objects": wv, "forbidden_chunk_id_substrings": ["_fig_"]},
        "embedder": EMBEDDER,
        "produced_by": {
            "run": run,
            "old_layout_keys": len(mn.get("old_layout_keys", [])),
            "stem_id_node_count": nj.get("stem_id_node_count"),
            # Contract steps the producing code did not yet implement; their
            # surfaces (TEACHES salience on the edge, pages/, vectors without
            # _fig_ objects, outline sections) are NOT contract-shaped here.
            "pending_steps": ["d", "e", "f", "g"],
            "copied_not_observed": ["weaviate.server", "embedder", "neo4j.never_written"],
        },
    }
    # Bytes, not write_text: Windows text mode would write CRLF.
    with open(out_path, "wb") as f:
        f.write((json.dumps(golden, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print(f"wrote {out_path}: slides={len(slides)} sections={len(sections)} "
          f"concepts={len(concepts)} teaches={len(teaches)} salience_location={loc} "
          f"weaviate={len(wv)} minio_keys={len(mn['keys'])}")


if __name__ == "__main__":
    if len(sys.argv) != 7:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
