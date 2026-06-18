"""Standing guard: exactly ONE embedding-model name string in doc-tools.

Pairs with invincible-agent's tests/routing/test_embed_contract.py. The
vector-search contract lives in doc_tools/utils/embed.py, NOT in Weaviate
config. Cross-repo agreement on model name + dim is enforced by code
review on the DEFAULT_EMBED_MODEL and EXPECTED_EMBED_DIM constants in
the two embed.py files; this guard enforces in-repo single-source-of-truth.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_TOOLS = REPO_ROOT / "doc_tools"

KNOWN_EMBEDDING_MODEL_NAMES = (
    "nomic-embed-text",
    "nomic-embed-8k:latest",
    "text-embedding-3-small",
    "text-embedding-3-large",
    "text-embedding-ada-002",
    "BAAI/bge-large-en-v1.5",
)

# The canonical contract assignment — must appear exactly once.
CONTRACT_DECLARATION = re.compile(r"DEFAULT_EMBED_MODEL\s*=\s*['\"]")

# Allowed fallback assignments — may appear zero or more times; an
# explicitly-named variable signals intent at review time. None today;
# add patterns here if a provider-specific fallback shows up.
FALLBACK_DECLARATIONS: tuple = ()


def _is_allowed_line(line: str) -> bool:
    if CONTRACT_DECLARATION.search(line):
        return True
    return any(pat.search(line) for pat in FALLBACK_DECLARATIONS)


def _is_contract_declaration(line: str) -> bool:
    return bool(CONTRACT_DECLARATION.search(line))


def _line_is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _scan_file(text: str) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    in_docstring = False
    docstring_delim = None
    for lineno, line in enumerate(text.splitlines(), start=1):
        if in_docstring:
            assert docstring_delim is not None
            if line.count(docstring_delim) % 2 == 1:
                in_docstring = False
                docstring_delim = None
        else:
            for delim in ('"""', "'''"):
                if line.count(delim) % 2 == 1:
                    in_docstring = True
                    docstring_delim = delim
                    break
        if not any(name in line for name in KNOWN_EMBEDDING_MODEL_NAMES):
            continue
        if _is_contract_declaration(line):
            out.append((lineno, line.strip(), "contract"))
            continue
        if _is_allowed_line(line):
            out.append((lineno, line.strip(), "fallback"))
            continue
        if in_docstring or _line_is_comment(line):
            out.append((lineno, line.strip(), "docstring_or_comment"))
            continue
        out.append((lineno, line.strip(), "violation"))
    return out


def test_only_canonical_embedding_model_name_in_doc_tools():
    declarations: list[tuple[str, int, str]] = []
    violations: list[tuple[str, int, str]] = []

    for py_file in DOC_TOOLS.rglob("*.py"):
        if any(part.startswith(".") for part in py_file.relative_to(DOC_TOOLS).parts):
            continue
        if "baml_client" in py_file.parts:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, snippet, kind in _scan_file(text):
            if kind == "contract":
                declarations.append((str(py_file), lineno, snippet))
            elif kind == "violation":
                violations.append((str(py_file), lineno, snippet))

    assert len(declarations) == 1, (
        f"DEFAULT_EMBED_MODEL declaration must appear exactly once across "
        f"doc_tools/. Found {len(declarations)}:\n"
        + "\n".join(f"  {f}:{ln}  {snippet}" for f, ln, snippet in declarations)
    )

    assert not violations, (
        f"Hardcoded embedding model name(s) found outside the contract.\n"
        f"Resolve by calling doc_tools.utils.embed.embed_document() or "
        f"embed_query() instead. They read LLM_EMBED_MODEL from env "
        f"(default 'nomic-embed-text') and apply the correct task prefix.\n"
        + "\n".join(f"  {f}:{ln}  {snippet}" for f, ln, snippet in violations)
    )


EMBED_MODULE_RELATIVE = "doc_tools/utils/embed.py"
PREFIX_STRINGS = ("search_document: ", "search_query: ")
FORBIDDEN_LOW_LEVEL_SYMBOLS = ("embed_text", "embed_texts", "_post_embedding")


def test_prefix_strings_only_in_embed_module():
    """search_document: / search_query: literal strings may only appear in
    doc_tools/utils/embed.py."""
    violations: list[tuple[str, int, str]] = []
    embed_module_abs = DOC_TOOLS.parent / EMBED_MODULE_RELATIVE

    for py_file in DOC_TOOLS.rglob("*.py"):
        if py_file.resolve() == embed_module_abs.resolve():
            continue
        if any(part.startswith(".") for part in py_file.relative_to(DOC_TOOLS).parts):
            continue
        if "baml_client" in py_file.parts:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(p in line for p in PREFIX_STRINGS):
                if line.lstrip().startswith("#"):
                    continue
                violations.append((str(py_file), lineno, line.strip()))

    assert not violations, (
        "Task-prefix literal strings found outside "
        f"{EMBED_MODULE_RELATIVE}.\n"
        "Resolve by calling embed_document() / embed_query() from "
        "doc_tools.utils.embed.\n"
        + "\n".join(f"  {f}:{ln}  {snippet}" for f, ln, snippet in violations)
    )


def test_no_low_level_embed_symbols_outside_embed_module():
    """embed_text / embed_texts / _post_embedding only exist (and are only
    callable) inside doc_tools/utils/embed.py."""
    violations: list[tuple[str, int, str]] = []
    embed_module_abs = DOC_TOOLS.parent / EMBED_MODULE_RELATIVE

    for py_file in DOC_TOOLS.rglob("*.py"):
        if py_file.resolve() == embed_module_abs.resolve():
            continue
        if any(part.startswith(".") for part in py_file.relative_to(DOC_TOOLS).parts):
            continue
        if "baml_client" in py_file.parts:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        in_docstring = False
        docstring_delim = None
        for lineno, line in enumerate(text.splitlines(), start=1):
            if in_docstring:
                assert docstring_delim is not None
                if line.count(docstring_delim) % 2 == 1:
                    in_docstring = False
                    docstring_delim = None
                continue
            for delim in ('"""', "'''"):
                if line.count(delim) % 2 == 1:
                    in_docstring = True
                    docstring_delim = delim
                    break
            if in_docstring:
                continue
            if line.lstrip().startswith("#"):
                continue
            for sym in FORBIDDEN_LOW_LEVEL_SYMBOLS:
                import re as _re
                if _re.search(rf"\b{sym}\b", line):
                    violations.append((str(py_file), lineno, line.strip()))
                    break

    assert not violations, (
        "Low-level embed symbols (embed_text / embed_texts / _post_embedding) "
        f"used outside {EMBED_MODULE_RELATIVE}.\n"
        "Resolve by calling embed_document() (write side) or embed_query() "
        "(read side) instead.\n"
        + "\n".join(f"  {f}:{ln}  {snippet}" for f, ln, snippet in violations)
    )
