"""``concepts.normalise``: unify the Concept nodes of a domain into CanonicalConcepts.

Deterministic, no LLM. Inputs are the Concept names, the TEACHES ``related_terms``
(contract v4) and the Weaviate vectors of the Slides that teach each Concept. Output:

* ``(:CanonicalConcept)-[:ALIGNS_TO {status:'auto'}]->(:Concept)`` for high-confidence
  links (same align key, or each side lists the other as a related term);
* ``(:CanonicalConcept)-[:PROPOSED_ALIGNS_TO {status:'open'}]->(:Concept)`` review
  proposals for everything weaker, for the workbench to accept or reject.

It never merges Concept nodes and never writes ``ALIAS_OF``. It replaces the workbench's
LLM-only ``harmonize_concepts``; the shape wb reads is kept (CanonicalConcept -> Concept,
``cc.name``). The rules are contract ``training-workbench.md`` section 4.7.

Ownership: the pass owns auto ALIGNS_TO edges, OPEN proposals and CanonicalConcepts whose
``source`` is ``concepts.normalise``. A human decision (``status 'accepted'``), a legacy
edge with no status (wb's harmonizer) and a rejected proposal are never changed.

``plan_alignment`` is pure; ``load_records`` / ``load_existing`` / ``apply_plan`` are the
only I/O. The declared pass name is ``concepts.normalise`` (see ``doc_tools/passes``).
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from doc_tools.utils.concept_identity import normalize_concept_name

log = logging.getLogger(__name__)

SOURCE = "concepts.normalise"

#: Contract 4.7 confidences. Auto links are never proposals.
CONF_EXACT = 1.0
CONF_MUTUAL = 0.95
CONF_SELF = 1.0

_METHOD_RANK = {"exact": 2, "mutual_related_terms": 1}
_AUTO_CONF = {"exact": CONF_EXACT, "mutual_related_terms": CONF_MUTUAL, "self": CONF_SELF}

#: Strongest first. (floor-with-cos, no-cos fixed) are the table rows of contract 4.7.
_SIGNALS = ("related_term_one_way", "plural", "acronym", "token_overlap")
_SIGNAL_CONF = {
    "related_term_one_way": (0.5, 0.5, 0.70),
    "plural": (0.5, 0.5, 0.80),
    "acronym": (0.4, 0.5, 0.60),
    "token_overlap": (0.2, 0.6, 0.40),
}

_LABEL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_VECTOR_BATCH = 200


@dataclass(frozen=True)
class AlignSettings:
    propose_min: float = 0.70
    max_proposals: int = 5

    @classmethod
    def from_env(cls) -> "AlignSettings":
        raw = os.getenv("TRAINING_ALIGN_PROPOSE_MIN")
        return cls(propose_min=float(raw)) if raw else cls()


@dataclass
class ConceptRecord:
    id: str
    name: str
    name_normalized: str
    related_terms: List[str] = field(default_factory=list)
    slides: List[str] = field(default_factory=list)
    courses: List[str] = field(default_factory=list)
    teach_count: int = 0
    vector: Optional[List[float]] = None


@dataclass
class Existing:
    """What the graph already holds about alignment, keyed by Concept id / cc key.

    A cc key is ``coalesce(cc.id, cc.name)``: wb's harmonizer MERGEd by name and wrote no id.
    """
    canon: Dict[str, Optional[str]] = field(default_factory=dict)       # cc key -> source
    auto: Dict[str, Set[str]] = field(default_factory=dict)             # concept -> owned auto cc keys
    pinned: Dict[str, Dict[str, Optional[str]]] = field(default_factory=dict)  # concept -> {cc: status}
    rejected: Set[Tuple[str, str]] = field(default_factory=set)         # (cc, concept)
    open_proposals: Set[Tuple[str, str]] = field(default_factory=set)   # (cc, concept)


@dataclass
class CanonicalPlan:
    id: str
    name: str
    exists: bool
    foreign: bool  # exists and is not ours: attach edges only, never SET


@dataclass
class AutoEdge:
    concept_id: str
    cc_id: str
    method: str
    confidence: float


@dataclass
class Proposal:
    cc_id: str
    concept_id: str
    other_id: str  # the Concept whose component supplied the cc
    confidence: float
    method: str
    evidence: List[str]
    cos: Optional[float]


@dataclass
class AlignmentPlan:
    canonicals: Dict[str, CanonicalPlan] = field(default_factory=dict)
    auto_edges: List[AutoEdge] = field(default_factory=list)
    proposals: List[Proposal] = field(default_factory=list)
    drop_auto: List[str] = field(default_factory=list)  # pinned concepts that still hold an auto edge
    managed: Set[str] = field(default_factory=set)       # concepts whose stale open proposals may be dropped
    stats: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- keys

def align_key(name: str) -> str:
    """`normalize_concept_name`, then every non-alphanumeric character becomes a space,
    then whitespace collapses. `Hydraulic-Pump`, `HYDRAULIC PUMP` and `Hydraulic/Pump`
    share a key; `Lockout/Tagout` is `lockout tagout`."""
    folded = normalize_concept_name(name)
    spaced = "".join(ch if ch.isalnum() else " " for ch in folded)
    return " ".join(spaced.split())


def _key_of(rec: ConceptRecord) -> str:
    return align_key(rec.name) or rec.name_normalized or rec.id


def _canonical_id(domain: str, name_key: str) -> str:
    return "canonical_" + hashlib.sha256(f"{domain}\x1f{name_key}".encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- signals

def _plural_variants(key: str) -> Set[str]:
    """The key as written, with every token's trailing `s` stripped, and with every token's
    trailing `es` stripped (tokens of 4+ characters). Two keys are the same plural pair when
    their variant sets meet, so `valve`/`valves` (strip `s`) and `box`/`boxes` (strip `es`)
    both match. The contract's one-sided "strip es or s" misses `valve`/`valves`."""
    toks = key.split()
    one = " ".join(t[:-1] if len(t) >= 4 and t.endswith("s") else t for t in toks)
    two = " ".join(t[:-2] if len(t) >= 4 and t.endswith("es") else t for t in toks)
    return {key, one, two}


def _initials(key: str) -> Optional[str]:
    toks = key.split()
    return "".join(t[0] for t in toks) if len(toks) >= 2 else None


def _jaccard_overlap(a: str, b: str) -> bool:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return False
    shared = ta & tb
    return (len(shared) / len(ta | tb) >= 0.5) and any(len(t) >= 4 for t in shared)


def _cosine(a: Optional[Sequence[float]], b: Optional[Sequence[float]]) -> Optional[float]:
    if a is None or b is None:
        return None
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return None
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _proposal_confidence(signals: Iterable[str], cos: Optional[float]) -> Tuple[str, float]:
    sig = next(s for s in _SIGNALS if s in set(signals))
    base, weight, fixed = _SIGNAL_CONF[sig]
    if cos is None:
        return sig, fixed
    return sig, base + weight * max(cos, 0.0)


# --------------------------------------------------------------------------- plan

class _UF:
    def __init__(self, items: Iterable[str]):
        self.p = {i: i for i in items}

    def find(self, x: str) -> str:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def plan_alignment(records: Sequence[ConceptRecord], existing: Existing, *,
                   scope: Optional[str] = None, settings: Optional[AlignSettings] = None,
                   domain: str = "TRAINING") -> AlignmentPlan:
    """The whole decision, with no I/O. Records and components span the WHOLE domain so ids
    stay consistent; `scope` (a Course id) only narrows what is EMITTED."""
    settings = settings or AlignSettings()
    recs = {r.id: r for r in sorted(records, key=lambda r: r.id)}
    ids = list(recs)
    key = {i: _key_of(recs[i]) for i in ids}
    by_key: Dict[str, List[str]] = defaultdict(list)
    for i in ids:
        by_key[key[i]].append(i)
    termkeys = {i: {k for k in (align_key(t) for t in recs[i].related_terms) if k} for i in ids}

    # 1. Auto links: undirected. link[(a, b)] = method, a < b.
    link: Dict[Tuple[str, str], str] = {}
    for members in by_key.values():
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                link[(members[x], members[y])] = "exact"
    for a in ids:
        for tk in termkeys[a]:
            for b in by_key.get(tk, ()):
                if b != a and key[a] in termkeys[b]:
                    link.setdefault((min(a, b), max(a, b)), "mutual_related_terms")

    # 2. Components.
    uf = _UF(ids)
    for a, b in link:
        uf.union(a, b)
    comps: Dict[str, List[str]] = defaultdict(list)
    for i in ids:
        comps[uf.find(i)].append(i)

    # A member's method is the strongest link INCIDENT to it (a member joined only
    # transitively keeps the method of its own link to the component).
    method_of: Dict[str, str] = {}
    for (a, b), m in link.items():
        for i in (a, b):
            if _METHOD_RANK[m] > _METHOD_RANK.get(method_of.get(i), 0):
                method_of[i] = m

    def member_method(i: str) -> str:
        return method_of.get(i, "self")

    pinned = {i: v for i, v in existing.pinned.items() if i in recs and v}
    scope_ids = {i for i in ids if scope is None or scope in recs[i].courses}

    # 3. A cc per component. Pinned ccs are claimed first so no other component reuses one.
    single_pinned: Dict[str, str] = {}
    conflicts: Dict[str, List[str]] = {}
    claimed: Set[str] = set()
    for root, members in comps.items():
        ccs = sorted({cc for m in members for cc in pinned.get(m, {})})
        if len(ccs) == 1:
            single_pinned[root] = ccs[0]
            claimed.add(ccs[0])
        elif len(ccs) > 1:
            conflicts[root] = ccs
            claimed.update(ccs)

    plan = AlignmentPlan()
    comp_cc: Dict[str, Optional[str]] = {}
    created = reused = 0
    for root in sorted(comps, key=lambda r: min(comps[r])):
        members = sorted(comps[root])
        chosen = min(members, key=lambda m: (-recs[m].teach_count, len(recs[m].name), recs[m].name))
        chosen_name = recs[chosen].name
        if root in conflicts:
            comp_cc[root] = None
            continue
        if root in single_pinned:
            cc = single_pinned[root]
        else:
            held = Counter(c for m in members for c in existing.auto.get(m, ()) if c not in claimed)
            if held:
                top = max(held.values())
                cc = min(c for c, n in held.items() if n == top)
            else:
                cc = _canonical_id(domain, align_key(chosen_name) or key[chosen])
                if cc in claimed:
                    cc = _canonical_id(domain, key[chosen] + "\x1f" + members[0])
            claimed.add(cc)
        comp_cc[root] = cc
        if any(m in scope_ids for m in members):
            src = existing.canon.get(cc)
            exists = cc in existing.canon
            plan.canonicals[cc] = CanonicalPlan(
                id=cc, name=chosen_name, exists=exists, foreign=exists and src != SOURCE)
            if exists:
                reused += 1
            else:
                created += 1

    # Emitted auto edges + conflict proposals.
    conflict_n = 0
    multi = 0
    auto_n = Counter()
    emit_roots = {r for r, ms in comps.items() if any(m in scope_ids for m in ms)}
    for root in emit_roots:
        members = sorted(comps[root])
        plan.managed.update(members)
        cc = comp_cc[root]
        if root in conflicts:
            conflict_n += 1
            for m in members:
                if m in pinned:
                    continue
                meth = member_method(m)
                for pc in conflicts[root]:
                    if (pc, m) in existing.rejected:
                        continue
                    plan.proposals.append(Proposal(pc, m, m, _AUTO_CONF[meth], meth, [meth], None))
            continue
        for m in members:
            if m in pinned:
                if existing.auto.get(m):
                    plan.drop_auto.append(m)
                continue
            meth = member_method(m)
            plan.auto_edges.append(AutoEdge(m, cc, meth, _AUTO_CONF[meth]))
            auto_n[meth] += 1
    multi = sum(1 for r in emit_roots if len(comps[r]) > 1)

    # 4. Lexical proposals across components.
    cand: Dict[Tuple[str, str], Set[str]] = defaultdict(set)

    def add(a: str, b: str, sig: str) -> None:
        if a != b:
            cand[(min(a, b), max(a, b))].add(sig)

    for a in ids:  # one-way related term (mutual ones are already one component)
        for tk in termkeys[a]:
            for b in by_key.get(tk, ()):
                add(a, b, "related_term_one_way")
    buckets: Dict[str, List[str]] = defaultdict(list)
    for i in ids:
        for v in _plural_variants(key[i]):
            buckets[v].append(i)
    for members in buckets.values():
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                a, b = members[x], members[y]
                if key[a] != key[b] and _plural_variants(key[a]) & _plural_variants(key[b]):
                    add(a, b, "plural")
    initials: Dict[str, List[str]] = defaultdict(list)
    for i in ids:
        ini = _initials(key[i])
        if ini:
            initials[ini].append(i)
    for i in ids:
        if " " not in key[i] and 2 <= len(key[i]) <= 6:
            for j in initials.get(key[i], ()):
                add(i, j, "acronym")
    tok_idx: Dict[str, List[str]] = defaultdict(list)
    for i in ids:
        for t in set(key[i].split()):
            if len(t) >= 4:
                tok_idx[t].append(i)
    seen_overlap: Set[Tuple[str, str]] = set()
    for members in tok_idx.values():
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                pair = (min(members[x], members[y]), max(members[x], members[y]))
                if pair not in seen_overlap:
                    seen_overlap.add(pair)
                    if _jaccard_overlap(key[pair[0]], key[pair[1]]):
                        add(pair[0], pair[1], "token_overlap")

    slide_sets = {i: set(recs[i].slides) for i in ids}
    comp_of = {i: uf.find(i) for i in ids}
    lexical: List[Proposal] = []
    for (a, b), sigs in cand.items():
        if comp_of[a] == comp_of[b]:
            continue
        if slide_sets[a] & slide_sets[b]:  # co-taught: the model listed them as different
            continue
        if scope is not None and a not in scope_ids and b not in scope_ids:
            continue
        cos = _cosine(recs[a].vector, recs[b].vector)
        meth, conf = _proposal_confidence(sigs, cos)
        if conf < settings.propose_min:
            continue
        for target, other in ((a, b), (b, a)):
            cc = comp_cc.get(comp_of[other])
            if cc is None or (cc, target) in existing.rejected:
                continue
            if cc in pinned.get(target, {}):
                continue
            lexical.append(Proposal(cc, target, other, conf, meth, sorted(sigs), cos))
    # Cap per target Concept, highest confidence first (ties: deterministic by cc, other).
    per_target: Dict[str, List[Proposal]] = defaultdict(list)
    for p in lexical:
        per_target[p.concept_id].append(p)
    for target in sorted(per_target):
        ranked = sorted(per_target[target], key=lambda p: (-p.confidence, p.cc_id, p.other_id))
        plan.proposals.extend(ranked[: settings.max_proposals])

    # Canonicals referenced by an emitted proposal must be attachable even when their own
    # component is out of scope (the cc exists already or is created by the fleet run).
    for p in plan.proposals:
        if p.cc_id not in plan.canonicals and p.cc_id in existing.canon:
            plan.canonicals[p.cc_id] = CanonicalPlan(
                p.cc_id, "", True, existing.canon.get(p.cc_id) != SOURCE)
    # A proposal whose cc is not yet in the graph and not in this plan cannot be written.
    plan.proposals = [p for p in plan.proposals if p.cc_id in plan.canonicals]

    by_method = Counter(p.method for p in plan.proposals)
    acc = sum(1 for v in pinned.values() if "accepted" in v.values())
    plan.stats = {
        "concepts": len(ids),
        "components": len(comps),
        "multi_member_components": multi,
        "auto_edges": {m: auto_n.get(m, 0) for m in ("exact", "mutual_related_terms", "self")},
        "proposals": dict(by_method),
        "canonical_created": created,
        "canonical_reused": reused,
        "pinned_accepted": acc,
        "pinned_legacy": len(pinned) - acc,
        "rejected_pairs": len(existing.rejected),
        "conflicting_components": conflict_n,
        "concepts_without_vector": sum(1 for r in recs.values() if r.vector is None),
    }
    return plan


# --------------------------------------------------------------------------- I/O

def _label(value: str, what: str) -> str:
    if not _LABEL.match(value or ""):
        raise ValueError(f"{what} {value!r} is not a safe Neo4j label")
    return value


def _unit_mean(vectors: List[List[float]]) -> Optional[List[float]]:
    acc: Optional[List[float]] = None
    n = 0
    for v in vectors:
        norm = math.sqrt(sum(x * x for x in v))
        if norm == 0:
            continue
        if acc is None:
            acc = [0.0] * len(v)
        elif len(v) != len(acc):
            continue
        for k, x in enumerate(v):
            acc[k] += x / norm
        n += 1
    return [x / n for x in acc] if acc is not None and n else None


def _slide_vectors(weaviate_client, collection: str, slide_ids: Sequence[str]) -> Dict[str, List[float]]:
    from weaviate.classes.query import Filter
    from weaviate.util import generate_uuid5

    coll = weaviate_client.collections.get(collection)
    by_uuid = {str(generate_uuid5(s)): s for s in slide_ids}
    out: Dict[str, List[float]] = {}
    ids = list(slide_ids)
    for start in range(0, len(ids), _VECTOR_BATCH):
        batch = ids[start:start + _VECTOR_BATCH]
        res = coll.query.fetch_objects(
            filters=Filter.by_property("chunk_id").contains_any(batch),
            limit=len(batch) * 2, include_vector=True)
        for obj in res.objects:
            props = obj.properties or {}
            if props.get("chunk_kind") == "section":
                continue
            vec = obj.vector
            if isinstance(vec, dict):
                vec = vec.get("default") or next(iter(vec.values()), None)
            sid = by_uuid.get(str(obj.uuid)) or props.get("chunk_id")
            if vec and sid:
                out[sid] = [float(x) for x in vec]
    return out


def load_records(neo4j_client, weaviate_client, collection: str, domain: str, *,
                 slide_label: str = "Chunk", course_label: str = "Document") -> List[ConceptRecord]:
    d, sl, cl = _label(domain, "domain"), _label(slide_label, "slide label"), _label(course_label, "course label")
    rows = neo4j_client.execute_query(f"""
        MATCH (c:Concept:{d})
        OPTIONAL MATCH (s:{sl}:{d})-[t:TEACHES]->(c)
        OPTIONAL MATCH (course:{cl}:{d})-[:HAS_CHILD]->(s)
        RETURN c.id AS id, c.name AS name, c.name_normalized AS name_normalized,
               s.id AS slide, course.id AS course, t.related_terms AS related_terms
    """, {}) or []
    recs: Dict[str, ConceptRecord] = {}
    terms: Dict[str, Set[str]] = defaultdict(set)
    for row in rows:
        r = recs.get(row["id"])
        if r is None:
            name = row.get("name") or ""
            r = recs[row["id"]] = ConceptRecord(
                id=row["id"], name=name,
                name_normalized=row.get("name_normalized") or normalize_concept_name(name))
        if row.get("slide") and row["slide"] not in r.slides:
            r.slides.append(row["slide"])
            r.teach_count += 1
            for t in row.get("related_terms") or ():
                if t and str(t).strip():
                    terms[r.id].add(str(t).strip())
        if row.get("course") and row["course"] not in r.courses:
            r.courses.append(row["course"])
    for r in recs.values():
        r.related_terms = sorted(terms[r.id])
        r.slides.sort()
        r.courses.sort()
    all_slides = sorted({s for r in recs.values() for s in r.slides})
    vectors = _slide_vectors(weaviate_client, collection, all_slides) if all_slides else {}
    for r in recs.values():
        r.vector = _unit_mean([vectors[s] for s in r.slides if s in vectors])
    return sorted(recs.values(), key=lambda r: r.id)


def load_existing(neo4j_client, domain: str) -> Existing:
    d = _label(domain, "domain")
    ex = Existing()
    for row in neo4j_client.execute_query(f"""
        MATCH (cc:CanonicalConcept)-[r:ALIGNS_TO]->(c:Concept:{d})
        RETURN coalesce(cc.id, cc.name) AS cc, cc.source AS source, c.id AS concept, r.status AS status
    """, {}) or []:
        ex.canon[row["cc"]] = row.get("source")
        if row.get("status") == "auto":
            ex.auto.setdefault(row["concept"], set()).add(row["cc"])
        else:
            ex.pinned.setdefault(row["concept"], {})[row["cc"]] = row.get("status")
    for row in neo4j_client.execute_query(f"""
        MATCH (cc:CanonicalConcept)-[p:PROPOSED_ALIGNS_TO]->(c:Concept:{d})
        RETURN coalesce(cc.id, cc.name) AS cc, cc.source AS source, c.id AS concept, p.status AS status
    """, {}) or []:
        ex.canon.setdefault(row["cc"], row.get("source"))
        if row.get("status") == "rejected":
            ex.rejected.add((row["cc"], row["concept"]))
        elif row.get("status") == "open":
            ex.open_proposals.add((row["cc"], row["concept"]))
    return ex


def apply_plan(neo4j_client, plan: AlignmentPlan, domain: str) -> Dict[str, int]:
    """Idempotent. Every statement is parameterised and batched with UNWIND. Guards live in
    the Cypher: an auto edge is only ever replaced when its status is 'auto', a proposal is
    only ever touched when it is absent or 'open'."""
    d = _label(domain, "domain")
    q = neo4j_client.execute_query

    ours = [{"id": c.id, "name": c.name} for c in plan.canonicals.values() if not c.foreign and c.name]
    if ours:
        q(f"""
            UNWIND $rows AS row
            MERGE (cc:CanonicalConcept:{d} {{id: row.id}})
            ON CREATE SET cc.name = row.name, cc.domain = $domain,
                          cc.source = '{SOURCE}', cc.created_at = datetime()
            WITH cc, row WHERE cc.source = '{SOURCE}'
            SET cc.name = row.name
        """, {"rows": ours, "domain": domain})

    if plan.drop_auto:
        q(f"""
            UNWIND $ids AS cid
            MATCH (:CanonicalConcept)-[old:ALIGNS_TO]->(c:Concept:{d} {{id: cid}})
            WHERE old.status = 'auto'
            DELETE old
        """, {"ids": plan.drop_auto})

    if plan.auto_edges:
        rows = [{"concept": e.concept_id, "cc": e.cc_id, "method": e.method,
                 "confidence": e.confidence} for e in plan.auto_edges]
        q(f"""
            UNWIND $rows AS row
            MATCH (other:CanonicalConcept)-[old:ALIGNS_TO]->(c:Concept:{d} {{id: row.concept}})
            WHERE old.status = 'auto' AND coalesce(other.id, other.name) <> row.cc
            DELETE old
        """, {"rows": rows})
        q(f"""
            UNWIND $rows AS row
            MATCH (c:Concept:{d} {{id: row.concept}})
            MATCH (cc:CanonicalConcept) WHERE coalesce(cc.id, cc.name) = row.cc
            OPTIONAL MATCH (cc)-[ex:ALIGNS_TO]->(c)
            WITH cc, c, row, ex WHERE ex IS NULL OR ex.status = 'auto'
            MERGE (cc)-[r:ALIGNS_TO]->(c)
            SET r.status = 'auto', r.method = row.method, r.confidence = row.confidence,
                r.source = '{SOURCE}', r.updated_at = datetime()
        """, {"rows": rows})

    keep = [[p.cc_id, p.concept_id] for p in plan.proposals]
    if plan.managed:
        q(f"""
            MATCH (cc:CanonicalConcept)-[p:PROPOSED_ALIGNS_TO]->(c:Concept:{d})
            WHERE c.id IN $managed AND p.status = 'open'
              AND NOT [coalesce(cc.id, cc.name), c.id] IN $keep
            DELETE p
        """, {"managed": sorted(plan.managed), "keep": keep})
    if plan.proposals:
        rows = [{"cc": p.cc_id, "concept": p.concept_id, "confidence": p.confidence,
                 "method": p.method, "evidence": p.evidence, "cos": p.cos}
                for p in plan.proposals]
        q(f"""
            UNWIND $rows AS row
            MATCH (c:Concept:{d} {{id: row.concept}})
            MATCH (cc:CanonicalConcept) WHERE coalesce(cc.id, cc.name) = row.cc
            OPTIONAL MATCH (cc)-[old:PROPOSED_ALIGNS_TO]->(c)
            WITH cc, c, row, old WHERE old IS NULL OR old.status = 'open'
            MERGE (cc)-[p:PROPOSED_ALIGNS_TO]->(c)
            SET p.status = 'open', p.confidence = row.confidence, p.method = row.method,
                p.evidence = row.evidence, p.cos = row.cos
        """, {"rows": rows})

    gone = q(f"""
        MATCH (cc:CanonicalConcept:{d}) WHERE cc.source = '{SOURCE}'
          AND NOT (cc)-[:ALIGNS_TO]-()
          AND size([(cc)-[x]-() WHERE NOT (type(x) = 'PROPOSED_ALIGNS_TO' AND x.status = 'open') | x]) = 0
        WITH cc DETACH DELETE cc
        RETURN count(*) AS n
    """, {})
    return {"canonical_deleted": int(gone[0]["n"]) if gone else 0}


def normalise(neo4j_client, weaviate_client, collection: str, domain: str = "TRAINING",
              course_id: Optional[str] = None, dry_run: bool = False, *,
              settings: Optional[AlignSettings] = None) -> Dict[str, Any]:
    """load -> plan -> (apply unless dry_run) -> a summary dict, also logged as one line."""
    t0 = time.monotonic()
    records = load_records(neo4j_client, weaviate_client, collection, domain)
    existing = load_existing(neo4j_client, domain)
    t1 = time.monotonic()
    plan = plan_alignment(records, existing, scope=course_id,
                          settings=settings or AlignSettings.from_env(), domain=domain)
    t2 = time.monotonic()
    summary = dict(plan.stats)
    summary["canonical_deleted"] = 0
    if not dry_run:
        summary.update(apply_plan(neo4j_client, plan, domain))
    t3 = time.monotonic()
    summary["seconds"] = {"load": round(t1 - t0, 2), "plan": round(t2 - t1, 2),
                          "apply": round(t3 - t2, 2)}
    summary["dry_run"] = dry_run
    log.info("concepts.normalise domain=%s course=%s %s", domain, course_id, summary)
    return summary
