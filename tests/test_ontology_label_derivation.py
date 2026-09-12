"""Derived class labels — the fix for "S3000L is primed, loads, and is invisible".

`/classes` selects `?cls a owl:Class ; rdfs:label ?label` with the LABEL REQUIRED,
and S3000L declares no labels at all. Every consumer behind that query — the SPO
interview's authorized-subject menu, `/operable_subjects`, the router's candidate
pool — was reading a SUSTAINMENT vocabulary that silently omitted the domain's
largest standard. Nothing errored: a caller asking about a failure mode got a clean
"no such subject", indistinguishable from the term not existing.

The fix is NOT loosening the query (a menu needs names). It derives the label at the
seed step and stamps its provenance, so a reader can always tell a name the spec
authored from one the seeder made up.

FRAGMENTS HERE ARE REAL S3000L DATA, copied from the source ontology
(http://www.lksoft.com/s3kl#, 773 classes). Synthetic fixtures would let the
heuristic pass against shapes the standard does not actually contain — and the
shape that matters most (`..._1`) is one no one would think to invent.
"""
import rdflib

from doc_tools.assets.ontology_assets import (
    humanize_uri_fragment,
    derive_missing_class_labels,
    LABEL_SOURCE_PREDICATE,
    LABEL_SOURCE_AUTHORED,
    LABEL_SOURCE_DERIVED,
    LABEL_SOURCE_DERIVED_OPAQUE,
)

S3KL = "http://www.lksoft.com/s3kl#"


def _graph(*fragments, authored=None):
    """A graph of s3kl classes; `authored` maps fragment -> an existing rdfs:label."""
    g = rdflib.Graph()
    for f in fragments:
        uri = rdflib.URIRef(S3KL + f)
        g.add((uri, rdflib.RDF.type, rdflib.OWL.Class))
        if authored and f in authored:
            g.add((uri, rdflib.RDFS.label, rdflib.Literal(authored[f])))
    return g


def _label(g, fragment):
    return str(next(g.objects(rdflib.URIRef(S3KL + fragment), rdflib.RDFS.label)))


def _source(g, fragment):
    return str(next(g.objects(rdflib.URIRef(S3KL + fragment), LABEL_SOURCE_PREDICATE)))


# ---------------------------------------------------------------------------
# The humanizer, on the shapes the standard actually contains
# ---------------------------------------------------------------------------

def test_camelcase_is_split_into_words():
    """The packet's worked example — and the MINORITY shape, at 396 of 773."""
    assert humanize_uri_fragment("LSAFailureMode")[0] == "LSA Failure Mode"


def test_the_underscore_shape_is_the_DOMINANT_one():
    """377 of 773 fragments contain an underscore. A heuristic tuned only on the
    camelCase example would be tuned on the smaller half of the corpus."""
    assert humanize_uri_fragment("AggregatedElementType_Family")[0] == (
        "Aggregated Element Type Family")
    assert humanize_uri_fragment("BreakdownElementIdentifier_catalogueSequenceNumber")[0] == (
        "Breakdown Element Identifier Catalogue Sequence Number")


def test_a_leading_acronym_survives_the_split():
    """36 fragments lead with an acronym. A naive camel splitter emits
    'L S A Failure Mode' — every one of them mangled, quietly."""
    assert humanize_uri_fragment("ASDSystemHardwareBreakdown")[0] == (
        "ASD System Hardware Breakdown")
    assert humanize_uri_fragment("LSACandidateIndicator")[0] == "LSA Candidate Indicator"


def test_bare_boolean_operators_are_not_spelled_out():
    """AND / OR / NOT are three real classes whose whole name is the operator.

    THIS CAUGHT A LIVE BUG. The first splitter ordered its all-caps alternative
    after the generic camel one, so it never fired and `AND` came out as 'A N D'.
    The fragment populations in the finding are what made it worth testing a
    three-letter class at all."""
    for op in ("AND", "OR", "NOT"):
        assert humanize_uri_fragment(op)[0] == op


def test_an_alphanumeric_standard_code_is_kept_whole():
    """`S1000D` is a standard's name, not two words. Also caught by the smoke run:
    the first splitter produced 'S1000 D'."""
    label, _ = humanize_uri_fragment("SubtaskMaintenanceLocation_S1000D_ItemLocationCode_A")
    assert "S1000D" in label and "S1000 D" not in label


def test_a_doubled_underscore_yields_no_empty_word():
    """`...Class__acidification` is real. Splitting naively leaves an empty segment,
    which renders as a double space in a menu."""
    label, _ = humanize_uri_fragment(
        "HardwarePartEnvironmentalAspectPlannedDisposalClass__acidification")
    assert "  " not in label
    assert label.endswith("Acidification")


# ---------------------------------------------------------------------------
# THE RED CASE — a fragment that cannot yield a sane name
# ---------------------------------------------------------------------------

def test_a_bare_code_tail_is_marked_OPAQUE_not_passed_off_as_a_name():
    """THE CASE THE DEFINITION OF DONE REQUIRES, on real data.

    `BreakdownElementEssentiality_1/_2/_3` carry their meaning entirely in
    `s3kl:xsdCode` (1/2/3) and nowhere in the fragment. The derived string
    'Breakdown Element Essentiality 1' READS informative and tells the reader
    nothing — it is exactly as uninformative as the bare IRI, while looking like a
    name someone chose. Two states (authored/derived) would file it under 'derived'
    and call the job done; the third state is what keeps the limit visible."""
    frags = ["BreakdownElementEssentiality_1",
             "BreakdownElementEssentiality_2",
             "BreakdownElementEssentiality_3"]
    g = _graph(*frags)
    derive_missing_class_labels(g)

    for f in frags:
        assert _source(g, f) == LABEL_SOURCE_DERIVED_OPAQUE, (
            f"{f} was presented as a derived NAME; its meaning is in xsdCode and "
            f"the fragment tail is only an index"
        )


def test_single_letter_tails_are_opaque_too():
    """The other real shape: `..._ItemLocationCode_A` through `_D`. The peer's
    packet named only the numeric three; measuring the corpus found four more."""
    frags = [f"SubtaskMaintenanceLocation_S1000D_ItemLocationCode_{c}" for c in "ABCD"]
    g = _graph(*frags)
    derive_missing_class_labels(g)
    for f in frags:
        assert _source(g, f) == LABEL_SOURCE_DERIVED_OPAQUE


def test_having_an_xsdCode_does_NOT_make_a_fragment_opaque():
    """THE OVER-CORRECTION, pinned. 384 of 773 classes carry `xsdCode`, but their
    fragments are overwhelmingly informative — `DocumentType_Drawing` has
    xsdCode='DRW' and is a perfectly good name. Keying opaqueness on "has a code"
    would mark 384 good names as placeholders and gut the fix it was meant to
    sharpen. Opaqueness is a property of the FRAGMENT, not of the sibling triple."""
    g = _graph("DocumentType_Drawing", "NonConformanceType_Concession")
    uri = rdflib.URIRef(S3KL + "DocumentType_Drawing")
    g.add((uri, rdflib.URIRef(S3KL + "xsdCode"), rdflib.Literal("DRW")))
    derive_missing_class_labels(g)

    assert _source(g, "DocumentType_Drawing") == LABEL_SOURCE_DERIVED
    assert _label(g, "DocumentType_Drawing") == "Document Type Drawing"


# ---------------------------------------------------------------------------
# Provenance, and the positive control
# ---------------------------------------------------------------------------

def test_an_authored_label_is_KEPT_and_marked_authored():
    """THE POSITIVE CONTROL, and it is not decoration. Without it a seal asserting
    "every class has a label" cannot tell derivation-worked from
    derivation-overwrote-everything — both produce a fully labelled graph."""
    g = _graph("LSAFailureMode", "FailureMode", authored={"FailureMode": "Failure Mode (ISO)"})
    counts = derive_missing_class_labels(g)

    assert _label(g, "FailureMode") == "Failure Mode (ISO)", "an authored name was overwritten"
    assert not list(g.objects(rdflib.URIRef(S3KL + "FailureMode"), LABEL_SOURCE_PREDICATE)), (
        "an authored label must not be stamped as seeder-provenance"
    )
    assert counts[LABEL_SOURCE_AUTHORED] == 1
    assert counts[LABEL_SOURCE_DERIVED] == 1


def test_skos_prefLabel_and_dcterms_title_also_count_as_authored():
    """S3000L has none of these, but other primed ontologies do. Deriving over one
    would replace a curator's name with a machine's."""
    for pred in ("http://www.w3.org/2004/02/skos/core#prefLabel",
                 "http://purl.org/dc/terms/title"):
        g = _graph("SomeClass")
        g.add((rdflib.URIRef(S3KL + "SomeClass"), rdflib.URIRef(pred), rdflib.Literal("Curated")))
        counts = derive_missing_class_labels(g)
        assert counts[LABEL_SOURCE_AUTHORED] == 1, f"{pred} was not honoured"
        assert counts[LABEL_SOURCE_DERIVED] == 0


def test_the_provenance_triple_uses_the_contract_predicate():
    """CROSS-REPO CONTRACT. The seal in invincible-agent queries this IRI; changing
    it silently makes the seal read zero and report a clean graph."""
    assert str(LABEL_SOURCE_PREDICATE) == "http://internal/mesh#labelSource"
    g = _graph("LSAFailureMode")
    derive_missing_class_labels(g)
    assert _source(g, "LSAFailureMode") == LABEL_SOURCE_DERIVED


def test_blank_node_classes_are_skipped():
    """Anonymous owl:Class restrictions are not vocabulary — they have no fragment,
    and naming them would invent thousands of hex-id 'classes' in every menu."""
    g = rdflib.Graph()
    g.add((rdflib.BNode(), rdflib.RDF.type, rdflib.OWL.Class))
    counts = derive_missing_class_labels(g)

    assert counts["skipped_blank_node"] == 1
    assert counts[LABEL_SOURCE_DERIVED] == 0
    assert not list(g.objects(None, rdflib.RDFS.label))


def test_derivation_is_idempotent():
    """Re-priming is routine. A second pass must find its own labels and add
    nothing — otherwise every re-prime doubles the label triples."""
    g = _graph("LSAFailureMode", "AggregatedElementType_Family")
    derive_missing_class_labels(g)
    after_first = len(g)
    counts = derive_missing_class_labels(g)

    assert len(g) == after_first, "a second pass added triples"
    assert counts[LABEL_SOURCE_AUTHORED] == 2
    assert counts[LABEL_SOURCE_DERIVED] == 0


def test_every_class_gets_a_label_so_none_stays_invisible():
    """THE ORIGINAL BUG, stated as the property it broke. The consumer query
    requires rdfs:label; a class without one reaches no menu."""
    frags = ["LSAFailureMode", "AND", "AggregatedElementType_Family",
             "BreakdownElementEssentiality_1", "ASDSystemHardwareBreakdown"]
    g = _graph(*frags)
    derive_missing_class_labels(g)

    unlabelled = [f for f in frags
                  if not list(g.objects(rdflib.URIRef(S3KL + f), rdflib.RDFS.label))]
    assert unlabelled == [], f"still invisible to /classes: {unlabelled}"
