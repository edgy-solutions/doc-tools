"""A populated grounding pool is not a searchable one. Lane 74's packet, 2026-09-19.

THE MEASUREMENT THAT MAKES THIS FILE NECESSARY (ia-74, 2026-09-19,
``2026-09-19-packet-from-74-the-seam-returns-one-and-the-vector-half-is-dead.md``):

    shard J5Eirv929wug   objects=26239   vectorIndexingStatus=READY   vectorQueueLength=0
    24,924 of those rows carry a readable 768-dim vector
    near_vector(safety#Hazard's OWN stored vector), no filter        n=0
    nearObject{id:"<safety#Hazard uuid>"}
      -> "explorer: get class: vectorize search vector: nearObject params:
          vector not found for target: default"

Every row present. Every row countable. Every row carrying a vector. And the vector half of
every hybrid search on ``OntologyClass`` and ``Predicate`` returning nothing, fleet-wide, with
no log line — the "falling back to BM25" message prints only when ``embed_query`` RAISES, and
it never raises. The router has been answering on BM25 alone, which does not even stem
("hazard" matches five classes, "hazards" matches none).

WHY THE ROW SEAL NEXT DOOR CANNOT SEE IT, which is the whole reason this is a separate
assertion and not a stronger version of that one. ``_additional{vector}`` and the client's
``include_vector`` both read the LEGACY unnamed slot, and the row genuinely has a vector
there. The collection is indexed on the NAMED space ``default``, which is empty. Every
instrument that asks "does this row have a vector" answers yes. Only one that asks the server
to USE it answers no.

So the assertion is: AN OBJECT IS ITS OWN NEAREST NEIGHBOUR, OR THE INDEX IS NOT THERE.

WHAT IS DELIBERATELY NOT FIXED IN THIS PASS, asserted here so the gap is visible rather than
forgotten. The ``collections.create`` that probably causes it is named in the packet, but the
mechanism (that a bare create on client 4.21.0 emits the named space) is 74's INFERENCE and
was explicitly not measured. 74 is running a scratch-collection experiment to settle it, and
the two candidate repairs are not interchangeable. The detector lands now; the repair lands on
the measurement. The rebuild of 26,239 existing rows is Chris's to authorize either way.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

_SRC = (pathlib.Path(__file__).resolve().parents[1]
        / "doc_tools" / "assets" / "ontology_assets.py")

EX = "http://example.com/ontology#"


def _load(*names: str) -> dict:
    import rdflib
    from weaviate.util import generate_uuid5
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    ns: dict = {"rdflib": rdflib, "generate_uuid5": generate_uuid5}
    wanted = set(names)
    for node in tree.body:
        got = None
        if isinstance(node, ast.FunctionDef):
            got = node.name
        elif isinstance(node, ast.Assign) and node.targets and isinstance(node.targets[0], ast.Name):
            got = node.targets[0].id
        if got in wanted:
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(_SRC), "exec"), ns)
    missing = wanted - set(ns)
    assert not missing, f"could not load {missing} from {_SRC.name}"
    return ns


_seal = _load("seal_a_written_row_is_RETRIEVABLE")["seal_a_written_row_is_RETRIEVABLE"]

_TO_WRITE = [
    {"uri": EX + "Hazard", "label": "Hazard", "definition": "A hazard."},
    {"uri": EX + "Part", "label": "Part", "definition": "A part."},
]
#: sorted()[0] of the two URIs above — the probe is deterministic on purpose.
_PROBE = EX + "Hazard"


class _Log:
    def __init__(self):
        self.warnings: list = []
        self.infos: list = []

    def warning(self, m):
        self.warnings.append(m)

    def info(self, m):
        self.infos.append(m)


class _Ctx:
    def __init__(self):
        self.log = _Log()


class _Obj:
    def __init__(self, uri, vector=None):
        self.properties = {"uri": uri}
        self.vector = vector or {}


class _Collection:
    """A Weaviate collection with a switchable index, so both substrates are testable.

    ``healthy``      near_object returns the probe first, as DocumentChunk does today.
    ``dead_index``   near_object raises the server's real message, as OntologyClass does.
    ``wrong_row``    near_object answers but without the probe — an index holding a
                     different vector for the row than the row carries.
    """

    def __init__(self, mode="healthy", vector_present=True):
        self.mode = mode
        self.vector_present = vector_present
        self.query = self

    def fetch_object_by_id(self, uuid, include_vector=False):
        return _Obj(_PROBE, {"default": [0.1] * 768} if self.vector_present else {})

    def near_object(self, uuid, limit=None, return_properties=None):
        if self.mode == "dead_index":
            raise Exception(
                "explorer: get class: vectorize search vector: nearObject params: "
                "vector not found for target: default"
            )

        class _Res:
            pass
        r = _Res()
        r.objects = [] if self.mode == "wrong_row" else [_Obj(_PROBE)]
        return r


def test_a_healthy_index_passes():
    """POSITIVE CONTROL. DocumentChunk answers correctly on this very server, so a seal
    that could never be green would be measuring nothing."""
    ctx = _Ctx()
    assert _seal(_Collection("healthy"), _TO_WRITE, "SUSTAINMENT", ctx) == _PROBE
    assert any("Retrievability seal green" in m for m in ctx.log.infos)


def test_THE_MEASURED_SUBSTRATE_FAILS():
    """The condition of the sandbox on 2026-09-19: every row present, the index empty.

    This is the assertion the row seal cannot make. If this test ever passes against the
    real store without the writer being fixed, the seal has stopped asking the server to
    USE the vector and has gone back to asking whether one exists.
    """
    with pytest.raises(Exception) as err:
        _seal(_Collection("dead_index"), _TO_WRITE, "SUSTAINMENT", _Ctx())
    msg = str(err.value)
    assert "RETRIEVABILITY SEAL FAILED" in msg
    assert "vector not found for target: default" in msg
    assert "Lane 74" in msg, (
        "the failure does not point at the packet that measured it -- a red nobody can "
        "trace is a red that gets muted"
    )


def test_an_index_that_answers_WITHOUT_the_row_also_fails():
    """An object is its own nearest neighbour. Anything else means the vector the index
    holds for that row is not the vector the row carries, which is a quieter version of
    the same defect and would otherwise read as a pass."""
    with pytest.raises(Exception) as err:
        _seal(_Collection("wrong_row"), _TO_WRITE, "SUSTAINMENT", _Ctx())
    assert "own nearest neighbour" in str(err.value)


def test_a_vector_less_probe_row_is_SKIPPED_not_failed():
    """The embed fallback writes vector-less rows ON PURPOSE (BM25 still answers, a
    backfill can populate later). Asking one of those to find itself would fail for a
    reason that has nothing to do with the index, and would blame the index for the
    gateway."""
    ctx = _Ctx()
    assert _seal(_Collection("healthy", vector_present=False), _TO_WRITE, "X", ctx) == ""
    assert any("SKIPPED" in m for m in ctx.log.warnings)
    assert any("not a pass" in m for m in ctx.log.warnings), (
        "a skipped probe must say it is an unmade measurement, or the log reads as green"
    )


def test_the_probe_is_deterministic():
    """A re-run asks the same question. A randomly chosen probe turns an intermittent
    index fault into an intermittent test, which is how a real red gets called flaky."""
    seen = {_seal(_Collection("healthy"), _TO_WRITE, "X", _Ctx()) for _ in range(5)}
    assert seen == {_PROBE}


def test_the_seal_runs_BESIDE_the_row_seal_not_instead_of_it():
    """Both, in the write path. The row seal catches a dropped row; this one catches a
    pool that has every row and cannot search any of them. Deleting either loses a
    distinct failure."""
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "sync_ontology_to_weaviate")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "seal_declared_classes_are_rows" in called
    assert "seal_a_written_row_is_RETRIEVABLE" in called


def test_the_seal_asks_the_SERVER_to_use_the_vector():
    """Not `include_vector`, not `_additional{vector}` -- both read the legacy slot and
    both say yes on the broken substrate. Only near_object routes through the index."""
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "seal_a_written_row_is_RETRIEVABLE")
    attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    assert "near_object" in attrs, (
        "the retrievability seal no longer issues a nearObject query, so it has stopped "
        "being able to see the condition it exists for"
    )


def test_the_create_site_still_carries_the_held_defect_note():
    """The writer is knowingly unfixed pending 74's scratch-collection result. If the note
    goes without the create changing, the next reader finds a bare create with no reason
    and 'fixes' it on 74's own un-measured inference -- which is the one thing the packet
    asks nobody to do."""
    src = _SRC.read_text(encoding="utf-8")
    assert "KNOWN DEFECT, NOT YET FIXED HERE" in src
    assert "scratch-collection" in src
    assert "REBUILD IS CHRIS" in src.upper()
