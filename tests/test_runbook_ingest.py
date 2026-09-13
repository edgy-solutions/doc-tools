"""Runbook frontmatter ingest — the prefix pass-through, sealed.

The whole risk of ADR-0041 ingest-on-arrival is one step: turning an author-written
compact IRI into the full IRI the graph is keyed on. An unknown prefix PASSES
THROUGH VERBATIM if nothing stops it — the page stores `docs:runbook-x`, the
linker MATCHes full-IRI nodes, the two never meet, and the page registers
accepted-and-unreachable with nothing red at any layer. Fourth instance of that
class in this codebase this week; first caught before a row existed.

FIXTURES ARE THE REAL FRONTMATTER, copied from invincible-agent's
`docs/runbooks/`. Two of the rules below are ones I would have got backwards by
designing from the description instead of reading the pages: the template is
deliberately unfillable so an unedited copy is REFUSED, and an edgeless runbook is
ADMITTED (R-015). A synthetic fixture would have encoded my guess at both.
"""
import pytest

from doc_tools.utils.runbook_ingest import (
    PREFIXES,
    RunbookRefused,
    ingest_page,
    parse_frontmatter,
    resolve_iri,
)

# Real frontmatter, `docs/runbooks/adding-an-engine.md` shape.
FILLED = """\
---
iri: docs:runbook-adding-an-engine
explains:
  - mesh:resolveInstance
doc_kind: how-to
audience_hint: platform engineer
---

# Runbook — adding an engine
"""

# Real frontmatter, `docs/runbooks/rolling-a-service.md`: NO targets, on purpose.
EDGELESS = """\
---
iri: docs:runbook-rolling-a-service
explains:
doc_kind: how-to
audience_hint: operator
---

# Runbook — rolling a service
"""

# Real frontmatter, `docs/runbooks/_TEMPLATE.md`, shipped unfillable.
TEMPLATE = """\
---
iri: docs:runbook-REPLACE-ME
explains:
  - REPLACE:ME
doc_kind: how-to
audience_hint: REPLACE-ME
---

# Runbook — TEMPLATE
"""


# ---------------------------------------------------------------------------
# THE POSITIVE CONTROL — one page, one RESOLVING edge
# ---------------------------------------------------------------------------

def test_a_filled_page_yields_a_full_iri_and_one_resolving_edge():
    """THE CONTROL THAT IS USUALLY MISSING. Without it, every refusal test below
    passes just as well against an ingest that refuses EVERYTHING — a sealed
    pass-through and a broken ingest are indistinguishable from the negative
    side alone."""
    iri, explains, fm = ingest_page(FILLED, page="adding-an-engine.md")

    assert iri == "http://invincible-agent/docs#runbook-adding-an-engine"
    assert explains == ["http://invincible-agent/mesh#resolveInstance"]
    assert fm["doc_kind"] == "how-to"
    # Nothing compact survives — the downstream MATCH is against full IRIs.
    assert ":" in iri and not iri.startswith("docs:")


def test_an_edgeless_runbook_is_ADMITTED():
    """R-015, ruled 2026-09-11, and the rule I would have inverted by default.

    `rolling-a-service.md` carries no targets because the mesh models no
    deployment verb — it declares four lowercase verbs and 72 classes, and not one
    concerns rolling, images or health. Minting `mesh:rollService` to make the
    edge look tidy is exactly what the invented-IRI rule refuses. Requiring >= 1
    target would push authors to invent one, turning the gate into a generator of
    the thing it guards against. An edgeless page is still reachable by audience
    and by text."""
    iri, explains, _ = ingest_page(EDGELESS, page="rolling-a-service.md")
    assert iri == "http://invincible-agent/docs#runbook-rolling-a-service"
    assert explains == []


# ---------------------------------------------------------------------------
# THE REFUSALS — each names the page
# ---------------------------------------------------------------------------

def test_a_page_with_no_frontmatter_is_refused_BY_NAME():
    with pytest.raises(RunbookRefused) as e:
        ingest_page("# Just a heading\n\nSome prose.\n", page="stray-notes.md")
    assert "stray-notes.md" in str(e.value), "the refusal must name the page"
    assert "frontmatter" in str(e.value).lower()


def test_the_unedited_TEMPLATE_is_refused():
    """The template's own frontmatter says it is "DELIBERATELY UNFILLABLE AS
    SHIPPED" so a copy published without being filled in is refused here rather
    than admitted as a page that explains nothing. Matching the PLACEHOLDER, not
    the filename, is what makes that hold for `my-runbook.md` copied and never
    edited — a filename convention enforces nothing."""
    with pytest.raises(RunbookRefused) as e:
        ingest_page(TEMPLATE, page="my-new-runbook.md")
    assert "my-new-runbook.md" in str(e.value)
    assert "placeholder" in str(e.value).lower() or "REPLACE" in str(e.value)


def test_the_placeholder_rule_fires_ON_ITS_OWN():
    """R-026, AND A MUTATION FOUND IT RATHER THAN A REVIEW.

    The test above passes even with the placeholder check DELETED — because the
    full template also carries `explains: [REPLACE:ME]`, whose `REPLACE` prefix is
    unknown, so the unknown-prefix rule refuses the page anyway and its message
    happens to contain the substring "REPLACE". Two rules cover the same fixture;
    the assertion could not tell which fired, and a mutant with no placeholder
    rule at all came back green.

    This fixture removes the other rule's reach: `explains` is empty (legal, per
    R-015) so nothing but the page's own placeholder IRI can cause a refusal. Now
    the assertion is about the rule it names."""
    only_placeholder = """\
---
iri: docs:runbook-REPLACE-ME
explains:
doc_kind: how-to
audience_hint: platform engineer
---

# Runbook — copied and never filled in
"""
    with pytest.raises(RunbookRefused) as e:
        ingest_page(only_placeholder, page="copied-verbatim.md")
    msg = str(e.value)
    assert "copied-verbatim.md" in msg
    assert "placeholder" in msg.lower() or "_TEMPLATE" in msg, (
        "refused, but not by the placeholder rule — some other rule is covering "
        "for it and the template check could be deleted unnoticed"
    )


def test_an_unknown_prefix_is_REFUSED_not_passed_through():
    """THE MECHANISM ALL FOUR INSTANCES RODE IN ON. A resolver that expands what
    it knows and returns the input unchanged otherwise is the bug — the verbatim
    compact IRI is accepted by every layer and matched by none."""
    with pytest.raises(RunbookRefused) as e:
        resolve_iri("wiki:some-page", page="p.md")
    msg = str(e.value)
    assert "wiki" in msg and "verbatim" in msg.lower()


def test_the_pass_through_is_sealed_for_explains_targets_too():
    """Sealing only the page's own `iri:` leaves the edges unresolved, which is
    the same defect one field over — and harder to see, because the page itself
    would look correctly ingested."""
    page = FILLED.replace("mesh:resolveInstance", "wiki:resolveInstance")
    with pytest.raises(RunbookRefused) as e:
        ingest_page(page, page="adding-an-engine.md")
    assert "wiki" in str(e.value)


def test_a_bare_token_is_refused():
    with pytest.raises(RunbookRefused):
        resolve_iri("runbook-adding-an-engine", page="p.md")


def test_absolute_iris_pass_unchanged():
    """Non-vacuity for the refusals above: something DOES resolve without a table."""
    for absolute in ("http://invincible-agent/docs#x",
                     "https://example.org/y",
                     "urn:li:mlModel:(x,y,PROD)"):
        assert resolve_iri(absolute, page="p.md") == absolute


def test_a_page_without_an_iri_is_refused():
    with pytest.raises(RunbookRefused) as e:
        ingest_page("---\ndoc_kind: how-to\n---\n\n# x\n", page="nameless.md")
    assert "nameless.md" in str(e.value)


def test_malformed_frontmatter_yaml_is_refused_not_silently_skipped():
    with pytest.raises(RunbookRefused) as e:
        parse_frontmatter("---\niri: [unclosed\n---\n\n# x\n", page="broken.md")
    assert "broken.md" in str(e.value)


# ---------------------------------------------------------------------------
# The cross-repo constant
# ---------------------------------------------------------------------------

def test_the_prefix_table_matches_the_DECLARED_namespaces():
    """CROSS-REPO CONSTANT WITH NO SHARED ENFORCEMENT. These values are copied
    from invincible-agent master ad00891 — mesh_system.ttl:680 for `docs:`, and
    the mesh namespace ruled canonical 2026-09-12. Nothing fails if the two repos
    drift; the pages just stop resolving, silently, which is the same class of
    failure this table exists to prevent. This pin makes a drift on OUR side red.
    It cannot see theirs."""
    assert PREFIXES["docs"] == "http://invincible-agent/docs#"
    assert PREFIXES["mesh"] == "http://invincible-agent/mesh#"
    # The rejected namespace, named explicitly — per R-026, a pin that only
    # restates the constant cannot tell the canonical value from the wrong one.
    for ns in PREFIXES.values():
        assert not (ns or "").startswith("http://internal/"), (
            "a prefix drifted back to http://internal/ — the namespace that "
            "reached a seed TTL with ten citations and matched nothing"
        )


def test_an_undeclared_prefix_refuses_rather_than_inventing_an_expansion():
    """The state `docs:` was in this morning: used by five pages, declared
    nowhere. Resolving it then would have meant inventing the IRI every one of
    those pages is keyed on — and every check would have passed, because they
    would all have been wrong the same way."""
    import doc_tools.utils.runbook_ingest as mod
    original = mod.PREFIXES.copy()
    try:
        mod.PREFIXES["provisional"] = None
        with pytest.raises(RunbookRefused) as e:
            resolve_iri("provisional:thing", page="p.md")
        assert "NO DECLARED" in str(e.value) or "declared" in str(e.value).lower()
    finally:
        mod.PREFIXES.clear()
        mod.PREFIXES.update(original)


# ---------------------------------------------------------------------------
# The graph half — the invented-IRI rule, and BOTH resolution questions
# ---------------------------------------------------------------------------
from unittest.mock import MagicMock

from doc_tools.utils.runbook_ingest import check_explains_targets

CLASS_TARGET = "http://invincible-agent/mesh#DispositionReview"
VERB_TARGET = "http://invincible-agent/mesh#resolveInstance"


def _graph(*, classes=(), relationships=()):
    """A neo4j session double that answers BOTH questions independently.

    Modelling them as two separate sets is the point: a double that returns one
    boolean could not express the state where a target exists as a relationship
    and not as a class, which is exactly the state that breaks a single-question
    probe. A fixture that cannot represent the bug cannot catch it.
    """
    session = MagicMock()

    def run(_cypher, uri=None, **_kw):
        return MagicMock(single=lambda: {
            "as_class": uri in classes,
            "as_relationship": uri in relationships,
        })

    session.run.side_effect = run
    return session


def test_a_target_that_is_a_CLASS_resolves():
    session = _graph(classes={CLASS_TARGET})
    assert check_explains_targets(session, [CLASS_TARGET], page="p.md") == {
        CLASS_TARGET: "class"
    }


def test_a_target_that_is_a_RELATIONSHIP_resolves():
    """THE ONE A SINGLE-QUESTION PROBE GETS WRONG, and it gets it wrong as a
    clean finding rather than a crash.

    Measured in-cluster: 8/8 targets resolved, 4 as classes and 4 as relationship
    types (seedCanvas, seedPortfolioCanvas, resolveInstance, enumerateInstances).
    A probe asking only the class question would have reported four REAL targets
    as dangling, with total confidence — refusing half a valid corpus and calling
    it a dangling-reference finding."""
    session = _graph(relationships={VERB_TARGET})
    assert check_explains_targets(session, [VERB_TARGET], page="p.md") == {
        VERB_TARGET: "relationship"
    }


def test_a_mixed_corpus_resolves_BOTH_KINDS_in_one_pass():
    """Non-vacuity for the pair above: the real corpus is mixed, so a check that
    handled either kind alone would still fail on the actual data."""
    session = _graph(classes={CLASS_TARGET}, relationships={VERB_TARGET})
    assert check_explains_targets(session, [CLASS_TARGET, VERB_TARGET], page="p.md") == {
        CLASS_TARGET: "class",
        VERB_TARGET: "relationship",
    }


def test_a_dangling_target_is_REFUSED_and_says_both_questions_were_asked():
    """The invented-IRI rule. The message has to state what was looked for —
    "not found" is only trustworthy when the reader can see the search."""
    session = _graph(classes={CLASS_TARGET})
    with pytest.raises(RunbookRefused) as e:
        check_explains_targets(session, ["http://invincible-agent/mesh#neverDefined"],
                               page="claims-too-much.md")
    msg = str(e.value)
    assert "claims-too-much.md" in msg and "neverDefined" in msg
    assert "OntologyClass" in msg and "relationship" in msg, (
        "a dangling refusal that does not name both questions cannot be trusted "
        "as a finding — it may be a single-question probe reporting a real target"
    )


def test_the_relationship_question_is_asked_on_r_iri_not_on_the_type_name():
    """Neo4j relationship TYPES cannot contain colons, so aitool_linker stores the
    full namespaced IRI as `r.iri` and uses the LOCAL NAME as the type. Matching
    on type name would compare a local name against a full IRI and find nothing —
    the same confident false negative, one layer down."""
    session = _graph(relationships={VERB_TARGET})
    check_explains_targets(session, [VERB_TARGET], page="p.md")
    cypher = session.run.call_args.args[0]
    assert "r.iri" in cypher, "the relationship question must key on the IRI property"
    assert "c.uri" in cypher, "the class question must key on the node's uri"


def test_an_edgeless_page_needs_no_graph_at_all():
    """R-015 again, at this layer: no targets means no queries, so an edgeless
    runbook cannot be refused by a graph that is empty or unreachable."""
    session = _graph()
    assert check_explains_targets(session, [], page="rolling-a-service.md") == {}
    session.run.assert_not_called()
