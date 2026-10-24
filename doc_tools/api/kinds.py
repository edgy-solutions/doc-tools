"""The payload behind ``GET /kinds/processable`` -- a route served NOWHERE.

RULED 2026-10-16 (F2): the push wins. This payload reaches Lane 1 by being PUT
from `doc_tools.components.processable_kinds_publisher`, not by anyone calling
this route, and `doc_tools.api.app` is wired into no chart on purpose. See that
module's docstring for the ruling and for the posture rule that applies the day
it IS served. The payload itself is the same either way -- one definition, two
transports, and only one of them deployed.

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
``xml_graph_sync_job`` on 2026-10-16 (2 chunks to Weaviate and Neo4j synced,
per run, with `triplesLoaded` 8 at the NEO4J stage). Serving arm 1 alone would
tell Lane 1's door that an S1000D data module cannot be processed, ten minutes
after ten of them were.

THAT `8` IS NOT A COUNT OF WHAT THE PARSER EMITTED, and an earlier version of
this line said "8 triples to Jena", which is where the premise "the S1000D
parser writes 8 identity triples per module" came from. `upload_to_jena`
(`assets/semantic_assets.py:911`) logs the graph URI and NO triple count; the
only count in this pipeline is Neo4j's `triplesLoaded`, returned by
`n10s.rdf.import.fetch` (`:1058-1068`), i.e. after n10s mapping. Measured the
same day, the builder emits 5 / 9 / 11 / 12 / 14 / 48 triples over the six MRAD
fixtures and matches `invincible-agent`'s `tests/fixtures/s1000d_mrad/mrad.ttl`
99-for-99. Two instruments at two stages; naming one with the other's stage is
what made a non-defect look like one.

So ``kinds`` is the union MINUS the hold list, and ``arms`` is published
alongside it unfiltered: a door that needs to know WHICH path a kind takes can
see it, and a disagreement between the arms stays visible instead of being
averaged away.

AND THE UNION IS NOT THE LAST WORD. Arm membership is evidence that a PASS
exists; it is not evidence that a DROP has ever travelled that path. ``xml`` is
held out by ruling until a user-drop sensor processes a bare ``xml`` drop end to
end, and ``held_out`` publishes that decision with the measurement that would
retire it -- see HELD_OUT. ``ingestable_kinds()`` is the one definition of the
advertised list, shared with the publisher that PUTs it to Lane 1's door.
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

#: Kinds this door does NOT advertise even if an arm claims them, with the
#: measurement that releases each one. RULED 2026-10-16: "hold xml out of
#: ingestable_kinds() until a user-drop sensor actually processes a bare xml
#: drop; s1000d-data-module is in, proven by ten."
#:
#: WHY A HOLD LIST AND NOT JUST THE ARM MATH. Today the arms already agree that
#: `xml` is unrunnable, so `ingestable_kinds()` would omit it anyway -- which is
#: precisely why the hold is written down. The one bare-`xml` user drop measured
#: (`rev188-door-probe.xml`) HALTED at stage 1, while the ten
#: `s1000d-data-module` drops completed all five stages; so arm membership is
#: evidence about a PASS, and this list is evidence about a DROP. The day a
#: parser row for `xml` is added, arm 2 would start claiming it and this door
#: would start advertising a path no drop has ever travelled. The hold stops
#: that silently happening, and `unblocks_when` says exactly what retires it.
#:
#: Every entry is published in the payload. An omission with no reason reads as
#: a bug to the consumer -- Lane 1 would be right to file it as one.
HELD_OUT = {
    "xml": {
        "reason": "no user drop of a bare `xml` has been processed end to end",
        "evidence": (
            "rev188-door-probe.xml halted at stage 1 (the sibling manifest "
            "declared `xml`, which no arm can run); the ten drops that did "
            "complete all five stages on 2026-10-16 were s1000d-data-module"
        ),
        "unblocks_when": (
            "a user-drop sensor processes a bare `xml` drop through to a parse "
            "artifact -- then delete this entry, in the same commit as the "
            "measurement that justifies it"
        ),
        "ruled": "2026-10-16",
    },
}


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


def ingestable_kinds() -> tuple:
    """The list this door ADVERTISES: either arm can run it, and no hold applies.

    ONE DEFINITION, TWO CONSUMERS -- the `GET /kinds/processable` payload and the
    publisher that PUTs it to Lane 1's door
    (`doc_tools.components.processable_kinds_publisher`). A publisher that
    recomputed the list would be a second answer to the same question, and the
    two would drift exactly the way the two arms already did.

    `arms` stays in the payload unfiltered, so a kind an arm claims and the hold
    list withholds is VISIBLE as that, rather than looking like an arm that
    forgot it. See HELD_OUT.
    """
    arms = processable_arms()
    union = set(arms[ARM_PYTHON_PASS]) | set(arms[ARM_INGRESS_USER_XML])
    return tuple(sorted(union - set(HELD_OUT)))


def held_out_entries() -> list:
    """HELD_OUT as published rows, each naming the arm(s) that claim the kind.

    `claimed_by` is empty for a kind no arm can run today (the live `xml` case):
    the hold is then belt and braces, and saying so is more useful than implying
    the hold is what is keeping it out.
    """
    arms = processable_arms()
    rows = []
    for kind in sorted(HELD_OUT):
        row = dict(HELD_OUT[kind])
        row["kind"] = kind
        row["claimed_by"] = sorted(a for a, ks in arms.items() if kind in ks)
        rows.append(row)
    return rows


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
    # `kinds` is the ADVERTISED list, not the raw union: the honest list is the
    # one a consumer keying on the obvious field gets. `arms` below still
    # carries the raw sets, and `held_out` says what the difference is and what
    # would retire it.
    kinds = list(ingestable_kinds())

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
        # Advertised-but-withheld, with the measurement that releases each one.
        # Carried in the PAYLOAD and not only in a commit message, because the
        # consumer of the omission is a door, and a door cannot read git.
        "held_out": held_out_entries(),
        "registered_count": len(KIND_MAPPING),
        "image": os.environ.get("DOC_TOOLS_IMAGE"),
        "registry_fingerprint": registry_fingerprint(),
    }
