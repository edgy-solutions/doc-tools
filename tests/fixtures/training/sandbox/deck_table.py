"""Tabulate each fixture golden against the training-workbench contract (stdlib, local).

    python deck_table.py <fixtures_dir> <measure.json> <never_written.json>[,<more.json>] <out.md>

Every cell is computed from the golden (what the sandbox ingest wrote) or from
measure.json (what python-pptx says the deck holds). Nothing is assumed.
"""
import json
import os
import re
import sys

EMPTY_LINE = re.compile(r"^\[\w+\]\s*$")
CURRENT_KEYS = {"pipeline_version", "manifest_key", "prefix", "updated_at"}


def yn(ok):
    return "yes" if ok else "**NO**"


def row(slug, g, m, nw):
    cid = g["ingest_id"]
    hexd = cid.removeprefix("sha256:")
    n4 = g["neo4j"]
    nodes = n4["slides"]["nodes"]
    nums = sorted(s["number"] for s in nodes)
    n_pptx = m["slide_count"]
    missing = sorted(set(range(1, n_pptx + 1)) - set(nums))
    ids_ok = (cid == "sha256:" + g["fixture"]["deck_sha256"]
              and all(s["id"] == f"{cid}_p{s['number']}" for s in nodes))
    mn = g["minio"]
    root = f"training/generated/{hexd}/"
    pb = g["produced_by"]
    layout_ok = (mn["current_json_key"] == root + "current.json"
                 and all(k.startswith(root) for k in mn["keys_required"])
                 and pb["old_layout_keys"] == 0 and pb["stem_id_node_count"] == 0)
    cj = mn["current_json"] or {}
    cur_ok = set(cj) == CURRENT_KEYS and cj["manifest_key"].startswith(cj["prefix"]) \
        and cj["prefix"] == root + cj["pipeline_version"] + "/"
    labels_ok = (n4["course"]["labels"] == ["Document", "Course", "TRAINING"]
                 and n4["slides"]["labels"] == ["Chunk", "Slide", "TRAINING"])
    props = n4["course"]["props"]
    has_slide = "HAS_SLIDE" in n4["course_slide_edges"] and "HAS_CHILD" in n4["course_slide_edges"]
    text_ok = all(not EMPTY_LINE.match(line) for s in nodes for line in (s["text"] or "").split("\n"))
    textless = sum(1 for s in nodes if not (s["text"] or "").strip())
    objs = g["weaviate"]["objects"]
    fig = [o for o in objs if "_fig_" in (o["properties"].get("chunk_id") or "")]
    txt = [o for o in objs if o not in fig]
    with_text = {s["id"] for s in nodes if (s["text"] or "").strip()}
    wv_ok = {o["properties"]["chunk_id"] for o in txt} == with_text
    vec_ok = all(o["vector_length"] == 768 for o in objs)
    nd = n4["nondeterministic"]
    pages = sum(1 for k in mn["keys_required"] if "/pages/" in k)
    nwr = nw.get(cid, {})
    nw_ok = nwr.get("forbidden_label_nodes") == 0 and nwr.get("forbidden_rels") == 0 \
        and nwr.get("course_nodes") == 1
    return [
        slug,
        f"{n_pptx}" + (f" (hidden {','.join(map(str, m['hidden']))})" if m["hidden"] else ""),
        f"{len(nodes)}" + (f" — **missing {','.join(map(str, missing))}**" if missing else ""),
        str(textless),
        yn(ids_ok), yn(layout_ok), yn(cur_ok), yn(labels_ok),
        repr(props.get("title")), repr(props.get("business_unit")),
        yn(has_slide), yn(text_ok),
        f"{len(txt)}/{len(with_text)} {yn(wv_ok)}",
        f"{len(fig)}" + (" (f)" if fig else ""),
        yn(vec_ok),
        f"{len(nd['teaches'])} on {nd['salience_location']}" + ("" if nd['salience_location'] == "edge" else " (d)") if nd["teaches"] else "0 (no concepts)",
        f"{pages}/{n_pptx} (e)" if pages != n_pptx else f"{pages}/{n_pptx}",
        f"{len(nd['sections']['nodes'])} (g)",
        f"{len(nd['edges']['section_slide'])} (g)",
        yn(nw_ok) if nwr else "not measured",
    ]


HEAD = ["deck", "pptx slides", "Slide nodes", "text-less", "ids §3", "layout §5", "current.json §5",
        "labels §4", "title", "business_unit", "HAS_CHILD+HAS_SLIDE", "no empty lines",
        "Weaviate text obj / text slides", "_fig_ obj", "vec 768", "TEACHES salience",
        "pages/ pngs", "sections", "section→slide edges", "never_written"]


def main(fx, measure_path, nw_paths, out):
    measure = json.load(open(measure_path, encoding="utf-8"))
    nw = {}
    for p in nw_paths.split(","):
        nw.update(json.load(open(p, encoding="utf-8")))
    rows = []
    for slug in sorted(os.listdir(fx)):
        gp = os.path.join(fx, slug, "golden.json")
        if not os.path.isfile(gp) or slug not in measure:
            continue
        rows.append(row(slug, json.load(open(gp, encoding="utf-8")), measure[slug], nw))
    lines = ["| " + " | ".join(HEAD) + " |", "|" + "---|" * len(HEAD)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    with open(out, "wb") as f:
        f.write(("\n".join(lines) + "\n").encode("utf-8"))
    print(f"wrote {out}: {len(rows)} rows")


if __name__ == "__main__":
    main(*sys.argv[1:])
