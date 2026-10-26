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
    #: prefix. With no ``ingress_prefix`` a row MAY still declare suffixes, and they then
    #: gate that kind's own inbound sensor (``course``). With an
    #: ``ingress_prefix`` they are required.
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
#: BUILT IS NOT WIRED, and this tuple only ever claimed the former. That
#: distinction NARROWED and this paragraph used to deny it: PR #94 added an
#: ingest route, and ``doc_tools/assets/doors_ingestion.py`` now calls
#: ``run_passes_for_kind("doors-export", ...)``, so a declared pass IS
#: dispatched by name in production for that kind. The earlier wording
#: ("nothing dispatches a pass by name yet ... no ingest calls it") was left
#: standing after the code moved under it, which is how a docstring claiming
#: Helm was absent from CI in this repo reached two merged PRs. The remaining
#: format-level rows declare no domain, so the write path still short-circuits
#: those at "origin unresolved".
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
    # ``cad.cad_document_identity`` -- the deterministic identity read for a
    # CAD drop, declared by the ``cad`` row (architect authorisation
    # 2026-10-13) and listed here because it does not exist.
    #
    # STALE JUSTIFICATION CORRECTED (2026-10-25). This comment used to read
    # "Nothing resolves for namespace ``cad``: there is no ``cad*.py`` in any
    # pass package." That is no longer true -- #99 added
    # ``doc_tools/passes/cad.py`` with ``step_ap242_identity`` and
    # ``dxf_identity``, declared by the ``step-ap242`` and ``dxf`` rows. The
    # TUPLE MEMBERSHIP is still correct, because what is unbuilt is this NAME:
    # no ``cad_document_identity`` exists in that module.
    # ``test_nothing_listed_unbuilt_is_actually_built`` resolves the dotted
    # name, not the module, which is why it stayed green across #99 and why
    # only the prose was wrong. Left in place rather than deleted because a
    # reader comparing this tuple against the overlay (lane 01 did, on
    # 2026-10-23) would otherwise conclude the whole namespace is empty.
    #
    # What it must do when it is built: read part number, revision, CAGE and
    # contract/program identifiers out of CAD METADATA -- a STEP header's
    # FILE_NAME/FILE_DESCRIPTION entities, a DWG/DXF header block, or the
    # product-data attributes a native CATIA/SolidWorks part carries -- with
    # the entity or attribute that produced each value as its source, and
    # refuse rather than guess. Same two invariants as
    # ``doc_tools/passes/identity.py``, over a locator that is not text at all.
    #
    # It is NOT a title-block OCR of a drawing sheet. A drawing SHEET exported
    # to PDF is a ``pdf`` drop and already has a pass; this one is for the
    # model file, where the identity is structured data and reading it is
    # deterministic.
    #
    # Not urgent in the way an empty tuple would suggest: no dispatcher maps a
    # pass name to a callable yet, this kind declares no domain so the write
    # path short-circuits it at "origin unresolved", and no sensor launches a
    # run for a CAD drop in the first place.
    "cad.cad_document_identity",
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
    # No TTL declares a training class yet; owed by Lane 1 (packet to follow).
    "training:Course",
    # The FIFTH and SIXTH leaves, owed by Lane 1 alongside the others above:
    # the STEP AP242 and DXF format-level kinds. As with the others, the rows
    # are registered now and the outputs resolve when the TTL lands.
    "mesh:StepAp242Artifact",
    "mesh:DxfArtifact",
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
    # The training-domain course kind (2026-10-23 restore-training directive,
    # lane tr). Reached by PATH: training/course/<folder>/<deck> (ADR-0021).
    "course": ContentKindEntry(
        kind_source_value="course",
        kind="course",
        extractor_config="training_default",
        baml_function="ExtractConcepts",
        target_ontology_class="http://edgy-solutions.com/ontology/training#Course",
        domain_type="training",
        passes=("core.baml::ExtractOutline", "training.baml::ExtractConcepts",
                "render.pages"),
        outputs=("training:Course",),
        file_suffixes=(".pptx", ".pdf", ".docx"),
        ingress_prefix=None,
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
    # ``cad`` — the CAD drop. ARCHITECT AUTHORISATION 2026-10-13: "add the cad
    # format row to KIND_MAPPING (architect authorisation, cite this)". Placed
    # beside ``pdf`` rather than with the other format rows because the
    # ontology pairs them: ``mesh:CADArtifact`` is "the drop-box's SECOND case,
    # alongside PDF (ADR-0041 §8's `ContentKind` pairing)".
    #
    # THE OUTPUT CLASS IS NOT A PHANTOM, and that is the one thing worth
    # checking before adding a row. ``mesh:CADArtifact`` is declared —
    # ``invincible-agent/setup/ontologies/mesh_system.ttl:808``, ``a owl:Class ;
    # rdfs:subClassOf mesh:Artifact ; rdfs:label "CAD Artifact"`` — so unlike
    # ``mesh:EngineeringDocumentArtifact`` and its two siblings this row owes
    # Lane 1 nothing and goes nowhere near ``PHANTOM_OUTPUTS``.
    #
    # The same TTL comment prescribes this row's shape rather than leaving it
    # to taste: "Same selection rule as the PDF kind: declared via
    # `manifest.metadata.content_kind`, resolved to this class, never
    # LLM-classified." So: declaration-only selection, and the class as the
    # target the declared string resolves to.
    #
    # NO DOMAIN, under the 2026-10-02 ruling that governs every format row
    # here: a file format is not an origin. A STEP or DWG reaches this repo
    # from design, manufacturing and sustainment alike, and the geometry says
    # nothing about which.
    #
    # NOT ALIASED TO ``engineering-document``, in either direction. The
    # architect's 2026-10-02 words were "Don't alias it to CAD; an engineering
    # document is not a CAD artifact" — said of the engineering-document leaf,
    # and the asymmetry does not exist, so a CAD drop does not borrow that
    # leaf either. Each takes its own.
    #
    # WHAT THIS ROW UNBLOCKS, AND WHAT IT DOES NOT. It closes the halt: a drop
    # declaring ``content_kind: cad`` now resolves to a row instead of raising
    # ``UnclassifiableContentKindError`` at the ADR-0041 kind guard. It does
    # NOT make a CAD drop ingest. ``ingress_user_sensor``'s ``s3_filter`` is
    # ``^ingress-user/pdf/[0-9a-f]{64}/[^/]+\.pdf$``, which rejects
    # ``ingress-user/cad/<64hex>/part.step`` BY DESIGN (the D2 fix — a CAD drop
    # must never reach the PDF parser), so no run launches for one today. A
    # CAD-side sensor and extractor are separate work and are not ordered.
    #
    # The format guard at ``document_parser.py:221`` stays exactly as it is: it
    # refuses ``domain_type in ("pdf", "cad")`` as a SEMANTIC domain. This row
    # is the other half of that same statement — ``cad`` is a legitimate
    # CONTENT KIND and an illegitimate DOMAIN — and the two halves live in the
    # two places that enforce them.
    "cad": ContentKindEntry(
        kind_source_value="cad",
        kind="cad",
        extractor_config="",
        baml_function="",
        target_ontology_class="http://edgy-solutions.com/ontology/mesh#CADArtifact",
        domain_type=None,
        # NOT ``identity.document_identity``, and the reason is the input, not
        # the intent. That pass takes PAGE TEXTS and anchors on title-block
        # labels; a STEP/DWG payload has no page text at all, so declaring it
        # would register a pass that cannot run on this kind's own input and
        # would resolve to a callable, hiding that fact from
        # ``tests/test_passes_registry.py``. Same resolution as the ``xml``
        # row: declare the pass this kind needs and list it UNBUILT until it
        # exists.
        passes=("cad.cad_document_identity",),
        outputs=("mesh:CADArtifact",),
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
        passes=("identity.identity_from_doors_text", "doors.requirements_rows"),
        outputs=("mesh:DoorsExportArtifact",),
    ),
    # STEP AP242 and DXF: CAD file formats, identity pass only (no extraction).
    # domain_type=None is deliberate: under the 2026-10-02 ruling a FILE FORMAT
    # IS NOT AN ORIGIN. A STEP or DXF file can come from any system of record,
    # exactly as the pdf / xml / doors-export rows argue. Reached only by an
    # explicit declaration; an unregistered CAD format (iges, sldprt, ...) still
    # HALTS as UnclassifiableContentKindError.
    "step-ap242": ContentKindEntry(
        kind_source_value="step-ap242",
        kind="step-ap242",
        extractor_config="",
        baml_function="",
        target_ontology_class=(
            "http://edgy-solutions.com/ontology/mesh#StepAp242Artifact"
        ),
        domain_type=None,
        passes=("cad.step_ap242_identity",),
        outputs=("mesh:StepAp242Artifact",),
    ),
    "dxf": ContentKindEntry(
        kind_source_value="dxf",
        kind="dxf",
        extractor_config="",
        baml_function="",
        target_ontology_class=(
            "http://edgy-solutions.com/ontology/mesh#DxfArtifact"
        ),
        domain_type=None,
        passes=("cad.dxf_identity",),
        outputs=("mesh:DxfArtifact",),
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


def domain_label_for_kind(kind: str) -> Optional[str]:
    """Uppercase domain label for a registered kind, or None when the kind is
    unknown or declares no domain.

    Exists so the label has ONE definition per route. A kind-derived label and
    a plugin-derived label (``BaseDomainPlugin.domain_label``,
    plugins/base.py:175-180) computed two different ways drift apart, exactly
    as the two processability arms did. The sanitization here is deliberately
    byte-for-byte that property's: ``.upper().replace(" ", "_").replace("-", "_")``.

    Resolves through ``_BY_KIND``, the module's one kind index, rather than
    scanning ``KIND_MAPPING`` again -- a second traversal is a second lookup
    convention, and those are what drift.
    """
    entry = _BY_KIND.get(kind)
    if entry is None or not entry.domain_type:
        return None
    return entry.domain_type.upper().replace(" ", "_").replace("-", "_")


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


def inbound_suffix_pattern(entry: ContentKindEntry) -> str:
    r"""Sensor ``s3_filter`` for a path-derived kind, GENERATED from its suffixes.

    dag_tools applies the filter with ``re.match`` against the full key, so
    this is anchored by match semantics: ``(?i)^.*\.(ext|ext)$``.
    """
    import re

    if not entry.file_suffixes:
        raise ValueError(f"content kind {entry.kind!r} declares no file_suffixes")
    exts = "|".join(re.escape(s.lstrip(".")) for s in entry.file_suffixes)
    return rf"(?i)^.*\.({exts})$"


def ingress_user_prefixes() -> dict[str, str]:
    """``ingress_prefix`` -> its generated pattern, for every row declaring one.
    This is the "generic prefix per kind registration": the seam's legal shapes
    come from the registry, not from literals in definitions.py."""
    return {
        e.ingress_prefix: ingress_user_key_pattern(e)
        for e in KIND_MAPPING.values()
        if e.ingress_prefix
    }


KIND_UNBUILT_PASS = "unbuilt_pass"
KIND_PASS_IS_A_CLASS = "pass_is_a_class"
KIND_PASS_UNRESOLVED = "pass_unresolved"   # 0 hits, or >1 ambiguous hits
KIND_PASS_NOT_CALLABLE = "pass_not_callable"
KIND_NO_PASSES = "no_passes"

KIND_REASON_CODES: tuple[str, ...] = (
    KIND_UNBUILT_PASS,
    KIND_PASS_IS_A_CLASS,
    KIND_PASS_UNRESOLVED,
    KIND_PASS_NOT_CALLABLE,
    KIND_NO_PASSES,
)


def _pass_unrunnable_reason(dotted: str) -> Optional[tuple[str, str]]:
    """``None`` if this one pass is runnable, else ``(reason_code, detail)``.

    The single predicate both ``processable_kinds()`` and ``kind_exclusions()``
    are built on, so the positive and negative sets cannot drift apart.
    """
    import inspect

    # Lazy: dispatch imports this module.
    from doc_tools.passes.dispatch import resolve_python_pass

    if dotted in UNBUILT_PASSES:
        return (KIND_UNBUILT_PASS,
                f"pass {dotted!r} is listed in UNBUILT_PASSES: declared but not built")
    if "::" in dotted:
        return None  # BAML arm, dispatched elsewhere
    hits = resolve_python_pass(dotted)
    if not hits:
        return (KIND_PASS_UNRESOLVED,
                f"pass {dotted!r} resolved to 0 hits: no such python pass in this image")
    if len(hits) != 1:
        return (KIND_PASS_UNRESOLVED,
                f"pass {dotted!r} resolved to {len(hits)} hits: ambiguous, dispatch needs exactly 1")
    fn = hits[0][1]
    if inspect.isclass(fn):
        return (KIND_PASS_IS_A_CLASS,
                f"pass {dotted!r} resolves to a class; dispatch refuses a class by contract")
    if not callable(fn):
        return (KIND_PASS_NOT_CALLABLE,
                f"pass {dotted!r} resolves to a non-callable; dispatch refuses it by contract")
    return None


def _kind_exclusion(e: ContentKindEntry) -> Optional[dict]:
    """``None`` if every declared pass of ``e`` is runnable, else its exclusion
    entry, reported on the FIRST unrunnable pass in declared order."""
    if not e.passes:
        return {"kind": e.kind, "reason_code": KIND_NO_PASSES, "pass": None,
                "detail": f"kind {e.kind!r} declares no passes, so there is nothing to run"}
    for p in e.passes:
        r = _pass_unrunnable_reason(p)
        if r is not None:
            code, detail = r
            n = len(e.passes)
            if n > 1:
                detail += (f"; first unrunnable pass of {n} declared, in the order "
                           f"they would run")
            return {"kind": e.kind, "reason_code": code, "pass": p, "detail": detail}
    return None


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

    Measured at the time of writing: ``cad`` and ``xml`` are excluded (their
    passes are unbuilt) and ``s1000d-data-module`` is excluded
    (``s1000d.S1000dGraphBuilder`` is a class, which dispatch refuses by
    contract).

    THIS IS ONE ARM, NOT THE ANSWER TO "can the image process X". An earlier
    revision of this docstring called all of those exclusions CORRECT; that is
    true of THIS arm and false of the image. ``xml_ingestion``'s user-drop table
    routes ``s1000d-data-module`` to the very class this function rejects, and on
    2026-10-16 ten ODMRAD data modules completed all five stages of
    ``xml_graph_sync_job`` through it. Ask ``doc_tools.api.kinds`` for the union
    of the arms; it is what ``GET /kinds/processable`` serves, and it names each
    arm so the disagreement stays visible.
    """
    # SORTED, because iagent_mesh.ingest.registered_kinds() is sorted and this
    # is documented as its narrower subset -- an unsorted subset of a sorted set
    # reads as a different set to anyone diffing or displaying the two.
    return tuple(sorted(
        e.kind for e in KIND_MAPPING.values() if _kind_exclusion(e) is None
    ))


def kind_exclusions() -> tuple[dict, ...]:
    """Every registered kind this image CANNOT process, with the cause.

    Sorted by kind. Each entry: {"kind", "reason_code", "pass", "detail"}.
    ``pass`` is the dotted pass string that caused it, or None for no_passes.
    ``detail`` is a sentence naming the pass and the cause -- a door that merely
    omits a kind tells the human nothing.
    """
    out = [x for x in (_kind_exclusion(e) for e in KIND_MAPPING.values()) if x]
    return tuple(sorted(out, key=lambda d: d["kind"]))
