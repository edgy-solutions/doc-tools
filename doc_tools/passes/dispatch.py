"""The passes dispatcher: runs the passes a ``KIND_MAPPING`` row declares.

Before this module every declared pass was inert -- ``KIND_MAPPING`` named them
and nothing executed them. This is the thing that runs them, with nothing
format-specific in it.

THE CONTRACT IS A VOCABULARY, BOUND BY PARAMETER NAME
-----------------------------------------------------
A pass declares what it consumes by naming parameters out of
:class:`PassContext`'s fields (``pages``, ``text``, ``raw_bytes``, ``doc_id``).
Those four names ARE the contract. They are deliberately format-neutral: no
``export_text``, no ``xml_bytes``. A pass joins the vocabulary or it is refused.

WHY CONTRACT ERRORS RAISE INSTEAD OF DEGRADING
----------------------------------------------
A contract error (a class, a non-callable, a required parameter outside the
vocabulary, ``*args``/``**kwargs``, an unresolvable or ambiguous name) is a
REGISTRATION defect, not a document problem. ADR-0021 halts on an unresolvable
kind rather than defaulting one; this is the same class of fault one layer in.
A mis-declared row that degrades quietly is how a kind runs zero passes while
every test stays green. A pass raising its OWN exception on a bad document
(``IdentityError``, ``DoorsParseError``) is the opposite case -- a document
problem -- and is recorded as ``"refused"``, the degrade-never-fail rule
``doc_tools/plugins/sustainment.py`` follows.

THE ONE RESOLVER
----------------
:func:`resolve_python_pass` is the only place a dotted name becomes a symbol.
``tests/test_passes_registry.py`` imports it rather than carrying a copy. Two
resolvers that agree today disagree later, and the failure is a pass that tests
as present and dispatches as missing.

The namespace segment does not name a module: ``identity`` is
``doc_tools/passes/identity.py`` but ``s1000d`` is
``doc_tools/parsers/s1000d_rdf.py``. So the candidate packages are SEARCHED and
the caller is told every hit, so it can require exactly one.
"""
from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Mapping

from doc_tools.utils.content_kind import UNBUILT_PASSES, _lookup

_PKG_ROOT = Path(__file__).resolve().parents[1]

#: Where a Python pass may live, as ``(import package, directory)``. Both are
#: searched because the namespace segment of a pass name does not say which.
PASS_PACKAGES: tuple[tuple[str, Path], ...] = (
    ("doc_tools.passes", _PKG_ROOT / "passes"),
    ("doc_tools.parsers", _PKG_ROOT / "parsers"),
)


class PassContractError(RuntimeError):
    """A pass registration that cannot be dispatched. Never caught here."""


@dataclass(frozen=True)
class PassContext:
    """The format-neutral vocabulary a pass may consume, by parameter name."""

    pages: tuple[str, ...] = ()
    text: str = ""
    raw_bytes: bytes = b""
    doc_id: str = ""

    def bindings(self) -> Mapping[str, object]:
        """The vocabulary as a plain mapping; a new field needs no dispatcher edit."""
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass(frozen=True)
class PassResult:
    name: str          # the dotted name as declared
    status: str        # "ok" | "refused" | "unbuilt" | "baml"
    value: object = None
    error: str = ""


# ---------------------------------------------------------------------------
# The one resolver
# ---------------------------------------------------------------------------

def candidate_modules(namespace: str) -> list[str]:
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


def resolve_python_pass(dotted: str) -> list[tuple[str, object]] | None:
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
    for modname in candidate_modules(namespace):
        module = importlib.import_module(modname)
        target = getattr(module, symbol, None)
        if target is not None:
            hits.append((modname, target))
    return hits or None


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _bind(dotted: str, modname: str, fn, vocab: Mapping[str, object]) -> dict:
    """Build the keyword arguments for ``fn`` from the vocabulary."""
    kwargs: dict[str, object] = {}
    for pname, param in inspect.signature(fn).parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            raise PassContractError(
                f"pass {dotted!r} (module {modname}) declares "
                f"{'*' if param.kind is param.VAR_POSITIONAL else '**'}{pname}; "
                f"a pass must declare what it consumes, and a catch-all makes a "
                f"typo'd vocabulary key look like an accepted one")
        if pname in vocab:
            kwargs[pname] = vocab[pname]
        elif param.default is param.empty:
            raise PassContractError(
                f"pass {dotted!r} (module {modname}) has required parameter "
                f"{pname!r} outside the vocabulary {sorted(vocab)}")
        # else: has a default and is not in the vocabulary -> leave it alone
    return kwargs


def run_pass(dotted: str, ctx: PassContext) -> PassResult:
    """Run one declared pass. Contract defects raise; document defects record."""
    # Skipped, never resolved and never called.
    if dotted in UNBUILT_PASSES:
        return PassResult(name=dotted, status="unbuilt")
    if "::" in dotted:  # BAML: this dispatcher calls no model
        return PassResult(name=dotted, status="baml")

    if not (dotted.rpartition(".")[0] and dotted.rpartition(".")[2]):
        raise PassContractError(
            f"pass {dotted!r} is not <namespace>.<symbol>")
    hits = resolve_python_pass(dotted)
    if not hits:
        raise PassContractError(
            f"pass {dotted!r} resolves to nothing in "
            f"{[p for p, _ in PASS_PACKAGES]}")
    if len(hits) > 1:
        raise PassContractError(
            f"pass {dotted!r} resolves to {len(hits)} symbols "
            f"({[m for m, _ in hits]}); a name must identify one implementation")
    modname, fn = hits[0]
    if inspect.isclass(fn):
        raise PassContractError(
            f"pass {dotted!r} (module {modname}) is a class; constructing is "
            f"not processing -- it would build an empty object, parse nothing "
            f"and return successfully. Declare a function entry point")
    if not callable(fn):
        raise PassContractError(
            f"pass {dotted!r} (module {modname}) is not callable")

    kwargs = _bind(dotted, modname, fn, ctx.bindings())
    try:
        value = fn(**kwargs)
    except PassContractError:
        raise
    except Exception as exc:  # the pass's own refusal: a document problem
        return PassResult(name=dotted, status="refused", error=str(exc))
    return PassResult(name=dotted, status="ok", value=value)


def run_passes_for_kind(kind: str, ctx: PassContext) -> tuple[PassResult, ...]:
    """Run every pass the kind's row declares, in declared order.

    The row documents its order as meaningful, so it is preserved. An unknown
    kind raises: no default is invented (ADR-0021).
    """
    entry = _lookup(kind)
    if entry is None:
        raise PassContractError(f"unknown content kind {kind!r}; no default is invented")
    return tuple(run_pass(name, ctx) for name in entry.passes)
