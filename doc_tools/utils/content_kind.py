"""ADR-0021 deterministic content-kind selection at ingest.

Single source of truth for "what kinds exist and what each maps to."
Adding a kind = one row in ``KIND_MAPPING`` + the target ``OntologyClass``
declared in the matching TTL.

Precedence (per ADR-0021 §Decision):

    1. ``manifest.metadata.content_kind`` (explicit declaration)
    2. Path-derived segment AFTER the ``domain_type`` segment of the S3 key
    3. **HALT** with :class:`UnclassifiableContentKindError` — never silent default

The legacy ``domain_type`` chain in ``semantic_assets.py`` used to fall through
to a hardcoded ``"Training"`` default. That is gone: the 2026-10-02 ruling made
the registered kind's declared domain the authority, so the asymmetry this
module's docstring used to defer to "a future ADR" has been collapsed.

── A FORMAT-LEVEL KIND DECLARES NO DOMAIN ─────────────────────────────────────
ARCHITECT RULING 2026-10-02: *"KIND_MAPPING rows: pcn, pdn → SUSTAINMENT;
s1000d-data-module → MAINTENANCE; engineering-document, doors-export, pdf →
none (origin resolved by evidence, not kind)."*

So ``ContentKindEntry.domain_type`` is ``Optional[str]`` and ``None`` is a
POSITIVE assertion, not a missing value: a PDF, an engineering document or a
DOORS export has no domain OF ITS OWN. Origin is resolved from evidence
(document identity → system of record → steward), and a domain-consumption
table decides who sees it. Picking a domain from the file format instead is
what would write unvetted content into a vetted domain's graph.

Until origin resolves, such a drop is visible to the dropper only and lands in
**no domain graph**. The stage is "origin unresolved" — not a staging domain,
and there is deliberately NO ``INGRESS`` domain class to put it in. The write
path implements that as an early return; see ``semantic_assets.py``'s
``OriginUnresolved`` short-circuit.

── UPPERCASE IN THE RULING, LOWERCASE IN THE ROW ──────────────────────────────
The ruling writes the domains as ``SUSTAINMENT``/``MAINTENANCE``; the rows
below carry ``"sustainment"``/``"maintenance"``. Same value, two spellings that
already existed in this codebase: ``domain_type`` is the lowercase pipeline
value (``if domain_type == "sustainment"`` selects the plugin) and
``domain_label`` is ``domain_type.upper()``, the Neo4j label and the
``<http://internal/{DOMAIN}_INSTANCES>`` graph name. The rows hold the former
so the ruling's ``SUSTAINMENT`` is what reaches the graph.

── THE ROWS ARE ALSO THE PICKER'S LEGAL SET ───────────────────────────────────
``iagent_mesh.ingest.registered_kinds()`` defines the picker's options as the
registered rows themselves. Those rows are PROJECTED from this table into
``registry/content_kinds/*.yaml`` by ``scripts/generate_kind_registrations.py``
— generated, never hand-maintained, with the drift pinned by
``tests/test_kind_registry.py``. The registration model is
``extra="forbid"`` and has no domain field (the SDK ships no rows and takes no
position on domain), so the declared domain rides beside the rows in
``registry/content_kind_domains.json``, generated from the same pass.
"""

from dataclasses import dataclass
from typing import Optional


class UnclassifiableContentKindError(Exception):
    """Raised when neither metadata.content_kind nor the path-derived segment
    yields a kind_source_value present in ``KIND_MAPPING``.

    Per ADR-0021 §Precedence rule §3 the kind-selection chain MUST halt here.
    There is no silent default — that is the rule the legacy ``domain_type``
    chain broke and that this resolver deliberately does not inherit.
    """


@dataclass(frozen=True)
class ContentKindEntry:
    """A single row of the ADR-0021 mapping table.

    The row IS the contract: adding a content kind = adding an entry to
    ``KIND_MAPPING`` whose ``target_ontology_class`` is declared in the
    matching domain TTL (e.g. ``mfg_extension.ttl`` for manufacturing).
    """
    kind_source_value: str
    kind: str
    extractor_config: str
    baml_function: str
    target_ontology_class: str

    #: ``None`` means THIS KIND DECLARES NO DOMAIN (see the module docstring).
    #: It is an assertion about format-level kinds, not an unfilled field.
    domain_type: Optional[str]

    #: ADR-0021 → SDK projection: the extraction passes this kind runs, in
    #: order, as ``ContentKindRegistration.passes``. Non-empty (the SDK model
    #: refuses ``()``: "a kind with no pass is not a kind").
    passes: tuple[str, ...] = ()

    #: The target ``OntologyClass`` CURIEs the ``INSTANCE_OF`` edge is stamped
    #: against, as ``ContentKindRegistration.outputs``. Non-empty.
    outputs: tuple[str, ...] = ()

    #: The path segment under ``ingress-user/`` a drop of this kind lands at.
    #: ``None`` means THIS KIND IS NOT DROPPABLE AT THE USER SEAM.
    #: This is a FORMAT-level property, which is why only the format-level rows
    #: declare one: the seam's own ``kind`` column is the file format/arrival shape
    #: (``ingest_status.KINDS``, whose comment says exactly that), while the
    #: CONTENT kind rides separately in ``manifest.metadata.content_kind``. An
    #: S1000D data module therefore arrives under the generic ``xml`` prefix and
    #: declares ``s1000d-data-module`` in its manifest -- two channels, by design.
    ingress_prefix: Optional[str] = None

    #: Lowercase filename extensions, dot included, that the seam accepts for this
    #: prefix. Empty when ``ingress_prefix`` is None.
    file_suffixes: tuple[str, ...] = ()

    #: ``ContentKindRegistration.identity_field`` -- the field whose value
    #: identifies the artifact. Optional in the SDK model.
    identity_field: Optional[str] = None

    #: ``ContentKindRegistration.seeds_workflow`` -- the workflow this kind seeds.
    seeds_workflow: Optional[str] = None


#: Passes and output classes that are DECLARED HERE but not yet reachable —
#: kept as data so the phantoms stay visible instead of being discovered by a
#: failing ingest. Enumerated by ``tests/test_kind_registry.py``, which asserts
#: this is exactly the set of undeclared/unbuilt references in the table.
#:
#: ``identity.document_identity`` — the pass the architect ordered on
#: 2026-10-02 ("document number, revision, CAGE code, contract/program
#: identifiers from title blocks and DOORS module attributes, verbatim with
#: sources, refused if not printed") — is NO LONGER UNBUILT. It is
#: ``doc_tools/passes/identity.py``, deterministic and sealed on two fixtures.
#:
#: BUILT IS NOT WIRED, and this tuple only ever claimed the former. Nothing
#: dispatches a pass by name yet, and the three kinds that declare this one all
#: declare no domain, so the write path still short-circuits them at
#: "origin unresolved". The pass is callable; no ingest calls it.
#:
#: The tuple is now self-enforcing rather than hand-maintained:
#: ``tests/test_passes_registry.py`` requires every declared pass to resolve to
#: a callable at ``doc_tools.passes.<namespace>.<name>`` UNLESS it is listed
#: here, AND requires everything listed here NOT to resolve. So a pass cannot
#: be built while still declared unbuilt, and cannot be declared without being
#: either built or listed.
UNBUILT_PASSES: tuple[str, ...] = (
    # ``xml.xml_document_identity`` -- the deterministic identity read for a
    # generic XML drop. Declared by the ``xml`` row because it is what that row
    # needs; listed here because it does not exist. Nothing resolves for
    # namespace ``xml``: there is no ``xml*.py`` in any pass package, which is
    # what ``test_nothing_listed_unbuilt_is_actually_built`` requires of every
    # name in this tuple.
    #
    # What it must do when it is built: read document number, revision, CAGE
    # and contract/program identifiers out of ELEMENTS AND ATTRIBUTES, with the
    # XPath that produced each value as its source, and refuse rather than guess
    # -- the same two invariants ``doc_tools/passes/identity.py`` enforces for
    # title blocks, over a different locator. Qualify every XPath by ancestor;
    # a bare ``//dmCode`` has already stolen a module's own ident in this repo.
    #
    # It is not urgent in the way an empty tuple would suggest it is: no
    # dispatcher maps a pass name to a callable yet, and this kind declares no
    # domain, so the write path short-circuits it at "origin unresolved" before
    # any pass would run.
    "xml.xml_document_identity",
)

#: Output classes with no ``owl:Class`` declaration in any TTL yet. ADR-0019 §6
#: calls these phantoms: an output URI is a phantom until it resolves to a
#: declared class. Both are owed by Lane 1 in
#: ``invincible-agent/setup/ontologies/mesh_system.ttl`` — whose ContentKind
#: tree comments that "A THIRD LEAF IS A FUTURE COMMIT, NOT A WIDER ENUM
#: HERE". ``mesh:EngineeringDocumentArtifact`` is the leaf the architect
#: ordered on 2026-10-02 ("add the third leaf… Don't alias it to CAD; an
#: engineering document is not a CAD artifact"); ``mesh:DoorsExportArtifact``
#: is its sibling, requested in the same packet. Registering the rows now and
#: letting them resolve when the TTL lands is the ordered sequence.
PHANTOM_OUTPUTS = (
    "mesh:EngineeringDocumentArtifact",
    "mesh:DoorsExportArtifact",
    # The generic-XML leaf, owed in the same place as its two siblings.
    # It is the FOURTH leaf of a tree whose comment says a third is "a
    # future commit, not a wider enum here" -- so it is requested with a
    # document behind it, which is what that comment asks for: the S1000D
    # 3xx planning types, which no shipping row can classify.
    "mesh:XMLArtifact",
)


# The mapping table. THE single source of truth for content kinds.
#
# "No row" and "HALT" are wired to the same condition by the resolver
# (``_lookup`` returning ``None`` triggers ``raise``). They cannot diverge.
#
# Rows 2-7 land the 2026-10-02 ruling: the shipping kinds, registered with
# their domains, as the rows the picker derives from. New rows remain the
# architect's call.
KIND_MAPPING: dict[str, ContentKindEntry] = {
    "work-instructions": ContentKindEntry(
        kind_source_value="work-instructions",
        kind="work-instruction",
        extractor_config="manufacturing_default",
        baml_function="ExtractWorkInstructions",
        target_ontology_class="http://edgy-solutions.com/ontology/mfg#WorkInstruction",
        domain_type="manufacturing",
        passes=("manufacturing.baml::ExtractWorkInstructions",),
        outputs=("mfg:WorkInstruction",),
    ),
    # ── Domain-declaring kinds ────────────────────────────────────────────
    "pcn": ContentKindEntry(
        kind_source_value="pcn",
        kind="pcn",
        extractor_config="sustainment_default",
        baml_function="ExtractHeader",
        target_ontology_class="http://edgy-solutions.com/ontology/pcn#ProcessChangeNotification",
        domain_type="sustainment",
        # Two passes, in the order SustainmentPlugin runs them: the header
        # (doc-level identity/dates) then the parts grid.
        passes=(
            "sustainment.baml::ExtractHeader",
            "sustainment.baml::ExtractParts",
        ),
        outputs=("pcn:ProcessChangeNotification", "pcn:Component"),
    ),
    "pdn": ContentKindEntry(
        kind_source_value="pdn",
        kind="pdn",
        extractor_config="sustainment_default",
        baml_function="ExtractHeader",
        target_ontology_class="http://edgy-solutions.com/ontology/pcn#ProductDiscontinuationNotice",
        domain_type="sustainment",
        passes=(
            "sustainment.baml::ExtractHeader",
            "sustainment.baml::ExtractParts",
        ),
        outputs=("pcn:ProductDiscontinuationNotice", "pcn:Component"),
    ),
    "s1000d-data-module": ContentKindEntry(
        kind_source_value="s1000d-data-module",
        kind="s1000d-data-module",
        # Not a BAML extractor: the S1000D path is a deterministic XML→RDF
        # parse (doc_tools/parsers/s1000d_rdf.py's S1000dGraphBuilder), so
        # baml_function is empty rather than invented.
        extractor_config="s1000d_default",
        baml_function="",
        target_ontology_class="http://edgy-solutions.com/ontology/mil#DataModule",
        domain_type="maintenance",
        # STILL THE CLASS, deliberately, and the passes dispatcher REFUSES it
        # for that reason: a class takes config only, so "call the declared
        # pass" would construct an empty builder, parse nothing, and succeed.
        # The conforming entry point now exists -- s1000d_rdf.data_module_graph
        # -- but this kind is SHARED with the platform overlay and sealed by
        # tests/test_overlay_kind_drift.py, so the declaration moves on both
        # sides at once or not at all. Packet dated 2026-10-08 asks for that.
        passes=("s1000d.S1000dGraphBuilder",),
        outputs=("mil:DataModule",),
    ),
    # ── Format-level kinds: NO DOMAIN (origin resolved by evidence) ────────
    "pdf": ContentKindEntry(
        kind_source_value="pdf",
        kind="pdf",
        extractor_config="",
        baml_function="",
        # mesh:PDFArtifact is already declared in mesh_system.ttl's ContentKind
        # tree — this is the one format-level row whose output is NOT a phantom.
        target_ontology_class="http://edgy-solutions.com/ontology/mesh#PDFArtifact",
        domain_type=None,
        passes=("identity.document_identity",),
        outputs=("mesh:PDFArtifact",),
        ingress_prefix="pdf",
        file_suffixes=(".pdf",),
    ),
    "engineering-document": ContentKindEntry(
        kind_source_value="engineering-document",
        kind="engineering-document",
        extractor_config="",
        baml_function="",
        target_ontology_class=(
            "http://edgy-solutions.com/ontology/mesh#EngineeringDocumentArtifact"
        ),
        domain_type=None,
        passes=("identity.document_identity",),
        outputs=("mesh:EngineeringDocumentArtifact",),
    ),
    "doors-export": ContentKindEntry(
        kind_source_value="doors-export",
        kind="doors-export",
        extractor_config="",
        baml_function="",
        target_ontology_class=(
            "http://edgy-solutions.com/ontology/mesh#DoorsExportArtifact"
        ),
        domain_type=None,
        # NOT ``identity.document_identity``: that pass scans everything it is
        # given for title-block labels, so a requirement whose OBJECT TEXT
        # reads "Contract No: ..." would be read as the module's identity.
        # ``identity_from_doors_text`` scopes the read to the preamble above
        # the column-header row. Sealed by
        # tests/test_passes_dispatch.py::test_doors_object_text_contract_line_is_not_the_identity
        passes=("identity.identity_from_doors_text",),
        outputs=("mesh:DoorsExportArtifact",),
    ),
    # ``xml`` is the generic XML drop: an XML document that is NOT an S1000D
    # data module. It exists because without it such a drop HALTS. The S1000D
    # 3xx planning types are the measured case -- they carry 320 types under
    # the bare root, so the row that classifies a data module cannot classify
    # them, and ADR-0021 §3 then (correctly) refuses the drop entirely.
    #
    # IT DOES NOT WEAKEN THE HALT for an undeclared drop. A kind is reached
    # only by an explicit ``metadata.content_kind: xml`` or by a path whose
    # segment after the domain IS ``xml`` (``_derive_from_path`` requires
    # ``parts[0] == domain_type``). A file that declares nothing and sits at no
    # such path still halts, which is the behaviour ADR-0021 is protecting.
    #
    # It also does not shadow ``s1000d-data-module``: precedence is metadata
    # first, and a drop that declares ``s1000d-data-module`` gets that row. A
    # data module DECLARED as ``xml`` would take the generic path -- that is a
    # mis-declaration at the seam, not something this table can detect, and the
    # resolver deliberately never second-guesses a declaration by sniffing the
    # file.
    #
    # NO DOMAIN, under the same 2026-10-02 ruling as pdf/engineering-document/
    # doors-export: a file format is not an origin. "XML" says even less about
    # provenance than "PDF" does -- S1000D, DITA, IADS, MIL-STD-40051 and a
    # DOORS export are all XML and belong to different systems of record. If
    # the format-level kinds were ever going to assert a domain, this is the row
    # that shows why they cannot.
    "xml": ContentKindEntry(
        kind_source_value="xml",
        kind="xml",
        extractor_config="",
        baml_function="",
        target_ontology_class="http://edgy-solutions.com/ontology/mesh#XMLArtifact",
        domain_type=None,
        # NOT ``identity.document_identity``, and the difference matters.
        # That pass takes PAGE TEXTS and is anchored on title-block labels
        # (``Document No.:`` and the aliases beside it). An XML document has
        # neither pages nor title-block lines: its identity is in elements and
        # attributes. Declaring the title-block pass here would not fail --
        # it would run and find nothing, which is the failure mode this repo
        # keeps re-learning (a stubbed call and a missing prompt file both read
        # as a near-pass). So the row declares the pass it ACTUALLY needs,
        # which is not built, and admits that in UNBUILT_PASSES.
        passes=("xml.xml_document_identity",),
        outputs=("mesh:XMLArtifact",),
        ingress_prefix="xml",
        file_suffixes=(".xml",),
    ),
}


#: Secondary index: the REGISTERED KIND spelling → the same row.
#:
#: Why it exists. The picker's legal set is
#: ``registered_kinds(registrations)``, i.e. the ``kind`` values — while
#: ``KIND_MAPPING`` is keyed by ``kind_source_value``. For six of the seven
#: rows the two spellings coincide. For the seventh they do NOT
#: (``work-instructions`` → ``work-instruction``), so a picker offering the
#: registered kind would send a value the mapping table has no key for, and
#: ADR-0021's halt would fire on a kind that IS registered. Both spellings
#: resolving to one row is what makes "the legal set IS the registered rows"
#: true rather than nearly true. Pinned by
#: ``tests/test_kind_registry.py::test_the_registered_kind_spelling_also_resolves``.
_BY_KIND: dict[str, ContentKindEntry] = {e.kind: e for e in KIND_MAPPING.values()}


def _lookup(kind_source_value: Optional[str]) -> Optional[ContentKindEntry]:
    """One lookup over both spellings. ``None`` in → ``None`` out → HALT."""
    if not kind_source_value:
        return None
    return KIND_MAPPING.get(kind_source_value) or _BY_KIND.get(kind_source_value)


def _derive_from_path(s3_key: str, domain_type: Optional[str]) -> Optional[str]:
    """Per ADR-0021 §Path-derived: segment AFTER the ``domain_type`` segment.

    Returns ``None`` on shape mismatch (key has < 2 segments, or first
    segment does not match ``domain_type``). The caller's halt fires at
    the table lookup — ``None`` is not in the table — so a malformed path
    routes THROUGH the halt rather than around it.
    """
    if not s3_key or domain_type is None:
        return None
    parts = s3_key.split("/")
    if len(parts) < 2 or parts[0] != domain_type:
        return None
    return parts[1]


def resolve_content_kind(
    manifest_metadata: dict, s3_key: str
) -> ContentKindEntry:
    """ADR-0021 precedence: metadata > path > HALT.

    The function NEVER returns a default. The only way to NOT raise is for
    the resolved ``kind_source_value`` to have a row in ``KIND_MAPPING``
    (under either its ``kind_source_value`` or its ``kind`` spelling).
    Table-miss == unclassifiable == HALT. Contract tested by
    ``test_unclassifiable_kind_HALTS_does_not_default``.

    A returned row may declare ``domain_type=None``. That is NOT a failure to
    resolve — the kind resolved, and what it says is "I have no domain." The
    caller owns what to do with it (``semantic_assets.py`` returns
    "origin unresolved" and writes nothing).

    Empty-string handling (sharpening 2026-06-20 architect ruling): an
    explicit ``content_kind = ""`` value in ``manifest_metadata`` is
    treated as ABSENT — i.e. falls through to path-derive. The decision is
    that an empty-string from JSON/metadata tooling reflects a "field exists
    but unset" shape, not an explicit "no kind" assertion. A
    genuinely-wrong explicit value (``content_kind = "nonsense"``) does NOT
    fall through — it goes straight to the table lookup, finds no row, and
    halts. That asymmetry is deliberate: explicit-wrong should halt loudly;
    explicit-empty is treated as "no signal given." The behavior is named
    here and tested by
    ``test_empty_string_content_kind_falls_through_to_path``.
    """
    raw_metadata_value = manifest_metadata.get("content_kind")
    # Strip whitespace; treat empty/whitespace-only as ABSENT (deliberate
    # named decision, NOT an `or`-truthiness accident).
    metadata_value = raw_metadata_value.strip() if isinstance(raw_metadata_value, str) else raw_metadata_value
    if metadata_value:
        kind_source_value = metadata_value
    else:
        kind_source_value = _derive_from_path(s3_key, manifest_metadata.get("domain_type"))

    entry = _lookup(kind_source_value)
    if entry is None:
        raise UnclassifiableContentKindError(
            f"No KIND_MAPPING row for kind_source_value={kind_source_value!r} "
            f"(from manifest.metadata.content_kind={raw_metadata_value!r} "
            f"or path-derive over s3_key={s3_key!r}). "
            f"Per ADR-0021 §Precedence the kind-selection chain HALTS here — "
            f"there is no silent default. Either add a row to KIND_MAPPING "
            f"(in doc_tools/utils/content_kind.py) with a registered "
            f"target_ontology_class and BAML extractor, or correct the "
            f"upstream manifest/path. Registered kinds: "
            f"{sorted(_BY_KIND)}."
        )
    return entry


def ingress_user_key_pattern(entry: ContentKindEntry) -> str:
    r"""The sensor gate for one format-level row, GENERATED rather than written.

    ``^ingress-user/<prefix>/[0-9a-f]{64}/[^/]+\.(ext|ext)$`` -- a single
    suffix is emitted without the group, so the pdf row reproduces the
    previously hand-written literal byte for byte.

    Raises ValueError if the row declares no ``ingress_prefix``.
    """
    import re

    if not entry.ingress_prefix:
        raise ValueError(
            f"content kind {entry.kind!r} declares no ingress_prefix; it is not "
            f"droppable at the ingress-user seam")
    if not entry.file_suffixes:
        raise ValueError(
            f"content kind {entry.kind!r} declares ingress_prefix "
            f"{entry.ingress_prefix!r} but no file_suffixes")
    exts = [re.escape(s.lstrip(".")) for s in entry.file_suffixes]
    group = exts[0] if len(exts) == 1 else "(" + "|".join(exts) + ")"
    return (
        rf"^ingress-user/{re.escape(entry.ingress_prefix)}/[0-9a-f]{{64}}/[^/]+\.{group}$"
    )


def ingress_user_prefixes() -> dict[str, str]:
    """``ingress_prefix`` -> its generated pattern, for every row declaring one.
    This is the "generic prefix per kind registration": the seam's legal shapes
    come from the registry, not from literals in definitions.py."""
    return {
        e.ingress_prefix: ingress_user_key_pattern(e)
        for e in KIND_MAPPING.values()
        if e.ingress_prefix
    }


def processable_kinds() -> tuple[str, ...]:
    """Registered kinds every declared pass of which this repo can actually run.

    ADR-0041 section 4 is "classifier suggests, human confirms into
    manifest.metadata.content_kind", and the picker's legal set is
    ``registered_kinds()``. That set is WIDER than what the dispatcher can
    execute, so a suggester built on it alone would offer a kind that fails at
    dispatch. This is the narrower set: a kind qualifies only if none of its
    declared passes is in ``UNBUILT_PASSES`` and none resolves to a class or a
    non-callable (``dispatch.py`` raises ``PassContractError`` for both).
    BAML passes (``<ns>.baml::<Fn>``) are dispatched by a different arm and
    count as processable.

    Measured at the time of writing: ``xml`` is excluded (its only pass is
    unbuilt) and ``s1000d-data-module`` is excluded (``s1000d.S1000dGraphBuilder``
    is a class, which dispatch refuses by contract). Both exclusions are
    CORRECT, not gaps to paper over.
    """
    import inspect

    # Lazy: dispatch imports this module.
    from doc_tools.passes.dispatch import resolve_python_pass

    def _runnable(dotted: str) -> bool:
        if dotted in UNBUILT_PASSES:
            return False
        if "::" in dotted:
            return True
        hits = resolve_python_pass(dotted)
        if not hits or len(hits) != 1:
            return False
        fn = hits[0][1]
        return not inspect.isclass(fn) and callable(fn)

    # SORTED, because iagent_mesh.ingest.registered_kinds() is sorted and this
    # is documented as its narrower subset -- an unsorted subset of a sorted set
    # reads as a different set to anyone diffing or displaying the two.
    return tuple(sorted(
        e.kind for e in KIND_MAPPING.values()
        if e.passes and all(_runnable(p) for p in e.passes)
    ))
