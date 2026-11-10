"""The sandbox readback -> golden chain reproduces the contract-v5 golden.

`tests/fixtures/training/sandbox/` turns what a sandbox ingest wrote into a
per-deck golden: tr_readback.py reads the stores, build_golden.py shapes the
readback, deck_table.py tabulates it. Those goldens are what wb receives, so they
must have make_golden.py's shape. This inverts the authoritative golden.json into
the readback tr_readback.py would have produced for it, runs the chain on it, and
asserts the golden comes back out. A v5 field the chain drops fails here, not in
wb's fake store.
"""
import importlib.util
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "training"
SANDBOX = FIXTURES / "sandbox"
GOLDEN = json.loads((FIXTURES / "golden.json").read_text(encoding="utf-8"))


def _load(name):
    spec = importlib.util.spec_from_file_location(f"sandbox_{name}", SANDBOX / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _readback(g):
    """What tr_readback.py writes, for the stores golden `g` describes."""
    n4, nd = g["neo4j"], g["neo4j"]["nondeterministic"]
    cid = g["ingest_id"]
    desc = [{"id": s["id"], "labels": n4["slides"]["labels"],
             "props": {**{k: v for k, v in s.items() if k != "elements"},
                       "elements": json.dumps(s["elements"])}}
            for s in n4["slides"]["nodes"]]
    sec_keys = ("id", "title", "level", "start_page", "end_page", "concept_summary",
                "summary", "objectives")
    desc += [{"id": s["id"], "labels": nd["sections"]["labels"],
              "props": {k: s[k] for k in sec_keys if k in s}}
             for s in nd["sections"]["nodes"]]
    rel = lambda t, a, b, name=None, props=None: {  # noqa: E731
        "type": t, "start_id": a, "end_id": b, "end_name": name, "props": props or {}}
    e = nd["edges"]
    rels = [rel(t, cid, s["id"]) for s in n4["slides"]["nodes"] for t in n4["course_slide_edges"]]
    rels += [rel("HAS_SECTION", x["from"], x["to"]) for x in e["HAS_SECTION"]]
    rels += [rel(t, x["from"], x["to"]) for x in e["section_slide"]
             for t in nd["sections"]["section_slide_edges"]]
    by_name = {c["name"]: c for c in nd["concepts"]["nodes"]}
    rels += [rel("COVERS", x["from"], by_name[x["to"]]["id"], x["to"],
                 {"score": x["score"], "frequency": x["frequency"]}) for x in e["COVERS"]]
    rels += [rel("TEACHES", x["from"], by_name[x["to"]]["id"], x["to"],
                 {"salience": x["salience"], "related_terms": x["related_terms"]}) for x in e["TEACHES"]]
    mn = g["minio"]
    return {
        "deck_key": g["drop"]["keys_in_order"][-1], "ingest_id": cid,
        "minio": {"bucket": mn["bucket"], "keys": [{"key": k, "size": 1, "sha256": None}
                                                    for k in mn["keys_required"]],
                  "current_json_key": mn["current_json_key"], "current_json": mn["current_json"],
                  "manifest_key": mn["current_json"]["manifest_key"], "old_layout_keys": []},
        "neo4j": {
            "course": {"labels": n4["course"]["labels"], "props": n4["course"]["props"], "duplicates": 0},
            "descendants": desc, "relationships": rels,
            "concepts": [{"name": c["name"], "labels": nd["concepts"]["labels"], "props": c}
                         for c in nd["concepts"]["nodes"]],
            "alias_of": [{"from_name": x["from"], "to_name": x["to"],
                          "props": {k: v for k, v in x.items() if k not in ("from", "to")}}
                         for x in e["ALIAS_OF"]],
            "alignment": [], "stem_id_node_count": 0},
        "weaviate": {"collection": "DocumentChunk", "objects": [
            {"uuid": o["uuid"], "properties": o["properties"], "vector_length": 768}
            for o in g["weaviate"]["objects"] + nd["section_objects"]["objects"]]},
    }


def _build(tmp_path, readback=None):
    rb, runs, out = tmp_path / "rb.json", tmp_path / "runs.jsonl", tmp_path / "golden.json"
    rb.write_text(json.dumps(readback or _readback(GOLDEN)), encoding="utf-8")
    runs.write_text(json.dumps({"key": GOLDEN["drop"]["keys_in_order"][-1], "success": True}) + "\n",
                    encoding="utf-8")
    folder = GOLDEN["drop"]["keys_in_order"][-1].rsplit("/", 1)[0]
    _load("build_golden").main(str(rb), str(runs), str(FIXTURES / GOLDEN["fixture"]["deck"]),
                               str(FIXTURES / GOLDEN["fixture"]["metadata"]), folder, str(out))
    return json.loads(out.read_text(encoding="utf-8"))


def _by(xs, *keys):
    return sorted(xs, key=lambda x: json.dumps([x.get(k) for k in keys], default=str))


def test_the_chain_reproduces_the_v5_golden(tmp_path):
    b, g = _build(tmp_path), GOLDEN
    assert b["contract_version"] == g["contract_version"] == 5
    assert b["ingest_id"] == g["ingest_id"]
    assert b["fixture"] == g["fixture"]
    assert b["drop"]["keys_in_order"] == g["drop"]["keys_in_order"]
    bn, gn = b["neo4j"], g["neo4j"]
    assert bn["course"] == gn["course"]
    assert bn["slides"] == gn["slides"]
    assert sorted(bn["course_slide_edges"]) == sorted(gn["course_slide_edges"])
    assert bn["never_written"] == gn["never_written"]
    assert bn["written_only_by"] == gn["written_only_by"]
    bd, gd = bn["nondeterministic"], gn["nondeterministic"]
    assert bd["sections"]["labels"] == gd["sections"]["labels"]
    assert _by(bd["sections"]["nodes"], "id") == _by(gd["sections"]["nodes"], "id")
    assert bd["concepts"] == gd["concepts"]
    assert _by(bd["teaches"], "slide", "concept") == _by(gd["teaches"], "slide", "concept")
    for k in ("HAS_SECTION", "section_slide", "COVERS", "TEACHES", "ALIAS_OF"):
        assert _by(bd["edges"][k], "from", "to") == _by(gd["edges"][k], "from", "to"), k
    # vector_length is the sandbox golden's observation; make_golden.py has no vectors.
    strip = lambda os_: [{"uuid": o["uuid"], "properties": o["properties"]} for o in os_]  # noqa: E731
    assert (_by(strip(bd["section_objects"]["objects"]), "uuid")
            == _by(strip(gd["section_objects"]["objects"]), "uuid"))
    assert _by(strip(b["weaviate"]["objects"]), "uuid") == _by(strip(g["weaviate"]["objects"]), "uuid")
    for k in ("current_json_key", "current_json", "prefix", "keys_required"):
        assert b["minio"][k] == g["minio"][k], k
    assert b["produced_by"]["alignment_edges"] == []


def test_a_figure_object_left_by_an_older_image_is_excluded_and_counted(tmp_path):
    rb = _readback(GOLDEN)
    rb["weaviate"]["objects"].append(
        {"uuid": "00000000-0000-5000-8000-000000000000", "vector_length": 768,
         "properties": {"chunk_id": f"{GOLDEN['ingest_id']}_fig_slide_1_img_0", "text": "Figure"}})
    b = _build(tmp_path, rb)
    assert not any("_fig_" in o["properties"]["chunk_id"] for o in b["weaviate"]["objects"])
    assert b["produced_by"]["stale_fig_objects_excluded"] == 1


def test_the_v5_fields_are_not_vacuous():
    """The comparison above proves nothing about a field the golden leaves empty."""
    nd = GOLDEN["neo4j"]["nondeterministic"]
    assert any(t["related_terms"] for t in nd["teaches"])
    assert nd["edges"]["ALIAS_OF"]
    assert nd["section_objects"]["objects"]
    assert any("summary" in s for s in nd["sections"]["nodes"])
    assert any(s["objectives"] for s in nd["sections"]["nodes"])
    assert {o["properties"]["chunk_kind"] for o in GOLDEN["weaviate"]["objects"]} == {"slide"}
    assert GOLDEN["neo4j"]["course"]["props"]["outline_source"]


def test_deck_table_reads_a_v5_golden(tmp_path):
    b = _build(tmp_path)
    n = len(b["neo4j"]["slides"]["nodes"])
    nw = {b["ingest_id"]: {"course_nodes": 1, "forbidden_label_nodes": 0, "forbidden_rels": 0,
                           "alignment_rels": {}}}
    row = _load("deck_table").row("hydraulics", b, {"slide_count": n, "hidden": []}, nw)
    head = _load("deck_table").HEAD
    assert len(row) == len(head)
    cell = dict(zip(head, row))
    nd = b["neo4j"]["nondeterministic"]
    assert cell["section obj / noted sections"].endswith("yes")
    assert cell["ALIAS_OF"] == str(len(nd["edges"]["ALIAS_OF"]))
    assert cell["alignment edges (dry: 0)"] == "0"
    assert cell["never_written"] == "yes"
    assert cell["Weaviate text obj / text slides"].endswith("yes")
