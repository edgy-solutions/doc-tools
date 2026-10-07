"""The declared-pass / built-pass correspondence, enforced both directions.

``UNBUILT_PASSES`` used to be a hand-maintained list of names someone had to
remember to prune. It went stale the moment a pass was built, and a stale
"unbuilt" marker is worse than none: it tells the next reader that a working
code path does not exist, and it exempts that path from the only check that
asks whether a declared pass is real.

So the list is checked against the filesystem, in BOTH directions:

  * every pass any ``KIND_MAPPING`` row declares must RESOLVE -- unless it is
    listed as unbuilt;
  * every name listed as unbuilt must NOT resolve, or the list is stale.

A PASS NAME HAS NO SINGLE CONVENTION, WHICH IS THE FINDING
----------------------------------------------------------
Writing this test on the assumption that a pass is a dotted Python name under
``doc_tools.passes`` turned two rows red, and correctly both times. The four
declared names use three different schemes::

    manufacturing.baml::ExtractWorkInstructions   BAML function, baml_src/
    sustainment.baml::ExtractHeader               BAML function, baml_src/
    sustainment.baml::ExtractParts                BAML function, baml_src/
    identity.document_identity                    function, doc_tools/passes/
    s1000d.S1000dGraphBuilder                     class, doc_tools/parsers/

Two things follow, and nothing anywhere said either of them:

1. ``::`` marks a BAML function; its absence marks a Python symbol. That is the
   ONLY structural signal, so it is what the resolver branches on.
2. The namespace segment does not name a module. ``identity`` is
   ``doc_tools/passes/identity.py``, but ``s1000d`` is
   ``doc_tools/parsers/s1000d_rdf.py`` -- a different package AND a different
   filename. So a Python pass is resolved by SEARCHING the candidate packages
   for the symbol, and the search is required to find exactly one. This repo
   already ships two S1000D parsers (``s1000d_ingest``, ``s1000d_rdf``) of
   which only one is wired; a second definition of a declared symbol would make
   "the pass" ambiguous, and an ambiguous pass name silently resolves to
   whichever module the search reaches first.

The point of the file is that before it, none of these five names was checked
by anything. A typo in one was discoverable only by an ingest failing at
dispatch.

A BAML reference resolves only if the function is declared in ``baml_src`` AND
present in the GENERATED client. Those are two facts, not one: editing a
``.baml`` file without re-running ``baml-cli generate`` leaves the declaration
in place and the carrier missing, which is invisible to every unit test that
does not call the function.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from doc_tools.utils.content_kind import KIND_MAPPING, UNBUILT_PASSES

REPO_ROOT = Path(__file__).resolve().parents[1]
BAML_SRC = REPO_ROOT / "baml_src"

#: Where a Python pass may live, as ``(import package, directory)``. Both are
#: searched because the namespace segment of a pass name does not say which.
PASS_PACKAGES: tuple[tuple[str, Path], ...] = (
    ("doc_tools.passes", REPO_ROOT / "doc_tools" / "passes"),
    ("doc_tools.parsers", REPO_ROOT / "doc_tools" / "parsers"),
)

#: The generated carriers a BAML function must appear in. Text-checked rather
#: than imported: importing the client pulls in runtime configuration (model
#: endpoints, keys) that a unit test has no business requiring.
GENERATED_CLIENTS = (
    REPO_ROOT / "doc_tools" / "baml_client" / "sync_client.py",
    REPO_ROOT / "doc_tools" / "baml_client" / "async_client.py",
)


def _candidate_modules(namespace: str) -> list[str]:
    """Modules a pass named ``<namespace>.<symbol>`` could live in.

    A module matches if its filename IS the namespace or begins with it plus an
    underscore -- which is what admits ``s1000d_rdf`` for namespace ``s1000d``.
    Derived from the filesystem, never from a hand-written map, so a renamed
    module shows up as an unresolvable pass instead of a stale lookup table.
    """
    out: list[str] = []
    for package, directory in PASS_PACKAGES:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.py")):
            stem = path.stem
            if stem == "__init__":
                continue
            if stem == namespace or stem.startswith(f"{namespace}_"):
                out.append(f"{package}.{stem}")
    return out


def _resolve_python(dotted: str) -> list[tuple[str, object]] | None:
    """Every ``(module, symbol)`` a Python pass name resolves to, or None.

    ALL hits are returned rather than the first, so a caller can require
    uniqueness. Import errors are deliberately NOT caught: every candidate here
    came from a glob, so the file exists, and a module that fails to import is a
    defect in code that DOES exist -- swallowing it would let a pass with a
    syntax error or a missing dependency pass for one that was never built.
    """
    namespace, _, symbol = dotted.rpartition(".")
    assert namespace and symbol, f"pass name {dotted!r} is not <namespace>.<symbol>"
    hits: list[tuple[str, object]] = []
    for modname in _candidate_modules(namespace):
        module = importlib.import_module(modname)
        target = getattr(module, symbol, None)
        if target is not None:
            hits.append((modname, target))
    return hits or None


def _baml_declares(baml_file: str, function_name: str) -> bool:
    path = BAML_SRC / baml_file
    if not path.is_file():
        return False
    pattern = re.compile(
        r"^\s*function\s+" + re.escape(function_name) + r"\s*\(", re.MULTILINE)
    return bool(pattern.search(path.read_text(encoding="utf-8")))


def _generated_carries(function_name: str) -> list[Path]:
    """The generated clients that expose ``function_name`` as a method."""
    pattern = re.compile(
        r"^\s*(?:async\s+)?def\s+" + re.escape(function_name) + r"\s*\(",
        re.MULTILINE)
    return [p for p in GENERATED_CLIENTS
            if p.is_file() and pattern.search(p.read_text(encoding="utf-8"))]


def _resolve(dotted: str):
    """Resolve a pass name under whichever scheme it uses, or None.

    Truthy on success. ``::`` is the only thing that distinguishes the two
    schemes in the table, so it is the only thing branched on.
    """
    if "::" in dotted:
        baml_file, _, function_name = dotted.partition("::")
        if not _baml_declares(baml_file, function_name):
            return None
        return _generated_carries(function_name) or None
    return _resolve_python(dotted)


def _declared_passes() -> set[str]:
    return {p for entry in KIND_MAPPING.values() for p in entry.passes}


def _declared(kind: str) -> list[str]:
    """Declared passes of one scheme: ``"baml"`` or ``"python"``."""
    want_baml = kind == "baml"
    return sorted(p for p in _declared_passes() if ("::" in p) is want_baml)


# ---------------------------------------------------------------------------
# Both directions of the correspondence
# ---------------------------------------------------------------------------

def test_every_declared_pass_is_built_or_admitted_unbuilt():
    """No row may declare a pass that neither exists nor is admitted unbuilt.

    Catches a typo'd, renamed or deleted pass at collection time instead of at
    dispatch time, under both schemes. Before this test none of the five
    declared names was checked by anything at all.
    """
    for dotted in sorted(_declared_passes()):
        if dotted in UNBUILT_PASSES:
            continue
        assert _resolve(dotted), (
            f"{dotted!r} is declared by a KIND_MAPPING row but does not "
            f"resolve. A '::' name must be declared in baml_src/ AND present "
            f"in the generated client; a dotted name must be a symbol in one "
            f"of {[p for p, _ in PASS_PACKAGES]}. Either build it or add it "
            f"to UNBUILT_PASSES."
        )


def test_nothing_listed_unbuilt_is_actually_built():
    """The direction that keeps the exemption list from going stale.

    If a name here resolves, the pass was built and the list was not updated --
    which is exactly how ``identity.document_identity`` would have sat in this
    tuple after ``doc_tools/passes/identity.py`` landed, exempting a working
    path from the check above.
    """
    for dotted in UNBUILT_PASSES:
        assert _resolve(dotted) is None, (
            f"{dotted!r} is listed in UNBUILT_PASSES but resolves to something "
            f"real. The pass is built; remove it from the tuple."
        )


def test_unbuilt_passes_are_all_declared_somewhere():
    """A name nobody declares does not need an exemption.

    An orphan here is a leftover: either a row was deleted and this was not, or
    the name is misspelled -- in which case the row's REAL pass is silently
    unexempted and the first test is checking a name that does not exist.
    """
    declared = _declared_passes()
    for dotted in UNBUILT_PASSES:
        assert dotted in declared, (
            f"{dotted!r} is exempted as unbuilt but no KIND_MAPPING row "
            f"declares it. Declared passes are {sorted(declared)}."
        )


# ---------------------------------------------------------------------------
# The state this PR establishes, pinned by name
# ---------------------------------------------------------------------------

def test_document_identity_resolves_and_is_not_exempt():
    """Pinned by name so a revert is loud.

    "The pass exists" and "the pass is no longer exempt" are two separate
    facts, and a future edit could restore the exemption without breaking
    either generic test above: the first would skip the pass, the third would
    still pass.
    """
    assert "identity.document_identity" not in UNBUILT_PASSES
    hits = _resolve("identity.document_identity")
    assert hits and len(hits) == 1
    modname, target = hits[0]
    assert modname == "doc_tools.passes.identity"
    assert callable(target)


# ---------------------------------------------------------------------------
# The two schemes, and the ambiguity a search-based resolver can hide
# ---------------------------------------------------------------------------

def test_both_naming_schemes_are_present_and_both_resolve():
    """Pins the finding, so the next reader does not assume one scheme.

    If the table ever holds only one scheme this test fails and should be
    retired deliberately -- rather than someone writing a single-scheme
    resolver again and reporting a real row as broken.
    """
    baml, python = _declared("baml"), _declared("python")
    assert baml, "no BAML-style pass references left; retire this test"
    assert python, "no Python-style pass references left; retire this test"
    for dotted in baml + python:
        assert _resolve(dotted), dotted


@pytest.mark.parametrize("dotted", _declared("python"))
def test_each_python_pass_resolves_to_exactly_one_symbol(dotted):
    """Uniqueness, because the resolver searches rather than addresses.

    A namespace admits every module whose filename starts with it, so two
    modules defining the same symbol would both match and the pass name would
    no longer identify one implementation. That is not hypothetical here:
    ``s1000d_ingest`` and ``s1000d_rdf`` both exist and only one is wired, so a
    symbol appearing in both would resolve to whichever the search reached
    first -- which may not be the one the registry means.
    """
    hits = _resolve_python(dotted)
    assert hits, dotted
    assert len(hits) == 1, (
        f"{dotted!r} resolves to {len(hits)} symbols: "
        f"{[m for m, _ in hits]}. A pass name must identify one "
        f"implementation; disambiguate the name or the modules."
    )


@pytest.mark.parametrize("dotted", _declared("baml"))
def test_each_baml_pass_is_declared_and_generated(dotted):
    """Both halves of a BAML reference, reported separately.

    Editing a ``.baml`` file without re-running ``baml-cli generate`` leaves
    the declaration in place and the carrier missing. Every unit test that does
    not actually call the function stays green, so the failure surfaces at
    runtime. These assertions name which half is missing.
    """
    baml_file, _, function_name = dotted.partition("::")
    assert _baml_declares(baml_file, function_name), (
        f"baml_src/{baml_file} declares no `function {function_name}(`")
    assert _generated_carries(function_name), (
        f"`function {function_name}` is declared in baml_src/{baml_file} but "
        f"no generated client exposes it -- run `baml-cli generate`")


# ---------------------------------------------------------------------------
# The resolver's own negative cases
# ---------------------------------------------------------------------------

def test_a_nonexistent_pass_does_not_resolve():
    """Without these, every assertion above could pass vacuously: a resolver
    that returned something for any input would satisfy them all."""
    assert _resolve("identity.no_such_pass") is None
    assert _resolve("no_such_namespace.no_such_pass") is None
    assert _resolve("sustainment.baml::NoSuchFunction") is None
    assert _resolve("no_such_file.baml::ExtractHeader") is None


def test_a_malformed_pass_name_is_rejected_not_swallowed():
    """A name with no namespace separator is a malformed row, not an unbuilt
    pass. Returning None for it would let a typo masquerade as work not done
    yet."""
    with pytest.raises(AssertionError):
        _resolve("no_dot_here")
