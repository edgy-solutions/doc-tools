"""The batch-fixture scrubber: substitutes part-shaped identifiers in a text layer
and emits the ledger that proves what it did.

Implements the engine ``docs/contracts/scrub-ledger.md`` section 9 says was
missing ("No scrubber. No tokeniser, no allowlist file, no PDF rewriting"). It
emits into ``ledger.py``'s API and changes none of it. Design:
``invincible-agent/sessions/2026-10-22-design-from-7f-batch-fixture-scrubber-for-chris-review.md``.

THE ONE HARD RULE (design 3.3)
------------------------------
**Allowlist by VOCABULARY, scrub by SHAPE, and let the allowlist win.** Matching
order is allowlist FIRST; substitution only on what survives it. The tempting
simplification (scrub everything part-shaped) silently destroys the headers, and
the headers are what the fixture tests.

WHY THE INPUT IS BLOCKS AND NOT TEXT
------------------------------------
``SubstitutionClass`` requires every substitution to say what it WAS, and a class
cannot be guessed from a string: the scrubber knows it because it knows which
column or block it took the value from. A block that declares no class
(``scrub_class=None``) can only have a candidate substituted if that candidate
EQUALS an original already classified in another block (design 2.2a: the notice
that names a part in prose and again in a table).

That rule is LOAD-BEARING. This repo has already written page furniture into a
scored field, and ``DIC-034 R5`` and ``Page 2 of 6`` are part-shaped by
``looks_like_mpn``. A scrubber that scrubbed every part-shaped token would
rewrite the form number, the page footer and the revision stamp. A candidate in
an unclassed block that matches no known original is therefore NOT guessed at:
it is reported as ``unclassified``, and in ``strict`` mode the leak test is
REFUSED for it -- an unclassified part-shaped token cannot be promised scrubbed.

WHAT THIS ENGINE DOES NOT DO
----------------------------
No PDF rewriting (so the equivalence seal is ``not_run``, and the ledger is NOT
committable -- correct, because a text layer is not a committable PDF fixture),
no image scrubbing, no mapping store. Nothing under ``doc_tools/`` imports this
module (design 7: the scrubber is not in the ingest path).
"""
from __future__ import annotations

import datetime as _dt
from collections import Counter
from dataclasses import dataclass, replace
from typing import Dict, Iterable, List, Optional, Tuple

from doc_tools.scrub.allowlist import Allowlist
from doc_tools.scrub.draw import (RESERVED_LEADING_UPPER, Drawer)
from doc_tools.scrub.ledger import (LEDGER_VERSION, AllowlistRule, CheckName,
                                    CheckResult, MappingPolicy, Policy,
                                    PolicyAnswer, ScrubLedger, SourceRef,
                                    SubstitutionClass, redact, shape_of,
                                    shapes_equal)

TOOL_VERSION = "doc_tools.scrub.scrubber/1"

#: A scrubbed candidate must be at least this long: matches
#: ``table_text_layer._MIN_AFFIX_REPAIR_LEN`` ("matches looks_like_mpn: below
#: this a prefix match means nothing").
MIN_CANDIDATE_LEN = 4

RECOMMENDED_POLICY = Policy(
    manufacturer_name=PolicyAnswer.ALLOWLISTED,
    dates=PolicyAnswer.ALLOWLISTED,
    mapping=MappingPolicy.ONE_WAY,
    enters_scored_corpus=False,
    authority=(
        "RECOMMENDATION, NOT A RULING: section 5 of the 2026-10-22 design "
        "asks four rulings and none has landed. These are the four answers "
        "recommended there (manufacturer allowlisted, dates allowlisted, "
        "one-way mapping, not in the scored corpus); a fixture built under "
        "them is invalidated by any ruling that disagrees."))


@dataclass(frozen=True)
class Block:
    text: str
    page: int  # >= 1
    kind: str  # Site.kind: "table_cell" | "body_text" | "caption" | ...
    row: Optional[int] = None
    col: Optional[int] = None
    scrub_class: Optional[SubstitutionClass] = None


@dataclass(frozen=True)
class ScrubOutcome:
    blocks: Tuple[Block, ...]  # scrubbed, same order, same geometry
    text: str  # the scrubbed blocks joined as given
    ledger: ScrubLedger  # validated through ScrubLedger.model_validate
    unclassified: Tuple[str, ...]  # part-shaped tokens in unclassed blocks
    mapping: Optional[Dict[str, str]]  # ONLY when policy.mapping is RETAINED


def describe_source(blocks: Iterable[Block], *, bucket: str, key: str,
                    data: bytes) -> SourceRef:
    """A ``SourceRef`` for a text layer: location and redacted digest only."""
    blocks = tuple(blocks)
    if not blocks:
        raise ValueError("no blocks to describe")
    return SourceRef(bucket=bucket, key=key, sha256=redact(data),
                     pages=max(b.page for b in blocks),
                     tables=sum(1 for b in blocks if b.kind == "table_cell"))


# ----------------------------------------------------------------------
# Tokenising and the candidate floor
# ----------------------------------------------------------------------
def _tokens(text: str) -> List[Tuple[int, int, str]]:
    """Whitespace/separator tokens with trailing ``.,;:`` stripped.

    Reuses ``table_text_layer._DOC_TOKEN`` and ``_TOKEN_TRAILERS`` rather than
    writing a third tokeniser (imports are lazy: that module pulls the
    extraction stack).
    """
    from doc_tools.utils.table_text_layer import _DOC_TOKEN, _TOKEN_TRAILERS

    out = []
    for m in _DOC_TOKEN.finditer(text):
        tok = m.group(0).rstrip(_TOKEN_TRAILERS)
        if tok:
            out.append((m.start(), m.start() + len(tok), tok))
    return out


def _is_candidate(token: str) -> bool:
    """The candidate floor (after the allowlist-overlap test).

    ``looks_like_mpn`` is a CELL test, not a token test: ``looks_like_mpn("2")``
    is true, so ``Page 2 of 6`` would otherwise be two candidates. The length
    and letter-AND-digit conditions exist for that measurement.
    """
    from doc_tools.utils.table_text_layer import looks_like_mpn

    return (len(token) >= MIN_CANDIDATE_LEN
            and looks_like_mpn(token)
            and any(c.isalpha() for c in token)
            and any(c.isdigit() for c in token))


def _is_candidate_shape_only(token: str) -> bool:
    """The floor of the tempting simplification: any identifier-shaped token.
    Used only by the inverted-precedence guard hook."""
    return any(c.isalnum() for c in token)


def _candidates(text: str, spans, floor) -> List[Tuple[int, int, str]]:
    out = []
    for start, end, tok in _tokens(text):
        if any(s.start < end and start < s.end for s in spans):
            continue  # THE PRECEDENCE RULE: the allowlist wins
        if floor(tok):
            out.append((start, end, tok))
    return out


def _rules_for(policy: Policy) -> frozenset:
    rules = set(AllowlistRule)
    if policy.manufacturer_name is PolicyAnswer.SCRUBBED:
        rules.discard(AllowlistRule.MANUFACTURER_NAME)
    if policy.dates is PolicyAnswer.SCRUBBED:
        rules.discard(AllowlistRule.DATE)
    return frozenset(rules)


# ----------------------------------------------------------------------
def scrub(blocks: Iterable[Block], *, salt: bytes, salt_ref: str,
          fixture_id: str, source: SourceRef, allowlist: Allowlist,
          policy: Policy = RECOMMENDED_POLICY,
          known_mpns: frozenset = frozenset(),
          strict: bool = True,
          mapping_ref: Optional[str] = None,
          run_at: Optional[str] = None,
          _allowlist_first: bool = True) -> ScrubOutcome:
    """Scrub ``blocks`` and return the scrubbed blocks with a validated ledger.

    ``_allowlist_first`` exists ONLY so a test can invert the precedence and
    prove it is load-bearing (design 3.3's guard). Inverted, the allowlist is
    not consulted for candidacy and the floor is shape-only -- "scrub everything
    identifier-shaped" -- which is the simplification that destroys the headers.
    The production default is True and nothing outside tests passes False.
    """
    blocks = tuple(blocks)
    retained = policy.mapping is MappingPolicy.RETAINED
    if retained and not mapping_ref:
        raise ValueError("policy.mapping is retained: mapping_ref must name "
                         "where the mapping lives")
    if not retained and mapping_ref:
        raise ValueError("policy.mapping is one_way: a one-way scrub keeps no "
                         "re-identification key, so there is no mapping_ref")

    rules = _rules_for(policy)
    floor = _is_candidate if _allowlist_first else _is_candidate_shape_only

    def spans_of(text: str):
        return allowlist.spans(text, rules=rules)

    src_spans = [spans_of(b.text) for b in blocks]
    used_spans = src_spans if _allowlist_first else [() for _ in blocks]
    cands = [_candidates(b.text, used_spans[i], floor)
             for i, b in enumerate(blocks)]

    # Pass 1: classified blocks define the originals and their classes.
    classes: Dict[str, SubstitutionClass] = {}
    for b, cs in zip(blocks, cands):
        if b.scrub_class is None:
            continue
        for _s, _e, tok in cs:
            classes.setdefault(tok, b.scrub_class)

    allow_texts = {s.text for spans in src_spans for s in spans}
    all_candidates = {tok for cs in cands for _s, _e, tok in cs}
    drawer = Drawer(salt, forbidden=frozenset(known_mpns) | frozenset(all_candidates)
                    | frozenset(allow_texts))
    draws = {orig: drawer.draw(orig) for orig in classes}  # first-seen order

    # Pass 2: rewrite every block; record every occurrence.
    sites: Dict[str, List[dict]] = {o: [] for o in draws}
    unclassified: set = set()
    out_blocks: List[Block] = []
    for b, cs in zip(blocks, cands):
        pieces, cursor = [], 0
        for s, e, tok in cs:
            if tok in draws:
                pieces.append(b.text[cursor:s])
                pieces.append(draws[tok].replacement)
                cursor = e
                sites[tok].append({"page": b.page, "kind": b.kind,
                                   "row": b.row, "col": b.col})
            elif b.scrub_class is None:
                unclassified.add(tok)
        pieces.append(b.text[cursor:])
        out_blocks.append(replace(b, text="".join(pieces)))
    out_blocks_t = tuple(out_blocks)
    text = "\n".join(b.text for b in out_blocks_t)
    unclassified_t = tuple(sorted(unclassified))

    substitutions = [
        {"class": classes[o].value, "shape": shape_of(o), "original": redact(o),
         "replacement": d.replacement, "occurrences": len(sites[o]),
         "sites": sites[o], "reserved_space": d.reserved_space,
         "redraws": d.redraws}
        for o, d in draws.items()]

    # ---- the six checks, measured -------------------------------------
    src_counts: Counter = Counter()
    for spans in src_spans:
        for s in spans:
            src_counts[(s.text, s.rule)] += 1
    out_counts: Counter = Counter()
    for b in out_blocks_t:
        for s in spans_of(b.text):
            out_counts[(s.text, s.rule)] += 1

    hits = sum(1 for o in draws if o in text)
    k = len(unclassified_t)
    if hits:
        leak_result = CheckResult.FAIL
    elif strict and k:
        leak_result = CheckResult.REFUSED
    else:
        leak_result = CheckResult.PASS
    leak_detail = (
        f"{len(draws)} originals searched for in the scrubbed text layer: "
        f"{hits} present. {k} part-shaped token(s) sit in blocks that declare "
        f"no class and match no classified original.")
    if strict and k and not hits:
        leak_detail += (
            " REFUSED (strict): an unclassified part-shaped token cannot be "
            "promised scrubbed; failing closed.")
    elif k:
        leak_detail += " Not refused because strict is off: the leak test is weaker."
    leak_detail += (
        " SCOPE: the text layer produced by this scrub only. Annotations, XMP "
        "metadata, embedded attachments and glyphs inside an image are invisible "
        "to a text-layer scrub and are NOT covered.")
    if policy.dates is PolicyAnswer.SCRUBBED:
        leak_detail += (" dates were scrubbed under this policy: LTB scoring "
                        "cannot come off this fixture.")

    shape_bad = sum(1 for o, d in draws.items()
                    if not shapes_equal(shape_of(o), d.replacement))
    allow_ok = src_counts == out_counts
    lost = sum((src_counts - out_counts).values())
    struct_bad = 0
    for a, b in zip(blocks, out_blocks_t):
        if (a.page, a.kind, a.row, a.col, len(a.text)) != (
                b.page, b.kind, b.row, b.col, len(b.text)):
            struct_bad += 1
    originals_set = set(draws)
    repls = [d.replacement for d in draws.values()]
    coll = [r for r in repls if r in originals_set or r in known_mpns
            or r in allow_texts]
    coll_bad = len(coll) + (len(repls) - len(set(repls)))
    redraws = sum(d.redraws for d in draws.values())

    def chk(result, detail, **m):
        return {"result": result.value, "detail": detail, "measurements": m}

    checks = {
        CheckName.LEAK_TEST.value: chk(
            leak_result, leak_detail, originals=len(draws), hits=hits,
            unclassified_candidates=k,
            scope="text layer produced by this scrub"),
        CheckName.SHAPE_EQUALITY.value: chk(
            CheckResult.PASS if not shape_bad else CheckResult.FAIL,
            f"shapes_equal measured for each of {len(draws)} substitutions; "
            f"{shape_bad} mismatch(es).",
            substitutions=len(draws), mismatches=shape_bad),
        CheckName.ALLOWLIST_INTEGRITY.value: chk(
            CheckResult.PASS if allow_ok else CheckResult.FAIL,
            f"allowlist spans counted in the source and in the output: "
            f"{sum(src_counts.values())} in the source, "
            f"{sum(out_counts.values())} in the output, {lost} lost. A header "
            f"present fewer times than the source had it is a header scrubbed.",
            distinct=len(src_counts), source_spans=sum(src_counts.values()),
            output_spans=sum(out_counts.values()), lost=lost),
        CheckName.STRUCTURE_INVARIANCE.value: chk(
            CheckResult.PASS if not struct_bad and len(blocks) == len(out_blocks_t)
            else CheckResult.FAIL,
            f"{len(blocks)} blocks; page, kind, row, col and character length "
            f"compared per block: {struct_bad} changed. Length is a free "
            f"invariant because a shape-preserving replacement is the same length.",
            blocks=len(blocks), length_deltas=struct_bad),
        CheckName.EQUIVALENCE_SEAL.value: chk(
            CheckResult.NOT_RUN,
            "The seal runs the extractor on the source and on the fixture and "
            "compares after applying the mapping; this scrub produces a TEXT "
            "LAYER, not a PDF, so there is no fixture to extract from, and PDF "
            "rewriting is the next link in the chain."),
        CheckName.COLLISION_CHECK.value: chk(
            CheckResult.PASS if not coll_bad else CheckResult.FAIL,
            f"{len(repls)} replacements checked against the {len(originals_set)} "
            f"originals, the {len(known_mpns)} known MPNs supplied, the allowlisted "
            f"strings and each other: {coll_bad} collision(s); {redraws} "
            f"redraw(s) were forced. The check is only as strong as the set it "
            f"checks against: a caller that supplies an empty known-MPN set "
            f"(this one supplied {len(known_mpns)}) gets a check that proves "
            f"nothing about real part numbers.",
            checked=len(repls), redraws=redraws, known_mpns=len(known_mpns),
            reserved_space="leading uppercase from {" + ",".join(
                RESERVED_LEADING_UPPER) + "}"),
    }

    allowlisted = [{"text": t, "rule": r.value, "count": n}
                   for (t, r), n in sorted(src_counts.items(),
                                           key=lambda kv: (kv[0][1].value, kv[0][0]))]
    now = run_at or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {
        "ledger_version": LEDGER_VERSION,
        "fixture_id": fixture_id,
        "source": source.model_dump(),
        "scrub": {"tool_version": TOOL_VERSION, "run_at": now,
                  "salt_ref": salt_ref, "allowlist_ref": allowlist.ref,
                  "mapping_ref": mapping_ref if retained else None},
        "substitutions": substitutions,
        "allowlisted": allowlisted,
        "verification": {"checks": checks},
        "policy": policy.model_dump(),
    }
    ledger = ScrubLedger.model_validate(doc)

    # A one-way scrub keeps no re-identification key; returning one would be the
    # accident the policy exists to prevent.
    mapping = ({o: d.replacement for o, d in draws.items()} if retained else None)
    return ScrubOutcome(blocks=out_blocks_t, text=text, ledger=ledger,
                        unclassified=unclassified_t, mapping=mapping)
