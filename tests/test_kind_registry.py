"""The shipping content kinds, registered — ruling 2026-10-02.

*"7f registers the shipping kinds (PDF, EngineeringDocument, PCN, PDN,
S1000D-data-module) with their domains, as the kind-registration rows the
picker derives from."*

and, on what "with their domains" means for the format-level ones:

*"KIND_MAPPING rows: pcn, pdn → SUSTAINMENT; s1000d-data-module → MAINTENANCE;
engineering-document, doors-export, pdf → none (origin resolved by evidence,
not kind)."*

THREE SEAMS ARE PINNED HERE, and they fail in three different ways if left
unpinned:

 1. **The table vs the rows.** ``registered_kinds()`` makes the picker's legal
    set the registered rows. If the rows drifted from ``KIND_MAPPING``, the
    picker would offer a kind the mapping table cannot resolve, and ADR-0021's
    halt would fire on a kind that IS registered.
 2. **The two spellings of a kind.** The table is keyed by
    ``kind_source_value``; the picker offers ``kind``. They differ for exactly
    one row.
 3. **The phantoms.** Two output classes and one pass are declared before they
    exist. That is the ordered sequence the architect set, not an oversight —
    so the set of not-yet-real references is asserted to be EXACTLY the
    declared one, which turns "someone added a third phantom quietly" into a
    failure.
"""
import json
from pathlib import Path

import pytest

from doc_tools.utils.content_kind import (
    KIND_MAPPING,
    PHANTOM_OUTPUTS,
    UNBUILT_PASSES,
    UnclassifiableContentKindError,
    resolve_content_kind,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROWS_DIR = REPO_ROOT / "registry" / "content_kinds"
DOMAINS_FILE = REPO_ROOT / "registry" / "content_kind_domains.json"

#: The ruling, transcribed as data. Lowercase because ``domain_type`` is the
#: pipeline value and ``domain_label`` is its uppercase (the Neo4j label and
#: the ``<http://internal/{DOMAIN}_INSTANCES>`` graph name) — the ruling's
#: SUSTAINMENT/MAINTENANCE is what reaches the graph either way.
RULED_DOMAINS = {
    "pcn": "sustainment",
    "pdn": "sustainment",
    "s1000d-data-module": "maintenance",
    "engineering-document": None,
    "doors-export": None,
    "pdf": None,
    # Not from the 2026-10-02 ruling — the `cad` row is the architect's
    # 2026-10-13 authorisation. It is transcribed here because it is governed
    # by the SAME clause ("a file format is not an origin") and a row pinned by
    # nothing is a row that can drift to a domain nobody granted it.
    "cad": None,
    # Not from the 2026-10-02 ruling either — the `course` row is the
    # architect's 2026-10-23 restore-training directive (ADR-0059, lane tr),
    # and its NAME is Chris's 2026-10-23 ruling: "a kind names the document,
    # not the domain" (a course deck in the training domain, the way a PCN is a
    # notice in sustainment). Unlike cad it declares a domain, and the drop
    # path `training/course/` carries it (contract v2).
    "course": "training",
}


# --------------------------------------------------------------------------- #
# 1. The ruling, row by row
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind,domain", sorted(RULED_DOMAINS.items(), key=str))
def test_the_ruled_domain_is_what_the_row_declares(kind, domain):
    entry = KIND_MAPPING[kind]
    assert entry.domain_type == domain, (
        f"{kind!r} must declare domain {domain!r}; row says "
        f"{entry.domain_type!r}"
    )


def test_a_format_level_kind_declares_none_and_that_is_not_an_empty_string():
    """``None``, not ``""``. The difference is load-bearing: ``""`` is falsy
    the same way a missing value is, so it would read as "nobody filled this
    in" at every call site — while ``None`` here is a POSITIVE assertion that
    a PDF has no domain of its own. The write path branches on
    ``is None``, so an empty string would sail past it into
    ``"".upper()`` and a blank Neo4j label.
    """
    for kind in ("pdf", "cad", "engineering-document", "doors-export", "xml"):
        assert KIND_MAPPING[kind].domain_type is None


def test_the_registered_kind_spelling_also_resolves():
    """Seam 2. ``work-instructions`` (the kind-source value, the table key) and
    ``work-instruction`` (the registered kind, what a picker offers) must reach
    the same row, or "the legal set IS the registered rows" is false for one of
    seven rows — and false in the direction that halts a legitimate drop.
    """
    by_source = resolve_content_kind({"content_kind": "work-instructions"}, "")
    by_kind = resolve_content_kind({"content_kind": "work-instruction"}, "")
    assert by_source is by_kind

    for entry in KIND_MAPPING.values():
        assert resolve_content_kind({"content_kind": entry.kind}, "") is entry


def test_an_unregistered_kind_still_halts():
    """Adding six rows must not have turned the halt into a near-miss match."""
    with pytest.raises(UnclassifiableContentKindError):
        resolve_content_kind({"content_kind": "pcn-notice"}, "")


def test_only_the_training_course_prefix_path_derives_onto_a_row():
    """Why adding these rows changes nothing for the live corpus.

    ``_derive_from_path`` returns the segment AFTER the domain segment. The
    configured sensors watch ``manufacturing/inbound/`` and
    ``sustainment/inbound/``, so a curated key path-derives to ``"inbound"``,
    which has no row — the PCN corpus keeps taking the scoped-migration
    fallback it takes today. The new rows are reachable only through an
    EXPLICIT ``metadata.content_kind``, which only the ``/ingest`` door sets.
    That is the measurement behind claiming this PR is inert for the gate, so
    it is pinned rather than asserted in prose.

    The one deliberate exception: the training sensor on ``training/course/``
    path-derives onto the ``course`` row on purpose (contract v2, 2026-10-23).
    It is pinned with a positive control so the derivation cannot silently
    stop working while the negative half stays green.
    """
    from doc_tools.utils.content_kind import _derive_from_path

    assert _derive_from_path("sustainment/inbound/x.pdf", "sustainment") == "inbound"
    assert "inbound" not in KIND_MAPPING
    with pytest.raises(UnclassifiableContentKindError):
        resolve_content_kind(
            {"domain_type": "sustainment"}, "sustainment/inbound/x.pdf"
        )
    assert (
        _derive_from_path("training/course/hydraulics-fixture/deck.pptx", "training")
        == "course"
    )
    assert (
        resolve_content_kind({"domain_type": "training"}, "training/course/x/d.pptx")
        is KIND_MAPPING["course"]
    )


# --------------------------------------------------------------------------- #
# 2. The projection the picker reads
# --------------------------------------------------------------------------- #
def test_the_generated_rows_are_in_sync_with_the_table():
    """Seam 1, as the generator's own ``--check``."""
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "generate_kind_registrations.py"),
         "--check"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_rows_load_and_validate_through_the_sdk():
    """The rows are only the picker's legal set if the SDK accepts them.

    ``load_content_kind_registrations`` applies the whole composer discipline
    — one row per file, keyed by ``kind``, duplicate keys and empty files
    refused — and then builds each row through a model that is
    ``extra="forbid"`` and demands non-empty ``passes``/``outputs``. So this
    one call covers the file conventions and the field contract together.

    MEASURED, not deferred to CI: run against a pristine ``v0.9.5`` tree (the
    ``pyproject`` pin), all seven rows load and ``registered_kinds()`` returns
    them sorted. The installed venv copy predates the ``ingest`` module, which
    is why this skips locally.

    **IF THIS TEST STARTS FAILING WITH "domain Field required", THAT IS THE
    ALARM, NOT A BUG HERE** — and it would mean a 0.9.7 shipped in a shape the
    architect already ruled against. The in-flight, untagged 0.9.7 first added
    a REQUIRED non-empty ``domain: str`` to ``ContentKindRegistration``
    ("a kind with no domain has no audience"), which refused all seven of these
    row files and could not represent the ruling's ``none`` for ``pdf`` /
    ``engineering-document`` / ``doors-export`` at all — a required non-empty
    string has no spelling for "this kind has no domain of its own".

    RESOLVED 2026-10-02: the field goes ``str | None``, optional, in lane/ca's
    next commit, and these rows register against that shape unchanged. An
    optional field is ignorable; it is the required one that was unsatisfiable
    without inventing a domain for a format-level kind. The rows do not gain a
    ``domain`` key here: at the ``v0.9.5`` pin the model is ``extra="forbid"``,
    so that migration travels with the pin bump —
    ``test_a_domain_key_in_a_row_would_be_refused_at_the_pin`` carries the
    detail.
    """
    ingest = pytest.importorskip(
        "iagent_mesh.ingest",
        reason="the installed iagent_mesh predates v0.9.5's ingest module; CI "
               "installs the pinned SDK and runs this",
    )
    rows = ingest.load_content_kind_registrations(ROWS_DIR)
    assert ingest.registered_kinds(rows) == tuple(
        sorted(e.kind for e in KIND_MAPPING.values())
    )
    for row in rows:
        entry = KIND_MAPPING[row.kind] if row.kind in KIND_MAPPING else next(
            e for e in KIND_MAPPING.values() if e.kind == row.kind
        )
        assert row.passes == entry.passes
        assert row.outputs == entry.outputs


def test_a_domain_key_in_a_row_would_be_refused_at_the_pin():
    """Why the domain rides BESIDE the rows instead of in them — AT THE PIN.

    At ``v0.9.5``, ``ContentKindRegistration`` is ``extra="forbid"`` with
    exactly ``kind``/``passes``/``outputs`` and no domain field: the SDK ships
    no rows and takes no position on domain. So ``domain:`` in a YAML row would
    not be ignored, it would raise, and the whole registry directory would stop
    loading — measured, ``ValidationError``. That is the constraint the sidecar
    ``content_kind_domains.json`` exists to satisfy.

    THIS ASSERTION IS PINNED TO THE PIN, AND IT IS EXPECTED TO INVERT. At a
    later SDK the same call that raises here becomes the only one that
    SUCCEEDS, so it is written as a shape-conditional rather than a bare
    ``raises``: a pin bump then produces a readable statement of which shape
    arrived instead of a bare assertion error.

    THE COLLISION IS RULED (2026-10-02): ``domain`` becomes ``str | None`` —
    OPTIONAL. So the mere PRESENCE of the field is the expected end state and
    is NOT an alarm; this test accepts it and still passes. What stays an alarm
    is a **required** ``domain``, because a required non-empty string has no
    spelling for the ruled ``none`` on ``pdf`` / ``engineering-document`` /
    ``doors-export``, and the only way to satisfy it would be to invent a
    domain for a format-level kind — writing unvetted content into a vetted
    domain's graph, which is the exact failure the ruling prevents.

    What the optional field does NOT do is make the rows carry it yet. At the
    ``v0.9.5`` pin the model is ``extra="forbid"``, so a ``domain:`` key in a
    YAML row still raises; the sidecar stays until the pin bump, and the row
    migration (``domain: null`` for the three format-level kinds, retiring
    ``content_kind_domains.json``) travels WITH that bump, not before it.
    """
    ingest = pytest.importorskip("iagent_mesh.ingest")
    model_fields = ingest.ContentKindRegistration.model_fields
    fields = set(model_fields)
    if "domain" in fields:
        assert not model_fields["domain"].is_required(), (
            "the installed SDK declares `domain` as a REQUIRED field on "
            "ContentKindRegistration. The 2026-10-02 ruling is `str | None` "
            "(optional): a required non-empty domain cannot express the ruled "
            "`none` for pdf / engineering-document / doors-export. Do NOT "
            "invent a domain for a format-level kind to satisfy the model -- "
            "take it back to the architect and to lane/ca."
        )
        # The ruled shape. AND THE ROWS STILL DO NOT CARRY `domain`, which is
        # no longer "pending the pin bump": the pin bump happened (v0.9.11,
        # 2026-10-29) and the migration this comment used to promise is
        # WITHDRAWN. The architect's 2026-10-24 ownership ruling gives `domain`
        # to the platform's deployment overlay, so moving it into our rows
        # would make this repo a second source of truth for a field another
        # repo rules on. The sidecar is not a workaround for `extra="forbid"`
        # any more -- it is where a field we declare but do not own belongs.
        # See doc_tools/utils/kind_registrations.py and
        # test_the_platform_owned_fields_are_absent_by_ruling below.
        return
    assert fields == {"kind", "passes", "outputs"}, sorted(fields)
    with pytest.raises(Exception):
        ingest.ContentKindRegistration(
            kind="pcn", passes=("x",), outputs=("y",), domain="sustainment"
        )


def test_the_domain_sidecar_covers_every_registered_kind():
    payload = json.loads(DOMAINS_FILE.read_text(encoding="utf-8"))["domains"]
    assert payload == {
        e.kind: e.domain_type for e in KIND_MAPPING.values()
    }
    # And the ruling's six, under their registered spelling.
    for kind, domain in RULED_DOMAINS.items():
        assert payload[KIND_MAPPING[kind].kind] == domain


# --------------------------------------------------------------------------- #
# 3. The phantoms stay visible
# --------------------------------------------------------------------------- #
def test_the_phantom_outputs_are_exactly_the_two_owed_by_lane_1():
    """ADR-0019 §6: an output URI is a phantom until it resolves to a declared
    class. Two are, by the architect's own sequencing — ``mesh_system.ttl`` is
    Lane 1's TTL and the leaf lands there ("7f registers the row now and it
    resolves when the TTL lands"). Asserting the set EXACTLY means a third
    phantom cannot arrive unannounced.

    The name and the "two" above are stale: the set now has more members,
    each announced in ``PHANTOM_OUTPUTS`` with its owner (``training:Course``
    is Lane 1's, 2026-10-23). The set equality is what holds, not the count.
    """
    declared_curies = {
        "mfg:WorkInstruction",
        "pcn:ProcessChangeNotification",
        "pcn:ProductDiscontinuationNotice",
        "pcn:Component",
        "mil:DataModule",
        "mesh:PDFArtifact",
        # Declared, and checked before the `cad` row was added rather than
        # assumed: mesh_system.ttl:808, `a owl:Class ; rdfs:subClassOf
        # mesh:Artifact ; rdfs:label "CAD Artifact"`. It is the one artifact
        # leaf besides PDF that Lane 1 already shipped, so the `cad` row owes
        # them nothing and must NOT appear in PHANTOM_OUTPUTS.
        "mesh:CADArtifact",
    }
    all_outputs = {o for e in KIND_MAPPING.values() for o in e.outputs}
    assert all_outputs - declared_curies == set(PHANTOM_OUTPUTS)
    # NARROWED 2026-10-13, when the architect authorised the `cad` row. This
    # assertion used to read `"mesh:CADArtifact" not in all_outputs`, which
    # forbade ANY row from targeting the CAD leaf. That is not what was ruled.
    # The ruling was about one specific aliasing — "Don't alias it to CAD; an
    # engineering document is not a CAD artifact" — said of the
    # engineering-document leaf, so it is engineering-document that must not
    # reach for this class. A `cad` row targeting the CAD leaf is the ruling
    # being honoured, not broken: it is exactly why the two leaves are
    # separate. Checked against the row, not the table, so the next row to
    # target mesh:CADArtifact is free to and this one still cannot.
    assert "mesh:CADArtifact" not in KIND_MAPPING["engineering-document"].outputs, (
        "the architect ruled against aliasing an engineering document to CAD: "
        "'an engineering document is not a CAD artifact'"
    )
    assert KIND_MAPPING["cad"].outputs == ("mesh:CADArtifact",), (
        "the cad row targets the leaf the TTL declares for it, and nothing else"
    )


def test_every_unbuilt_pass_belongs_to_a_kind_that_writes_nothing():
    """The safety property that makes declaring an unbuilt pass harmless.

    An unbuilt pass is harmless only while nothing can reach it: every kind
    that declares one must also declare no domain, because a domainless kind
    short-circuits at "origin unresolved" before any pass could be dispatched.
    If someone gave a DOMAIN-declaring kind an unbuilt pass, this test fails
    and says so.

    ``UNBUILT_PASSES`` is currently EMPTY — ``identity.document_identity`` is
    built (``doc_tools/passes/identity.py``) — which makes this test vacuously
    true today. That is the point of leaving it: it is the guard that has to
    hold the next time a row declares something before it exists. Whether a
    listed pass is genuinely unbuilt is enforced separately, by
    ``tests/test_passes_registry.py``.
    """
    for entry in KIND_MAPPING.values():
        unbuilt = set(entry.passes) & set(UNBUILT_PASSES)
        if unbuilt:
            assert entry.domain_type is None, (
                f"{entry.kind!r} declares unbuilt pass(es) {sorted(unbuilt)} "
                f"AND a domain ({entry.domain_type!r}), so the pipeline would "
                f"try to run a pass that does not exist"
            )


def test_every_row_has_a_nonempty_pass_and_output():
    """The SDK model refuses ``()`` for either ("a kind with no pass is not a
    kind, it is a row someone forgot to finish"). Checked here too, so the
    failure names the table row rather than a YAML file."""
    for source, entry in KIND_MAPPING.items():
        assert entry.passes, f"{source!r} has no passes"
        assert entry.outputs, f"{source!r} has no outputs"
        assert len(set(entry.passes)) == len(entry.passes), source
        assert len(set(entry.outputs)) == len(entry.outputs), source


def test_the_rows_on_disk_are_the_sdk_projection():
    """THE ADOPTION, PINNED. Seam 1 above (`--check`) says the files match the
    table; this says the files ARE ``ContentKindRegistration`` objects.

    ``scripts/generate_kind_registrations.py`` renders from
    ``doc_tools.utils.kind_registrations.registrations()``, so a row the SDK
    would refuse cannot reach the directory -- building it is the step that
    produces the bytes. Loading them back through the SDK's own composer and
    comparing to the projection closes the loop in the other direction: the
    disk and the model agree field for field, not merely kind for kind.

    The row PAYLOADS were byte-unchanged when this landed (only the generated
    header comment moved), which is the point -- the adoption changes where the
    bytes come from, not what they say.
    """
    ingest = pytest.importorskip("iagent_mesh.ingest")
    from doc_tools.utils.kind_registrations import registrations

    projected = registrations()
    assert len(projected) == len(KIND_MAPPING)
    loaded = ingest.load_content_kind_registrations(ROWS_DIR)
    assert tuple(sorted(loaded, key=lambda r: r.kind)) == projected


def test_the_platform_owned_fields_are_absent_by_ruling():
    """``domain``/``arrives_as``/``review_shape``/``label`` are the platform's.

    The architect's ruling of 2026-10-24, amending 10-07, quoted in
    ``tests/test_overlay_kind_drift.py``: *"the platform owns what a kind IS
    (kind, domain, arrives_as, review_shape, label); doc-tools owns what it RUNS
    (passes)."* All four exist on the model at the v0.9.11 pin, so leaving them
    unset is now a CHOICE and has to be pinned as one -- otherwise the next
    reader finds four empty fields and fills them, which is how a mirrored
    registry becomes a second source of truth.

    THE DISAGREEMENT BEHIND THIS ARM IS SETTLED, AND IT WENT THIS WAY. The arm
    was opened against a live collision: iagent-mesh's v0.9.11 changelog says of
    ``arrives_as`` *"ca adds the field, 7f fills in KIND_MAPPING's rows with
    it"* -- 2026-10-21, three days before the ownership ruling moved the field
    to the platform. This lane reported the collision rather than settling it by
    editing a file. The architect's ruling of **2026-10-30** closed it: *"ownership
    stands as ruled 10-24: the platform registry declares
    kind/domain/arrives_as/review_shape/label (Lane 1 fills them from your
    packet); doc-tools declares passes. Your decline + test stay."* So the older
    changelog line is superseded, the values reach the platform as a PACKET from
    this lane rather than as rows in this tree, and this arm is **permanent** --
    not a placeholder awaiting a ruling. Deleting it would re-open the second
    source of truth the 10-24 and 10-30 rulings both close.
    """
    ingest = pytest.importorskip("iagent_mesh.ingest")
    from doc_tools.utils.kind_registrations import (
        PLATFORM_OWNED_FIELDS,
        registrations,
    )

    model_fields = ingest.ContentKindRegistration.model_fields
    absent = [f for f in PLATFORM_OWNED_FIELDS if f not in model_fields]
    assert not absent, (
        f"{absent} no longer exist on ContentKindRegistration. These are the "
        f"fields the ownership ruling assigns to the platform; if the SDK "
        f"dropped one, the ruling has nothing to attach to -- take it to "
        f"lane/ca rather than deleting the name here."
    )
    for reg in registrations():
        for field in PLATFORM_OWNED_FIELDS:
            assert getattr(reg, field) == model_fields[field].default, (
                f"row {reg.kind!r} declares {field!r}, which the 2026-10-24 "
                f"ownership ruling gives to the platform's overlay. doc-tools' "
                f"rows MIRROR that side; they do not author it."
            )


def test_the_projection_fills_exactly_what_doc_tools_owns():
    """Three of thirteen fields are set; eight stay at their defaults by reason.

    ``exclude_defaults`` is the whole assertion: what a row SAYS is what it
    sets, and today every row sets exactly the three fields doc-tools owns.
    ``identity_field`` and ``seeds_workflow`` are projected when a row declares
    one and no row does, so a row that starts declaring one adds its key here
    and this arm is the place that records it. ``branch``/``refresh`` have no
    counterpart on ``ContentKindEntry`` at all (ADR-0063 section 1, unchanged by
    this pin), and ``parent_link_field``/``id_namespaces`` are unset pending a
    measurement rather than a decision -- see the projection module.
    """
    pytest.importorskip("iagent_mesh.ingest")
    from doc_tools.utils.kind_registrations import registrations

    for reg in registrations():
        assert set(reg.model_dump(exclude_defaults=True)) == {
            "kind", "passes", "outputs"
        }, reg.kind
