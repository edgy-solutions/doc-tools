"""Gate for the training-workbench contract (docs/contracts/training-workbench.md).

One test per surface, all against ``tests/fixtures/training/golden.json``. A
surface that a later lane-tr step delivers is ``xfail(strict=True)`` naming that
step; the step's PR flips it (strict, so an unflipped pass fails the suite).
The ``nondeterministic`` block of the golden is LLM-derived example data: only
its SHAPE is asserted, by ``assert_llm_shape``, which later live or fake-driven
tests reuse.
"""
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from doc_tools.utils.content_kind import KIND_MAPPING

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "training"
DECK = FIXTURES / "hydraulics_fixture.pptx"
META = FIXTURES / "metadata.json"
GOLDEN = json.loads((FIXTURES / "golden.json").read_text(encoding="utf-8"))

INGEST_ID = GOLDEN["ingest_id"]
HEX = INGEST_ID.removeprefix("sha256:")
SLIDES = GOLDEN["neo4j"]["slides"]["nodes"]
SLIDE_IDS = [s["id"] for s in SLIDES]
NONDET = GOLDEN["neo4j"]["nondeterministic"]


def assert_llm_shape(sections, concepts, teaches, slide_ids, ingest_id):
    """Shape of LLM-derived graph data (sections, concepts, TEACHES rows)."""
    numbers = {int(i.rsplit("_p", 1)[1]) for i in slide_ids}
    names = [c["name"] for c in concepts]
    assert len(names) == len(set(names)), "one Concept per name"
    for c in concepts:
        assert c["domain"] == "TRAINING", c
    sec_ids = {s["id"] for s in sections}
    id_re = re.compile(rf"^{re.escape(ingest_id)}(_s\d+)+$")
    for s in sections:
        assert id_re.match(s["id"]), s["id"]
        assert s["parent"] == ingest_id or s["parent"] in sec_ids, s["parent"]
        assert isinstance(s["level"], int) and s["level"] >= 1
        assert s["start_page"] in numbers, s["start_page"]
        assert isinstance(s["end_page"], int) and s["end_page"] >= 0
        assert len(s["concept_summary"]) <= 10
        assert all(n in names for n in s["concept_summary"]), s["concept_summary"]
    for t in teaches:
        assert t["slide"] in slide_ids, t
        assert t["concept"] in names, t
        assert isinstance(t["salience"], float) and 0.0 <= t["salience"] <= 1.0, t


def test_fixture_bytes_are_pinned():
    fx = GOLDEN["fixture"]
    assert hashlib.sha256(DECK.read_bytes()).hexdigest() == fx["deck_sha256"]
    assert hashlib.sha256(META.read_bytes()).hexdigest() == fx["metadata_sha256"]
    assert GOLDEN["ingest_id"] == "sha256:" + fx["deck_sha256"]


def test_golden_ids_follow_the_contract():
    from weaviate.util import generate_uuid5

    course = GOLDEN["neo4j"]["course"]["props"]
    assert course["id"] == INGEST_ID
    assert course["current_key"] == f"training/generated/{HEX}/current.json"
    assert course["title"] == json.loads(META.read_text(encoding="utf-8"))["title"]
    assert course["filename"] == "hydraulics_fixture.pptx"

    numbers = [s["number"] for s in SLIDES]
    assert all(isinstance(n, int) for n in numbers)
    assert numbers == list(range(1, len(numbers) + 1))
    for s in SLIDES:
        assert s["id"] == f"{INGEST_ID}_p{s['number']}"
        assert s["id"].rsplit("_p", 1) == [INGEST_ID, str(s["number"])]
        assert len(s["text"]) <= 500
        assert not any(re.match(r"^\[\w+\] $", ln) for ln in s["text"].split("\n")), s["id"]

    mi = GOLDEN["minio"]
    prefix = mi["prefix"]
    assert prefix == f"training/generated/{HEX}/<pipeline_version>/"
    cj = mi["current_json"]
    assert cj["prefix"] == prefix and prefix.endswith("/")
    assert cj["manifest_key"] == prefix + "manifest.json"
    keys = mi["keys_required"]
    assert all(k.startswith(prefix) for k in keys)
    for k in ("text.json", "manifest.json", *(f"pages/page_{n}.png" for n in numbers)):
        assert prefix + k in keys, k

    objs = GOLDEN["weaviate"]["objects"]
    assert len(objs) == len(SLIDES)
    by_chunk = {o["properties"]["chunk_id"]: o for o in objs}
    for s in SLIDES:
        o = by_chunk[s["id"]]
        p = o["properties"]
        assert p["doc_id"] == INGEST_ID and p["domain"] == "TRAINING"
        assert o["uuid"] == str(generate_uuid5(p["chunk_id"]))
        assert p["text"][:500] == s["text"]
    for bad in GOLDEN["weaviate"]["forbidden_chunk_id_substrings"]:
        assert not any(bad in c for c in by_chunk), bad


def test_nondeterministic_example_has_the_contract_shape():
    assert_llm_shape(NONDET["sections"]["nodes"], NONDET["concepts"]["nodes"],
                     NONDET["teaches"], SLIDE_IDS, INGEST_ID)


def test_example_edges_follow_the_section_4_2_rules():
    """The explicit `edges` block is what wb's fake store loads, so it must be
    exactly what the contract's rules give from the example sections and TEACHES."""
    sections, edges = NONDET["sections"]["nodes"], NONDET["edges"]
    assert edges["HAS_SECTION"] == [{"from": s["parent"], "to": s["id"]} for s in sections]
    assert edges["TEACHES"] == [{"from": t["slide"], "to": t["concept"], "salience": t["salience"]}
                                for t in NONDET["teaches"]]
    numbers = {s["id"]: s["number"] for s in SLIDES}
    covers = []
    for sec in sections:
        reached = [sid for sid, n in numbers.items()
                   if n >= sec["start_page"] and (sec["end_page"] == 0 or n <= sec["end_page"])]
        assert sorted(e["to"] for e in edges["section_slide"] if e["from"] == sec["id"]) == sorted(reached)
        sal = {}
        for t in NONDET["teaches"]:
            if t["slide"] in reached:
                sal.setdefault(t["concept"], []).append(t["salience"])
        mine = sorted(({"from": sec["id"], "to": c, "score": round(sum(v) / len(v), 6), "frequency": len(v)}
                       for c, v in sal.items()), key=lambda r: -r["score"])
        assert sec["concept_summary"] == [r["to"] for r in mine][:10], sec["id"]
        covers += mine
    assert sorted(edges["COVERS"], key=json.dumps) == sorted(covers, key=json.dumps)


def _strip(el, keys):
    el = json.loads(json.dumps(el, default=str))
    for k in keys:
        head, _, tail = k.partition(".")
        if tail:
            el.get(head, {}).pop(tail, None)
        else:
            el.pop(head, None)
    return el


def test_extraction_reproduces_the_golden_slides(tmp_path):
    from collections import defaultdict

    from doc_tools.utils.extraction import extract_text_and_metadata
    from doc_tools.utils.layout_detector import detect_layout
    from doc_tools.utils.pptx_media_extractor import extract_images_from_pptx

    elements = extract_text_and_metadata(str(DECK), extract_images=True,
                                         image_output_dir=str(tmp_path))
    by_page = defaultdict(list)
    for el in elements:
        by_page[el.get("metadata", {}).get("page_number", 1)].append(el)
    vol = GOLDEN["volatile_element_keys"]
    got = []
    for n in sorted(by_page):
        els = by_page[n]
        text = "\n".join(f"[{e.get('type', 'Text')}] {e.get('text', '')}"
                         for e in els if e.get("text", "").strip())
        got.append({"id": f"{INGEST_ID}_p{n}", "number": n, "text": text[:500],
                    "asset_type": "PPTX", "layout_style": detect_layout(els),
                    "elements": [_strip(e, vol) for e in els]})
    assert got == SLIDES

    media = sorted(Path(p).name for p in extract_images_from_pptx(str(DECK), str(tmp_path)))
    prefix = GOLDEN["minio"]["prefix"] + "images/"
    want = sorted(k[len(prefix):] for k in GOLDEN["minio"]["keys_required"] if k.startswith(prefix))
    assert media == want


def test_never_written_lists_the_workbench_owned_names():
    nw = GOLDEN["neo4j"]["never_written"]
    assert set(nw["labels"]) == {"Project", "TargetNode", "User", "CanonicalConcept"}
    assert set(nw["relations"]) == {"OWNS", "ALIGNS_TO", "SUGGESTED_SOURCE", "DERIVED_FROM"}
    banned = [":Project", ":TargetNode", ":CanonicalConcept", ":ALIGNS_TO",
              ":SUGGESTED_SOURCE", ":DERIVED_FROM", ":OWNS"]
    hits = []
    for py in (REPO_ROOT / "doc_tools").rglob("*.py"):
        src = py.read_text(encoding="utf-8", errors="replace")
        hits += [f"{py.relative_to(REPO_ROOT)}: {b}" for b in banned if b in src]
    assert not hits, hits


def test_training_kind_row_and_sensor():
    row = KIND_MAPPING.get("course")
    assert row is not None, "no KIND_MAPPING row 'course'"
    assert row.kind == "course" and row.domain_type == "training"
    assert {".pptx", ".pdf", ".docx"} <= {s if s.startswith(".") else "." + s
                                          for s in row.file_suffixes}
    # ingress_prefix is the Lane-1 ingress-user/<fmt>/ path (sealed to {pdf, xml}
    # by test_ingress_prefix_registry.py); the course row must leave it None.
    assert row.ingress_prefix is None
    src = (REPO_ROOT / "doc_tools" / "definitions.py").read_text(encoding="utf-8")
    assert "training/course/" in src
    # Contract section 2: the PATH carries the kind (ADR-0021 <domain>/<kind>/...),
    # and the sidecar carries neither. The parser stamps domain_type from the
    # first key segment; path-derive then reads "course" from the second.
    from doc_tools.utils.content_kind import resolve_content_kind

    meta = json.loads(META.read_text(encoding="utf-8"))
    assert "content_kind" not in meta and "domain_type" not in meta
    deck_key = GOLDEN["drop"]["keys_in_order"][-1]
    assert deck_key.startswith("training/course/")
    assert resolve_content_kind({**meta, "domain_type": "training"}, deck_key) is row


@pytest.mark.xfail(strict=True, reason="lane tr step d")
def test_teaches_salience_is_on_the_edge():
    from doc_tools.plugins.models import BaseSection, DocumentNode
    from doc_tools.plugins.training import Concept, SlideAugmentation, TrainingPlugin

    sid = f"{INGEST_ID}_p2"
    rows = [t for t in NONDET["teaches"] if t["slide"] == sid]
    assert rows
    aug = SlideAugmentation(concepts=[Concept(name=t["concept"], salience=t["salience"])
                                      for t in rows], objectives=[])
    node = DocumentNode(
        base_extraction=BaseSection(title="s2", level=1, page_start=2, content="x", node_id=sid),
        domain_augmentation=aug)
    config = SimpleNamespace(graph_node_label="Document", graph_child_label="Slide")
    cypher, _ = TrainingPlugin(domain_type="training").to_graph_queries(
        [node], config, doc_id=INGEST_ID)

    concept_merge = re.compile(r"MERGE\s*\(\s*\w*\s*:Concept[^{)]*\{([^}]*)\}")
    teaches_rel = re.compile(r"\[\s*\w*\s*:TEACHES\b([^\]]*)\]")
    edge_queries = [q for q in cypher if teaches_rel.search(q["query"])]
    assert edge_queries, "no query writes TEACHES"
    for q in edge_queries:
        for m in concept_merge.finditer(q["query"]):
            keys = re.findall(r"(\w+)\s*:", m.group(1))
            assert "salience" not in keys, "salience in the Concept MERGE key"
            assert keys == ["name"], keys
        assert "TRAINING" in q["query"] or "TRAINING" in map(str, q["params"].values())
        assert re.search(r"\.domain\s*=|domain\s*:", q["query"]), "Concept domain not set"

    def sets_salience_on_edge(q):
        rel = teaches_rel.search(q["query"])
        after = q["query"][rel.start():]
        return bool(re.search(r"\{[^}]*salience\s*:", rel.group(0))
                    or re.search(r"\w+\.salience\s*=", after))

    for t in rows:
        assert any(t["salience"] in q["params"].values() and sets_salience_on_edge(q)
                   for q in edge_queries), t


@pytest.mark.xfail(strict=True, reason="lane tr step c")
def test_ids_and_versioned_layout():
    """Real test checks course props, slide ids and the minio prefix/current.json/keys_required in golden."""
    pytest.fail("not built: lane tr step c — the step's PR replaces this body with a real assertion against golden")


@pytest.mark.xfail(strict=True, reason="lane tr step e")
def test_render_pages_writes_page_pngs():
    """Real test checks that every pages/page_{n}.png in golden minio.keys_required is rendered."""
    pytest.fail("not built: lane tr step e — the step's PR replaces this body with a real assertion against golden")


@pytest.mark.xfail(strict=True, reason="lane tr step f")
def test_vectors_written_and_no_figure_objects():
    """Real test checks golden weaviate.objects carry vectors and no chunk_id has a forbidden substring."""
    pytest.fail("not built: lane tr step f — the step's PR replaces this body with a real assertion against golden")


@pytest.mark.xfail(strict=True, reason="lane tr step g")
def test_outline_pages_come_from_element_metadata():
    """Real test checks golden section start_page/end_page equal the element page_number metadata, not LLM output."""
    pytest.fail("not built: lane tr step g — the step's PR replaces this body with a real assertion against golden")
