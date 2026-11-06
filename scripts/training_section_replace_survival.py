#!/usr/bin/env python
"""Live check: a Section-subtree replace leaves everything else in the graph alone.

Contract: docs/contracts/training-workbench.md section 4.4 rule 4 and 4.5. Runs
against a REAL Neo4j (NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD, never printed), so
it can run in a pod with no pytest. Prints a JSON of counts and exits nonzero on
any mismatch.

Everything it writes carries one run tag (``uuid4().hex``): a Course id
``sha256:`` + sha256(tag), its Slides ``{course}_p1..4`` and its Sections
``{course}_s...``, Concepts named ``zz-survival-{tag}-a|b|c`` (Concepts are shared
across courses by name, so theirs must be unique) and one
``CanonicalConcept {id: "zz-survival-{tag}"}`` aligned to concept a (this script
only stands in for workbench data). Cleanup DETACH DELETEs only nodes carrying the
tag, and asserts that 0 remain.

    .venv/Scripts/python.exe scripts/training_section_replace_survival.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from doc_tools.passes.structural import CourseSection, OutlineBuildError, build_outline  # noqa: E402
from doc_tools.plugins.models import BaseSection, DocumentNode  # noqa: E402
from doc_tools.plugins.training import (  # noqa: E402
    Concept, OutlineAugmentation, SlideAugmentation, TrainingPlugin,
)

CONFIG = SimpleNamespace(graph_node_label="Document", graph_child_label="Chunk")
SLIDES = 4
TEACHES = {1: [("a", 0.9)], 2: [("a", 0.7), ("b", 0.6)], 3: [("b", 0.8)], 4: [("c", 0.5), ("a", 0.4)]}


def _sec(title, start, end, *subs, level=1):
    return CourseSection(title=title, level=level, start_page=start, end_page=end,
                         subsections=list(subs))


# A: four Sections, two of them nested. B: two, so A's nested ids must disappear.
OUTLINE_A = [_sec("A one", 1, 2),
             _sec("A two", 3, 4, _sec("A two-a", 3, 3, level=2), _sec("A two-b", 4, 4, level=2))]
OUTLINE_B = [_sec("B one", 1, 3), _sec("B two", 4, 4)]


def _replace_queries(plugin, course_id, outline):
    node = DocumentNode(
        base_extraction=BaseSection(title="Course", level=0, page_start=0, content="", node_id=course_id),
        domain_augmentation=OutlineAugmentation(sections=outline, metadata={}, outline_source="llm"))
    cypher, _ = plugin.to_graph_queries([node], CONFIG)
    return [q for q in cypher if "DETACH DELETE" in q["query"]]


def _expected_covers(outline, names):
    """The contract 4.2 rule, recomputed in Python: (section_suffix, concept) -> score."""
    out, slides = {}, {}

    def walk(secs, parent):
        for i, s in enumerate(secs):
            sid = f"{parent}_s{i}"
            reach = [n for n in range(1, SLIDES + 1) if s.start_page <= n <= s.end_page]
            slides[sid] = reach
            acc = {}
            for n in reach:
                for c, sal in TEACHES.get(n, []):
                    acc.setdefault(names[c], []).append(sal)
            for c, v in acc.items():
                out[(sid, c)] = round(sum(v) / len(v), 6)
            walk(s.subsections, sid)

    walk(outline, "")
    return out, slides


def _counts(client, cid, tag):
    def one(q):
        return client.execute_query(q, {"cid": cid, "tag": tag})[0]["n"]

    return {
        "Course": one("MATCH (n:Course:TRAINING {id: $cid}) RETURN count(n) AS n"),
        "Slide": one("MATCH (n:Slide:TRAINING) WHERE n.id STARTS WITH $cid RETURN count(n) AS n"),
        "Concept": one("MATCH (n:Concept:TRAINING) WHERE n.name STARTS WITH 'zz-survival-' + $tag "
                       "RETURN count(n) AS n"),
        "Section": one("MATCH (n:Section:TRAINING) WHERE n.id STARTS WITH $cid RETURN count(n) AS n"),
        "TEACHES": one("MATCH (:Slide:TRAINING)-[r:TEACHES]->(c:Concept:TRAINING) "
                       "WHERE c.name STARTS WITH 'zz-survival-' + $tag RETURN count(r) AS n"),
        "COVERS": one("MATCH (s:Section:TRAINING)-[r:COVERS]->(:Concept:TRAINING) "
                      "WHERE s.id STARTS WITH $cid RETURN count(r) AS n"),
        "ALIGNS_TO": one("MATCH (:Concept:TRAINING)-[r:ALIGNS_TO]->"
                         "(:CanonicalConcept {id: 'zz-survival-' + $tag}) RETURN count(r) AS n"),
        "HAS_SECTION": one("MATCH (:TRAINING)-[r:HAS_SECTION]->(s:Section:TRAINING) "
                           "WHERE s.id STARTS WITH $cid RETURN count(r) AS n"),
        "section_slide": one("MATCH (s:Section:TRAINING)-[r:HAS_CHILD]->(:Slide:TRAINING) "
                             "WHERE s.id STARTS WITH $cid RETURN count(r) AS n"),
    }


def _section_ids(client, cid):
    rows = client.execute_query(
        "MATCH (n:Section:TRAINING) WHERE n.id STARTS WITH $cid RETURN n.id AS id", {"cid": cid})
    return sorted(r["id"] for r in rows)


def _cleanup(client, cid, tag):
    p = {"cid": cid, "tag": tag}
    client.execute_query("MATCH (n:TRAINING) WHERE n.id STARTS WITH $cid DETACH DELETE n", p)
    client.execute_query("MATCH (n:Concept:TRAINING) WHERE n.name STARTS WITH 'zz-survival-' + $tag "
                         "DETACH DELETE n", p)
    client.execute_query("MATCH (n:CanonicalConcept {id: 'zz-survival-' + $tag}) DETACH DELETE n", p)
    return client.execute_query(
        "MATCH (n) WHERE (n.id IS NOT NULL AND n.id STARTS WITH $cid) "
        "OR (n.name IS NOT NULL AND n.name STARTS WITH 'zz-survival-' + $tag) "
        "OR n.id = 'zz-survival-' + $tag RETURN count(n) AS n", p)[0]["n"]


def run(client) -> dict:
    tag = uuid.uuid4().hex
    cid = "sha256:" + hashlib.sha256(tag.encode()).hexdigest()
    names = {k: f"zz-survival-{tag}-{k}" for k in "abc"}
    plugin = TrainingPlugin(domain_type="training")
    problems, report = [], {"tag": f"len={len(tag)}", "course": f"sha256:{cid[7:15]}"}
    try:
        # --- seed: Course, Slides, TEACHES (real plugin queries), the stand-in wb edge
        client.execute_query("MERGE (n:Document:Course:TRAINING {id: $cid}) SET n.title = 'zz survival'",
                             {"cid": cid})
        slide_nodes = []
        for n in range(1, SLIDES + 1):
            sid = f"{cid}_p{n}"
            client.execute_query(
                "MATCH (p:Document:TRAINING {id: $cid}) "
                "MERGE (c:Chunk:Slide:TRAINING {id: $sid}) SET c.number = $n "
                "MERGE (p)-[:HAS_CHILD]->(c) MERGE (p)-[:HAS_SLIDE]->(c)",
                {"cid": cid, "sid": sid, "n": n})
            slide_nodes.append(DocumentNode(
                base_extraction=BaseSection(title=f"s{n}", level=1, page_start=n, content="", node_id=sid),
                domain_augmentation=SlideAugmentation(
                    concepts=[Concept(name=names[c], salience=s) for c, s in TEACHES.get(n, [])])))
        slide_queries, _ = plugin.to_graph_queries(slide_nodes, CONFIG)
        for q in slide_queries:
            client.execute_query(q["query"], q["params"])
        client.execute_query(
            "MERGE (k:CanonicalConcept {id: 'zz-survival-' + $tag}) "
            "WITH k MATCH (c:Concept:TRAINING {name: $a}) MERGE (c)-[:ALIGNS_TO]->(k)",
            {"tag": tag, "a": names["a"]})

        def replace(outline):
            (q,) = _replace_queries(plugin, cid, outline)
            client.execute_query(q["query"], q["params"])      # one statement, one transaction
            plugin.execute_pass2_rollup(client, cid, CONFIG)

        # --- outline A, then A again
        replace(OUTLINE_A)
        a1 = _counts(client, cid, tag)
        ids_a = _section_ids(client, cid)
        replace(OUTLINE_A)
        a2 = _counts(client, cid, tag)
        report["A"] = a1
        if a1 != a2:
            problems.append(f"same outline A again changed counts: {a1} -> {a2}")
        if a1["Section"] != 4 or a1["Slide"] != SLIDES or a1["Concept"] != 3:
            problems.append(f"seed counts unexpected: {a1}")

        # --- a failed build executes nothing
        def broken():
            raise RuntimeError("llm down")
        try:
            build_outline([], broken)
            problems.append("a failed extract did not raise OutlineBuildError")
        except OutlineBuildError:
            pass
        if _counts(client, cid, tag) != a1 or _section_ids(client, cid) != ids_a:
            problems.append("a failed build changed the graph")

        # --- a differently shaped outline B
        replace(OUTLINE_B)
        b = _counts(client, cid, tag)
        report["B"] = b
        if b["Section"] != 2:
            problems.append(f"B Section count {b['Section']} != 2")
        if _section_ids(client, cid) != [f"{cid}_s0", f"{cid}_s1"]:
            problems.append("A-only Sections remain after the replace")
        for k in ("Course", "Slide", "Concept", "TEACHES", "ALIGNS_TO"):
            if b[k] != a1[k]:
                problems.append(f"{k} changed across the replace: {a1[k]} -> {b[k]}")
        want_cov, want_slides = _expected_covers(OUTLINE_B, names)
        if b["COVERS"] != len(want_cov):
            problems.append(f"COVERS {b['COVERS']} != recomputed {len(want_cov)}")
        if b["section_slide"] != sum(len(v) for v in want_slides.values()):
            problems.append("Section->Slide count differs from the page-range rule")
        rows = client.execute_query(
            "MATCH (s:Section:TRAINING)-[r:COVERS]->(c:Concept:TRAINING) WHERE s.id STARTS WITH $cid "
            "RETURN s.id AS s, c.name AS c, r.score AS score", {"cid": cid})
        got = {(r["s"].replace(cid, ""), r["c"]): round(r["score"], 6) for r in rows}
        if got != want_cov:
            problems.append("COVERS scores differ from the section 4.2 recomputation")
    finally:
        left = _cleanup(client, cid, tag)
        report["left_after_cleanup"] = left
        if left:
            problems.append(f"{left} tagged node(s) remain after cleanup")
    report["problems"] = problems
    return report


def main() -> int:
    from doc_tools.utils.neo4j_client import Neo4jClient

    client = Neo4jClient()           # NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD from the environment
    try:
        report = run(client)
    finally:
        client.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
