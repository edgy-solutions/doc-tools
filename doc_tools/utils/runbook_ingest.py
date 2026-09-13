"""Runbook frontmatter -> DocPage, with the prefix pass-through sealed.

ADR-0041 ingest-on-arrival: a work-side runbook directory becomes `mesh:DocPage`
nodes carrying `explains` edges, so "what explains this verb" is a one-hop query
instead of a search index hoping to agree with reality (ADR-0037).

WHAT THIS MODULE IS FOR, AND WHY IT IS A SEPARATE SEAM. The whole risk of this
feature lives in ONE step: turning an author-written compact IRI (`docs:runbook-x`,
`mesh:resolveInstance`) into the full IRI the graph is keyed on. An unknown prefix
PASSES THROUGH VERBATIM if nothing stops it — the page stores `docs:runbook-x` as
its id, the linker's MATCH runs against full-IRI nodes, the two never meet, and
the page registers accepted-and-unreachable. Nothing is red at any layer. That is
the fourth instance of one class in this codebase this week, and the first caught
before a row existed.

So the rule is SEAL THE PASS-THROUGH, NOT JUST THE EXPANSION. A resolver that
expands what it knows and returns the input unchanged otherwise is the bug; the
unknown case has to refuse.

TWO HALVES, DELIBERATELY SEPARATE. Resolution (above) is a string operation and
needs no graph. EXISTENCE — the invented-IRI rule, "a doc that claims to explain
`mesh:composeReviewBatch` fails ingest if that IRI doesn't exist" (ADR-0037 §1) —
is a graph query and needs a session. `check_explains_targets` below is that half.
Keeping them apart is what lets the resolution rules be tested without standing up
Neo4j, and stops the graph half quietly pretending it does not need one.
Resolution is the PRECONDITION for existence: you cannot look up a target you have
not expanded.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

#: Compact-IRI prefixes this ingest will expand, and NOTHING ELSE resolves.
#:
#: `mesh:` was ruled canonical on 2026-09-12 (the served graph uses
#: `http://invincible-agent/{domain}#` everywhere the HUD renders it). The repo
#: previously carried BOTH that and `http://internal/mesh#`, and the wrong one
#: reached a seed TTL with ten citations on a namespace nothing else used — which
#: is the same pass-through failure this module exists to stop, one layer up.
#:
#: `docs:` WAS UNDECLARED WHEN THIS MODULE WAS FIRST WRITTEN — surveyed and found
#: in no ttl and no prefix table, while five runbook pages already carried
#: `iri: docs:runbook-…`. It is declared now, and this value is COPIED FROM THE
#: DECLARATION rather than chosen to match:
#:
#:   invincible-agent master ad00891
#:     setup/ontologies/mesh_system.ttl:680       @prefix docs: <http://invincible-agent/docs#>
#:     agent_fleet/utils/mesh_registration.py:646 "docs:": "http://invincible-agent/docs#"
#:
#: Read from both sides because a write-side table agreeing with itself proves
#: nothing; the ttl is what the graph is keyed on. Had it still been undeclared,
#: the right move was to REFUSE rather than pick a plausible expansion — every
#: page IRI would then have been wrong together, consistently, and every check
#: would have passed because they were all wrong the same way.
#:
#: THIS IS A CROSS-REPO CONSTANT WITH NO SHARED ENFORCEMENT. Nothing fails if
#: these two repos drift; the pages simply stop resolving, silently, which is the
#: same class of failure the table itself exists to prevent. A test pins the
#: value so a drift here is red, but it cannot see their side.
PREFIXES: Dict[str, Optional[str]] = {
    "mesh": "http://invincible-agent/mesh#",
    "docs": "http://invincible-agent/docs#",
}

#: Placeholders shipped in `docs/runbooks/_TEMPLATE.md`. The template's own
#: frontmatter says it is "DELIBERATELY UNFILLABLE AS SHIPPED" so that a copy
#: published without being filled in is refused, rather than admitted as a page
#: that explains nothing. That is the exclusion mechanism — NOT a filename
#: convention, which nothing enforces. Matching on the marker rather than on the
#: filename is what makes it hold for `my-new-runbook.md` copied from the template
#: and never edited.
_PLACEHOLDER = re.compile(r"REPLACE[-:_]?ME", re.IGNORECASE)

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)", re.DOTALL)


class RunbookRefused(Exception):
    """Ingest refused a page. The message NAMES the page and the reason.

    Refusals are the product here, not an error path: an admitted page that
    resolves to nothing is worse than a refused one, because it reports success.
    Every raise site states which file and which rule, so the remedy is in the
    log rather than in someone's head.
    """


def resolve_iri(compact: str, *, page: str) -> str:
    """Expand a compact IRI. REFUSES anything it cannot expand — never passes through.

    Absolute IRIs (`http://…`, `https://…`, `urn:…`) are returned unchanged: they
    are already the form the graph is keyed on and need no table.
    """
    value = (compact or "").strip()
    if not value:
        raise RunbookRefused(f"{page}: empty IRI — a page must name itself")

    if value.startswith(("http://", "https://", "urn:")):
        return value

    if ":" not in value:
        raise RunbookRefused(
            f"{page}: {value!r} is neither an absolute IRI nor prefixed. A bare "
            f"token cannot be resolved to a graph node, and storing it verbatim "
            f"would register a page nothing can reach."
        )

    prefix, _, local = value.partition(":")
    if prefix not in PREFIXES:
        raise RunbookRefused(
            f"{page}: unknown prefix {prefix!r} in {value!r}. Known prefixes: "
            f"{sorted(PREFIXES)}. REFUSING rather than storing it verbatim — an "
            f"unexpanded compact IRI is accepted by every layer and matched by "
            f"none, so the page would register successfully and be unreachable."
        )

    namespace = PREFIXES[prefix]
    if namespace is None:
        raise RunbookRefused(
            f"{page}: prefix {prefix!r} is recognised but has NO DECLARED "
            f"NAMESPACE. It is used by existing pages and declared in no ontology "
            f"and no prefix table. Resolving it would mean inventing the IRI that "
            f"every one of those pages is keyed on. Declare it in PREFIXES "
            f"(doc_tools/utils/runbook_ingest.py) once the canonical value is "
            f"ruled; until then these pages cannot be ingested correctly."
        )
    if not local:
        raise RunbookRefused(f"{page}: {value!r} has a prefix but no local name")

    return f"{namespace}{local}"


def parse_frontmatter(text: str, *, page: str) -> Dict[str, Any]:
    """Return the YAML frontmatter block, or REFUSE BY NAME if there is none."""
    match = _FRONTMATTER.match(text or "")
    if not match:
        raise RunbookRefused(
            f"{page}: no YAML frontmatter block. A page without frontmatter "
            f"declares no IRI and no explains targets, so it can be stored but "
            f"never reached — admitting it would grow the corpus without growing "
            f"what the corpus can answer."
        )

    import yaml  # local: keep this module importable without the extraction stack

    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        raise RunbookRefused(f"{page}: frontmatter is not valid YAML — {e}") from e

    if not isinstance(data, dict):
        raise RunbookRefused(
            f"{page}: frontmatter parsed to {type(data).__name__}, expected a mapping"
        )
    return data


def ingest_page(text: str, *, page: str) -> Tuple[str, List[str], Dict[str, Any]]:
    """Parse one runbook into `(page_iri, explains_iris, frontmatter)`.

    Raises `RunbookRefused` with a named reason for any page that must not enter
    the corpus. Returns fully-expanded IRIs — callers never see a compact form,
    so the pass-through cannot be reintroduced downstream by forgetting to expand.
    """
    data = parse_frontmatter(text, page=page)

    raw_iri = data.get("iri")
    if not isinstance(raw_iri, str) or not raw_iri.strip():
        raise RunbookRefused(f"{page}: frontmatter has no `iri:` — a page must name itself")

    if _PLACEHOLDER.search(raw_iri):
        raise RunbookRefused(
            f"{page}: `iri: {raw_iri}` still carries the _TEMPLATE.md placeholder. "
            f"The template is unfillable as shipped precisely so an unedited copy "
            f"is refused here rather than admitted as a page that explains nothing."
        )

    page_iri = resolve_iri(raw_iri, page=page)

    # `explains` MAY BE EMPTY, AND THE EMPTINESS IS A MEASUREMENT (ruled R-015,
    # 2026-09-11). `rolling-a-service.md` carries no targets because the mesh
    # models no deployment verb, and minting `mesh:rollService` to make the edge
    # look tidy is the exact move the invented-IRI rule refuses. An edgeless
    # runbook is still reachable by audience and by text. Requiring >= 1 target
    # would push authors toward inventing one, turning a gate into a generator of
    # the thing it guards against.
    raw_explains = data.get("explains") or []
    if isinstance(raw_explains, str):
        raw_explains = [raw_explains]
    if not isinstance(raw_explains, list):
        raise RunbookRefused(
            f"{page}: `explains:` must be a list, got {type(raw_explains).__name__}"
        )

    explains: List[str] = []
    for target in raw_explains:
        if not isinstance(target, str) or not target.strip():
            raise RunbookRefused(f"{page}: `explains` entry {target!r} is not a non-empty string")
        if _PLACEHOLDER.search(target):
            raise RunbookRefused(
                f"{page}: `explains` entry {target!r} is the _TEMPLATE.md placeholder"
            )
        explains.append(resolve_iri(target, page=page))

    return page_iri, explains, data


# ---------------------------------------------------------------------------
# The graph half — the invented-IRI rule
# ---------------------------------------------------------------------------

#: ASK BOTH QUESTIONS. AN `explains` TARGET MAY BE A NODE **OR** A RELATIONSHIP.
#:
#: A probe that asks only the class question reports every relationship-typed
#: target as dangling — with total confidence, as a clean finding, which is the
#: worst shape a wrong answer can take. Measured in-cluster by
#: invincible-agent-f3: 8/8 targets resolved, 4 as :OntologyClass nodes
#: (DispositionReview, Archetype, InstanceResolution, InstanceEnumeration) and 4
#: as relationship types (seedCanvas, seedPortfolioCanvas, resolveInstance,
#: enumerateInstances). The single-question version would have refused half a
#: fully valid corpus and called it a dangling-reference finding. This repo has
#: already met that instrument failure once on its verbs — which is why the
#: knowledge lives in `tests/_mesh_verbs.py` — and a work-side page explaining a
#: VERB rather than a class meets it again on the first try.
#:
#: THE SECOND QUESTION IS ASKED ON `r.iri`, NOT ON THE RELATIONSHIP TYPE. Neo4j
#: relationship types cannot contain colons, so `aitool_linker` stores the full
#: namespaced IRI as a property and uses the LOCAL NAME as the type (see
#: `get_verb_local_name`). Matching on type name would therefore compare a local
#: name against a full IRI and find nothing — a second way to produce the same
#: confident false negative, one layer down.
#:
#: Both answers are RETURNED, not collapsed to a boolean, so a refusal can state
#: that both questions were asked. "Not found" is only trustworthy when the
#: reader can see what was looked for.
_EXPLAINS_EXISTS_CYPHER = """
RETURN
  EXISTS { MATCH (c:OntologyClass) WHERE c.uri = $uri }   AS as_class,
  EXISTS { MATCH ()-[r]->() WHERE r.iri = $uri }          AS as_relationship
"""


def check_explains_targets(session, targets: List[str], *, page: str) -> Dict[str, str]:
    """Refuse any `explains` target that does not exist in the graph.

    `targets` must already be FULL IRIs — pass the output of `ingest_page`, never
    raw frontmatter. A compact IRI reaching here matches nothing and would be
    reported as dangling, which is the pass-through bug wearing the invented-IRI
    rule's clothes.

    Returns `{target: "class" | "relationship"}` for the targets that resolved, so
    a caller can record HOW each one resolved rather than only that it did.
    Raises `RunbookRefused`, naming the page and the target, on the first miss.
    """
    resolved: Dict[str, str] = {}
    for target in targets:
        record = session.run(_EXPLAINS_EXISTS_CYPHER, uri=target).single()
        as_class = bool(record["as_class"]) if record else False
        as_relationship = bool(record["as_relationship"]) if record else False

        if as_class:
            resolved[target] = "class"
        elif as_relationship:
            resolved[target] = "relationship"
        else:
            raise RunbookRefused(
                f"{page}: `explains` target {target} exists in the graph as "
                f"neither an :OntologyClass node nor a relationship (checked "
                f"both: node by c.uri, relationship by r.iri). The invented-IRI "
                f"rule refuses a page that claims to explain something that is "
                f"not there — a doc pointing at a target nobody defined is worse "
                f"than an edgeless page, because it reads as coverage."
            )
    return resolved
