"""Regenerate ``golden.json`` from the fixture deck (contract fixture).

golden.json is what doc-tools writes for ``hydraulics_fixture.pptx`` once lane
tr's steps b-g have landed. The deterministic half (ids, keys, slide text and
elements) is DERIVED here from the real extraction of the committed deck, so it
cannot drift from what the parser produces. The LLM half (sections, concepts) is
hand-written EXAMPLE data, marked ``nondeterministic``: doc-tools asserts its
shape only, and the workbench uses it as fake-store data.

Any change to the output is a contract change: bump ``contract_version`` and
send wb a packet. Run through the repo venv, from PowerShell (under git-bash,
the libmagic import hangs):

    .venv/Scripts/python.exe tests/fixtures/training/make_golden.py
"""
import hashlib
import json
import tempfile
from collections import defaultdict
from pathlib import Path

from weaviate.util import generate_uuid5

from doc_tools.passes.structural import outline_from_llm
from doc_tools.utils.concept_identity import concept_node_id, normalize_concept_name
from doc_tools.utils.extraction import extract_text_and_metadata
from doc_tools.utils.layout_detector import detect_layout
from doc_tools.utils.pptx_media_extractor import extract_images_from_pptx

HERE = Path(__file__).parent
DECK = HERE / "hydraulics_fixture.pptx"
META = HERE / "metadata.json"
BUCKET = "processing-artifacts"
DROP_FOLDER = "training/course/hydraulics-fixture"
DOMAIN = "TRAINING"
VERSION = "<pipeline_version>"

# Element keys whose value depends on the run (temp path, mtime, a hash of
# both), not on the deck. Stripped here; a comparison strips them on both sides.
VOLATILE_ELEMENT_KEYS = ["element_id", "metadata.parent_id", "metadata.file_directory",
                         "metadata.last_modified", "metadata.filename"]

# EXAMPLE LLM output. Slide 4's "Hydraulic pressure" at 0.3 sits under the
# workbench's salience >= 0.5 filter, and the concept is shared with slide 2, so
# the example exercises both the filter and one-Concept-per-identity: two slides
# teaching one concept give ONE node, keyed on (domain, normalized name).
EXAMPLE_TEACHES = {
    2: [("Pascal's law", 0.95), ("Hydraulic pressure", 0.8)],
    3: [("Hydraulic pump", 0.9), ("Gear pump", 0.6)],
    4: [("Hydraulic reservoir", 0.7), ("Hydraulic pressure", 0.3)],
}
# PROVISIONAL ExtractOutline reply (recorded: false), pinned so a re-run compares
# rather than regenerates. Titles and nesting are the LLM's; its pages are wrong on
# purpose (the measured defect), and the real outline pass ignores them: it anchors
# each title to the page whose Title element carries it. "Accumulator Sizing"
# anchors nowhere, so it is dropped. To be replaced by a recorded sandbox reply
# before the PR leaves draft.
FALLBACK_OUTLINE = [
    {"title": "Hydraulic Systems Fundamentals", "level": 1, "start_page": 2, "end_page": 2,
     "subsections": []},
    {"title": "Pascal's Law", "level": 1, "start_page": 1, "end_page": 4,
     "subsections": [
         {"title": "Hydraulic Pumps", "level": 2, "start_page": 2, "end_page": 2,
          "subsections": []}]},
    {"title": "Reservoir Schematic", "level": 1, "start_page": 3, "end_page": 0,
     "subsections": []},
    {"title": "Accumulator Sizing", "level": 1, "start_page": 4, "end_page": 4,
     "subsections": []},
]
# What the real pass must derive from FALLBACK_OUTLINE and the deck's elements.
# (suffix, title, level, start_page, end_page, parent_suffix)
EXPECTED_SECTIONS = [
    ("_s0", "Hydraulic Systems Fundamentals", 1, 1, 1, None),
    ("_s1", "Pascal's Law", 1, 2, 3, None),
    ("_s1_s0", "Hydraulic Pumps", 2, 3, 3, "_s1"),
    ("_s2", "Reservoir Schematic", 1, 4, 4, None),
]
# No two COVERS scores in a section tie, so concept_summary's order is defined.


def _strip(el: dict) -> dict:
    el = json.loads(json.dumps(el, default=str))
    for k in VOLATILE_ELEMENT_KEYS:
        head, _, tail = k.partition(".")
        if tail:
            el.get(head, {}).pop(tail, None)
        else:
            el.pop(head, None)
    return el


def main() -> None:
    deck_bytes = DECK.read_bytes()
    hexd = hashlib.sha256(deck_bytes).hexdigest()
    ingest_id = "sha256:" + hexd
    root = f"training/generated/{hexd}"
    prefix = f"{root}/{VERSION}/"

    with tempfile.TemporaryDirectory() as td:
        elements = extract_text_and_metadata(str(DECK), extract_images=True, image_output_dir=td)
        media = sorted(Path(p).name for p in extract_images_from_pptx(str(DECK), td))

    by_page = defaultdict(list)
    for el in elements:
        by_page[el.get("metadata", {}).get("page_number", 1)].append(el)
    numbers = sorted(by_page)
    assert numbers == list(range(1, len(numbers) + 1)), numbers

    slides, wv_objects = [], []
    for n in numbers:
        els = by_page[n]
        text = "\n".join(f"[{e.get('type', 'Text')}] {e.get('text', '')}"
                         for e in els if e.get("text", "").strip())
        sid = f"{ingest_id}_p{n}"
        slides.append({
            "id": sid, "number": n, "text": text[:500], "asset_type": "PPTX",
            "layout_style": detect_layout(els), "elements": [_strip(e) for e in els],
        })
        wv_objects.append({"uuid": str(generate_uuid5(sid)), "properties": {
            "text": text, "doc_id": ingest_id, "chunk_id": sid, "domain": DOMAIN}})

    meta = json.loads(META.read_text())
    course = {
        "id": ingest_id, "title": meta["title"], "filename": DECK.name,
        "business_unit": meta["business_unit"], "discipline": meta["engineering_discipline"],
        "audience": meta["audience"], "level": meta["level_of_material"],
        "delivery_method": meta["current_delivery_method"],
        "duration_hours": meta["duration_hours"], "version": meta["version"],
        "outline_source": "llm",
        "current_key": f"{root}/current.json",
    }

    # Sections come from the REAL outline pass over the deck's real elements.
    derived = []

    def _flat(secs, parent_suf):
        for i, s in enumerate(secs):
            suf = f"{parent_suf}_s{i}"
            derived.append((suf, s.title, s.level, s.start_page, s.end_page, parent_suf or None))
            _flat(s.subsections, suf)

    _flat(outline_from_llm(elements, [{"sections": FALLBACK_OUTLINE}]), "")
    assert derived == EXPECTED_SECTIONS, derived

    sections = []
    for suf, title, level, start, end, parent in derived:
        covered = [n for n in numbers if n >= start and (end == 0 or n <= end)]
        acc = defaultdict(list)
        for n in covered:
            for name, sal in EXAMPLE_TEACHES.get(n, []):
                acc[name].append(sal)
        covers = sorted(({"concept": c, "score": round(sum(v) / len(v), 6), "frequency": len(v)}
                         for c, v in acc.items()), key=lambda r: -r["score"])
        assert len({r["score"] for r in covers}) == len(covers), (suf, covers)
        sections.append({
            "id": ingest_id + suf, "title": title, "level": level, "start_page": start,
            "end_page": end, "parent": ingest_id + (parent or ""),
            "slides": [f"{ingest_id}_p{n}" for n in covered], "covers": covers,
            "concept_summary": [r["concept"] for r in covers][:10],
        })
    teaches = [{"slide": f"{ingest_id}_p{n}", "concept": name, "salience": sal}
               for n, pairs in sorted(EXAMPLE_TEACHES.items()) for name, sal in pairs]
    concepts = sorted({t["concept"] for t in teaches})
    # Explicit edges, so a fake store loads them instead of re-deriving them from
    # the id grammar and the COVERS rule (wb's request, contract section 4.2).
    edges = {
        "HAS_SECTION": [{"from": s["parent"], "to": s["id"]} for s in sections],
        "section_slide": [{"from": s["id"], "to": sid} for s in sections for sid in s["slides"]],
        "COVERS": [{"from": s["id"], "to": r["concept"], "score": r["score"], "frequency": r["frequency"]}
                   for s in sections for r in s["covers"]],
        "TEACHES": [{"from": t["slide"], "to": t["concept"], "salience": t["salience"]} for t in teaches],
    }

    golden = {
        "contract": "docs/contracts/training-workbench.md",
        # 3: concept nodes carry `id` and `name_normalized` (#167), and sections come
        # from structural.outline (step g). Section 11's rule -- non-placeholder content
        # changed, so the version moves and wb gets a packet.
        "contract_version": 3,
        "fixture": {
            "deck": DECK.name, "deck_sha256": hexd,
            "metadata": META.name, "metadata_sha256": hashlib.sha256(META.read_bytes()).hexdigest(),
        },
        "placeholders": {VERSION: "DOC_TOOLS_VERSION of the run that wrote the folder",
                         "<iso8601>": "write time of current.json"},
        "volatile_element_keys": VOLATILE_ELEMENT_KEYS,
        "drop": {"bucket": BUCKET,
                 "keys_in_order": [f"{DROP_FOLDER}/{META.name}", f"{DROP_FOLDER}/{DECK.name}"]},
        "ingest_id": ingest_id,
        "neo4j": {
            "course": {"labels": ["Document", "Course", DOMAIN], "props": course},
            "slides": {"labels": ["Chunk", "Slide", DOMAIN], "nodes": slides},
            "course_slide_edges": ["HAS_CHILD", "HAS_SLIDE"],
            "outline": {
                "source": "llm",
                "fallback": FALLBACK_OUTLINE,
                "recorded": False,
                "note": "The pinned ExtractOutline reply (neo4j.outline.fallback) with its pages "
                        "as the LLM gave them, wrong ones included; the real outline pass ignores "
                        "them. Provisional, replaced by a recorded sandbox ExtractOutline reply "
                        "before the PR leaves draft. A re-run compares its LLM titles to these "
                        "and reports the difference, rather than overwriting.",
            },
            "nondeterministic": {
                "note": "Sections are what the real structural.outline pass derives from "
                        "neo4j.outline.fallback and this deck's element pages (page numbers are "
                        "element page_number, never the LLM's). Concepts and TEACHES are LLM-derived "
                        "example data: doc-tools asserts their shape only; wb uses them as fake-store data.",
                "sections": {"labels": ["Section", DOMAIN],
                             "section_slide_edges": ["HAS_CHILD", "HAS_SLIDE"],
                             "nodes": sections},
                # A concept node carries its KEY, not just its label: `id` =
                # hash(domain, normalized name) is what the writer MERGEs on and what
                # `concept_id_unique` constrains, so a fake store built from this
                # fixture must be joinable the same way the real store is. Computed
                # here rather than hardcoded, so the fixture cannot drift from
                # `concept_identity.py` the way it drifted from the contract.
                "concepts": {"labels": ["Concept", DOMAIN],
                             "nodes": [{"id": concept_node_id(DOMAIN, c),
                                        "name": c,
                                        "name_normalized": normalize_concept_name(c),
                                        "domain": DOMAIN} for c in concepts]},
                "teaches": teaches,
                "edges": {
                    "note": "Concept endpoints are names (the node carries the `id` that "
                            "is the real key; an edge names the concept so a fake store "
                            "can resolve it without hashing). section_slide is written as both "
                            "HAS_CHILD and HAS_SLIDE. Each section's concept_summary is its "
                            "COVERS targets by score, descending, top 10.",
                    **edges,
                },
            },
            "never_written": {
                "labels": ["Project", "TargetNode", "User", "CanonicalConcept"],
                "relations": ["OWNS", "ALIGNS_TO", "SUGGESTED_SOURCE", "DERIVED_FROM"],
            },
        },
        "minio": {
            "bucket": BUCKET,
            "current_json_key": course["current_key"],
            "current_json": {"pipeline_version": VERSION, "manifest_key": f"{prefix}manifest.json",
                             "prefix": prefix, "updated_at": "<iso8601>"},
            "prefix": prefix,
            "keys_required": sorted([f"{prefix}text.json", f"{prefix}manifest.json"]
                                    + [f"{prefix}images/{m}" for m in media]
                                    + [f"{prefix}pages/page_{n}.png" for n in numbers]),
        },
        "weaviate": {
            "server": "1.27.0", "collection": "DocumentChunk", "distance": "cosine",
            "objects": sorted(wv_objects, key=lambda o: o["properties"]["chunk_id"]),
            "forbidden_chunk_id_substrings": ["_fig_"],
        },
        "embedder": {
            "env": {"base_url": ["LLM_BASE_URL", "OPENAI_BASE_URL"],
                    "api_key": ["LLM_API_KEY", "OPENAI_API_KEY"],
                    "model": ["LLM_EMBED_MODEL"]},
            "model_default": "nomic-embed-text", "dimension": 768,
            "document_prefix": "search_document: ", "query_prefix": "search_query: ",
            "normalized": False,
        },
    }
    # Bytes, not write_text: on Windows text mode writes CRLF, git commits LF, and
    # the sha256 wb pins would then differ from the working copy's.
    (HERE / "golden.json").write_bytes(
        (json.dumps(golden, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
