"""`concepts.normalise` (contract section 4.7): the pure planner, the Cypher guards, the wiring.

No cluster: records and existing state are built by hand, Neo4j is a recording fake.
"""
import math
import re

import pytest

from doc_tools.passes import concepts as C
from doc_tools.passes.concepts import (
    AlignSettings, ConceptRecord, Existing, align_key, apply_plan, plan_alignment)
from doc_tools.utils.concept_identity import concept_node_id, normalize_concept_name

D = "TRAINING"


def rec(name, *, terms=(), slides=(), courses=("c1",), teach=1, vec=None):
    return ConceptRecord(
        id=concept_node_id(D, name), name=name, name_normalized=normalize_concept_name(name),
        related_terms=sorted(terms), slides=list(slides) or [f"s_{name}"], courses=list(courses),
        teach_count=teach, vector=vec)


def plan(records, existing=None, scope=None, **kw):
    return plan_alignment(records, existing or Existing(), scope=scope,
                          settings=AlignSettings(**kw), domain=D)


def cc_of(p, name):
    return next(e.cc_id for e in p.auto_edges if e.concept_id == concept_node_id(D, name))


def proposals(p, target):
    return [x for x in p.proposals if x.concept_id == concept_node_id(D, target)]


# --- keys

@pytest.mark.parametrize("a", ["Hydraulic-Pump", "HYDRAULIC PUMP", "hydraulic  pump", "Hydraulic/Pump"])
def test_align_key_unifies_punctuation_case_and_spacing(a):
    assert align_key(a) == "hydraulic pump"


def test_align_key_lockout_tagout():
    assert align_key("Lockout/Tagout") == "lockout tagout"


def test_empty_key_falls_back_to_name_normalized():
    r = rec("---")
    assert align_key(r.name) == "" and C._key_of(r) == "---"


# --- auto links and components

def test_exact_key_joins_one_component_and_mutual_terms_join_another():
    recs = [rec("Hydraulic-Pump"), rec("hydraulic pump"),
            rec("PLC", terms=["Programmable Logic Controller"]),
            rec("Programmable Logic Controller", terms=["PLC"]), rec("Lone")]
    p = plan(recs)
    assert cc_of(p, "Hydraulic-Pump") == cc_of(p, "hydraulic pump")
    assert cc_of(p, "PLC") == cc_of(p, "Programmable Logic Controller")
    assert len({e.cc_id for e in p.auto_edges}) == 3
    assert p.stats["components"] == 3 and p.stats["multi_member_components"] == 2
    methods = {e.concept_id: (e.method, e.confidence) for e in p.auto_edges}
    assert methods[concept_node_id(D, "hydraulic pump")] == ("exact", 1.0)
    assert methods[concept_node_id(D, "PLC")] == ("mutual_related_terms", 0.95)
    assert methods[concept_node_id(D, "Lone")] == ("self", 1.0)
    assert len(p.auto_edges) == 5  # every unpinned Concept: exactly one auto edge


def test_one_way_related_term_does_not_join_it_becomes_a_proposal():
    recs = [rec("PLC", terms=["Programmable Logic Controller"]), rec("Programmable Logic Controller")]
    p = plan(recs)
    assert cc_of(p, "PLC") != cc_of(p, "Programmable Logic Controller")
    got = proposals(p, "PLC")
    assert [(x.method, x.confidence) for x in got] == [("related_term_one_way", 0.70)]
    assert got[0].cc_id == cc_of(p, "Programmable Logic Controller")
    assert len(proposals(p, "Programmable Logic Controller")) == 1  # both directions


# --- sticky ids and names

def test_new_component_gets_the_hash_id_and_the_documented_name():
    recs = [rec("Hydraulic Pump", teach=2), rec("hydraulic-pump", teach=2), rec("hydraulic/pump", teach=1)]
    p = plan(recs)
    (cc,) = {e.cc_id for e in p.auto_edges}
    assert cc == C._canonical_id(D, "hydraulic pump")
    # most TEACHES, then shortest, then smallest: "Hydraulic Pump" and "hydraulic-pump" tie on both
    # count and length (14), so the lexicographically smallest wins ("Hydraulic Pump" < "hydraulic-pump")
    assert p.canonicals[cc].name == "Hydraulic Pump" and not p.canonicals[cc].exists


def test_name_tie_break_shortest_wins():
    p = plan([rec("Hydraulic  Pump", teach=3), rec("hydraulic pump", teach=3)])
    (cc,) = p.canonicals
    assert p.canonicals[cc].name == "hydraulic pump"


def test_a_component_keeps_its_auto_cc_when_a_new_member_joins():
    old = rec("Hydraulic Pump")
    ex = Existing(canon={"canonical_old": C.SOURCE}, auto={old.id: {"canonical_old"}})
    p = plan([old, rec("hydraulic-pump")], ex)
    assert {e.cc_id for e in p.auto_edges} == {"canonical_old"}
    assert p.canonicals["canonical_old"].exists and not p.canonicals["canonical_old"].foreign
    assert p.stats["canonical_reused"] == 1 and p.stats["canonical_created"] == 0


def test_most_members_decide_and_ties_take_the_smallest_id():
    a, b, c = rec("Pump A"), rec("pump-a"), rec("pump/a")
    ex = Existing(canon={"canonical_b": C.SOURCE, "canonical_z": C.SOURCE},
                  auto={a.id: {"canonical_z"}, b.id: {"canonical_b"}, c.id: {"canonical_z"}})
    assert {e.cc_id for e in plan([a, b, c], ex).auto_edges} == {"canonical_z"}
    ex.auto[c.id] = {"canonical_b"}
    ex.auto[a.id] = {"canonical_z"}
    ex.auto[b.id] = set()
    assert {e.cc_id for e in plan([a, b, c], ex).auto_edges} == {"canonical_b"}


def test_a_split_component_does_not_hand_one_cc_to_both_halves():
    x, y = rec("Valve X"), rec("Valve Y")
    ex = Existing(canon={"canonical_old": C.SOURCE},
                  auto={x.id: {"canonical_old"}, y.id: {"canonical_old"}})
    p = plan([x, y], ex)
    assert len({e.cc_id for e in p.auto_edges}) == 2


# --- pinned

def test_pinned_members_get_no_auto_edge_and_unpinned_join_the_single_pinned_cc():
    acc, leg, new = rec("Pump A"), rec("Pump B"), rec("pump-a")
    ex = Existing(canon={"cc_human": "someone"},
                  pinned={acc.id: {"cc_human": "accepted"}})
    p = plan([acc, rec("Pump B"), new], ex)
    ids = {e.concept_id: e.cc_id for e in p.auto_edges}
    assert acc.id not in ids and ids[new.id] == "cc_human"
    assert p.canonicals["cc_human"].foreign  # attach edges only; never SET on it
    assert p.stats["pinned_accepted"] == 1 and p.stats["pinned_legacy"] == 0
    ex2 = Existing(canon={"legacy name": None}, pinned={leg.id: {"legacy name": None}})
    p2 = plan([leg, rec("pump-b")], ex2)
    assert all(e.concept_id != leg.id for e in p2.auto_edges)
    assert p2.stats["pinned_legacy"] == 1 and p2.stats["pinned_accepted"] == 0


def test_a_pinned_concept_loses_its_stale_auto_edge():
    r = rec("Pump A")
    p = plan([r], Existing(canon={"cc_h": "x", "cc_old": C.SOURCE},
                           pinned={r.id: {"cc_h": "accepted"}}, auto={r.id: {"cc_old"}}))
    assert p.drop_auto == [r.id] and not p.auto_edges


def test_conflicting_pinned_ccs_propose_instead_of_aligning():
    a, b, new = rec("Pump A"), rec("pump-a"), rec("Pump/A")
    ex = Existing(canon={"cc1": "h", "cc2": "h"},
                  pinned={a.id: {"cc1": "accepted"}, b.id: {"cc2": "accepted"}})
    p = plan([a, b, new], ex)
    assert p.stats["conflicting_components"] == 1
    assert not p.auto_edges
    got = proposals(p, "Pump/A")
    assert sorted(x.cc_id for x in got) == ["cc1", "cc2"]
    assert {(x.method, x.confidence) for x in got} == {("exact", 1.0)}


# --- proposals

def test_rejected_pair_is_never_reproposed():
    recs = [rec("PLC", terms=["Programmable Logic Controller"]), rec("Programmable Logic Controller")]
    base = plan(recs)
    cc_pl = cc_of(base, "Programmable Logic Controller")
    ex = Existing(rejected={(cc_pl, concept_node_id(D, "PLC"))})
    p = plan(recs, ex)
    assert proposals(p, "PLC") == []
    assert len(proposals(p, "Programmable Logic Controller")) == 1  # the other direction is not rejected
    assert p.stats["rejected_pairs"] == 1


def test_co_taught_pair_is_proposed_and_ranks_above_an_equal_pair_with_no_shared_slides():
    a = rec("PLC", terms=["Programmable Logic Controller"], slides=["s1"])
    b = rec("Programmable Logic Controller", slides=["s1", "s2"])
    p = plan([a, b])
    assert len(p.proposals) == 2 and p.proposal_pool[0].shared == 1
    # two equal-confidence pairs: only the co-taught one has shared slides, so it ranks first
    x, y = rec("Box", slides=["t1"]), rec("Boxes", slides=["t1"])
    u, v = rec("Pump", slides=["u1"]), rec("Pumps", slides=["u2"])
    pool = plan([x, y, u, v]).proposal_pool
    assert [(pp.a, pp.b) for pp in pool][0] == (min(x.id, y.id), max(x.id, y.id))
    assert [pp.shared for pp in pool] == [1, 0]


def _pairs(n, course="c1", shared_for=()):
    """n disjoint plural pairs ("Wn" / "Wns"), equal confidence; shared_for lists pair numbers
    whose two sides are co-taught."""
    out = []
    for k in range(n):
        sl = [f"sl{k}"] if k in shared_for else None
        out.append(rec(f"Widget{k:03d}", courses=(course,), slides=sl or [f"a{k}"]))
        out.append(rec(f"Widget{k:03d}s", courses=(course,), slides=sl or [f"b{k}"]))
    return out


def test_sixty_candidate_pairs_emit_the_top_fifty_by_the_ranking():
    shared = set(range(50))
    recs = _pairs(60, shared_for=shared)
    p = plan(recs)
    assert p.stats["proposals_computed"] == 60 and p.stats["proposals_emitted"] == 50
    assert len(p.proposals) == 100 and len(p.proposal_pool) == 60
    names = {x.concept_id for x in p.proposals}
    for k in range(60):
        want = k in shared
        assert (concept_node_id(D, f"Widget{k:03d}") in names) is want


def test_fleet_run_emits_the_union_of_each_courses_top_n():
    recs = _pairs(5, "c1", shared_for={0, 1}) + [
        rec(r.name.replace("Widget", "Gadget"), courses=("c2",), slides=[s.replace("a", "g").replace("b", "h") for s in r.slides])
        for r in _pairs(5, "c2", shared_for={3, 4})]
    p = plan(recs, proposals_per_course=2)
    got = {frozenset((x.concept_id, x.other_id)) for x in p.proposals}
    assert len(got) == 4 and p.stats["proposals_computed"] == 10 and p.stats["proposals_emitted"] == 4
    names = {concept_node_id(D, n) for n in ("Widget000", "Widget001", "Gadget003", "Gadget004")}
    assert {i for pair in got for i in pair} >= names
    # a course run emits only that course's pairs
    one = plan(recs, scope="c2", proposals_per_course=2)
    assert len({frozenset((x.concept_id, x.other_id)) for x in one.proposals}) == 2


def test_a_course_run_keeps_a_cross_course_pair_another_course_selected():
    # Widget pair ranks first in c1 (a shared slide); the Gizmo pair spans c1 and c2 and is
    # c2's only pair. Cap 1: c1 selects Widget, c2 selects Gizmo. The c1 run must still emit
    # Gizmo, or its `managed` delete would drop the proposal c2's run writes back.
    recs = [rec("Widget", slides=["sl1"]), rec("Widgets", slides=["sl1"]),
            rec("Gizmo", courses=("c1",)), rec("Gizmos", courses=("c2",))]
    fleet = plan(recs, proposals_per_course=1)
    ex = Existing(canon={cc: C.SOURCE for cc in fleet.canonicals})
    pairs = lambda p: {frozenset((x.concept_id, x.other_id)) for x in p.proposals}
    gizmo = frozenset(concept_node_id(D, n) for n in ("Gizmo", "Gizmos"))
    c1 = plan(recs, ex, scope="c1", proposals_per_course=1)
    assert gizmo in pairs(c1) and pairs(c1) == pairs(fleet)
    assert pairs(plan(recs, ex, scope="c2", proposals_per_course=1)) == {gizmo}


def test_from_env_reads_both_settings(monkeypatch):
    monkeypatch.setenv("TRAINING_ALIGN_PROPOSALS_PER_COURSE", "3")
    monkeypatch.setenv("TRAINING_ALIGN_PROPOSE_MIN", "0.5")
    s = AlignSettings.from_env()
    assert s.proposals_per_course == 3 and s.propose_min == 0.5
    p = plan_alignment(_pairs(10), Existing(), settings=s, domain=D)
    assert p.stats["proposals_emitted"] == 3 and p.stats["proposals_computed"] == 10
    monkeypatch.delenv("TRAINING_ALIGN_PROPOSALS_PER_COURSE")
    monkeypatch.delenv("TRAINING_ALIGN_PROPOSE_MIN")
    assert AlignSettings.from_env() == AlignSettings() and AlignSettings().proposals_per_course == 50


def test_a_pair_cut_by_the_cap_loses_its_stale_open_proposal():
    recs = _pairs(3)
    full = plan(recs, proposals_per_course=3)
    open_ = {(x.cc_id, x.concept_id) for x in full.proposals}
    ex = Existing(canon={cc: C.SOURCE for cc, _ in open_}, open_proposals=open_)
    capped = plan(recs, ex, proposals_per_course=1)
    assert capped.stats["proposals_emitted"] == 1
    assert len(capped.stale_proposals) == 4
    r = Recorder()
    apply_plan(r, capped, D)
    assert any("$stale" in q for q, _ in r.calls)


def test_reversed_legacy_edge_pins_the_concept_and_is_counted():
    r = rec("Pump A")
    ex = Existing(canon={"legacy name": None}, pinned={r.id: {"legacy name": None}}, legacy_reversed=1)
    p = plan([r, rec("pump-a")], ex)
    assert all(e.concept_id != r.id for e in p.auto_edges)
    assert p.stats["legacy_reversed_edges"] == 1 and p.stats["pinned_legacy"] == 1
    q = Recorder()
    apply_plan(q, p, D)
    assert not any("(cc)-[" in norm(c) and "MERGE" in c and "ALIGNS_TO" in c for c, _ in q.calls)


def test_an_accepted_proposal_becomes_an_aligns_to_and_the_auto_edge_goes():
    r, other = rec("PLC"), rec("Programmable Logic Controller")
    ex = Existing(canon={"cc_x": C.SOURCE, "cc_old": C.SOURCE}, auto={r.id: {"cc_old"}},
                  accepted={("cc_x", r.id): 0.6})
    p = plan([r, other], ex)
    assert [(m.concept_id, m.cc_id, m.confidence) for m in p.materialise] == [(r.id, "cc_x", 0.6)]
    assert p.drop_auto == [r.id] and all(e.concept_id != r.id for e in p.auto_edges)
    assert p.stats["accepted_materialised"] == 1 and p.stats["pinned_accepted"] == 1
    assert all((x.cc_id, x.concept_id) != ("cc_x", r.id) for x in p.proposals)
    rec_ = Recorder()
    apply_plan(rec_, p, D)
    qs = [norm(q) for q, _ in rec_.calls]
    mat = next(q for q in qs if "r.method = 'review'" in q)
    assert "MERGE (c)-[r:ALIGNS_TO]->(cc)" in mat and "r.status = 'accepted'" in mat
    assert not any("DELETE p" in q and "accepted" in q for q in qs)  # the proposal is the record
    # already materialised: nothing to do
    ex.aligned.add(("cc_x", r.id))
    assert plan([r, other], ex).materialise == []


def test_every_written_relationship_runs_concept_to_canonical():
    r = Recorder()
    p = plan(_pairs(2, shared_for={0}) + [rec("Box"), rec("Boxes")],
             Existing(canon={"cc_x": C.SOURCE}, accepted={("cc_x", concept_node_id(D, "Box")): 0.7},
                      auto={concept_node_id(D, "Boxes"): {"cc_stale"}}))
    apply_plan(r, p, D)
    bad = re.compile(r"\((cc|other)\b[^)]*\)-\[\w*:(PROPOSED_)?ALIGNS_TO[^\]]*\]->")
    good = re.compile(r"\(c\b[^)]*\)-\[\w*:(PROPOSED_)?ALIGNS_TO[^\]]*\]->\((cc|other)\b")
    seen = 0
    for q, _ in r.calls:
        n = norm(q)
        assert not bad.search(n), n
        seen += len(good.findall(n))
    assert seen >= 6


V1, V2, V0 = [1.0, 0.0], [0.6, 0.8], [0.0, 1.0]


@pytest.mark.parametrize("a,b,sig,no_vec", [
    (dict(name="PLC", terms=["Logic Controller Unit"]), dict(name="Logic Controller Unit"),
     "related_term_one_way", 0.70),
    (dict(name="Hydraulic Valve"), dict(name="Hydraulic Valves"), "plural", 0.80),
    (dict(name="Box"), dict(name="Boxes"), "plural", 0.80),
    (dict(name="PLC"), dict(name="Programmable Logic Controller"), "acronym", 0.60),
    (dict(name="Hydraulic Pump Safety"), dict(name="Hydraulic Pump Training"), "token_overlap", 0.40),
])
def test_each_signal_has_its_tabled_confidence_with_and_without_vectors(a, b, sig, no_vec):
    floor = {"related_term_one_way": (0.5, 0.5), "plural": (0.5, 0.5),
             "acronym": (0.4, 0.5), "token_overlap": (0.2, 0.6)}[sig]
    # without vectors
    got = plan([rec(**a), rec(**b)], propose_min=0.0).proposals
    assert {x.method for x in got} == {sig} and len(got) == 2
    assert {x.confidence for x in got} == {no_vec} and {x.cos for x in got} == {None}
    assert all(sig in x.evidence for x in got)
    # with vectors: cos(V1, V2) = 0.6, cos(V1, V0) = 0 clamps at the floor
    for other, cos in ((V2, 0.6), (V0, 0.0)):
        got = plan([rec(vec=V1, **a), rec(vec=other, **b)], propose_min=0.0).proposals
        assert {round(x.confidence, 9) for x in got} == {round(floor[0] + floor[1] * cos, 9)}
        assert {round(x.cos, 9) for x in got} == {cos}


def test_negative_cosine_clamps_at_zero():
    got = plan([rec("Box", vec=[1.0, 0.0]), rec("Boxes", vec=[-1.0, 0.0])], propose_min=0.0).proposals
    assert {x.confidence for x in got} == {0.5}  # clamped, not 0.5 - 0.5
    assert plan([rec("Box", vec=[1.0, 0.0]), rec("Boxes", vec=[-1.0, 0.0])]).proposals == []


def test_propose_min_filter():
    recs = [rec("PLC"), rec("Programmable Logic Controller")]  # acronym, no vectors: 0.60
    assert plan(recs).proposals == []
    assert len(plan(recs, propose_min=0.60).proposals) == 2


# --- scope

def test_course_scope_emits_nothing_for_components_without_that_course():
    mine = rec("Pump A", courses=("c1",))
    other = rec("Valve B", courses=("c2",))
    p = plan([mine, other], scope="c1")
    assert [e.concept_id for e in p.auto_edges] == [mine.id]
    assert set(p.canonicals) == {p.auto_edges[0].cc_id}
    assert p.managed == {mine.id}


def test_course_scope_keeps_ids_consistent_with_the_whole_domain_run():
    recs = [rec("Pump A", courses=("c1",)), rec("pump-a", courses=("c2",)), rec("Valve B", courses=("c2",))]
    full, scoped = plan(recs), plan(recs, scope="c1")
    assert cc_of(scoped, "Pump A") == cc_of(full, "Pump A") == cc_of(full, "pump-a")
    assert len(scoped.auto_edges) == 2  # the whole component is written, Valve B is not


def test_course_scope_proposals_need_one_side_in_scope():
    a = rec("Box", courses=("c1",))
    b = rec("Boxes", courses=("c2",))
    c = rec("Pump", courses=("c2",))
    d = rec("Pumps", courses=("c2",))
    full = plan([a, b, c, d])
    assert len(full.proposals) == 4
    scoped = plan([a, b, c, d], scope="c1")
    # b's cc is not in the graph yet (the fleet run creates it), so nothing can point at a
    assert {x.concept_id for x in scoped.proposals} == {b.id}
    ex = Existing(canon={cc_of(full, "Boxes"): C.SOURCE})
    scoped = plan([a, b, c, d], ex, scope="c1")
    assert {x.concept_id for x in scoped.proposals} == {a.id, b.id}


# --- apply

class Recorder:
    def __init__(self, deleted=0):
        self.calls, self.deleted = [], deleted

    def execute_query(self, query, parameters=None, db=None):
        self.calls.append((query, parameters or {}))
        return [{"n": self.deleted}] if "RETURN count(*)" in query else []


def full_plan():
    recs = [rec("Hydraulic-Pump"), rec("hydraulic pump"), rec("Box"), rec("Boxes")]
    return plan(recs, Existing(pinned={recs[2].id: {"cc_h": "accepted"}}, canon={"cc_h": "x"},
                               auto={recs[2].id: {"cc_old"}}))


def norm(q):
    return " ".join(q.split())


def test_apply_statements_guard_every_non_owned_edge():
    r = Recorder(deleted=2)
    out = apply_plan(r, full_plan(), D)
    assert out == {"canonical_deleted": 2}
    qs = [norm(q) for q, _ in r.calls]
    for q in qs:
        if "DELETE" in q and "ALIGNS_TO" in q and "PROPOSED_ALIGNS_TO" not in q and "DETACH" not in q:
            assert "status = 'auto'" in q
        if "DELETE p" in q:
            assert "p.status = 'open'" in q
        if "MERGE (c)-[r:ALIGNS_TO]" in q:
            assert "ex IS NULL OR ex.status = 'auto'" in q
        if "MERGE (c)-[p:PROPOSED_ALIGNS_TO]" in q:
            assert "old IS NULL OR old.status = 'open'" in q
        if "DETACH DELETE" in q:
            assert "cc.source = 'concepts.normalise'" in q and "NOT (cc)-[:ALIGNS_TO]-()" in q
            assert "'PROPOSED_ALIGNS_TO' AND x.status = 'open'" in q
        if "SET cc.name" in q:
            assert "cc.source = 'concepts.normalise'" in q
    assert not any("rejected" in q for q in qs)
    assert not any("description" in q for q in qs)
    assert not any("ALIAS_OF" in q for q in qs)


def test_apply_never_sets_on_a_foreign_cc_and_is_parameterised():
    p = full_plan()
    r = Recorder()
    apply_plan(r, p, D)
    merged = [pr for q, pr in r.calls if "MERGE (cc:CanonicalConcept" in q]
    assert merged and all(row["id"] != "cc_h" for row in merged[0]["rows"])
    for q, params in r.calls:
        assert "Hydraulic" not in q and "cc_h" not in q  # values travel as parameters


def test_dry_run_issues_no_write_and_still_reports(monkeypatch):
    r = Recorder()
    r.execute_query = lambda q, p=None, db=None: (r.calls.append((q, p)) or [])
    monkeypatch.setattr(C, "_slide_vectors", lambda *a, **k: {})
    out = C.normalise(r, object(), "DocumentChunk", D, dry_run=True)
    assert out["dry_run"] is True and out["concepts"] == 0
    assert all(q.lstrip().startswith("MATCH") and "MERGE" not in q and "DELETE" not in q for q, _ in r.calls)
    assert set(out["seconds"]) == {"load", "plan", "apply"}


def test_unsafe_domain_label_is_refused():
    with pytest.raises(ValueError):
        apply_plan(Recorder(), full_plan(), "TRAINING) DETACH DELETE (n")


# --- loading

def test_load_records_unions_terms_counts_edges_and_averages_unit_vectors(monkeypatch):
    rows = [
        {"id": "k1", "name": "PLC", "name_normalized": "plc", "slide": "s1", "course": "c1",
         "related_terms": [" Programmable Logic Controller ", ""]},
        {"id": "k1", "name": "PLC", "name_normalized": "plc", "slide": "s2", "course": "c2",
         "related_terms": ["Controller", "Programmable Logic Controller"]},
        {"id": "k2", "name": "Bare", "name_normalized": "bare", "slide": None, "course": None,
         "related_terms": None},
    ]

    class Neo:
        def execute_query(self, q, p=None, db=None):
            return rows

    monkeypatch.setattr(C, "_slide_vectors", lambda w, c, ids: {"s1": [2.0, 0.0], "s2": [0.0, 5.0]})
    k1, k2 = C.load_records(Neo(), object(), "DocumentChunk", D)
    assert k1.related_terms == ["Controller", "Programmable Logic Controller"]
    assert k1.slides == ["s1", "s2"] and k1.courses == ["c1", "c2"] and k1.teach_count == 2
    assert k1.vector == [0.5, 0.5]
    assert k2.vector is None and k2.teach_count == 0


def test_slide_vectors_skip_section_objects_and_read_the_default_vector():
    from types import SimpleNamespace as NS

    from weaviate.util import generate_uuid5

    seen = {}

    class Query:
        def fetch_objects(self, **kw):
            seen.update(kw)
            return NS(objects=[
                NS(uuid=generate_uuid5("s1"), properties={"chunk_kind": "slide", "chunk_id": "s1"},
                   vector={"default": [1.0, 0.0]}),
                NS(uuid=generate_uuid5("sec"), properties={"chunk_kind": "section", "chunk_id": "sec"},
                   vector={"default": [0.0, 1.0]}),
                NS(uuid=generate_uuid5("s3"), properties={"chunk_id": "s3"}, vector=[0.0, 2.0]),
            ])

    client = NS(collections=NS(get=lambda name: NS(query=Query())))
    out = C._slide_vectors(client, "DocumentChunk", ["s1", "sec", "s3"])
    assert "sec" not in out and set(out) == {"s1", "s3"}
    assert seen["include_vector"] is True


def test_load_existing_classifies_edges():
    class Neo:
        def execute_query(self, q, p=None, db=None):
            if "PROPOSED_ALIGNS_TO" in q:
                return [{"cc": "a", "source": C.SOURCE, "concept": "x", "status": "rejected"},
                        {"cc": "a", "source": C.SOURCE, "concept": "y", "status": "open"},
                        {"cc": "h", "source": "x", "concept": "w", "status": "accepted", "confidence": 0.7}]
            if "(cc:CanonicalConcept)-[r:ALIGNS_TO]->(c:Concept" in q:  # wb's old, reversed shape
                return [{"cc": "old", "source": None, "concept": "v", "status": None}]
            return [{"cc": "a", "source": C.SOURCE, "concept": "x", "status": "auto"},
                    {"cc": "legacy", "source": None, "concept": "y", "status": None},
                    {"cc": "h", "source": "x", "concept": "z", "status": "accepted"}]

    ex = C.load_existing(Neo(), D)
    assert ex.auto == {"x": {"a"}}
    assert ex.pinned == {"y": {"legacy": None}, "z": {"h": "accepted"}, "v": {"old": None}}
    assert ex.legacy_reversed == 1 and ex.accepted == {("h", "w"): 0.7}
    assert ex.aligned == {("legacy", "y"), ("h", "z"), ("old", "v")}
    assert ex.rejected == {("a", "x")} and ex.open_proposals == {("a", "y")}


# --- wiring

def _manifest(monkeypatch=None):
    import json

    from tests.test_document_parser_versioning import _FakeS3Client
    from tests.test_training_workbench_golden import BUCKET, PIPELINE_VERSION

    cid = "sha256:" + "b" * 64
    text_key = f"training/generated/{'b' * 64}/{PIPELINE_VERSION}/text.json"
    elements = [{"type": "Title", "text": "Has text", "metadata": {"page_number": 1}}]
    client = _FakeS3Client()
    client.put_object(Bucket=BUCKET, Key=text_key, Body=json.dumps(elements).encode())
    return cid, client, {"doc_id": cid, "ingest_id": cid, "filename": "x.pptx",
                         "text_location": text_key, "metadata": {"domain_type": "training"},
                         "current_key": f"training/generated/{'b' * 64}/current.json"}


def _meta(ctx):
    return ctx.get_output_metadata("result") if hasattr(ctx, "get_output_metadata") else {}


def _wired_run(monkeypatch, mode, normalise):
    """Run the graph asset; the stubbed concept call raises, so the run itself fails on
    `failed:concept_parse` -- which is exactly the point: alignment is independent of it."""
    from tests.test_training_workbench_golden import _graph_run

    if mode is None:
        monkeypatch.delenv("TRAINING_CONCEPT_ALIGNMENT", raising=False)
    else:
        monkeypatch.setenv("TRAINING_CONCEPT_ALIGNMENT", mode)
    cid, client, manifest = _manifest()
    ctxs = []
    _graph_run(manifest, client, monkeypatch, normalise=normalise, ctx_out=ctxs)
    return cid, ctxs[0]


def test_ingest_defaults_to_a_dry_run(monkeypatch):
    # Contract v5 section 4.7: nothing is written until the workbench's harmonizer is off.
    calls = []
    cid, ctx = _wired_run(monkeypatch, None, lambda *a, **k: calls.append(k) or {})
    assert calls == [{"course_id": cid, "dry_run": True}]
    assert _meta(ctx)["concept_alignment"] == "dry"


def test_ingest_calls_the_pass_for_its_course_and_records_ok(monkeypatch):
    calls = []
    cid, ctx = _wired_run(monkeypatch, "on", lambda *a, **k: calls.append((a, k)) or {"concepts": 3})
    assert len(calls) == 1
    args, kw = calls[0]
    assert args[2:4] == ("DocumentChunk", "TRAINING") and kw == {"course_id": cid, "dry_run": False}
    meta = _meta(ctx)
    assert meta["concept_alignment"] == "ok"
    assert '"concepts": 3' in meta["concept_alignment_summary"]


def test_ingest_honours_off_and_dry(monkeypatch):
    calls = []
    _, ctx = _wired_run(monkeypatch, "off", lambda *a, **k: calls.append(k) or {})
    assert calls == [] and _meta(ctx)["concept_alignment"] == "off"
    _, ctx = _wired_run(monkeypatch, "dry", lambda *a, **k: calls.append(k) or {})
    assert [k["dry_run"] for k in calls] == [True] and _meta(ctx)["concept_alignment"] == "dry"


def test_a_raising_pass_does_not_fail_the_run_and_is_recorded(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x" * 500)

    from tests.test_training_workbench_golden import _graph_run, empty_section_reply

    cid, client, manifest = _manifest()
    ctxs = []
    # reraise=True: any exception out of the asset fails this test, so the run is green
    _graph_run(manifest, client, monkeypatch, normalise=boom, ctx_out=ctxs, reraise=True,
               extract=lambda self, text, instr: empty_section_reply(text))
    status = _meta(ctxs[0])["concept_alignment"]
    assert status.startswith("failed:RuntimeError: xxx") and len(status) == len("failed:RuntimeError: ") + 200


def test_a_non_training_run_never_calls_the_pass(monkeypatch):
    from tests.test_training_workbench_golden import _graph_run

    calls = []
    cid, client, manifest = _manifest()
    manifest["metadata"] = {"domain_type": "manufacturing"}
    ctxs = []
    _graph_run(manifest, client, monkeypatch, normalise=lambda *a, **k: calls.append(k) or {},
               ctx_out=ctxs)
    assert calls == []


def test_the_pass_is_declared_on_the_course_row_only():
    from doc_tools.utils.content_kind import KIND_MAPPING

    rows = [k for k, v in KIND_MAPPING.items() if "concepts.normalise" in v.passes]
    assert rows == ["course"]
    passes = KIND_MAPPING["course"].passes
    assert passes.index("training.baml::ExtractSectionConcepts") < passes.index(
        "concepts.normalise") < passes.index("render.pages")
    assert callable(C.normalise)


def test_the_job_defaults_to_a_dry_run_and_is_registered():
    from doc_tools.concept_alignment_job import NormaliseConceptsConfig, normalise_concepts_job
    from doc_tools.definitions import defs

    assert NormaliseConceptsConfig().dry_run is True
    assert defs.get_job_def("normalise_concepts_job") is not None
    assert normalise_concepts_job.name == "normalise_concepts_job"