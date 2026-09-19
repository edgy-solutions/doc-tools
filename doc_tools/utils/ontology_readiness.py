"""Per-domain ontology ingest posture — PURE, so the rules are testable without a cluster.

RULING 3 (architect, 2026-09-19), via Lane 1 dispatch 7f:

    Today the sentinel answers "is Weaviate up". The ruling: one class per manifest entry,
    per domain. A sentinel that checks a single well-known class is a STORE LIVENESS CHECK
    WEARING AN INGEST CHECK'S NAME — it is green the moment Weaviate answers, including when
    the MAINTENANCE domain ingested nothing at all.

    That is not hypothetical here: the safety classes were re-ingested once, by hand, and the
    sentinel was green on both sides of that. It could not tell.

WHAT THE INCUMBENT ACTUALLY IS, since the dispatch describes it rather than naming it.
`agent_fleet/ontology_service/main.py:/health` in invincible-agent returns
`{"jena_configured": ..., "neo4j_configured": ...}` — both read out of
`substrate_posture.py`, which derives them FROM THE ENVIRONMENT. It is a configuration
read, not a store read; it cannot see a row and so cannot see a missing one. Its own
docstring already caught this class of error once ("`jena_configured` replaces the former
`jena_reachable`, which reported `endpoint != ""` — a CONFIGURATION read wearing a
reachability name"). This module is one more step along the same axis: reachability is not
population either.

THE CIRCULARITY THAT MAKES THIS HARD, AND WHY THE EXPECTATION COMES FROM OUTSIDE THE STORE.
The obvious implementation asks Weaviate which domains it holds and checks each has rows.
That is vacuous exactly when it matters: a domain that ingested NOTHING contributes no rows,
so it is not in the list, so it is never checked, and the sentinel is green. The expected set
must come from somewhere the failure cannot erase it.

WHERE IT COMES FROM, AND WHY NOT THE MANIFEST. `CANONICAL_TTL_MANIFEST` lives in
`invincible-agent/setup/prime_databases.py`; doc-tools has no copy and must not grow one —
see the block comment above `partition_ontology_classes` for the two-masters argument in
full. The declared source available HERE is the ontology bucket in MinIO: prime uploads one
object per manifest entry and stamps `x-amz-meta-domain` on it. So the expectation is
`{s3_key -> domain}` read off the bucket — downstream of the manifest, outside Weaviate, and
not a second copy of anything. An entry that never ingested still has its object, so it is
still expected, so its absence still reds.

PER ENTRY, NOT PER DOMAIN, and the difference is the whole ruling. MAINTENANCE has SIX
manifest entries. A per-domain check passes when one of the six lands, which is the same
defect one level in.

FOUR STATES, NOT TWO — the same discipline as PRESENT/ABSENT/UNREAD on `_tool_urn` and as
authored/derived/derived-opaque on class labels. Two states would relabel a real limit as a
success:

    INGESTED      the entry has rows attributed to it. The only green state.
    ABSENT        the entry is declared and has no rows. The failure being hunted.
    EXCLUDED      the entry declares no groundable class AT ALL — every class it declares is
                  meta-ontology or a response shape, or it is a class-less policy/rules TTL.
                  Zero rows is CORRECT here, and calling it ABSENT would train readers to
                  ignore the red.
    UNATTRIBUTED  the domain has rows but none carries `source_ontology`, so this entry
                  cannot be told apart from its neighbours. Rows written before 2026-09-19
                  are all like this. NOT green: it is a measurement that could not be made,
                  and reporting it as INGESTED would be the sentinel lying in the direction
                  it was built to stop lying in.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

#: The only state that counts as ingested.
STATE_INGESTED = "INGESTED"
#: Declared by the bucket, zero rows in the store. The ruling's target.
STATE_ABSENT = "ABSENT"
#: Declared, and correctly contributes no groundable row.
STATE_EXCLUDED = "EXCLUDED"
#: Rows exist for the domain but carry no source, so this entry cannot be resolved.
STATE_UNATTRIBUTED = "UNATTRIBUTED"


@dataclass(frozen=True)
class EntryPosture:
    """One manifest entry (one s3 object), and whether its classes reached the store."""

    s3_key: str
    domain: str
    state: str
    rows: int

    @property
    def ready(self) -> bool:
        return self.state in (STATE_INGESTED, STATE_EXCLUDED)


@dataclass(frozen=True)
class DomainPosture:
    """One semantic domain, and every entry that claims to populate it."""

    domain: str
    entries: tuple[EntryPosture, ...]

    @property
    def rows(self) -> int:
        return sum(e.rows for e in self.entries)

    @property
    def not_ready(self) -> tuple[EntryPosture, ...]:
        return tuple(e for e in self.entries if not e.ready)

    @property
    def ready(self) -> bool:
        """A domain is ready when EVERY entry that claims it is ready.

        Not "when it has rows". A domain with five failed entries and one good one has rows,
        and is the exact state this module exists to refuse calling green.
        """
        return bool(self.entries) and not self.not_ready


def ontology_ingest_posture(
    declared: Mapping[str, str],
    rows_by_source: Mapping[str, int],
    excluded_sources: frozenset = frozenset(),
    unattributed_rows_by_domain: Mapping[str, int] | None = None,
) -> tuple[DomainPosture, ...]:
    """Derive the per-entry, per-domain posture. No I/O, no globals.

    Args:
        declared: ``{s3_key: DOMAIN}`` — every manifest entry, read off the ontology
            bucket. THE EXPECTATION, and it must come from here rather than from the
            store; see the module docstring on circularity.
        rows_by_source: ``{s3_key: row_count}`` as the store reports it.
        excluded_sources: entries known to contribute no groundable class by design
            (all-meta, all-response-shape, or class-less policy/rules TTLs). Zero rows is
            correct for these and must not read as a failure.
        unattributed_rows_by_domain: ``{DOMAIN: count}`` of rows carrying no
            ``source_ontology``. An entry with no rows of its own, in a domain that has
            unattributed rows, is UNATTRIBUTED rather than ABSENT — the measurement could
            not be made, which is not the same as the ingest having failed.

    Returns one DomainPosture per domain, domains sorted, entries sorted within each.
    """
    unattributed = dict(unattributed_rows_by_domain or {})
    by_domain: dict[str, list[EntryPosture]] = {}

    for s3_key in sorted(declared):
        domain = declared[s3_key]
        rows = int(rows_by_source.get(s3_key, 0))
        if rows > 0:
            state = STATE_INGESTED
        elif s3_key in excluded_sources:
            state = STATE_EXCLUDED
        elif unattributed.get(domain, 0) > 0:
            state = STATE_UNATTRIBUTED
        else:
            state = STATE_ABSENT
        by_domain.setdefault(domain, []).append(
            EntryPosture(s3_key=s3_key, domain=domain, state=state, rows=rows)
        )

    return tuple(
        DomainPosture(domain=d, entries=tuple(by_domain[d]))
        for d in sorted(by_domain)
    )


def format_posture(postures: tuple[DomainPosture, ...]) -> str:
    """A report a human reads in a log, listing every state rather than a verdict.

    A sentinel that prints only its verdict cannot be checked; the whole point of the four
    states is that the reader can see WHICH entry is in which, and the summary line is the
    last thing, not the only thing.
    """
    lines: list[str] = []
    for dp in postures:
        mark = "READY" if dp.ready else "NOT-READY"
        lines.append(f"{mark:<9} {dp.domain:<20} {dp.rows} row(s)")
        for e in dp.entries:
            lines.append(f"          - {e.state:<13} {e.s3_key} ({e.rows} row(s))")
    ready = sum(1 for p in postures if p.ready)
    lines.append(
        f"{ready}/{len(postures)} domain(s) ready; "
        f"{sum(len(p.not_ready) for p in postures)} entry/entries not ready."
    )
    return "\n".join(lines)
