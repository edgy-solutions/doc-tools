"""Project ``KIND_MAPPING`` onto the SDK's ``ContentKindRegistration``.

THIS IS THE ADOPTION. Before this module, doc-tools named
``ContentKindRegistration`` in comments and in ``tests/test_kind_registry.py``,
and ``scripts/generate_kind_registrations.py`` rendered the YAML rows as
hand-built strings -- so the SDK model validated the rows only when a test chose
to load them back. The projection now runs in the production package and the
generator renders FROM it, which makes the model load-bearing rather than
advisory: a row that the SDK would refuse cannot be written to
``registry/content_kinds/`` at all, because building it is the step that
produces the bytes.

WHICH FIELDS WE PROJECT, AND WHY THE REST STAY AT THEIR DEFAULTS. At the
v0.9.11 pin ``ContentKindRegistration`` is ``extra="forbid"`` with THIRTEEN
fields: ``kind``, ``branch``, ``passes``, ``outputs``, ``seeds_workflow``,
``identity_field``, ``refresh``, ``domain``, ``parent_link_field``,
``id_namespaces``, ``arrives_as``, ``review_shape``, ``label``. We set THREE on
every row (``kind``, ``passes``, ``outputs``) and project two more --
``identity_field``, ``seeds_workflow`` -- when a row declares one, which no row
does today. The remaining EIGHT are not oversights, and each is left at its
default for a stated reason:

  * ``domain``, ``arrives_as``, ``review_shape``, ``label`` -- **OWNED BY THE
    PLATFORM, NOT BY US.** The architect's ruling of 2026-10-24, amending
    10-07, quoted in ``tests/test_overlay_kind_drift.py``: *"the platform owns
    what a kind IS (``kind``, ``domain``, ``arrives_as``, ``review_shape``,
    ``label``); doc-tools owns what it RUNS (``passes``)."* The deployment
    overlay in ``invincible-agent`` is the authoritative registry for those,
    and our rows are the side that gets MIRRORED. Writing them here would make
    this repo a second source of truth for fields another repo rules on, which
    is precisely the drift the cross-repo seal exists to catch. Our own
    ``domain_type`` column is NOT withdrawn by that ruling -- it drives this
    image's write path, where a domain-less row writes nothing -- it is simply
    published beside the rows in ``registry/content_kind_domains.json``, which
    is what the seal compares against.

    THERE WAS A COLLISION HERE AND IT IS NOW RULED ON. iagent-mesh's own
    v0.9.11 changelog says, of ``arrives_as``, *"ca adds the field, 7f fills in
    KIND_MAPPING's rows with it"* -- dated 2026-10-21, three days BEFORE the
    ownership ruling that moved the field to the platform. This module declared
    none of the four and reported the disagreement rather than settling it by
    editing a file first. The architect ruled on **2026-10-30**: *"ownership
    stands as ruled 10-24: the platform registry declares
    kind/domain/arrives_as/review_shape/label (Lane 1 fills them from your
    packet); doc-tools declares passes. Your decline + test stay."* The
    changelog line is superseded. What this lane owes is therefore not a row
    here but a PACKET -- the per-kind values for ``domain``, ``arrives_as``,
    ``review_shape`` and ``label``, carried to Lane 1, who fills them into the
    platform registry that the server actually serves.

  * ``branch`` and ``refresh`` -- ``ContentKindEntry`` has no counterpart for
    either, which is ADR-0063 section 1's finding and is unchanged by this pin:
    the SDK has had ``branch="event"`` since 0.9.7, an event row requires
    ``seeds_workflow``/``identity_field`` and FORBIDS ``passes``/``outputs``,
    and we cannot express one. All thirteen rows are documents and none sets
    ``seeds_workflow``, so ``branch`` takes its ``"document"`` default honestly
    today. A new event kind is blocked on our own plumbing, not on the SDK.

  * ``parent_link_field`` (0.9.9) -- **MEASURED 2026-10-30, and the answer is
    that there is no such field to name.** It names the field of a kind's
    extracted output that holds its parent, and ``s1000d-data-module`` is the
    hierarchical kind the SDK says opened the ask. Read off the code rather
    than assumed: our S1000D pass emits an **RDF graph, not a row** --
    ``doc_tools/parsers/s1000d_rdf.py`` -- and the only fact container,
    ``S1000dFacts`` (``s1000d_ingest.py``), has nine slots (``dmc``,
    ``model_ident_code``, ``info_code``, ``system_code``, ``tech_name``,
    ``info_name``, ``tools``, ``spares``, ``kind_iri``), none of them a parent.
    No ``parent``/``partOf`` term exists in either module. The one
    module-to-module relation is ``mil:refersToDataModule``, asserted as
    ``(this_dm, refersToDataModule, target)`` at ``s1000d_rdf.py:271`` from
    every ``dmRef`` outside ``identAndStatusSection`` -- a flat cross-reference
    that does not distinguish a parent from a sibling or a successor, so a
    parent is derivable only by INVERTING it and only if the reference happened
    to point upward. So this field is not merely unmeasured here: it presumes a
    row-shaped output this kind does not produce. Unset is the true statement,
    and filling it would require naming a field that does not exist.

  * ``id_namespaces`` (0.9.11) -- the stable ID prefixes a kind's instances
    carry, e.g. ``("HAZ-", "CSI-")``. No kind we register has one: a PCN number
    is the manufacturer's own string with no prefix we could validate, and the
    SDK's validator would hold us to whatever we declared. The default ``()``
    is the true statement.

So the projected fields are ``kind``, ``passes``, ``outputs`` -- doc-tools'
own, by the ruling -- plus ``identity_field`` and ``seeds_workflow`` where a row
sets them, which no row does today. ``ingress_prefix`` and ``file_suffixes``
stay doc-tools-local: they describe the user-drop seam, the SDK has no field for
them, and ``extra="forbid"`` means offering one would raise.
"""
from __future__ import annotations

from iagent_mesh.ingest import ContentKindRegistration

from doc_tools.utils.content_kind import KIND_MAPPING, ContentKindEntry

#: The four ``ContentKindRegistration`` fields the 2026-10-24 ownership ruling
#: assigns to the platform. Kept as data, not prose, so
#: ``tests/test_kind_registry.py`` can assert that every row we emit leaves all
#: four at their model default -- a field absent because of a ruling, pinned as
#: such, rather than absent because nobody looked.
PLATFORM_OWNED_FIELDS = ("domain", "arrives_as", "review_shape", "label")


def registration_for(entry: ContentKindEntry) -> ContentKindRegistration:
    """One row, built through the SDK model so the SDK's validators run.

    Keyword-only on every field, and only the fields a row actually sets: an
    explicit ``identity_field=None`` and an omitted one are the same value to
    pydantic, but writing them conditionally keeps the generated YAML
    byte-unchanged for the twelve rows that declare neither.
    """
    optional = {}
    if entry.identity_field is not None:
        optional["identity_field"] = entry.identity_field
    if entry.seeds_workflow is not None:
        optional["seeds_workflow"] = entry.seeds_workflow
    return ContentKindRegistration(
        kind=entry.kind,
        passes=entry.passes,
        outputs=entry.outputs,
        **optional,
    )


def registrations() -> tuple[ContentKindRegistration, ...]:
    """Every registered kind, sorted by ``kind``.

    Sorted because ``iagent_mesh.ingest.registered_kinds`` returns its rows
    sorted and the registry directory is read as a set of files: a dict
    insertion order is not a contract and nothing downstream may depend on
    ours.
    """
    return tuple(
        registration_for(e) for e in sorted(KIND_MAPPING.values(), key=lambda e: e.kind)
    )
