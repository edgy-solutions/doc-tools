"""Deterministic S1000D info-code → mil:* content-kind classification.

Per B0 §1 (Step-0 spec, invincible-agent tests/routing/STEP0_DOCS_PHASE_SPEC.md):
**Format ingestion writes INSTANCES and CHUNKS only. Classification is
deterministic metadata mapping — NO LLM in the classification path.**

This module is the deterministic table. Read an S1000D info code,
return the canonical full-IRI mil:* class to set as INSTANCE_OF.
No model inference. No lookup table fuzziness. The S1000D info-code
families are a published standard, and the boundaries between
families are the boundaries between content kinds.

Per B0 §3 the families map as:

    0xx       → mil:DescriptiveDataModule    (what the system IS)
    2xx       → mil:ProcedureDataModule      (operation procedures)
    4xx       → mil:FaultIsolationDataModule (diagnostic / FI)
    5xx,7xx   → mil:ProcedureDataModule      (maintenance / repair / servicing)
    9xx       → mil:IllustratedPartsDataModule (IPD)

The ranges are S1000D Issue 4.x conventions. If the operating issue
differs, change INFO_CODE_RANGES; the rest of the pipeline reads
through this module.

**The table is deliberately incomplete.** 1xx, 3xx, 6xx and 8xx are
valid S1000D families with no mil:* class to map to; they are
enumerated in UNMAPPED_FAMILIES and every occurrence is counted in
FALLTHROUGH_COUNT rather than silently absorbed. Measured 2026-10-02
against the OpenDDIL mock: a 320A (maintenance-planning) module lands
as the bare root, and before this module counted it there was no
signal anywhere that it had.

B0 §3 also flags: "⚠ Confirm the info-code ranges against the
actual S1000D issue in use. The families are standardized but
boundaries shift issue-to-issue." This module is the single source
to verify and, if needed, correct.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Canonical full-IRI form — matches what mil_extension.ttl declares and
# what the canonical pipeline materialized as :OntologyClass nodes
# (verified 2026-06-13 — 10 mil:* classes in Neo4j at full-IRI form,
# Session-2 bootstrap acceptance test).
MIL_NS = "http://edgy-solutions.com/ontology/mil#"

DESCRIPTIVE_DATA_MODULE = MIL_NS + "DescriptiveDataModule"
PROCEDURE_DATA_MODULE = MIL_NS + "ProcedureDataModule"
FAULT_ISOLATION_DATA_MODULE = MIL_NS + "FaultIsolationDataModule"
ILLUSTRATED_PARTS_DATA_MODULE = MIL_NS + "IllustratedPartsDataModule"
DIAGRAM = MIL_NS + "Diagram"
DATA_MODULE_ROOT = MIL_NS + "DataModule"  # fallback root if info code missing


# Info-code families per S1000D Issue 4.x. The range is the FIRST DIGIT
# of the info code (which is itself typically a 3-character string like
# "041", "520", "920"). The mapping is intentionally simple: read the
# first digit, look up the kind. If a sub-range needs to split
# (e.g. some 7xx codes are SERVICING and route differently), do it
# here, not downstream.
INFO_CODE_RANGES: dict[str, str] = {
    "0": DESCRIPTIVE_DATA_MODULE,
    "2": PROCEDURE_DATA_MODULE,           # operation procedures
    "4": FAULT_ISOLATION_DATA_MODULE,
    "5": PROCEDURE_DATA_MODULE,           # maintenance / inspection
    "7": PROCEDURE_DATA_MODULE,           # repair / replacement / servicing
    "9": ILLUSTRATED_PARTS_DATA_MODULE,
}

# First digits that are VALID S1000D families but have no mil:* class to map
# to. Listed explicitly so "we have not decided this yet" is distinguishable
# from "we forgot this exists" — the same distinction mil_40051_classifier.py
# draws with its `_FALLTHROUGH_KIND` sentinel.
#
# Adding a kind for any of these is a TBox change, and per AGENTS.md the TTLs
# now live in `invincible-agent/setup/ontologies/*.ttl`, so it goes through the
# architect — not into this file as a silent new row. Until then every
# occurrence is counted below, so the cost of not having decided is visible.
UNMAPPED_FAMILIES: dict[str, str] = {
    "1": "operation/servicing-adjacent families",
    "3": "maintenance-planning / scheduled-maintenance",
    "6": "battle-damage assessment and repair",
    "8": "crew/operator and role-specific content",
}

# Fallthrough tally, keyed by the first digit that fell through ("3"), or by
# the sentinel MISSING_INFO_CODE_KEY when the DM carried no info code at all.
# Mirrors mil_40051_classifier.FALLTHROUGH_COUNT; same contract, same reason.
FALLTHROUGH_COUNT: dict[str, int] = {}

MISSING_INFO_CODE_KEY = "<missing>"


def reset_fallthrough_count() -> None:
    """Clear the fallthrough tally (tests, and per-ingest-run accounting)."""
    FALLTHROUGH_COUNT.clear()


def classify_data_module(info_code: str | None) -> str:
    """Return the canonical full-IRI mil:* content kind for an info code.

    Args:
        info_code: The S1000D information code (typically a 3-character
            string like "041", "520"). May be None or empty if the source
            DM lacks it; in that case returns the root mil:DataModule
            class so the instance still has an INSTANCE_OF edge (G2's
            "no orphan instances" invariant).

    Returns:
        The canonical full-IRI of the mil:* class to use as the
        instance's INSTANCE_OF target.

    No LLM. No fallback that calls a model. No "if uncertain, ask
    a classifier." If the info code is an unknown family, return the
    root class (mil:DataModule) so the instance still routes to the
    Q1 baseline (search the technical manuals).

    Side effect: both fallthrough paths — a missing info code, and a
    first digit absent from INFO_CODE_RANGES — log a warning AND
    increment FALLTHROUGH_COUNT, per the architect's standing rule
    for the sibling classifier: "Fallthrough to mil:DataModule must
    log/count when it fires (no silent absorption)."

    Unlike mil_40051_classifier.classify_40051_work_package, an
    unmapped family does NOT raise. The 40051 map is derived from a
    DTD that enumerates every work-package root, so an unknown root
    there means the map is stale. Info codes are an open 3-digit
    space: 1xx/3xx/6xx/8xx are legitimate S1000D content that this
    ontology has no class for yet (see UNMAPPED_FAMILIES). Raising
    would reject valid publications, so these are counted, not
    refused.
    """
    if not info_code or not info_code.strip():
        FALLTHROUGH_COUNT[MISSING_INFO_CODE_KEY] = (
            FALLTHROUGH_COUNT.get(MISSING_INFO_CODE_KEY, 0) + 1
        )
        logger.warning(
            "S1000D data module carries no info code; classifying as the root "
            "%s. The instance keeps an INSTANCE_OF edge (G2 'no orphan "
            "instances'), but it is NOT content-kind routable.",
            DATA_MODULE_ROOT,
        )
        return DATA_MODULE_ROOT

    first_digit = info_code.strip()[0:1]
    kind = INFO_CODE_RANGES.get(first_digit)
    if kind is None:
        FALLTHROUGH_COUNT[first_digit] = FALLTHROUGH_COUNT.get(first_digit, 0) + 1
        logger.warning(
            "S1000D info code %r falls in family %sxx, which has no mil:* "
            "content kind (%s). Classifying as the root %s — the data module "
            "will be indistinguishable from every other unclassified DM "
            "downstream. Adding a kind is a TBox change in "
            "invincible-agent/setup/ontologies and goes through the architect. "
            "Fallthrough tally for this family: %d.",
            info_code,
            first_digit,
            UNMAPPED_FAMILIES.get(first_digit, "family not recognised at all"),
            DATA_MODULE_ROOT,
            FALLTHROUGH_COUNT[first_digit],
        )
        return DATA_MODULE_ROOT
    return kind


# Instance-label ↔ class-name mapping (B0 §4's one decision inside B2).
#
# The prime script's existing instance constraints declare uniqueness on
# :Procedure / :ManufacturingStep / :Figure / :Part / :DataModule(dmc).
# Those are NEO4J LABELS the ingest writes for indexing + downstream
# queries. They are NOT the same as the §3 kind-classes
# (mil:ProcedureDataModule, etc.) which are the routing-visible CONCEPTS
# the resolver queries.
#
# The decision: each instance gets BOTH a Neo4j label (for the indexed
# unique constraint + Cypher queries that filter by label) AND an
# INSTANCE_OF edge to its kind-class (for the resolver's compat-walk).
# The mapping here is the explicit correspondence so the layers don't
# drift.
LABEL_TO_KIND: dict[str, str] = {
    "Procedure": PROCEDURE_DATA_MODULE,
    "ManufacturingStep": PROCEDURE_DATA_MODULE,
    "FaultIsolation": FAULT_ISOLATION_DATA_MODULE,
    "IPD": ILLUSTRATED_PARTS_DATA_MODULE,
    "Figure": DIAGRAM,
    "DataModule": DATA_MODULE_ROOT,  # generic container for non-content-kind DMs
}

KIND_TO_LABEL: dict[str, str] = {v: k for k, v in LABEL_TO_KIND.items()}


def label_for_kind(kind_iri: str) -> str:
    """Return the Neo4j instance label that pairs with this kind class."""
    return KIND_TO_LABEL.get(kind_iri, "DataModule")


def kind_for_label(label: str) -> str:
    """Return the kind class that pairs with this Neo4j instance label."""
    return LABEL_TO_KIND.get(label, DATA_MODULE_ROOT)
