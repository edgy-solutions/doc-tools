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


#: Passes and output classes that are DECLARED HERE but not yet reachable —
#: kept as data so the phantoms stay visible instead of being discovered by a
#: failing ingest. Enumerated by ``tests/test_kind_registry.py``, which asserts
#: this is exactly the set of undeclared/unbuilt references in the table.
#:
#: ``identity.document_identity`` is the document-identity pass the architect
#: ordered on 2026-10-02 ("document number, revision, CAGE code, contract/
#: program identifiers from title blocks and DOORS module attributes, verbatim
#: with sources, refused if not printed"). It is the NEXT item of work, not
#: built yet. Nothing runs it meanwhile: the three kinds that declare it all
#: declare no domain, so the write path short-circuits them at
#: "origin unresolved" before any pass could run.
UNBUILT_PASSES = ("identity.document_identity",)

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
PHANTOM_OUTPUTS = ("mesh:EngineeringDocumentArtifact", "mesh:DoorsExportArtifact")


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
        passes=("identity.document_identity",),
        outputs=("mesh:DoorsExportArtifact",),
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
