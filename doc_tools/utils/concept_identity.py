"""The identity of a `:Concept` node: `id = hash(domain, normalized name)`.

Lane tr found Neo4j carries **no uniqueness constraint on Concept at all**, so nothing
stops a second node for a concept that already exists. The architect's ruling of
2026-10-24 is explicit about the shape of the fix and about what it must NOT be:

    *"Do not add a name constraint -- the same name legitimately exists in different
    domains. Give Concept an id = hash(domain, normalized name), MERGE on the id, and a
    uniqueness constraint on the id."*

A name constraint would be wrong on the data, not merely inconvenient: `Torque Control`
taught in a TRAINING course and `Torque Control` as a MANUFACTURING concept are two
concepts that happen to share a label, and a global `REQUIRE c.name IS UNIQUE` would
collapse them into one node whose edges span two domains. Folding the domain into the id
keeps them apart *and* makes the within-domain duplicate impossible to create, which is
the half that was actually broken.

`#163` had already moved the MERGE key off `{id, name, salience}` onto `{name}` -- the
salience in the key meant one node per *salience*, so a concept named on two slides with
two saliences became two nodes and `TEACHES` carried no salience at all. Merging on name
fixed that but left the key unconstrained and unnormalized: `Torque control` and
`Torque  Control` are still two nodes, and nothing in the database refuses a third.

Why the id is a hash and not the name itself:

  * a constraint needs ONE property, and the identity is two facts (domain + name);
  * `concept_Torque_Control`-style ids collide for names that differ only in the
    characters the slug drops (`Torque/Control` and `Torque Control` slug identically)
    while `Torque control` and `Torque Control` slug DIFFERENTLY -- wrong in both
    directions at once;
  * a hash is stable across runs, courses and re-ingests without a lookup table, which
    matters because the writer MERGEs one concept at a time with no view of the rest.

The node also carries `name_normalized`, so the id is reproducible FROM THE NODE: a
later audit (or the migration) can recompute the id from stored fields instead of
trusting that whatever wrote the node used this module.
"""
import hashlib
import re
import unicodedata

# Bumped only if `normalize_concept_name` changes, which re-keys every Concept node and
# therefore requires a migration pass. Stored on nothing yet; it exists so that a future
# change has an obvious thing to grep for and a number to compare.
CONCEPT_ID_VERSION = 1

ID_PREFIX = "concept_"
# 16 hex = 64 bits. A domain's concept vocabulary is thousands of names at the outside;
# 64 bits is ~1 in 10^13 for a collision at that scale, and the full digest buys nothing
# but noise in every log line and graph browser that shows an id.
_DIGEST_CHARS = 16

_WHITESPACE = re.compile(r"\s+", re.UNICODE)


def normalize_concept_name(name: str) -> str:
    """The name, reduced to what makes two names the SAME concept.

    NFKC first, so a non-breaking space, a full-width letter or a composed accent cannot
    fork a concept; then every run of whitespace (including the NBSP that survives NFKC
    as a plain space) collapses to one; then strip, then casefold.

    Deliberately conservative about everything else. Punctuation is NOT stripped and
    words are NOT reordered: `pre-flight` and `pre flight` stay distinct because they
    may genuinely be distinct, and a normalizer that guesses merges concepts that no one
    asked it to merge. The failures this is sized for are the ones actually observed in
    slide text -- stray double spaces, a trailing space, inconsistent capitalization.
    """
    folded = unicodedata.normalize("NFKC", name or "")
    folded = _WHITESPACE.sub(" ", folded).strip()
    return folded.casefold()


def normalize_domain(domain: str) -> str:
    """The domain label, which is already canonical upstream (`TRAINING`), defended
    against case and whitespace drift the same way."""
    return _WHITESPACE.sub(" ", (domain or "")).strip().upper()


def concept_node_id(domain: str, name: str) -> str:
    """`concept_<16 hex>` over the normalized (domain, name) pair.

    The two parts are joined by `\\x1f` (ASCII unit separator), a character neither a
    domain label nor a concept name can contain, so no pair of inputs can be
    reassembled into another pair's digest input.
    """
    key = "%s\x1f%s" % (normalize_domain(domain), normalize_concept_name(name))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]
    return ID_PREFIX + digest


# The constraint the ruling asks for, by name, so the writer, the migration and any
# future bootstrap all create and look for the SAME one. `IF NOT EXISTS` makes it
# idempotent; Neo4j forbids schema and data operations in one transaction, so this is
# never issued alongside a MERGE.
CONCEPT_ID_CONSTRAINT = "concept_id_unique"
CREATE_CONCEPT_ID_CONSTRAINT = (
    "CREATE CONSTRAINT %s IF NOT EXISTS FOR (c:Concept) REQUIRE c.id IS UNIQUE"
    % CONCEPT_ID_CONSTRAINT
)
