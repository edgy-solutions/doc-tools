"""The payload behind ``GET /kinds/processable``.

Processability is a property of THIS image -- each declared pass is resolved
through ``doc_tools.passes.dispatch``, and the user-drop parser table is a
literal in ``doc_tools.assets.xml_ingestion`` -- so the answer is served from
here and never recomputed by a consumer. A consumer could not recompute it even
if it wanted to: the SDK's ``ContentKindRegistration`` is ``extra="forbid"``, so
no registration row can carry the answer, and a value cached anywhere else goes
stale against the image that would run the pass.

TWO ARMS, AND THEY DISAGREE -- WHICH IS WHY THIS PAYLOAD NAMES BOTH.
A kind is processable if EITHER arm can run it:

  * ``python_pass_dispatch`` -- ``content_kind.processable_kinds()``: every
    declared pass resolves through ``dispatch.resolve_python_pass``.
  * ``ingress_user_xml_parsers`` -- ``xml_ingestion.ingress_user_parsable_kinds()``:
    the kind has a parser class in the user-drop routing table.

The second arm is the one a USER DROP feeds, and it accepts a class, which the
first arm refuses by contract. So the two sets disagree on
``s1000d-data-module``: arm 1 excludes it, arm 2 routes it. MEASURED, NOT
ARGUED -- ten ODMRAD data modules completed all five stages of
``xml_graph_sync_job`` on 2026-10-16 (8 triples to Jena, 2 chunks to Weaviate,
Neo4j synced, per run). Serving arm 1 alone would tell Lane 1's door that an
S1000D data module cannot be processed, ten minutes after ten of them were.

So ``kinds`` is the UNION, and ``arms`` is published alongside it: a door that
needs to know WHICH path a kind takes can see it, and a disagreement between the
arms stays visible instead of being averaged away.
"""
import hashlib
import json
import os

from doc_tools.utils.content_kind import (
    KIND_MAPPING,
    kind_exclusions,
    processable_kinds,
)

#: Arm names, published in the payload. Stable strings: a consumer may key on
#: them, so they are part of the contract, not labels.
ARM_PYTHON_PASS = "python_pass_dispatch"
ARM_INGRESS_USER_XML = "ingress_user_xml_parsers"


def registry_fingerprint() -> str:
    """sha256 over the registry's (kind, passes) rows, first 16 hex. Lets two
    code locations be compared without diffing lists. Carries nothing from the
    environment."""
    rows = sorted([e.kind, list(e.passes)] for e in KIND_MAPPING.values())
    blob = json.dumps(rows, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def processable_arms() -> dict:
    """Each arm's kinds, sorted. Lazy import: this keeps ``doc_tools.api`` free
    of the Dagster asset graph until the payload is actually built."""
    from doc_tools.assets.xml_ingestion import ingress_user_parsable_kinds

    return {
        ARM_PYTHON_PASS: list(processable_kinds()),
        ARM_INGRESS_USER_XML: list(ingress_user_parsable_kinds()),
    }


def processable_kinds_payload() -> dict:
    """Deterministic: no timestamps, counters, or caller data. ``image`` is
    ``None`` when ``DOC_TOOLS_IMAGE`` is unset -- a state, not an error, and
    never a git sha (a sha names source, not the image that ran).

    ``excluded`` lists only kinds NEITHER arm can run, because a kind one arm
    routes is not excluded -- it is the s1000d case above. Each entry keeps the
    first arm's reason code, and its ``detail`` says the second arm has no
    parser either, so a door can tell a human WHY a kind is refused rather than
    silently omitting it. That sentence is the live OpenDDIL case: the ten
    drops' sibling probe declared ``xml``, which no arm can run, and it halted.
    """
    arms = processable_arms()
    routed = set(arms[ARM_INGRESS_USER_XML])
    kinds = sorted(set(arms[ARM_PYTHON_PASS]) | routed)

    excluded = []
    for e in kind_exclusions():
        if e["kind"] in routed:
            continue
        e = dict(e)
        e["detail"] = (
            e["detail"].rstrip()
            + " No ingress-user XML parser is registered for it either, so no"
            " arm can run it."
        )
        excluded.append(e)

    return {
        "kinds": kinds,
        "arms": arms,
        "excluded": excluded,
        "registered_count": len(KIND_MAPPING),
        "image": os.environ.get("DOC_TOOLS_IMAGE"),
        "registry_fingerprint": registry_fingerprint(),
    }
