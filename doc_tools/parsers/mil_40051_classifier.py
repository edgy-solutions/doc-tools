r"""Deterministic MIL-STD-40051 work-package → mil:* content-kind classification.

The sibling of mil_info_code_map.py (which keys S1000D info codes).
40051's analog of the S1000D info-code system is the **WP root element**
itself — the DTD declares a separate element for each WP type
(maintwp, tswp, descwp, plwp, ...), and the root tag IS the type.

Per the architect's 2026-06-13 40051-track assignment:

  > "Step 0 — build the classifier map from the DTD, not the samples.
  > The 40051E_5_0.dtd is in the package. Enumerate every WP root
  > element it declares, not just maintwp/tswp from the two exemplars.
  > Build the WP_ROOT_TO_KIND map covering the full set. Fallthrough to
  > mil:DataModule must log/count when it fires (no silent absorption)."

This module is the DTD-derived enumeration. The map below was built by
grepping `^<!ELEMENT \S*wp\S* ` against the shipped DTD
(tests/fixtures/iads_40051_demo/40051E_5_0.dtd) and assigning each
element to the most natural existing mil:* kind. Fallthroughs are
EXPLICIT entries with value `_FALLTHROUGH_KIND` — they are NOT silent
defaults. Adding a new WP root to the DTD without an entry here makes
`classify_40051_work_package` raise (KeyError surfaced as a count
increment + warning), keeping the architect's "no silent absorption"
contract.

Determinism: same root tag → same kind on every run. No body inspection.
No LLM. No content-aware fuzziness. The kind decision is metadata-only.

G1: this module NEVER writes :OntologyClass nodes. The mil:* constants
are imported from mil_info_code_map (the canonical pipeline materializes
those nodes via mil_extension.ttl).

MORNING DECISION (banked, 2026-06-13): the reference/index/admin cluster
(toolidwp, nsnindxwp, pnindxwp, refdesindxwp, refwp, tsindxwp, mrplwp,
torquewp, aalwp, macwp, orschwp, wtloadwp, substitute-matwp,
chgwplist, loepwp, genwp) currently falls through to mil:DataModule
because no existing kind fits cleanly. The architect's hard limit:
"new content kinds are a TBox change and those go through you." A
future TBox session may add mil:ReferenceDataModule and/or
mil:IndexDataModule, at which point these entries get updated. Until
then the FALLTHROUGH_COUNT counter surfaces every instance the
ambiguity hits, so the cost of NOT yet making that decision is visible.
"""

from __future__ import annotations

from doc_tools.parsers.mil_info_code_map import (
    DATA_MODULE_ROOT,
    DESCRIPTIVE_DATA_MODULE,
    PROCEDURE_DATA_MODULE,
    FAULT_ISOLATION_DATA_MODULE,
    ILLUSTRATED_PARTS_DATA_MODULE,
    MIL_NS,
)


# Sentinel used in the map to mark entries that are KNOWN-AMBIGUOUS and
# bank a morning TBox decision. Distinguishes "I considered this and
# couldn't pick" from "I forgot this exists" — the latter makes
# classify_40051_work_package raise.
_FALLTHROUGH_KIND = DATA_MODULE_ROOT


# WP_ROOT_TO_KIND — enumerated from 40051E_5_0.dtd via:
#   grep '^<!ELEMENT \S*wp\S* ' 40051E_5_0.dtd
# plus chgwplist/loepwp (admin WPs whose root tags don't end in "wp" by
# DTD spelling but ARE WPs by purpose).
#
# Curated 2026-06-13 by reading each element's content model in the DTD
# to confirm the assignment (e.g. maintwp's content model includes
# maintsk+ which is the procedure backbone; tswp's includes %tsdata;
# which is the faultproc/symptom/malfunc/action vocabulary; etc.).
WP_ROOT_TO_KIND: dict[str, str] = {
    # ---- mil:ProcedureDataModule (operational + maintenance + manufacturing) -
    "maintwp":                  PROCEDURE_DATA_MODULE,  # canonical maintenance
    "gen.maintwp":              PROCEDURE_DATA_MODULE,  # general maintenance
    "genrepairwp":              PROCEDURE_DATA_MODULE,
    "auxeqpwp":                 PROCEDURE_DATA_MODULE,
    "compchklistwp":            PROCEDURE_DATA_MODULE,
    "destruct-materialwp":      PROCEDURE_DATA_MODULE,
    "dmwr_operationalreqwp":    PROCEDURE_DATA_MODULE,
    "emergencywp":              PROCEDURE_DATA_MODULE,
    "eqploadwp":                PROCEDURE_DATA_MODULE,
    "facilwp":                  PROCEDURE_DATA_MODULE,
    "lubewp":                   PROCEDURE_DATA_MODULE,
    "manuwp":                   PROCEDURE_DATA_MODULE,
    "mobilwp":                  PROCEDURE_DATA_MODULE,
    "opcheckwp":                PROCEDURE_DATA_MODULE,
    "opunuwp":                  PROCEDURE_DATA_MODULE,
    "opusualwp":                PROCEDURE_DATA_MODULE,
    "perseqpwp":                PROCEDURE_DATA_MODULE,
    "pmcswp":                   PROCEDURE_DATA_MODULE,
    "pmi-cklistwp":             PROCEDURE_DATA_MODULE,
    "pmiwp":                    PROCEDURE_DATA_MODULE,
    "pms-inspecwp":             PROCEDURE_DATA_MODULE,
    "pshopanalwp":              PROCEDURE_DATA_MODULE,
    "qawp":                     PROCEDURE_DATA_MODULE,
    "storagewp":                PROCEDURE_DATA_MODULE,
    "surwp":                    PROCEDURE_DATA_MODULE,

    # ---- mil:FaultIsolationDataModule (diagnostic / TS) ----------------------
    "tswp":                     FAULT_ISOLATION_DATA_MODULE,  # canonical TS
    "diagnosticwp":             FAULT_ISOLATION_DATA_MODULE,
    "opcheck-tswp":             FAULT_ISOLATION_DATA_MODULE,
    "damage-assesswp":          FAULT_ISOLATION_DATA_MODULE,

    # ---- mil:DescriptiveDataModule (informational / what-the-system-IS) -----
    "descwp":                   DESCRIPTIVE_DATA_MODULE,  # canonical descriptive
    "ammo.markingwp":           DESCRIPTIVE_DATA_MODULE,
    "ammowp":                   DESCRIPTIVE_DATA_MODULE,
    "bdar-geninfowp":           DESCRIPTIVE_DATA_MODULE,
    "bdartoolswp":              DESCRIPTIVE_DATA_MODULE,
    "coeibiiwp":                DESCRIPTIVE_DATA_MODULE,
    "csi.wp":                   DESCRIPTIVE_DATA_MODULE,
    "ctrlindwp":                DESCRIPTIVE_DATA_MODULE,
    "destruct-introwp":         DESCRIPTIVE_DATA_MODULE,
    "dmwr_introwp":             DESCRIPTIVE_DATA_MODULE,
    "dmwr_qarwp":               DESCRIPTIVE_DATA_MODULE,
    "ginfowp":                  DESCRIPTIVE_DATA_MODULE,
    "handreceiptwp":            DESCRIPTIVE_DATA_MODULE,
    "introwp":                  DESCRIPTIVE_DATA_MODULE,
    "macintrowp":               DESCRIPTIVE_DATA_MODULE,
    "manu_items_introwp":       DESCRIPTIVE_DATA_MODULE,
    "natowp":                   DESCRIPTIVE_DATA_MODULE,
    "oipwp":                    DESCRIPTIVE_DATA_MODULE,
    "pm-ginfowp":               DESCRIPTIVE_DATA_MODULE,
    "pmcsintrowp":              DESCRIPTIVE_DATA_MODULE,
    "pms-ginfowp":              DESCRIPTIVE_DATA_MODULE,
    "ppmgeninfowp":             DESCRIPTIVE_DATA_MODULE,
    "stowagewp":                DESCRIPTIVE_DATA_MODULE,
    "techdescwp":               DESCRIPTIVE_DATA_MODULE,
    "thrywp":                   DESCRIPTIVE_DATA_MODULE,
    "tsintrowp":                DESCRIPTIVE_DATA_MODULE,
    "wiringwp":                 DESCRIPTIVE_DATA_MODULE,

    # ---- mil:IllustratedPartsDataModule (parts lists) -----------------------
    "plwp":                     ILLUSTRATED_PARTS_DATA_MODULE,  # canonical IPD
    "bulk_itemswp":             ILLUSTRATED_PARTS_DATA_MODULE,
    "explistwp":                ILLUSTRATED_PARTS_DATA_MODULE,
    "inventorywp":              ILLUSTRATED_PARTS_DATA_MODULE,
    "kitswp":                   ILLUSTRATED_PARTS_DATA_MODULE,
    "mrplwp":                   ILLUSTRATED_PARTS_DATA_MODULE,
    "stl_partswp":              ILLUSTRATED_PARTS_DATA_MODULE,
    "stlwp":                    ILLUSTRATED_PARTS_DATA_MODULE,
    "supitemwp":                ILLUSTRATED_PARTS_DATA_MODULE,

    # ---- fallthrough cluster (MORNING DECISION BANKED) ----------------------
    # Reference / index / authority lists — no clean kind among the
    # existing five. Bank as mil:ReferenceDataModule candidate.
    "aalwp":                    _FALLTHROUGH_KIND,
    "macwp":                    _FALLTHROUGH_KIND,
    "nsnindxwp":                _FALLTHROUGH_KIND,
    "orschwp":                  _FALLTHROUGH_KIND,
    "pnindxwp":                 _FALLTHROUGH_KIND,
    "refdesindxwp":             _FALLTHROUGH_KIND,
    "refwp":                    _FALLTHROUGH_KIND,
    "substitute-matwp":         _FALLTHROUGH_KIND,
    "toolidwp":                 _FALLTHROUGH_KIND,
    "torquewp":                 _FALLTHROUGH_KIND,
    "tsindxwp":                 _FALLTHROUGH_KIND,
    "wtloadwp":                 _FALLTHROUGH_KIND,
    # Administrative — not content but still ABox-trackable:
    "chgwplist":                _FALLTHROUGH_KIND,
    "loepwp":                   _FALLTHROUGH_KIND,
    # Generic placeholder WPs:
    "genwp":                    _FALLTHROUGH_KIND,
}


# Process-local counter of fallthrough hits. Tests assert this is
# non-zero after ingesting any TM that exercises the fallthrough cluster
# (positive control), AND that the counter reflects the actual count
# (sanity). Reset between ingest runs by callers that want isolation.
FALLTHROUGH_COUNT: dict[str, int] = {}


def reset_fallthrough_count() -> None:
    """Test convenience — reset the per-root fallthrough counter."""
    FALLTHROUGH_COUNT.clear()


def classify_40051_work_package(root_tag: str) -> str:
    """Return the canonical full-IRI mil:* kind for a 40051 WP root tag.

    Args:
        root_tag: The XML root element's tag name (e.g., "maintwp",
            "tswp"). Case-sensitive — 40051 DTD declares lowercase
            element names. Callers must pass the verbatim tag.

    Returns:
        The canonical full-IRI of the mil:* class to use as the
        instance's INSTANCE_OF target. Always non-None — G2 contract.

    Raises:
        ValueError: if root_tag is NOT in WP_ROOT_TO_KIND. This is
            intentional and architectural: the DTD enumerates every
            WP type, this module enumerates every kind assignment.
            A KeyError means the DTD added a new WP type and nobody
            updated this map. The right fix is to UPDATE the map
            (after deciding the assignment), not to add a silent
            default. Surface, don't absorb.

    Side effect: when the assignment is a banked fallthrough
    (mil:DataModule), increments FALLTHROUGH_COUNT[root_tag] so the
    cost of NOT yet making the morning TBox decision stays visible.
    """
    if root_tag not in WP_ROOT_TO_KIND:
        raise ValueError(
            f"40051 root tag {root_tag!r} is not in WP_ROOT_TO_KIND. "
            f"Either the DTD has added a new WP type (update the map), "
            f"or the input XML is malformed (the root is not a WP). "
            f"Per architect: 'fallthrough to mil:DataModule must log/count "
            f"when it fires (no silent absorption)' — an UNKNOWN tag is "
            f"a different case and must raise."
        )
    kind = WP_ROOT_TO_KIND[root_tag]
    if kind == _FALLTHROUGH_KIND:
        FALLTHROUGH_COUNT[root_tag] = FALLTHROUGH_COUNT.get(root_tag, 0) + 1
    return kind


# Non-WP front-matter / navigation tags present in IADS packages that
# the caller may want to skip cleanly (rather than feed to the
# classifier, which would raise). Listed here so the ingest pipeline
# has a single shared opinion on what to skip.
NON_WP_ROOT_TAGS: frozenset[str] = frozenset({
    "Dataset",        # IADS-level dataset wrapper
    "frntcover",      # front cover
    "rearcover",      # back cover
    "titleblk",       # title block
    "toc",            # table of contents
    "howtouse",       # "how to use this manual"
    "warnsumm",       # warning summary front-matter
    "alphaindx",      # alphabetical index
    "indxalpha",
    "auth",           # authentication page
    "wpidx",          # WP-level index page
})


def is_wp_root(root_tag: str) -> bool:
    """True if root_tag is a known 40051 WP type (in WP_ROOT_TO_KIND)."""
    return root_tag in WP_ROOT_TO_KIND


def wp_kind_label_pairs() -> list[tuple[str, str]]:
    """All (root_tag, kind_iri) pairs as a sorted list.

    Convenience for tests / docs that want to enumerate the map
    without importing the dict directly.
    """
    return sorted(WP_ROOT_TO_KIND.items())


__all__ = [
    "WP_ROOT_TO_KIND",
    "FALLTHROUGH_COUNT",
    "NON_WP_ROOT_TAGS",
    "MIL_NS",
    "classify_40051_work_package",
    "is_wp_root",
    "reset_fallthrough_count",
    "wp_kind_label_pairs",
]
